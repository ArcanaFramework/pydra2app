"""Extraction of archive resources that are added to an image.

Resources marked with ``extract: true`` are unpacked rather than added as the archive
they are distributed as. Which tool is needed is worked out from the file extension, and
is installed into the image alongside the other system packages if it isn't there
already.
"""

from __future__ import annotations

import logging
import shutil
import typing as ty
from pathlib import Path

import attrs
from fileformats.application import Bzip, Gzip, Tar, TarGzip, Zip

logger = logging.getLogger("pydra2app")

#: The archive types that can be extracted outside of the image, in the order they are
#: tried. The order is the point of the union: a '.tar.gz' matches both TarGzip and
#: Gzip, and has to be extracted as the former to yield its contents rather than the tar
#: it holds. Anything not listed here is extracted within the image instead
EXTRACTABLE_ARCHIVES = TarGzip | Tar | Zip | Gzip | Bzip


@attrs.define(frozen=True)
class ExtractionMethod:
    """How an archive of a given type is unpacked.

    Attributes
    ----------
    name : str
        what the method is called, for error messages
    suffixes : tuple[str, ...]
        the file extensions the method applies to, longest matched first so that
        '.tar.gz' isn't mistaken for '.gz'
    packages : dict[str, tuple[str, ...]]
        the system packages the tool is provided by, keyed by package manager
    command : str
        the shell command that unpacks it, taking 'archive' and 'dest' placeholders
    """

    name: str
    suffixes: ty.Tuple[str, ...]
    packages: ty.Dict[str, ty.Tuple[str, ...]]
    command: str

    def extract_command(self, archive: str, dest: str) -> str:
        return self.command.format(archive=archive, dest=dest)

    def system_packages(self, package_manager: str) -> ty.Tuple[str, ...]:
        """The packages to install for `package_manager`, falling back to the apt names"""
        return self.packages.get(package_manager, self.packages["apt"])


#: The archive types that can be extracted, longest suffixes first so that the most
#: specific match wins
EXTRACTION_METHODS: ty.Tuple[ExtractionMethod, ...] = (
    ExtractionMethod(
        name="tar+gzip",
        suffixes=(".tar.gz", ".tgz"),
        packages={"apt": ("tar", "gzip"), "yum": ("tar", "gzip")},
        command='tar -xzf "{archive}" -C "{dest}"',
    ),
    ExtractionMethod(
        name="tar+bzip2",
        suffixes=(".tar.bz2", ".tbz2", ".tbz"),
        packages={"apt": ("tar", "bzip2"), "yum": ("tar", "bzip2")},
        command='tar -xjf "{archive}" -C "{dest}"',
    ),
    ExtractionMethod(
        name="tar+xz",
        suffixes=(".tar.xz", ".txz"),
        packages={"apt": ("tar", "xz-utils"), "yum": ("tar", "xz")},
        command='tar -xJf "{archive}" -C "{dest}"',
    ),
    ExtractionMethod(
        name="tar",
        suffixes=(".tar",),
        packages={"apt": ("tar",), "yum": ("tar",)},
        command='tar -xf "{archive}" -C "{dest}"',
    ),
    ExtractionMethod(
        name="zip",
        suffixes=(".zip",),
        packages={"apt": ("unzip",), "yum": ("unzip",)},
        command='unzip -q "{archive}" -d "{dest}"',
    ),
    ExtractionMethod(
        name="7-zip",
        suffixes=(".7z",),
        packages={"apt": ("p7zip-full",), "yum": ("p7zip",)},
        command='7z x -y -o"{dest}" "{archive}"',
    ),
    ExtractionMethod(
        name="gzip",
        suffixes=(".gz",),
        packages={"apt": ("gzip",), "yum": ("gzip",)},
        command='gunzip -c "{archive}" > "{dest}/{stem}"',
    ),
    ExtractionMethod(
        name="bzip2",
        suffixes=(".bz2",),
        packages={"apt": ("bzip2",), "yum": ("bzip2",)},
        command='bunzip2 -c "{archive}" > "{dest}/{stem}"',
    ),
    ExtractionMethod(
        name="xz",
        suffixes=(".xz",),
        packages={"apt": ("xz-utils",), "yum": ("xz",)},
        command='unxz -c "{archive}" > "{dest}/{stem}"',
    ),
)


class UnrecognisedArchiveError(Exception):
    """Raised when a resource is to be extracted but its type can't be worked out"""


def method_for(name: str) -> ExtractionMethod:
    """Find how to extract an archive, from its file extension.

    Parameters
    ----------
    name : str
        the file name, path or URL of the archive

    Returns
    -------
    ExtractionMethod
        how to extract it

    Raises
    ------
    UnrecognisedArchiveError
        if the extension isn't one that can be extracted
    """
    # a URL may carry a query string or fragment after the file name
    cleaned = name.split("?")[0].split("#")[0].rstrip("/").lower()
    for method in EXTRACTION_METHODS:
        for suffix in method.suffixes:
            if cleaned.endswith(suffix):
                return method
    raise UnrecognisedArchiveError(
        f"Did not recognise '{name}' as an archive that can be extracted. Recognised "
        "extensions are: "
        + ", ".join(s for m in EXTRACTION_METHODS for s in m.suffixes)
    )


def extract_command(method: ExtractionMethod, archive: str, dest: str) -> str:
    """The command that extracts `archive` into `dest`, which is created first"""
    stem = Path(archive).name
    for suffix in method.suffixes:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return method.command.format(archive=archive, dest=dest, stem=stem)


def extract_locally(archive: Path, dest: Path) -> bool:
    """Attempt to extract `archive` into `dest` outside of the image.

    Extracting on the build host instead of within the image keeps the archive out of
    the image altogether, but relies on fileformats having a converter for the archive
    type, so it is only ever an optimisation: callers fall back to extracting within the
    image when it doesn't succeed.

    The type is detected by fileformats rather than taken from the file extension, since
    the file is at hand to be inspected, so an archive whose extension doesn't match its
    contents isn't extracted as something it isn't.

    What ends up in `dest` is what the equivalent command would leave there if it were
    run inside the image, i.e. the archive's top-level entries, so that it doesn't
    matter which of the two extracted it.

    Parameters
    ----------
    archive : Path
        the archive to extract
    dest : Path
        the directory to extract it into

    Returns
    -------
    bool
        whether the archive was extracted
    """
    from fileformats.generic import Directory

    for archive_class in ty.get_args(EXTRACTABLE_ARCHIVES):
        if not archive_class.matches(archive):
            continue
        try:
            classified = archive_class[Directory]
            extracted = Directory.convert(classified(archive))
        except Exception as e:
            logger.debug(
                "Could not extract '%s' as %s outside of the image (%s)",
                archive,
                archive_class.__name__,
                e,
            )
            continue
        # the converter returns the archive's single top-level entry rather than the
        # directory it unpacked into, so it is placed under its own name within `dest`,
        # which is where extracting within the image would put it
        extracted_path = Path(extracted.fspath)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / extracted_path.name
        if extracted_path.is_dir():
            shutil.copytree(extracted_path, target)
        else:
            shutil.copy(extracted_path, target)
        logger.debug("Extracted '%s' as %s", archive, archive_class.__name__)
        return True
    logger.debug(
        "'%s' wasn't extracted outside of the image, so it will be extracted within it",
        archive,
    )
    return False

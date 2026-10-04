"""Downloading and extraction of the resources that are added to an image.

Resources marked with ``extract: true`` are unpacked rather than added as the archive
they are distributed as. Archives provided locally are unpacked on the build host, so
that the archive never enters the image. Remote resources are downloaded (and unpacked)
within the image, in a single layer that installs the tools it needs, and removes them
again afterwards if they weren't already there.
"""

from __future__ import annotations

import bz2
import gzip
import logging
import lzma
import os
import shutil
import tarfile
import typing as ty
import zipfile
from pathlib import Path

import attrs

logger = logging.getLogger("pydra2app")


@attrs.define(frozen=True)
class Tool:
    """A command-line tool that is installed into the image if it isn't there already

    Attributes
    ----------
    command : str
        the executable used to detect whether the tool is already present
    packages : dict[str, tuple[str, ...]]
        the system packages the tool is provided by, keyed by package manager
    """

    command: str
    packages: ty.Dict[str, ty.Tuple[str, ...]]

    def system_packages(self, package_manager: str) -> ty.Tuple[str, ...]:
        """The packages to install for `package_manager`, falling back to the apt names"""
        return self.packages.get(package_manager, self.packages["apt"])


CURL = Tool("curl", {"apt": ("curl", "ca-certificates"), "yum": ("curl",)})
TAR = Tool("tar", {"apt": ("tar",), "yum": ("tar",)})
GZIP = Tool("gzip", {"apt": ("gzip",), "yum": ("gzip",)})
BZIP2 = Tool("bzip2", {"apt": ("bzip2",), "yum": ("bzip2",)})
XZ = Tool("xz", {"apt": ("xz-utils",), "yum": ("xz",)})
UNZIP = Tool("unzip", {"apt": ("unzip",), "yum": ("unzip",)})
SEVEN_ZIP = Tool("7z", {"apt": ("p7zip-full",), "yum": ("p7zip",)})


def _extract_tar(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as tfile:  # the compression is detected automatically
        tfile.extractall(dest, filter="data")


def _extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zfile:
        zfile.extractall(dest)
        # zipfile doesn't restore permissions, unlike unzip, so executables would
        # otherwise lose their executable bits
        for info in zfile.infolist():
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                os.chmod(dest / info.filename, mode)


def _decompressor(
    opener: ty.Callable[..., ty.Any], suffixes: ty.Tuple[str, ...]
) -> ty.Callable[[Path, Path], None]:
    def decompress(archive: Path, dest: Path) -> None:
        with opener(archive, "rb") as src, open(
            dest / _stem(archive.name, suffixes), "wb"
        ) as dst:
            shutil.copyfileobj(src, dst)

    return decompress


def _stem(name: str, suffixes: ty.Tuple[str, ...]) -> str:
    for suffix in suffixes:
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


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
    tools : tuple[Tool, ...]
        the tools needed to run `command` within the image
    command : str
        the shell command that unpacks it within the image, taking 'archive', 'dest'
        and 'stem' placeholders
    extract_locally : Callable[[Path, Path], None], optional
        unpacks it on the build host, into the same layout as `command` would, or None
        if it can't be
    """

    name: str
    suffixes: ty.Tuple[str, ...]
    tools: ty.Tuple[Tool, ...]
    command: str
    extract_locally: ty.Optional[ty.Callable[[Path, Path], None]] = attrs.field(
        default=None, eq=False
    )

    def system_packages(self, package_manager: str) -> ty.Tuple[str, ...]:
        """The packages that provide the tools for `package_manager`"""
        return tuple(
            p for tool in self.tools for p in tool.system_packages(package_manager)
        )


#: The archive types that can be extracted, longest suffixes first so that the most
#: specific match wins
EXTRACTION_METHODS: ty.Tuple[ExtractionMethod, ...] = (
    ExtractionMethod(
        name="tar+gzip",
        suffixes=(".tar.gz", ".tgz"),
        tools=(TAR, GZIP),
        command='tar -xzf "{archive}" -C "{dest}"',
        extract_locally=_extract_tar,
    ),
    ExtractionMethod(
        name="tar+bzip2",
        suffixes=(".tar.bz2", ".tbz2", ".tbz"),
        tools=(TAR, BZIP2),
        command='tar -xjf "{archive}" -C "{dest}"',
        extract_locally=_extract_tar,
    ),
    ExtractionMethod(
        name="tar+xz",
        suffixes=(".tar.xz", ".txz"),
        tools=(TAR, XZ),
        command='tar -xJf "{archive}" -C "{dest}"',
        extract_locally=_extract_tar,
    ),
    ExtractionMethod(
        name="tar",
        suffixes=(".tar",),
        tools=(TAR,),
        command='tar -xf "{archive}" -C "{dest}"',
        extract_locally=_extract_tar,
    ),
    ExtractionMethod(
        name="zip",
        suffixes=(".zip",),
        tools=(UNZIP,),
        command='unzip -q "{archive}" -d "{dest}"',
        extract_locally=_extract_zip,
    ),
    ExtractionMethod(
        name="7-zip",
        suffixes=(".7z",),
        tools=(SEVEN_ZIP,),
        command='7z x -y -o"{dest}" "{archive}"',
    ),
    ExtractionMethod(
        name="gzip",
        suffixes=(".gz",),
        tools=(GZIP,),
        command='gunzip -c "{archive}" > "{dest}/{stem}"',
        extract_locally=_decompressor(gzip.open, (".gz",)),
    ),
    ExtractionMethod(
        name="bzip2",
        suffixes=(".bz2",),
        tools=(BZIP2,),
        command='bunzip2 -c "{archive}" > "{dest}/{stem}"',
        extract_locally=_decompressor(bz2.open, (".bz2",)),
    ),
    ExtractionMethod(
        name="xz",
        suffixes=(".xz",),
        tools=(XZ,),
        command='unxz -c "{archive}" > "{dest}/{stem}"',
        extract_locally=_decompressor(lzma.open, (".xz",)),
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
    """The command that extracts `archive` into `dest`, which must already exist"""
    stem = _stem(Path(archive).name, method.suffixes)
    return method.command.format(archive=archive, dest=dest, stem=stem)


def extract_locally(archive: Path, dest: Path) -> None:
    """Extract `archive` into `dest` on the build host, so that the archive itself
    doesn't need to enter the image.

    What ends up in `dest` is the archive's top-level entries, i.e. what the equivalent
    command would leave there if it were run inside the image.

    Parameters
    ----------
    archive : Path
        the archive to extract, the type of which is determined by its extension
    dest : Path
        the directory to extract it into, created if it doesn't exist

    Raises
    ------
    UnrecognisedArchiveError
        if the archive's extension isn't recognised, or it is of a type that can only
        be extracted within the image
    """
    method = method_for(archive.name)
    if method.extract_locally is None:
        raise UnrecognisedArchiveError(
            f"{method.name} archives, such as '{archive}', can't be extracted on the "
            "build host. Extract it before providing it as a resource, or provide it "
            "by URL instead so it is extracted within the image"
        )
    dest.mkdir(parents=True, exist_ok=True)
    method.extract_locally(archive, dest)
    logger.debug("Extracted '%s' as %s", archive, method.name)


def download_command(
    url: str,
    dest: str,
    package_manager: str,
    method: ty.Optional[ExtractionMethod] = None,
) -> str:
    """The command that downloads a remote resource into the image, and extracts it if
    `method` is given, as a single layer.

    The tools it needs are installed first if they aren't present, and are removed
    again at the end, so they don't remain in the image unless they were already
    there. Doing it all in the one layer also means the downloaded archive doesn't
    take up space in the image after it is deleted.

    Parameters
    ----------
    url : str
        where to download the resource from
    dest : str
        the path of the resource within the image, the directory it is extracted into
        if `method` is given, otherwise the path of the downloaded file
    package_manager : str
        the package manager of the base image, "apt" or "yum"
    method : ExtractionMethod, optional
        how to extract the downloaded archive, if it is to be extracted

    Returns
    -------
    str
        the shell command, to be passed to a RUN instruction
    """
    tools: ty.List[Tool] = [CURL]
    if method is not None:
        tools.extend(t for t in method.tools if t not in tools)
    if package_manager == "yum":
        is_installed = 'rpm -q "$p" >/dev/null 2>&1'
        install = "yum install -y -q $missing"
        uninstall = "yum remove -y -q $missing && yum clean all"
    else:
        is_installed = 'dpkg -s "$p" >/dev/null 2>&1'
        install = (
            "apt-get update -qq "
            "&& apt-get install -y -qq --no-install-recommends $missing"
        )
        uninstall = (
            "apt-get purge -y -qq --auto-remove $missing && rm -rf /var/lib/apt/lists/*"
        )
    # a tool's packages are only installed (and later removed) if its command is
    # missing *and* the package isn't already installed, so nothing that was there
    # before is removed. Grouped with braces rather than parentheses so that `missing`
    # is set in the current shell, not a subshell
    commands = [
        'missing=""',
        *(
            f"{{ command -v {tool.command} >/dev/null 2>&1 || for p in "
            + " ".join(tool.system_packages(package_manager))
            + f'; do {is_installed} || missing="$missing $p"; done; }}'
            for tool in tools
        ),
        f'if [ -n "$missing" ]; then {install}; fi',
    ]
    if method is None:
        commands.extend(
            [
                f'mkdir -p "$(dirname "{dest}")"',
                f'curl -fsSL "{url}" -o "{dest}"',
            ]
        )
    else:
        archive = f"/tmp/{Path(dest).name}-{Path(url.split('?')[0]).name}"
        commands.extend(
            [
                f'mkdir -p "{dest}"',
                f'curl -fsSL "{url}" -o "{archive}"',
                extract_command(method, archive, dest),
                f'rm -f "{archive}"',
            ]
        )
    commands.append(f'if [ -n "$missing" ]; then {uninstall}; fi')
    return " \\\n    && ".join(commands)

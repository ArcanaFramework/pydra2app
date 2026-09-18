import subprocess
import tarfile
import typing as ty
import zipfile
from pathlib import Path

import pytest

from pydra2app.core.image import P2AImage, extraction
from pydra2app.core.image.components import (
    CondaPackage,
    Docs,
    KnownIssue,
    License,
    PipPackage,
    Resource,
)


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.1", "==1.0.1"),
        ("1.0a9", "==1.0a9"),
        ("==1.0.1", "==1.0.1"),
        (">=1.0.1", ">=1.0.1"),
        ("<=1.0.1", "<=1.0.1"),
        ("~=1.0", "~=1.0"),
        ("!=1.0.1", "!=1.0.1"),
        (">1.0.1", ">1.0.1"),
        ("<1.0.1", "<1.0.1"),
        (None, None),
    ],
)
def test_pip_package_version_specifier(
    version: str | None, expected: str | None
) -> None:
    """A bare version number is treated as an exact pin, for backwards
    compatibility with specs that just give a version number, while an
    explicit specifier (e.g. ">=1.0.1") is passed through untouched"""
    assert PipPackage(name="a-package", version=version).version == expected


def test_pip_package_invalid_version_specifier() -> None:
    with pytest.raises(ValueError, match="Invalid version specifier"):
        PipPackage(name="a-package", version="not-a-version!!")


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.1", "a-package==1.0.1"),
        (">=1.0.1", "a-package>=1.0.1"),
        (None, "a-package"),
    ],
)
def test_pip_spec2str(version: str | None, expected: str) -> None:
    """The rendered pip install string carries through whichever comparison
    operator the version specifier was given with (defaulting to an exact
    pin for a bare version number)"""
    pip_spec = PipPackage(name="a-package", version=version)
    assert (
        P2AImage.pip_spec2str(pip_spec, dockerfile=None, build_dir=Path("/tmp"))
        == expected
    )


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.21", "=1.21"),
        ("==1.21.0", "==1.21.0"),
        (">=1.21", ">=1.21"),
        ("<=1.21", "<=1.21"),
        ("!=1.21", "!=1.21"),
        (">1.21", ">1.21"),
        ("<1.21", "<1.21"),
        ("=1.21", "=1.21"),
        (None, None),
    ],
)
def test_conda_package_version_specifier(
    version: str | None, expected: str | None
) -> None:
    """A bare version number is treated as conda's "starts with" pin (its
    existing, pre-change behaviour), while an explicit constraint (e.g.
    ">=1.21" or an exact "==1.21.0" pin) is passed through untouched"""
    assert CondaPackage(name="a-package", version=version).version == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://concatenate.readthefakedocs.io",
        "https://example.com/path/to/page?query=1#anchor",
        "http://localhost:8080/licenses",
    ],
)
def test_url_validator(url: str) -> None:
    assert Docs(info_url=url).info_url == url
    license = License(
        name="a-license",
        destination="/opt/license.txt",
        description="a license",
        info_url=url,
    )
    assert license.info_url == url
    assert KnownIssue(description="an issue", url=url).url == url
    assert Resource(name="a-resource", path=Path("/opt/resource"), url=url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "example.com",
        "/a/local/path",
        "ftp://example.com/file.txt",
        "http://",
        "http://example .com",
    ],
)
def test_url_validator_fail(url: str) -> None:
    with pytest.raises(ValueError, match="Invalid URL"):
        Docs(info_url=url)
    with pytest.raises(ValueError, match="Invalid URL"):
        KnownIssue(description="an issue", url=url)
    with pytest.raises(ValueError, match="Invalid URL"):
        Resource(name="a-resource", path=Path("/opt/resource"), url=url)


def test_url_validator_optional() -> None:
    """URLs of optional fields can be omitted, but required ones still need to be
    valid strings"""
    assert KnownIssue(description="an issue").url is None
    assert Resource(name="a-resource", path=Path("/opt/resource")).url is None
    with pytest.raises(TypeError, match="Invalid URL"):
        Docs(info_url=None)  # type: ignore[arg-type]


RESOURCE_URL = (
    "https://raw.githubusercontent.com/ArcanaFramework/pydra2app/main/LICENSE"
)


def _resource_image(resources: dict[str, ty.Any]) -> P2AImage:
    return P2AImage(
        name="test-resource-url-image",
        version="1.0",
        base_image={
            "name": "python",
            "tag": "3.12.5-slim-bookworm",
            "python": "python3",
            "package_manager": "apt",
            "conda_env": None,
        },
        resources=resources,
    )


def _render_resources(
    img: P2AImage, build_dir: Path, resources: dict[str, Path] | None = None
) -> list[str]:
    build_dir.mkdir(parents=True, exist_ok=True)
    dockerfile = img.init_dockerfile()
    img.add_resources(dockerfile, build_dir, resources=resources, resources_dir=None)
    return dockerfile.render().splitlines()


def test_add_resources_from_url(tmp_path: Path) -> None:
    """Resources that aren't provided locally are downloaded from their URL, which
    requires an ADD instruction as COPY only works with the build context"""
    img = _resource_image(
        {"a-resource": {"path": "/internal/path/to/LICENSE", "url": RESOURCE_URL}}
    )
    lines = _render_resources(img, tmp_path / "build-dir")
    assert f"ADD {RESOURCE_URL} /internal/path/to/LICENSE" in lines
    assert not any(ln.startswith("COPY") and RESOURCE_URL in ln for ln in lines)


def test_add_resources_local_overrides_url(tmp_path: Path) -> None:
    """A locally provided resource is used in preference to its URL"""
    img = _resource_image(
        {"a-resource": {"path": "/internal/path/to/LICENSE", "url": RESOURCE_URL}}
    )
    local_file = tmp_path / "LICENSE"
    local_file.write_text("local license")
    build_dir = tmp_path / "build-dir"
    lines = _render_resources(img, build_dir, resources={"a-resource": local_file})
    assert not any(RESOURCE_URL in ln for ln in lines)
    assert any(ln.startswith("COPY") and "resources/a-resource" in ln for ln in lines)
    assert (build_dir / "resources" / "a-resource").read_text() == "local license"


def test_add_resources_missing_without_url(tmp_path: Path) -> None:
    """Resources without a URL still need to be provided locally"""
    img = _resource_image({"a-resource": "/internal/path/to/a/resource.txt"})
    with pytest.raises(RuntimeError, match="Resource 'a-resource' specified"):
        _render_resources(img, tmp_path / "build-dir")


def test_add_resources_extract_remote(tmp_path: Path) -> None:
    """A remote archive is downloaded, unpacked and deleted in the one layer, so that
    it doesn't take up space in the image"""
    img = P2AImage(
        name="test-extract-remote",
        version="1.0",
        packages={"system": ["vim"]},
        resources={
            "archive": {
                "path": "/opt/archive",
                "url": "https://example.org/data.tar.gz",
                "extract": True,
            }
        },
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    plan = img.plan_resources(build_dir, resources=None, resources_dir=None)

    # the tools it needs are installed, the ones already asked for aren't repeated
    assert img.extraction_packages(plan) == ["tar", "gzip", "curl"]

    dockerfile = img.init_dockerfile()
    img.apply_resource_plan(dockerfile, plan)
    rendered = dockerfile.render()
    run_commands = [
        ln for ln in rendered.splitlines() if ln.startswith("RUN") or "&&" in ln
    ]
    joined = "\n".join(run_commands)
    assert 'curl -fsSL "https://example.org/data.tar.gz"' in joined
    assert 'tar -xzf "/tmp/archive-data.tar.gz" -C "/opt/archive"' in joined
    assert 'rm -f "/tmp/archive-data.tar.gz"' in joined
    # downloading, extracting and deleting must be the one layer, otherwise deleting
    # the archive doesn't reclaim the space it took
    assert rendered.count('RUN mkdir -p "/opt/archive"') == 1
    assert "ADD https://example.org/data.tar.gz" not in rendered


def test_add_resources_extract_local(tmp_path: Path) -> None:
    """A local archive that can be extracted on the build host doesn't enter the image
    at all, and needs no extraction tool installed in it"""
    archive = tmp_path / "payload.zip"
    contents = tmp_path / "payload"
    (contents / "nested").mkdir(parents=True)
    (contents / "nested" / "a.txt").write_text("a")
    with zipfile.ZipFile(archive, "w") as zfile:
        zfile.write(contents / "nested" / "a.txt", "payload/nested/a.txt")

    img = P2AImage(
        name="test-extract-local",
        version="1.0",
        resources={"payload": {"path": "/opt/payload", "extract": True}},
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    plan = img.plan_resources(build_dir, {"payload": archive}, resources_dir=None)

    assert img.extraction_packages(plan) == []
    assert plan[0].method is None  # nothing left to extract within the image
    staged = build_dir / plan[0].source  # type: ignore[operator]
    assert staged.is_dir()
    # the same layout as extracting within the image would give, i.e. the archive's
    # top-level entries, so that it doesn't matter which of the two extracted it
    assert (staged / "payload" / "nested" / "a.txt").read_text() == "a"

    dockerfile = img.init_dockerfile()
    img.apply_resource_plan(dockerfile, plan)
    assert "unzip" not in dockerfile.render()


def test_add_resources_extract_local_fallback(tmp_path: Path) -> None:
    """When the archive can't be extracted on the build host it is copied in and
    extracted within the image instead"""
    archive = tmp_path / "multi.zip"
    with zipfile.ZipFile(archive, "w") as zfile:
        # more than one member at the top level, which the fileformats converter
        # doesn't handle, so it falls back to extracting in the image
        zfile.writestr("one.txt", "one")
        zfile.writestr("two.txt", "two")

    img = P2AImage(
        name="test-extract-fallback",
        version="1.0",
        resources={"multi": {"path": "/opt/multi", "extract": True}},
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    plan = img.plan_resources(build_dir, {"multi": archive}, resources_dir=None)

    assert img.extraction_packages(plan) == ["unzip"]
    assert plan[0].method is not None
    # staged under its own name, as the extension is what the tool is chosen by
    assert plan[0].source.name == "multi.zip"  # type: ignore[union-attr]

    dockerfile = img.init_dockerfile()
    img.apply_resource_plan(dockerfile, plan)
    rendered = dockerfile.render()
    assert 'unzip -q "/tmp/multi.zip" -d "/opt/multi"' in rendered
    assert 'rm -f "/tmp/multi.zip"' in rendered


def test_extraction_method_detection() -> None:
    """The tool to extract with is determined by the file extension"""
    assert extraction.method_for("data.tar.gz").name == "tar+gzip"
    assert extraction.method_for("data.tgz").name == "tar+gzip"
    assert extraction.method_for("data.tar").name == "tar"
    assert extraction.method_for("data.zip").name == "zip"
    assert extraction.method_for("data.tar.xz").name == "tar+xz"
    # the more specific suffix wins over the one it ends with
    assert extraction.method_for("data.gz").name == "gzip"
    # a URL may carry a query string after the file name
    assert extraction.method_for("https://e.org/d.zip?raw=true").name == "zip"
    with pytest.raises(extraction.UnrecognisedArchiveError, match="Did not recognise"):
        extraction.method_for("data.txt")


def test_extraction_packages_differ_by_package_manager() -> None:
    method = extraction.method_for("data.tar.xz")
    assert method.system_packages("apt") == ("tar", "xz-utils")
    assert method.system_packages("yum") == ("tar", "xz")


def test_extract_locally_prefers_the_most_specific_format(tmp_path: Path) -> None:
    """A '.tar.gz' matches both Gzip and TarGzip, and has to be extracted as the latter
    to yield its contents rather than the tar it holds"""
    contents = tmp_path / "src" / "payload"
    contents.mkdir(parents=True)
    (contents / "hello.txt").write_text("hi")
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as tfile:
        tfile.add(contents, arcname="payload")

    dest = tmp_path / "dest"
    assert extraction.extract_locally(archive, dest)
    # extracted as a gzipped tar, not as a gzip holding a tar
    assert (dest / "payload" / "hello.txt").read_text() == "hi"


def test_extract_locally_matches_the_in_image_layout(tmp_path: Path) -> None:
    """However the archive is extracted, what ends up at the resource's path is the
    same, so that falling back to extracting in the image isn't noticeable"""
    contents = tmp_path / "src" / "payload"
    contents.mkdir(parents=True)
    (contents / "hello.txt").write_text("hi")
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as tfile:
        tfile.add(contents, arcname="payload")

    host = tmp_path / "host"
    assert extraction.extract_locally(archive, host)

    in_image = tmp_path / "in-image"
    in_image.mkdir()
    subprocess.run(
        extraction.extract_command(
            extraction.method_for(archive.name), str(archive), str(in_image)
        ),
        shell=True,
        check=True,
    )

    assert sorted(str(p.relative_to(host)) for p in host.rglob("*")) == sorted(
        str(p.relative_to(in_image)) for p in in_image.rglob("*")
    )


def test_extractable_archives_union_order_decides() -> None:
    """The order of the union is what picks between formats that both match, so it is
    pinned here: a '.tar.gz' matches both TarGzip and Gzip, and TarGzip has to win"""
    members = ty.get_args(extraction.EXTRACTABLE_ARCHIVES)
    names = [c.__name__ for c in members]
    assert names.index("TarGzip") < names.index("Gzip")


def test_extract_locally_declines_archives_that_dont_hold_a_directory(
    tmp_path: Path,
) -> None:
    """An archive holding a single file rather than a directory isn't extracted on the
    build host, and falls back to being extracted within the image.

    NB: the obvious extension of this, to also try `Zip[File]` for such archives, does
    not work: a zip *is* a file, so the conversion is a no-op that hands back the
    archive itself, which would then be copied to the resource's path still zipped.
    """
    lone = tmp_path / "lone.txt"
    lone.write_text("just a file")
    archive = tmp_path / "file.zip"
    with zipfile.ZipFile(archive, "w") as zfile:
        zfile.write(lone, "lone.txt")

    assert not extraction.extract_locally(archive, tmp_path / "dest")

    # the trap, pinned so that it isn't "fixed" into silently shipping the archive
    from fileformats.application import Zip
    from fileformats.generic import File

    unconverted = File.convert(Zip[File](archive))
    assert Path(unconverted.fspath) == archive  # i.e. nothing was extracted

    # the fallback handles it: the resource is copied in and extracted there instead
    img = P2AImage(
        name="test-file-archive",
        version="1.0",
        resources={"lone": {"path": "/opt/lone", "extract": True}},
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    plan = img.plan_resources(build_dir, {"lone": archive}, resources_dir=None)
    assert plan[0].method is not None
    assert img.extraction_packages(plan) == ["unzip"]

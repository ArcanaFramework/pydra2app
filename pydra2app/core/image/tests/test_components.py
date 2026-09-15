import typing as ty
from pathlib import Path

import pytest

from pydra2app.core.image import P2AImage
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


RESOURCE_URL = "https://raw.githubusercontent.com/ArcanaFramework/pydra2app/main/LICENSE"


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
    assert any(
        ln.startswith("COPY") and "resources/a-resource" in ln for ln in lines
    )
    assert (build_dir / "resources" / "a-resource").read_text() == "local license"


def test_add_resources_missing_without_url(tmp_path: Path) -> None:
    """Resources without a URL still need to be provided locally"""
    img = _resource_image({"a-resource": "/internal/path/to/a/resource.txt"})
    with pytest.raises(RuntimeError, match="Resource 'a-resource' specified"):
        _render_resources(img, tmp_path / "build-dir")

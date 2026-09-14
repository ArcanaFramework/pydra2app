from pathlib import Path

import pytest

from pydra2app.core.image import P2AImage
from pydra2app.core.image.components import PipPackage


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

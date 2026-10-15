"""Tests for `convert_to_datatype`, which maps a task field's type onto a DataType."""

import typing as ty

import pytest
from fileformats.core import DataType
from fileformats.generic import Directory, File
from fileformats.text import TextFile
import fileformats.field as ffield

from pydra2app.core.command.components import convert_to_datatype
from pydra2app.core.exceptions import Pydra2AppUsageError


class ConvertibleToMarker:
    """Stand-in for the marker fileformats >=0.21 attaches to convertible types.

    Only its presence in `Annotated.__metadata__` matters here, so the real
    class is not imported -- that would tie this test to a fileformats version.
    """

    def __init__(self, format: type) -> None:
        self.format = format


def test_plain_datatype_passes_through() -> None:
    assert convert_to_datatype(TextFile) is TextFile


def test_optional_datatype() -> None:
    assert convert_to_datatype(ty.Optional[TextFile]) == ty.Optional[TextFile]


def test_annotated_datatype_is_unwrapped() -> None:
    """fileformats >=0.21 wraps convertible datatypes in `Annotated`.

    Without unwrapping, an `Annotated` alias matches none of the branches and
    falls through to `issubclass(type_, (str, os.PathLike))`, which raises
    `TypeError: issubclass() arg 1 must be a class`.
    """
    annotated = ty.Annotated[TextFile, ConvertibleToMarker(format=TextFile)]
    assert convert_to_datatype(annotated) is TextFile


def test_annotated_union_is_unwrapped() -> None:
    """The real-world case: a union of the target and everything convertible to it.

    e.g. Annotated[NiftiGzX | DicomDir | DicomSeries, ConvertibleToMarker(...)]
    """
    annotated = ty.Annotated[
        ty.Union[TextFile, Directory], ConvertibleToMarker(format=TextFile)
    ]
    assert convert_to_datatype(annotated) == ty.Union[TextFile, Directory]


def test_annotated_optional_is_unwrapped() -> None:
    """An optional source of a convertible type -- both wrappers at once."""
    annotated = ty.Optional[
        ty.Annotated[TextFile, ConvertibleToMarker(format=TextFile)]
    ]
    assert convert_to_datatype(annotated) == ty.Optional[TextFile]


def test_nested_annotated_is_unwrapped() -> None:
    """Unwrapping is recursive, so nesting does not reintroduce the failure."""
    annotated = ty.Annotated[
        ty.Annotated[TextFile, ConvertibleToMarker(format=TextFile)], "other"
    ]
    assert convert_to_datatype(annotated) is TextFile


def test_primitive_is_converted_to_a_field() -> None:
    assert convert_to_datatype(str) is ffield.Text


def test_unconvertible_type_still_raises_usefully() -> None:
    """Unwrapping must not swallow the error for a genuinely unsupported type."""

    class NotADataType:
        pass

    with pytest.raises(Pydra2AppUsageError, match="Cannot convert type"):
        convert_to_datatype(NotADataType)


def test_annotated_unconvertible_type_still_raises_usefully() -> None:
    """...including when it arrives wrapped."""

    class NotADataType:
        pass

    with pytest.raises(Pydra2AppUsageError, match="Cannot convert type"):
        convert_to_datatype(ty.Annotated[NotADataType, "marker"])


def test_datatype_subclasses_are_recognised() -> None:
    assert issubclass(convert_to_datatype(File), DataType)

"""Tests for `convert_to_datatype`, which maps a task field's type onto a DataType."""

import typing as ty

import pytest
from fileformats.core import DataType
from fileformats.generic import Directory, File
from fileformats.medimage import DicomDir, DicomSeries, NiftiGz
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


def test_annotated_datatype_is_retained() -> None:
    """fileformats >=0.21 wraps convertible datatypes in `Annotated`.

    The annotation is retained so the datatype is written to MIME-like strings as
    "<namespace>/<format>+convertible-to". Without handling it, an `Annotated` alias
    matches none of the branches and falls through to
    `issubclass(type_, (str, os.PathLike))`, which raises
    `TypeError: issubclass() arg 1 must be a class`.
    """
    marker = ConvertibleToMarker(format=TextFile)
    annotated = ty.Annotated[TextFile, marker]
    assert convert_to_datatype(annotated) == annotated


def test_annotated_union_is_retained() -> None:
    """The real-world case: a union of the target and everything convertible to it.

    e.g. Annotated[NiftiGzX | DicomDir | DicomSeries, ConvertibleToMarker(...)]
    """
    marker = ConvertibleToMarker(format=TextFile)
    annotated = ty.Annotated[ty.Union[TextFile, Directory], marker]
    assert convert_to_datatype(annotated) == annotated


def test_annotated_optional_is_retained() -> None:
    """An optional source of a convertible type -- both wrappers at once."""
    marker = ConvertibleToMarker(format=TextFile)
    annotated = ty.Optional[ty.Annotated[TextFile, marker]]
    assert convert_to_datatype(annotated) == annotated


def test_annotated_inner_type_is_converted() -> None:
    """Only the annotation is retained, the type it wraps is still converted"""
    marker = ConvertibleToMarker(format=TextFile)
    assert convert_to_datatype(ty.Annotated[str, marker]) == (
        ty.Annotated[ffield.Text, marker]
    )


def test_nested_annotated_is_retained() -> None:
    """Nested annotations are flattened by `typing`, and all their metadata kept"""
    marker = ConvertibleToMarker(format=TextFile)
    annotated = ty.Annotated[ty.Annotated[TextFile, marker], "other"]
    assert convert_to_datatype(annotated) == ty.Annotated[TextFile, marker, "other"]


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


# The tests above build the `Annotated` by hand so they do not depend on a
# particular fileformats version. These two exercise the real thing, which is
# what actually broke: the wrapper fileformats itself produces.
# From @jamesdidathing's #70.


@pytest.mark.parametrize(
    "datatype",
    [
        NiftiGz,
        NiftiGz | DicomDir | DicomSeries,
        NiftiGz | None,
        ty.List[NiftiGz],
    ],
)
def test_annotated_is_transparent_for_real_datatypes(datatype: ty.Any) -> None:
    """Wrapping a type in `Annotated` must not change what the type it wraps
    converts to"""
    converted = convert_to_datatype(ty.Annotated[datatype, "conversion metadata"])
    assert (
        converted == ty.Annotated[convert_to_datatype(datatype), "conversion metadata"]
    )


def test_real_convertible_from_is_retained() -> None:
    """The actual failing case: `convertible_from()` output from fileformats.

    `NiftiGz.convertible_from()` returns an `Annotated[<union>,
    ConvertibleToMarker(NiftiGz)]`, which is precisely what raised
    `TypeError: issubclass() arg 1 must be a class`.

    The union's exact membership depends on which converters are installed
    (`fileformats-extras` adds the archive types, for instance), so this
    asserts the wrapper is retained and the known converters are present rather
    than pinning the whole set.
    """
    accepted = NiftiGz.convertible_from()
    converted = convert_to_datatype(accepted)

    assert converted == accepted
    assert ty.get_origin(converted) is ty.Annotated
    members = set(ty.get_args(ty.get_args(converted)[0]))
    assert {NiftiGz, DicomDir, DicomSeries} <= members

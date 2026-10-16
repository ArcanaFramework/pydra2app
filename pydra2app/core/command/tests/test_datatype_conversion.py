import typing as ty

import pytest
from fileformats.medimage import DicomDir, DicomSeries, NiftiGz

from pydra2app.core.command.components import convert_to_datatype


@pytest.mark.parametrize(
    "datatype",
    [
        NiftiGz,
        NiftiGz | DicomDir | DicomSeries,
        NiftiGz | None,
        list[NiftiGz],
    ],
)
def test_annotated_datatype(datatype):
    assert convert_to_datatype(ty.Annotated[datatype, "conversion metadata"]) == (
        convert_to_datatype(datatype)
    )


def test_convertible_formats():
    accepted = NiftiGz.convertible_from()
    converted = convert_to_datatype(accepted)
    assert set(ty.get_args(converted)) == {NiftiGz, DicomDir, DicomSeries}

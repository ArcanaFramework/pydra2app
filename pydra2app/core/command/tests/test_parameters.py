import typing as ty

import pytest

from pydra2app.core.command.components import (
    convert_to_datatype,
    datatype_label,
    dict_member,
    parse_parameter_value,
)
from pydra2app.core.exceptions import Pydra2AppUsageError
from pydra2app.core.image.app import App

JSON_EDITS_TYPE = dict[str, str] | list[tuple[str, str]] | None


@pytest.mark.parametrize(
    "type_,expected",
    [
        (dict[str, str], dict),
        (JSON_EDITS_TYPE, dict),
        (ty.Optional[dict[str, int]], dict),
        (int, None),
        (list[tuple[str, str]] | None, None),
    ],
)
def test_dict_member(type_: ty.Any, expected: type | None) -> None:
    member = dict_member(convert_to_datatype(type_))
    if expected is None:
        assert member is None
    else:
        assert ty.get_origin(member) is expected


@pytest.mark.parametrize(
    "type_,value,expected",
    [
        (dict[str, str], "a=1 b=2", {"a": "1", "b": "2"}),
        (dict[str, str], "", {}),
        # Split on the first "=" only, and quotes keep whitespace within values
        (
            JSON_EDITS_TYPE,
            "path=fmap/.* jq_expr='.IntendedFor = \"{bold}\"'",
            {"path": "fmap/.*", "jq_expr": '.IntendedFor = "{bold}"'},
        ),
        (dict[str, str], "a=b=c", {"a": "b=c"}),
        (dict[str, str], "a=", {"a": ""}),
        # Values are converted to the value type of the dict
        (dict[str, int], "x=1 y=2", {"x": 1, "y": 2}),
        (dict[str, bool], "on=true off=false", {"on": True, "off": False}),
        # Non-dict parameters are unaffected
        (int, "5", 5),
    ],
)
def test_parse_parameter_value(type_: ty.Any, value: str, expected: ty.Any) -> None:
    parsed = parse_parameter_value(convert_to_datatype(type_), value)
    if isinstance(expected, dict):
        assert parsed == expected
    else:
        assert parsed.to_primitive() == expected


@pytest.mark.parametrize("value", ["novalue", "=nokey", "a='unclosed"])
def test_parse_parameter_value_invalid(value: str) -> None:
    with pytest.raises(Pydra2AppUsageError):
        parse_parameter_value(convert_to_datatype(dict[str, str]), value)


@pytest.mark.parametrize(
    "type_,expected",
    [
        (JSON_EDITS_TYPE, "field/text=field/text pairs?"),
        (dict[str, int], "field/text=field/integer pairs"),
        (int | None, "field/integer?"),
    ],
)
def test_datatype_label(type_: ty.Any, expected: str) -> None:
    assert datatype_label(convert_to_datatype(type_)) == expected


def test_data_format_html_dict_parameter() -> None:
    """Documenting a dict parameter used to raise AttributeError in to_mime"""
    html = App._data_format_html(convert_to_datatype(JSON_EDITS_TYPE))
    assert "field/text=field/text pairs (optional)" in html

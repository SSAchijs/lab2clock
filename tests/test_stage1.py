import json

import pytest
from pydantic import ValidationError

from lab2clock.stage1 import RawItem, RawReport, json_schema


def item(**overrides):
    fields = {"name": "Glucose", "value": "5,6", "unit": "mmol/L", "page": 1}
    return fields | overrides


def test_schema_is_json_serialisable():
    assert json.loads(json.dumps(json_schema())) == json_schema()


def test_schema_requires_every_field_and_forbids_extras():
    schema = json_schema()
    raw_item = schema["$defs"]["RawItem"]
    assert set(raw_item["required"]) == {"name", "value", "unit", "page"}
    assert raw_item["additionalProperties"] is False
    assert schema["required"] == ["items"]
    assert schema["additionalProperties"] is False


def test_schema_types_value_as_string_and_unit_as_nullable():
    properties = json_schema()["$defs"]["RawItem"]["properties"]
    assert properties["value"]["type"] == "string"
    assert {"type": "null"} in properties["unit"]["anyOf"]


@pytest.mark.parametrize("value", ["5,6", "<0.5", "1.2 H", "12,345", " 6.0* "])
def test_value_is_kept_exactly_as_printed(value):
    assert RawItem(**item(value=value)).value == value


def test_name_and_unit_are_kept_exactly_as_printed():
    raw = RawItem(**item(name="葡萄糖 (GLU)", unit="µmol/L"))
    assert raw.name == "葡萄糖 (GLU)"
    assert raw.unit == "µmol/L"


def test_unit_may_be_null():
    assert RawItem(**item(unit=None)).unit is None


def test_unit_may_not_be_left_out():
    fields = item()
    del fields["unit"]
    with pytest.raises(ValidationError):
        RawItem(**fields)


@pytest.mark.parametrize("value", [5.6, 56])
def test_numeric_value_is_rejected_not_coerced(value):
    with pytest.raises(ValidationError):
        RawItem(**item(value=value))


@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"value": ""}, {"page": 0}, {"confidence": 0.9}],
)
def test_invalid_items_are_rejected(overrides):
    with pytest.raises(ValidationError):
        RawItem(**item(**overrides))


def test_report_round_trips_through_json():
    report = RawReport(items=[RawItem(**item()), RawItem(**item(unit=None, page=2))])
    assert RawReport.model_validate_json(report.model_dump_json()) == report

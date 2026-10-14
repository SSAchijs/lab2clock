import itertools
import json
from typing import get_args

import pandas as pd
import pytest
from pydantic import ValidationError

from bench.sample import OUT as PATIENTS
from bench.spec import (
    BASELINE,
    CBC,
    CHEMISTRY,
    RENDER_SPEC,
    TRUTH,
    Conditions,
    Language,
    Layout,
    RenderSpec,
    Truth,
    UnitSystem,
    printed_value,
    render_spec,
    truth,
)
from lab2clock.assemble import assemble
from lab2clock.clock_spec import MARKERS
from lab2clock.conversions import convert
from lab2clock.synonyms import LYMPHOCYTE_COUNT, match
from lab2clock.units import normalise_unit

REPORTS = [f"R{i:02d}" for i in range(1, 26)]

ALL_CONDITIONS = [
    Conditions(layout=layout, language=language, unit_system=units)
    for layout, language, units in itertools.product(
        get_args(Layout), get_args(Language), get_args(UnitSystem)
    )
]


@pytest.fixture(scope="module")
def patients():
    return pd.read_csv(PATIENTS, index_col="report")


def load(model, folder, report):
    return model.model_validate_json((folder / f"{report}.json").read_text())


# The committed files.


def test_one_truth_and_one_render_spec_per_report():
    assert sorted(p.stem for p in TRUTH.glob("*.json")) == REPORTS
    assert sorted(p.stem for p in RENDER_SPEC.glob("*.json")) == REPORTS


@pytest.mark.parametrize("report", REPORTS)
def test_committed_files_pass_the_schema(report):
    assert load(Truth, TRUTH, report).report == report
    assert load(RenderSpec, RENDER_SPEC, report).report == report


@pytest.mark.parametrize("report", REPORTS)
def test_committed_files_match_a_fresh_build(patients, report):
    # Catches a hand edit, or a change to the builder without regenerating.
    patient = patients.loc[report]
    assert load(Truth, TRUTH, report) == truth(patient)
    assert load(RenderSpec, RENDER_SPEC, report) == render_spec(patient, BASELINE)


@pytest.mark.parametrize("report", REPORTS)
def test_truth_holds_the_sampled_patient(patients, report):
    t = load(Truth, TRUTH, report)
    patient = patients.loc[report]
    assert (t.seqn, t.age, t.split) == (
        patient["SEQN"],
        patient["age"],
        patient["split"],
    )
    assert t.values == {m: patient[m] for m in MARKERS}


# Round trip: what a perfect reader returns comes back to the truth.


def assert_round_trip(spec: RenderSpec, t: Truth):
    out = assemble(spec.stage1(), age=t.age)
    assert out["ok"], out["issues"]
    assert out["missing"] == []
    # Exactly the distractors stay unmapped.
    distractors = [row.name for row in spec.rows if row.analyte is None]
    assert [item["name"] for item in out["unmapped"]] == distractors
    for row in spec.rows:
        assert match(row.name, row.unit) == row.analyte
        if row.analyte not in MARKERS:
            continue
        # Rounding to the printed decimals moves a value by at most half a step.
        step = convert(row.analyte, 10.0**-row.decimals, normalise_unit(row.unit))
        got = out["inputs"][row.analyte]["value"]
        assert got == pytest.approx(t.values[row.analyte], abs=step / 2 + 1e-9)


@pytest.mark.parametrize("report", REPORTS)
def test_committed_specs_read_back_to_the_truth(report):
    assert_round_trip(load(RenderSpec, RENDER_SPEC, report), load(Truth, TRUTH, report))


@pytest.mark.parametrize(
    "conditions",
    ALL_CONDITIONS,
    ids=lambda c: f"{c.layout}-{c.language}-{c.unit_system}",
)
def test_every_condition_reads_back_to_the_truth(patients, conditions):
    for _, patient in patients.iterrows():
        assert_round_trip(render_spec(patient, conditions), truth(patient))


def test_multi_page_puts_chemistry_on_page_two(patients):
    conditions = BASELINE.model_copy(update={"layout": "multi_page"})
    spec = render_spec(patients.iloc[0], conditions)
    pages = {row.analyte: row.page for row in spec.rows}
    assert pages["white_blood_cell_count"] == 1
    assert pages["creatinine"] == 2


def test_mixed_units_mix(patients):
    conditions = BASELINE.model_copy(update={"unit_system": "mixed"})
    units = {
        row.analyte: row.unit for row in render_spec(patients.iloc[0], conditions).rows
    }
    assert units["albumin"] == "g/L"
    assert units["glucose"] == "mg/dL"


# Printed values.


@pytest.mark.parametrize(
    ("marker", "value", "unit", "decimals", "expected"),
    [
        # Half up, as labs round, not half to even: 2.25 mg/L is 2.3.
        ("c_reactive_protein", 0.225, "mg/L", 1, "2.3"),
        # Float noise: 0.2259999999999999 mg/dL is 2.26 mg/L.
        ("c_reactive_protein", 0.2259999999999999, "mg/L", 1, "2.3"),
        ("c_reactive_protein", 0.04, "mg/dL", 2, "0.04"),
        ("albumin", 37.0, "g/L", 0, "37"),
        ("albumin", 37.0, "g/dL", 1, "3.7"),
        ("creatinine", 88.40, "µmol/L", 0, "88"),
        ("creatinine", 88.40, "mg/dL", 2, "1.00"),
        ("glucose", 5.55, "mg/dL", 0, "100"),
        ("white_blood_cell_count", 6.5, "x10^3/uL", 1, "6.5"),
    ],
)
def test_printed_value(marker, value, unit, decimals, expected):
    assert printed_value(marker, value, unit, decimals) == expected


def test_a_value_that_rounds_to_zero_fails():
    with pytest.raises(ValueError, match="rounds to 0"):
        printed_value("c_reactive_protein", 0.001, "mg/dL", 2)


# The schema.


def test_truth_needs_all_nine_markers():
    t = json.loads((TRUTH / "R01.json").read_text())
    del t["values"]["glucose"]
    with pytest.raises(ValidationError):
        Truth.model_validate(t)


def test_render_spec_refuses_unknown_keys():
    spec = json.loads((RENDER_SPEC / "R01.json").read_text())
    spec["rows"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        RenderSpec.model_validate(spec)


def test_stage1_view_drops_what_the_reader_cannot_see():
    spec = load(RenderSpec, RENDER_SPEC, "R01")
    item = spec.stage1().items[0].model_dump()
    assert set(item) == {"name", "value", "unit", "page"}


# Extra rows.


def test_us_report_calls_urea_bun(patients):
    conditions = BASELINE.model_copy(update={"unit_system": "us"})
    rows = {row.name: row for row in render_spec(patients.iloc[0], conditions).rows}
    assert rows["BUN"].unit == "mg/dL"
    assert "Urea" not in rows


def test_every_report_prints_the_same_extras(patients):
    for _, patient in patients.iterrows():
        rows = render_spec(patient, BASELINE).rows
        assert len(rows) == len(CBC) + len(CHEMISTRY)


def test_absolute_lymphocytes_feed_the_cross_check(patients):
    rows = render_spec(patients.iloc[0], BASELINE).rows
    assert [r.analyte for r in rows].count(LYMPHOCYTE_COUNT) == 1

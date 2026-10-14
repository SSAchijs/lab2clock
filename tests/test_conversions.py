import pytest

from lab2clock.clock_spec import BY_NAME, MARKERS
from lab2clock.conversions import (
    CONVERSIONS,
    TARGET_UNITS,
    ConversionError,
    convert,
)
from lab2clock.synonyms import LYMPHOCYTE_COUNT
from lab2clock.units import UNITS, normalise_unit

# One case per table entry: (analyte, unit, printed value, expected in target).
# Molar-mass factors are checked against the rounded factors labs publish
# (creatinine 88.4, glucose 0.0555), an independent route to the same number.
CASES = [
    ("albumin", "g/L", 42, 42),
    ("albumin", "g/dL", 4.2, 42),
    ("creatinine", "umol/L", 80, 80),
    ("creatinine", "mg/dL", 1.0, 88.4),
    ("glucose", "mmol/L", 5.5, 5.5),
    ("glucose", "mg/dL", 100, 5.55),
    ("c_reactive_protein", "mg/dL", 0.3, 0.3),
    ("c_reactive_protein", "mg/L", 3.0, 0.3),
    ("lymphocyte_percent", "%", 30, 30),
    ("mean_cell_volume", "fL", 90, 90),
    ("red_cell_distribution_width", "%", 13.1, 13.1),
    ("alkaline_phosphatase", "U/L", 70, 70),
    ("alkaline_phosphatase", "ukat/L", 1.5, 90),
    ("white_blood_cell_count", "10^3/uL", 6.5, 6.5),
    ("white_blood_cell_count", "/uL", 6500, 6.5),
    (LYMPHOCYTE_COUNT, "10^3/uL", 2.1, 2.1),
    (LYMPHOCYTE_COUNT, "/uL", 2100, 2.1),
]


@pytest.mark.parametrize(("analyte", "unit", "value", "expected"), CASES)
def test_converts(analyte, unit, value, expected):
    assert convert(analyte, value, unit) == pytest.approx(expected, rel=1e-3)


def test_every_entry_has_a_case():
    assert {(analyte, unit) for analyte, unit, _, _ in CASES} == set(CONVERSIONS)


def test_targets_come_from_clock_spec():
    for marker in MARKERS:
        assert TARGET_UNITS[marker] == BY_NAME[marker].unit
    assert TARGET_UNITS[LYMPHOCYTE_COUNT] == BY_NAME["white_blood_cell_count"].unit


def test_every_analyte_converts_from_its_target_unit_unchanged():
    for analyte, unit in TARGET_UNITS.items():
        assert CONVERSIONS[(analyte, unit)] == 1


def test_every_unit_is_canonical():
    for _, unit in CONVERSIONS:
        assert unit in UNITS
    for unit in TARGET_UNITS.values():
        assert unit in UNITS


def test_every_analyte_is_known():
    assert {analyte for analyte, _ in CONVERSIONS} == set(TARGET_UNITS)


@pytest.mark.parametrize(
    ("analyte", "unit"),
    [
        # Same unit, wrong analyte: mg/dL means nothing without a molar mass.
        ("albumin", "mg/dL"),
        ("lymphocyte_percent", "/uL"),
        ("white_blood_cell_count", "%"),
        # Not converted by guesswork.
        ("glucose", "g/L"),
        ("creatinine", "mmol/L"),
        # A bare number is not assumed to be in the clock's unit.
        ("c_reactive_protein", None),
        ("glucose", None),
        # Not a clock input.
        ("hemoglobin", "g/L"),
    ],
)
def test_unknown_pair_fails(analyte, unit):
    with pytest.raises(ConversionError):
        convert(analyte, 1.0, unit)


def test_white_cells_in_giga_per_litre_fail():
    # The unit normaliser casefolds G/L to g/L; the table must not take it.
    with pytest.raises(ConversionError):
        convert("white_blood_cell_count", 6.5, normalise_unit("G/L"))

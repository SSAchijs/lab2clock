import pytest

from lab2clock.clock_spec import BY_NAME
from lab2clock.conversions import TARGET_UNITS, convert
from lab2clock.derive import DerivationError, lymphocyte_percent
from lab2clock.synonyms import LYMPHOCYTE_COUNT


@pytest.mark.parametrize(
    ("count", "white_cells", "expected"),
    [
        (2.1, 7.0, 30),
        (1.5, 6.0, 25),
        (0, 5.0, 0),
        (8.0, 8.0, 100),
        # Lymphocytosis in CLL: most white cells are lymphocytes.
        (95.0, 100.0, 95),
    ],
)
def test_derives_percent(count, white_cells, expected):
    assert lymphocyte_percent(count, white_cells).value == pytest.approx(expected)


def test_is_flagged_as_derived():
    result = lymphocyte_percent(2.1, 7.0)
    assert result.derived is True
    assert result.sources == (LYMPHOCYTE_COUNT, "white_blood_cell_count")


def test_counts_share_a_unit():
    # The ratio is only a percent if both counts are in the same unit.
    assert TARGET_UNITS[LYMPHOCYTE_COUNT] == TARGET_UNITS["white_blood_cell_count"]


def test_lands_in_the_clock_unit():
    assert BY_NAME["lymphocyte_percent"].unit == "%"


def test_mixed_printed_units_give_the_same_percent():
    # A report printing cells/uL for one count and 10^3/uL for the other.
    count = convert(LYMPHOCYTE_COUNT, 2100, "/uL")
    white_cells = convert("white_blood_cell_count", 7.0, "10^3/uL")
    assert lymphocyte_percent(count, white_cells).value == pytest.approx(30)


@pytest.mark.parametrize(
    ("count", "white_cells"),
    [
        (2.1, 0),
        (2.1, -7.0),
        (-2.1, 7.0),
        # A share above 100% is a misread, for example 21 read for 2.1.
        (21.0, 7.0),
    ],
)
def test_impossible_inputs_fail(count, white_cells):
    with pytest.raises(DerivationError):
        lymphocyte_percent(count, white_cells)

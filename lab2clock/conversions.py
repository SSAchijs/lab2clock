"""The conversion table: turns a value in a printed unit into the clock's unit.

Keyed by (analyte, unit), because converting mg/dL to mmol/L depends on each
molecule's molar mass; a generic mg/dL converter is wrong by construction. A
pair not listed raises ConversionError, because a refused unit is visible and a
guessed one is not. That includes a missing unit: a bare number is not assumed
to be in the clock's unit.

Units are the canonical spellings from the unit normaliser. Target units come
from clock_spec. Every factor is a multiplication, and each cites its source.
"""

from lab2clock.clock_spec import BY_NAME, MARKERS
from lab2clock.synonyms import LYMPHOCYTE_COUNT


class ConversionError(ValueError):
    """An (analyte, unit) pair not in the table."""


# Molar masses, from PubChem.
_CREATININE_G_PER_MOL = 113.12  # C4H7N3O, CID 588.
_GLUCOSE_G_PER_MOL = 180.16  # C6H12O6, CID 5793.

# Lymphocyte percent is derived as count / white cells, so the count must be
# in the white-cell unit.
TARGET_UNITS: dict[str, str] = {
    **{marker: BY_NAME[marker].unit for marker in MARKERS},
    LYMPHOCYTE_COUNT: BY_NAME["white_blood_cell_count"].unit,
}

# (analyte, unit) -> factor that takes a value in that unit to TARGET_UNITS.
CONVERSIONS: dict[tuple[str, str], float] = {
    ("albumin", "g/L"): 1,
    # 1 dL = 0.1 L.
    ("albumin", "g/dL"): 10,
    ("creatinine", "umol/L"): 1,
    # 1 mg/dL = 10 mg/L = 10 / 113.12 mmol/L = 88.40 umol/L.
    ("creatinine", "mg/dL"): 10 / _CREATININE_G_PER_MOL * 1000,
    ("glucose", "mmol/L"): 1,
    # 1 mg/dL = 10 mg/L = 10 / 180.16 mmol/L = 0.05551 mmol/L.
    ("glucose", "mg/dL"): 10 / _GLUCOSE_G_PER_MOL,
    ("c_reactive_protein", "mg/dL"): 1,
    # 1 dL = 0.1 L. Most labs print mg/L, so this is the common path.
    ("c_reactive_protein", "mg/L"): 0.1,
    ("lymphocyte_percent", "%"): 1,
    ("mean_cell_volume", "fL"): 1,
    ("red_cell_distribution_width", "%"): 1,
    ("alkaline_phosphatase", "U/L"): 1,
    # 1 U = 1 umol/min (IUPAC-IUB 1979) and 1 kat = 1 mol/s (SI Brochure,
    # 9th ed., 2019), so 1 ukat = 1 umol/s = 60 U.
    ("alkaline_phosphatase", "ukat/L"): 60,
    ("white_blood_cell_count", "10^3/uL"): 1,
    # 1000 cells/uL = 1 x 10^3/uL.
    ("white_blood_cell_count", "/uL"): 0.001,
    (LYMPHOCYTE_COUNT, "10^3/uL"): 1,
    (LYMPHOCYTE_COUNT, "/uL"): 0.001,
}


def convert(analyte: str, value: float, unit: str | None) -> float:
    """value, in canonical unit `unit`, converted to the analyte's target unit.

    Raises ConversionError for an (analyte, unit) pair not in the table.
    """
    try:
        factor = CONVERSIONS[(analyte, unit)]
    except KeyError:
        raise ConversionError(f"no conversion for {analyte} in {unit!r}") from None
    return value * factor

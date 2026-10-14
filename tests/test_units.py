import pytest

from lab2clock.clock_spec import FIELDS
from lab2clock.units import UNITS, UnitError, normalise_unit


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        # As printed on MedRepBench reports for the nine markers.
        ("g/L", "g/L"),
        ("U/L", "U/L"),
        ("IU/L", "U/L"),
        ("mg/L", "mg/L"),
        ("mg/l", "mg/L"),
        ("ug/mL", "mg/L"),
        ("umol/L", "umol/L"),
        ("umol/l", "umol/L"),
        ("μmol/L", "umol/L"),
        ("mmol/L", "mmol/L"),
        ("mmoL/L", "mmol/L"),
        ("mg/dl", "mg/dL"),
        ("%", "%"),
        ("%CV", "%"),
        ("fL", "fL"),
        ("fl", "fL"),
        ("fl.", "fL"),
        ("10^9/L", "10^3/uL"),
        ("10E9/L", "10^3/uL"),
        ("E+9/L", "10^3/uL"),
        ("X10^9/L", "10^3/uL"),
        ("x10^9/L", "10^3/uL"),
        ("×10^9/L", "10^3/uL"),
        ("*10~9/L", "10^3/uL"),
        ("*10`9/L", "10^3/uL"),
        ("/uL", "/uL"),
        ("/ul", "/uL"),
        ("/μL", "/uL"),
        ("cells/uL", "/uL"),
        ("Cell/ul", "/uL"),
        ("CeLL/uL", "/uL"),
        ("个/ul", "/uL"),
        ("个/μl", "/uL"),
        # OCR slips: a final l read as 1.
        ("g/1", "g/L"),
        ("mg/1", "mg/L"),
        ("mmol/1", "mmol/L"),
        ("个/μ1", "/uL"),
        # English layouts.
        ("g/dL", "g/dL"),
        ("mg/dL", "mg/dL"),
        ("mg%", "mg/dL"),
        ("µmol/L", "umol/L"),
        ("µkat/L", "ukat/L"),
        ("µm³", "fL"),
        ("10⁹/L", "10^3/uL"),
        ("x10³/µL", "10^3/uL"),
        ("x10E3/uL", "10^3/uL"),
        ("10*3/uL", "10^3/uL"),
        ("K/uL", "10^3/uL"),
        ("thou/uL", "10^3/uL"),
        ("10^3/mm³", "10^3/uL"),
        ("10^3/mm^3", "10^3/uL"),
        ("cells/mm³", "/uL"),
        # NHANES codebooks.
        ("1000 cells/uL", "10^3/uL"),
        ("1000 cells/µL", "10^3/uL"),
        # Spaces, and full-width characters as on Chinese reports.
        (" mmol / L ", "mmol/L"),
        ("x 10^9 / L", "10^3/uL"),
        ("ｍｍｏｌ／Ｌ", "mmol/L"),
        ("㎎/㎗", "mg/dL"),
    ],
)
def test_normalises(printed, expected):
    assert normalise_unit(printed) == expected


def test_micro_sign_and_greek_mu_are_one_unit():
    micro_sign, greek_mu = "µmol/L", "μmol/L"
    assert micro_sign != greek_mu
    assert normalise_unit(micro_sign) == normalise_unit(greek_mu) == "umol/L"


@pytest.mark.parametrize(
    "printed",
    [
        # Urine white cells per high-power field, printed beside 白细胞.
        "/HP",
        "/HPF",
        "/Hp",
        "HP",
        # Garbled on MedRepBench: guessing would be worse than refusing.
        "uL",
        "Len/uL",
        "个/ul19",
        # Units of other analytes.
        "mg/L(FEU)",
        "mmol/mol",
        "ng/ml",
        "nmol/L",
        "pg",
    ],
)
def test_refuses_unknown_units(printed):
    with pytest.raises(UnitError):
        normalise_unit(printed)


def test_giga_per_litre_reads_as_grams_per_litre():
    # Keys are casefolded, so G/L cannot be told from g/L. A white-cell count
    # in G/L then fails in the conversion table rather than here.
    assert normalise_unit("G/L") == "g/L"


@pytest.mark.parametrize("printed", [None, "", "  "])
def test_no_unit_printed(printed):
    assert normalise_unit(printed) is None


@pytest.mark.parametrize("unit", list(UNITS))
def test_canonical_spellings_map_to_themselves(unit):
    assert normalise_unit(unit) == unit


@pytest.mark.parametrize("field", [f for f in FIELDS if f.name != "age"])
def test_clock_units_are_canonical(field):
    assert field.unit in UNITS


@pytest.mark.parametrize(
    ("unit", "spelling"),
    [(unit, spelling) for unit, spellings in UNITS.items() for spelling in spellings],
)
def test_every_listed_spelling_maps(unit, spelling):
    assert normalise_unit(spelling) == unit

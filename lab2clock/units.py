"""The unit normaliser: maps a unit as printed to one canonical spelling.

There are two characters for micro, the micro sign (U+00B5) and the Greek mu
(U+03BC). They look identical and compare as different strings, so µmol/L and
μmol/L would otherwise be two units. Spellings are reduced to a key, then
matched exactly against the list below; a unit not listed raises UnitError,
because a refused unit is visible and a guessed one is not.

Units of equal magnitude share one canonical spelling: 10^9/L, x10³/µL and K/uL
are all 10^3/uL, and µg/mL is mg/L. Units that differ by a factor stay apart,
and the conversion table maps between them.

Canonical spellings are ASCII ("u" for micro), matching clock_spec.

Seeded from the units MedRepBench prints for the nine markers, OCR slips
included, and from common English layouts. Urine white cells per high-power
field (/HP) are left out on purpose: they share the name 白细胞 with the blood
count, and must fail here rather than feed the clock.
"""

import re
import unicodedata


class UnitError(ValueError):
    """A printed unit not in the list."""


# Per canonical unit, spellings as printed.
UNITS: dict[str, tuple[str, ...]] = {
    # Also "G/L": keys are casefolded, so G/L (giga per litre, a cell count)
    # reads as g/L. A white-cell count printed in G/L then has no entry in the
    # conversion table and fails there.
    "g/L": ("g/L", "g/l", "g/1"),
    "g/dL": ("g/dL", "gm/dL", "g/100 mL", "g%"),
    # 1 µg/mL = 1 mg/L.
    "mg/L": ("mg/L", "mg/l", "mg/1", "ug/mL", "µg/mL", "μg/mL"),
    "mg/dL": ("mg/dL", "mg/dl", "mg/100 mL", "mg%", "㎎/㎗"),
    "umol/L": ("umol/L", "umol/l", "µmol/L", "μmol/L", "micromol/L"),
    "mmol/L": ("mmol/L", "mmoL/L", "mmol/1"),
    "%": ("%", "%CV"),
    # 1 µm³ = 1 fL.
    "fL": ("fL", "fl", "fl.", "µm³", "um3"),
    "U/L": ("U/L", "IU/L"),
    "ukat/L": ("ukat/L", "µkat/L", "μkat/L"),
    # 10^9/L = 10^3/uL = 1/nL.
    "10^3/uL": (
        "10^9/L",
        "10⁹/L",
        "×10^9/L",
        "X10^9/L",
        "x10^9/L",
        "10E9/L",
        "E+9/L",
        "10*9/L",
        "*10~9/L",
        "Gpt/L",
        "/nL",
        "10^3/uL",
        "10³/µL",
        "x10³/µL",
        "x10E3/uL",
        "10*3/uL",
        "K/uL",
        "K/µL",
        "thou/uL",
        # As in the NHANES codebooks. Not cells/uL, which is 1000 times smaller.
        "1000 cells/uL",
        "10^3/mm³",
        "K/mm³",
    ),
    # Single cells, 1000 times smaller than 10^3/uL.
    "/uL": (
        "/uL",
        "/ul",
        "/µL",
        "/μL",
        "cells/uL",
        "cell/uL",
        "个/uL",
        "个/μL",
        "个/μ1",
        "/mm³",
        "cells/mm³",
    ),
}

_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

# Every way the exponent of 10 is printed: 10^9, ×10⁹, 10E9, 10*9, *10~9, E+9.
_POWER_OF_TEN = re.compile(r"^[x×*]?(?:10(?:\^|\*{1,2}|e\+?|~)|e\+)(\d+)")


def _key(printed: str) -> str:
    """The form units are matched in.

    Superscript digits become ^ and digits first, because NFKC would turn 10⁹
    into 109. NFKC then turns full-width characters into normal width and the
    micro sign into mu, which becomes u. Case and spaces go, and a trailing
    full stop. OCR reads a final l as 1, so /1 and μ1 end in l: no unit is per
    one.
    """
    text = re.sub(
        "[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
        lambda digits: "^" + digits.group().translate(_SUPERSCRIPT_DIGITS),
        printed,
    )
    text = unicodedata.normalize("NFKC", text).casefold().replace("μ", "u")
    text = re.sub(r"\s+", "", text).rstrip(".")
    text = _POWER_OF_TEN.sub(r"10^\1", text)
    text = re.sub(r"(?<=[a-z])\^", "", text)  # mm^3 is mm3.
    return re.sub(r"(?<=[/u])1$", "l", text)


def _index() -> dict[str, str]:
    index: dict[str, str] = {}
    for unit, spellings in UNITS.items():
        for spelling in (unit, *spellings):
            key = _key(spelling)
            if index.setdefault(key, unit) != unit:
                raise ValueError(f"{spelling!r} is listed for {index[key]} and {unit}")
    return index


_INDEX = _index()


def normalise_unit(printed: str | None) -> str | None:
    """The canonical spelling of a printed unit, or None if none is printed.

    Raises UnitError for a unit not in the list.
    """
    if printed is None or not printed.strip():
        return None
    try:
        return _INDEX[_key(printed)]
    except KeyError:
        raise UnitError(f"unknown unit: {printed!r}") from None

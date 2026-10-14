"""The scorer: what counts as a correct reading, at stage 1 and end to end.

Stage 1 is scored against what was printed, because a reader can only be asked
to copy the page. A transcribed value or unit is correct when it equals the
printed one after normalising typography only: spaces, a decimal comma, the
two micro characters, superscript exponents, letter case. A different spelling
of the same unit, such as K/uL for 10^9/L or U/L for IU/L, is not the same
transcription, even though the core reads both the same; the end-to-end score
shows whether it mattered.

End to end, a clock input is correct when it is within 0.5% of the printed
value converted to the clock's unit. Comparing against the printed value, not
the unrounded truth, keeps the lab's rounding out of the pipeline's error: a
CRP of 0.24 printed 0.2 is 17% off the truth, and nothing downstream of the
printout could have known. The 0.5% absorbs floating-point noise, while the
smallest real slip, a factor of 10, is 900% off.

The printed value is converted with lab2clock's own unit normaliser and
conversion table. Reusing them means a wrong factor would move the answer and
the expected value alike, but the table is checked independently already: its
tests compare every factor with the rounded factors labs publish, and
bench.nhanes compares it with the SI columns NHANES computed itself.
"""

import math
import re
import unicodedata

from lab2clock.conversions import convert
from lab2clock.units import normalise_unit

# Relative tolerance for an end-to-end value.
TOLERANCE = 0.005

# A trailing abnormal-result flag. The stage-1 contract asks for the flag in
# the value, but most layouts print it in its own column, so a reader that
# copies it from there has not misread the value; the core discards it either
# way.
_FLAG = re.compile(r"(\((?:HH|LL|H|L)\)|HH|LL|H|L|[*!↑↓])$")

# One comma that is unambiguously a decimal mark: not before exactly three
# digits, where it may separate thousands (5,500 is not 5.500).
_DECIMAL_COMMA = re.compile(r"^([<>≤≥=+-]*\d+),(\d{1,2}|\d{4,})$")

_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _typography(printed: str) -> str:
    """Without spaces, in normal width, with full-width and odd characters gone."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", printed))


def stage1_value(printed: str) -> str:
    """A transcribed value, in the form two transcriptions are compared in."""
    text = _typography(printed).replace("−", "-")
    while (match := _FLAG.search(text)) and match.start() > 0:
        text = text[: match.start()]
    return _DECIMAL_COMMA.sub(r"\1.\2", text)


def stage1_unit(printed: str | None) -> str | None:
    """A transcribed unit, in the form two transcriptions are compared in.

    Superscript digits become ^ and digits first, because NFKC would turn 10⁹
    into 109. NFKC turns the micro sign into mu, which becomes u.
    """
    if printed is None or not printed.strip():
        return None
    text = re.sub(
        "[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
        lambda digits: "^" + digits.group().translate(_SUPERSCRIPT_DIGITS),
        printed,
    )
    text = _typography(text).casefold().replace("μ", "u").replace("×", "x")
    return text


def same_value(got: str, printed: str) -> bool:
    """Whether a transcribed value is the printed one."""
    return stage1_value(got) == stage1_value(printed)


def same_unit(got: str | None, printed: str | None) -> bool:
    """Whether a transcribed unit is the printed one."""
    return stage1_unit(got) == stage1_unit(printed)


def expected_input(marker: str, printed: str, unit: str | None) -> float:
    """The printed value of a marker, in the clock's unit.

    printed is as the generator prints it: a plain decimal number.
    """
    return convert(marker, float(printed), normalise_unit(unit))


def same_input(got: float, expected: float) -> bool:
    """Whether a clock input is the expected value, within the tolerance."""
    return math.isclose(got, expected, rel_tol=TOLERANCE)

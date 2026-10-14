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

Every marker that is not fully correct is attributed to the first stage that
went wrong, in pipeline order, so each error says which stage to fix:

- omitted: the printed row was not transcribed.
- value: its value was misread.
- unit: its unit was misread.
- mapping: its name did not map to its marker, or another row mapped to it.
- conversion: read and mapped correctly, but parsed, normalised or converted
  wrongly.
- flag: the checks withheld a correct value, or let a planted one through.

A misread can leave the clock input right, as a unit renamed from 10^9/L to
K/uL does, so a marker can carry an error and still be correct end to end.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from bench.spec import RenderSpec
from lab2clock.assemble import assemble
from lab2clock.clock_spec import MARKERS
from lab2clock.conversions import convert
from lab2clock.stage1 import RawItem, RawReport
from lab2clock.synonyms import LYMPHOCYTE_COUNT, match
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


# Attribution.

Stage = Literal["omitted", "value", "unit", "mapping", "conversion", "flag"]

# Issues raised while reading a row into the clock's unit; the rest are checks.
_READING_CHECKS = {"value", "unit", "conversion"}

# Per marker, the rows the checks compare it with. A misread count can make
# the cross-check withhold a correctly read percent.
_CROSS_CHECKED: dict[str, tuple[str, ...]] = {
    "lymphocyte_percent": (LYMPHOCYTE_COUNT, "white_blood_cell_count"),
}


@dataclass(frozen=True)
class Outcome:
    """How one marker of one report came out.

    expected: the printed value in the clock's unit, or None when the marker
        must be withheld: missing, planted, or knocked out by a planted
        white-cell count.
    got: the clock input delivered, or None when withheld.
    correct: whether got is expected, within the tolerance, or both are None.
    error: the first stage that went wrong, or None.
    """

    report: str
    marker: str
    expected: float | None
    got: float | None
    correct: bool
    error: Stage | None


def withheld(spec: RenderSpec) -> set[str]:
    """The markers a perfect pipeline withholds from this report.

    A planted white-cell count also breaks the lymphocyte cross-check, which
    cannot tell which of the two is wrong, so the percent goes with it.
    """
    out = {row.analyte for row in spec.rows if row.planted}
    if "white_blood_cell_count" in out:
        out.add("lymphocyte_percent")
    if spec.conditions.missing:
        out.add(spec.conditions.missing)
    return out


def _name(printed: str) -> str:
    return _typography(printed).casefold()


def align(spec: RenderSpec, response: RawReport) -> dict[int, int]:
    """Per printed row of an analyte, the index of the item read from it.

    Matched without the core's synonyms, so a name the core maps wrongly is
    still found: first by name, value, unit and page together, so a second row
    under the same name cannot take a correct row's place; then by name on the
    same page; then by name anywhere; then by value and unit on the same page,
    for a misread name. Each item is used once; a row with no item was
    omitted.
    """
    items = response.items
    used: set[int] = set()
    aligned: dict[int, int] = {}
    passes = [
        lambda row, item: (
            _name(item.name) == _name(row.name)
            and same_value(item.value, row.value)
            and same_unit(item.unit, row.unit)
            and item.page == row.page
        ),
        lambda row, item: _name(item.name) == _name(row.name) and item.page == row.page,
        lambda row, item: _name(item.name) == _name(row.name),
        lambda row, item: (
            same_value(item.value, row.value)
            and same_unit(item.unit, row.unit)
            and item.page == row.page
        ),
    ]
    for same in passes:
        for r, row in enumerate(spec.rows):
            if row.analyte is None or r in aligned:
                continue
            for i, item in enumerate(items):
                if i not in used and same(row, item):
                    aligned[r] = i
                    used.add(i)
                    break
    return aligned


def _misread(row, item: RawItem | None) -> Stage | None:
    """The stage-1 error in reading `row` as `item`, if any."""
    if item is None:
        return "omitted"
    if not same_value(item.value, row.value):
        return "value"
    if not same_unit(item.unit, row.unit):
        return "unit"
    return None


def score_report(spec: RenderSpec, response: RawReport, age: float) -> list[Outcome]:
    """Run a stage-1 response through the core and score every marker."""
    out = assemble(response, age=age)
    aligned = align(spec, response)
    items = response.items
    rows = {row.analyte: r for r, row in enumerate(spec.rows) if row.analyte}
    knocked_out = withheld(spec)

    def item_for(analyte: str) -> RawItem | None:
        r = rows.get(analyte)
        return items[aligned[r]] if r is not None and r in aligned else None

    outcomes = []
    for marker in MARKERS:
        r = rows.get(marker)
        row = spec.rows[r] if r is not None else None
        expected = (
            None
            if marker in knocked_out or row is None
            else expected_input(marker, row.value, row.unit)
        )
        delivered = out["inputs"].get(marker)
        got = delivered["value"] if delivered else None
        if expected is None:
            correct = got is None
        else:
            correct = got is not None and same_input(got, expected)

        item = item_for(marker)
        error: Stage | None = None
        if row is not None:
            error = _misread(row, item)
            if error is None and match(item.name, item.unit) != marker:
                error = "mapping"
        if error is None and any(
            match(other.name, other.unit) == marker
            for other in items
            if other is not item
        ):
            error = "mapping"
        if error is None and not correct:
            error = _attribute_core(marker, out, item, delivered, spec, item_for)
        outcomes.append(Outcome(spec.report, marker, expected, got, correct, error))
    return outcomes


def _attribute_core(marker, out, item, delivered, spec, item_for) -> Stage:
    """Why the core got a correctly read and mapped marker wrong."""
    if delivered is None:
        checks = {
            issue["check"]
            for issue in out["issues"]
            if issue["analyte"] == marker and issue["severity"] == "error"
        }
        if checks & _READING_CHECKS:
            return "conversion"
        # A check withheld it: blame a misread row it was compared with first.
        for related in _CROSS_CHECKED.get(marker, ()):
            row = next((row for row in spec.rows if row.analyte == related), None)
            stage = _misread(row, item_for(related)) if row else None
            if stage in ("value", "unit"):
                return stage
        return "flag"
    if item is None or delivered.get("source") != item.model_dump():
        return "mapping"
    # Delivered from the right row: either the checks let a planted value
    # through, or the conversion is wrong.
    if marker in withheld(spec):
        return "flag"
    return "conversion"

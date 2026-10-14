"""Assembly: runs a stage-1 report through every code stage into the output JSON.

Per printed row: match the name, normalise the unit, parse the value, convert
it to the clock's unit. Then the report-level checks, the lymphocyte
derivation, and the output.

An analyte with any error is withheld from the inputs, because error means the
value must not reach the clock. Warnings stay visible beside a delivered value.
Every input carries the row it was read from, exactly as printed, so anyone
auditing an output can see what the report said.
"""

from dataclasses import asdict, dataclass, replace
from typing import Any

from lab2clock.checks import (
    Issue,
    Reading,
    duplicates,
    limit,
    lymphocyte_consistency,
    missing,
    plausibility,
)
from lab2clock.clock_spec import BY_NAME, FIELD_NAMES, MARKERS
from lab2clock.conversions import ConversionError, convert
from lab2clock.derive import DerivationError, DerivedValue, lymphocyte_percent
from lab2clock.stage1 import RawItem, RawReport
from lab2clock.synonyms import LYMPHOCYTE_COUNT, match
from lab2clock.units import UnitError, normalise_unit
from lab2clock.values import ParsedValue, ValueParseError, parse_value

# The check named in the issue when a row fails before it has a value.
_ROW_CHECKS: dict[type[ValueError], str] = {
    UnitError: "unit",
    ValueParseError: "value",
    ConversionError: "conversion",
}


@dataclass(frozen=True)
class _Row:
    """One printed row read as an analyte, with its value in the clock's unit."""

    item: RawItem
    analyte: str
    unit: str | None
    parsed: ParsedValue
    value: float

    @property
    def reading(self) -> Reading:
        # A censored value compares as its limit, so two equal limits agree and
        # a limit against a measured value differs unless the limit could have
        # been printed for it.
        if self.parsed.censored:
            return Reading(self.value)
        return Reading(
            self.value, convert(self.analyte, 10.0**-self.parsed.decimals, self.unit)
        )


def _read(item: RawItem, analyte: str) -> _Row:
    unit = normalise_unit(item.unit)
    parsed = parse_value(item.value)
    return _Row(item, analyte, unit, parsed, convert(analyte, parsed.value, unit))


def _errored(issues: list[Issue]) -> set[str]:
    return {issue.analyte for issue in issues if issue.severity == "error"}


def _derive(rows: dict[str, _Row], issues: list[Issue]) -> DerivedValue | None:
    """Lymphocyte percent from counts, or None with any failure in `issues`."""
    count = rows.get(LYMPHOCYTE_COUNT)
    white_cells = rows.get("white_blood_cell_count")
    if count is None or white_cells is None:
        return None
    if count.parsed.censored or white_cells.parsed.censored:
        issues.append(
            Issue(
                "derivation",
                "error",
                "lymphocyte_percent",
                "not printed, and a censored count cannot give a ratio",
            )
        )
        return None
    try:
        return lymphocyte_percent(count.value, white_cells.value)
    except DerivationError as error:
        issues.append(Issue("derivation", "error", "lymphocyte_percent", str(error)))
        return None


def assemble(report: RawReport, age: float | None = None) -> dict[str, Any]:
    """The output JSON for one stage-1 report.

    age: the patient's age in years. It is not read from the report, so the
    caller supplies it; without it, age is listed as missing.

    Returns a dict with:
    - ok: True when no issue is an error, so every clock input is present.
    - inputs: per clock field, in pyaging's order, the value in the clock's
      unit, the printed row it came from (or the rows it was derived from),
      whether it was censored, and which way ("<" or ">" in limit), and
      whether it was derived. A value printed above a limit is withheld.
    - missing: clock fields with no value in inputs.
    - issues: every problem found, errors and warnings.
    - unmapped: printed rows that are not one of the clock's analytes.
    """
    issues: list[Issue] = []
    unmapped: list[dict[str, Any]] = []
    found: set[str] = set()
    read: dict[str, list[_Row]] = {}

    for item in report.items:
        analyte = match(item.name, item.unit)
        if analyte is None:
            unmapped.append(item.model_dump())
            continue
        found.add(analyte)
        try:
            row = _read(item, analyte)
        except (UnitError, ValueParseError, ConversionError) as error:
            issues.append(Issue(_ROW_CHECKS[type(error)], "error", analyte, str(error)))
            continue
        read.setdefault(analyte, []).append(row)

    issues += duplicates(
        {analyte: [row.reading for row in rows] for analyte, rows in read.items()}
    )

    # Agreeing duplicates are one result, so the first row stands for it.
    errored = _errored(issues)
    rows = {
        analyte: analyte_rows[0]
        for analyte, analyte_rows in read.items()
        if analyte not in errored
    }

    derived = None
    inconsistent = None
    if "lymphocyte_percent" not in found:
        derived = _derive(rows, issues)
        # A failed derivation has its own error, so it is not also missing.
        if derived is not None or "lymphocyte_percent" in _errored(issues):
            found.add("lymphocyte_percent")
    else:
        checked = [
            rows.get(name)
            for name in (
                "lymphocyte_percent",
                LYMPHOCYTE_COUNT,
                "white_blood_cell_count",
            )
        ]
        if all(row and not row.parsed.censored for row in checked):
            percent, count, white_cells = (row.reading for row in checked)
            if issue := lymphocyte_consistency(percent, count, white_cells):
                issues.append(issue)
                inconsistent = issue

    for analyte, row in rows.items():
        if analyte in MARKERS:
            issue = limit(analyte, row.item.value, row.value, row.parsed.limit)
            if issue:
                issues.append(issue)

    values = {analyte: row.value for analyte, row in rows.items() if analyte in MARKERS}
    if derived is not None:
        values["lymphocyte_percent"] = derived.value
    for analyte, value in values.items():
        if issue := plausibility(analyte, value):
            issues.append(issue)
    # The cross-check cannot tell a misread percent from a misread white-cell
    # count, so neither is trusted, unless the percent is implausible itself.
    if inconsistent and "lymphocyte_percent" not in _errored(
        [issue for issue in issues if issue.check == "plausibility"]
    ):
        issues.append(replace(inconsistent, analyte="white_blood_cell_count"))

    issues += missing(found)
    if age is None:
        issues.append(Issue("missing", "error", "age", "not given"))

    errored = _errored(issues)
    inputs: dict[str, dict[str, Any]] = {}
    for name in FIELD_NAMES:
        if name in errored:
            continue
        unit = BY_NAME[name].unit
        if name == "age" and age is not None:
            inputs[name] = {"value": age, "unit": unit}
        elif name == "lymphocyte_percent" and derived is not None:
            inputs[name] = {
                "value": derived.value,
                "unit": unit,
                "censored": False,
                "limit": None,
                "flags": [],
                "derived": True,
                "sources": [
                    rows[source].item.model_dump() for source in derived.sources
                ],
            }
        elif name in rows:
            row = rows[name]
            inputs[name] = {
                "value": row.value,
                "unit": unit,
                "censored": row.parsed.censored,
                "limit": row.parsed.limit,
                "flags": list(row.parsed.flags),
                "derived": False,
                "source": row.item.model_dump(),
            }

    return {
        "ok": not errored,
        "inputs": inputs,
        "missing": [name for name in FIELD_NAMES if name not in inputs],
        "issues": [asdict(issue) for issue in issues],
        "unmapped": unmapped,
    }

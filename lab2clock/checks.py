"""The checks: what a converted report is tested against before it feeds the clock.

Four checks, each returning issues rather than raising, so one report lists all
of its problems at once:

- plausibility: a value outside its field's error tier fails; outside its
  warning tier it warns. Limits come from clock_spec.
- missing: a marker the clock needs that the report did not give.
- duplicates: an analyte read more than once. Values that agree are one result
  printed twice; values that differ usually mean a previous result was read
  as the current one, and nothing tells which is which.
- consistency: the printed lymphocyte percent against count / white cells. It
  catches a misread digit that still falls inside a plausible range.

The last two compare values that were each rounded when printed, so they work
on intervals: a value printed as 2.1 lies anywhere in [2.05, 2.15]. Values
conflict only when no true values could have printed as they did, so a
correct report never fails on rounding, and there is no tolerance to tune.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isclose
from typing import Literal

from lab2clock.clock_spec import BY_NAME, MARKERS

Severity = Literal["warning", "error"]


@dataclass(frozen=True)
class Issue:
    """One problem found in a report.

    check: which check found it: plausibility, missing, duplicate, consistency,
        or, from assembly, unit, value, conversion, derivation.
    severity: error means the value must not reach the clock; warning means it
        is unusual but possible, and stays visible in the output.
    analyte: the analyte it concerns.
    """

    check: str
    severity: Severity
    analyte: str
    message: str


@dataclass(frozen=True)
class Reading:
    """A value in the clock's unit, with the rounding it was printed to.

    step: the place value of the last printed digit, converted to the clock's
        unit: 0.1 for 2.1 printed in 10^3/uL, 0.001 for 2100 printed in /uL.
        The true value lies within value +- step / 2. Censored values are not
        readings: a detection limit says nothing about where the value is.
    """

    value: float
    step: float = 0

    @property
    def low(self) -> float:
        return self.value - self.step / 2

    @property
    def high(self) -> float:
        return self.value + self.step / 2


def _overlap(*intervals: tuple[float, float]) -> bool:
    """Whether one value lies in every (low, high) interval."""
    low = max(interval[0] for interval in intervals)
    high = min(interval[1] for interval in intervals)
    # isclose, so intervals that only touch still overlap after float rounding.
    return low <= high or isclose(low, high)


def plausibility(analyte: str, value: float) -> Issue | None:
    """An issue if `value`, in the clock's unit, is outside a tier, else None.

    The error tier is checked first. The warning tier is skipped while it is
    None, which it is until the NHANES percentiles are computed.
    """
    field = BY_NAME[analyte]
    for severity, limits in (("error", field.error), ("warning", field.warn)):
        if limits is None:
            continue
        low, high = limits
        if not low <= value <= high:
            return Issue(
                "plausibility",
                severity,
                analyte,
                f"{value:g} {field.unit} is outside {low:g} to {high:g}",
            )
    return None


def missing(found: Iterable[str]) -> list[Issue]:
    """An error for each clock marker not in `found`.

    `found` includes derived values: a lymphocyte percent computed from
    counts is not missing.
    """
    present = set(found)
    return [
        Issue("missing", "error", marker, "not found on the report")
        for marker in MARKERS
        if marker not in present
    ]


def duplicates(readings: Mapping[str, Sequence[Reading]]) -> list[Issue]:
    """An issue for each analyte read more than once.

    If all readings agree within their rounding, it is one result printed
    twice, as in a report printing glucose in both mmol/L and mg/dL: a warning.
    Otherwise it is an error, because a previous result may have been read as
    the current one and the right value cannot be chosen.
    """
    issues = []
    for analyte, values in readings.items():
        if len(values) < 2:
            continue
        printed = ", ".join(f"{reading.value:g}" for reading in values)
        if _overlap(*((reading.low, reading.high) for reading in values)):
            issues.append(
                Issue(
                    "duplicate",
                    "warning",
                    analyte,
                    f"read {len(values)} times, agreeing: {printed}",
                )
            )
        else:
            issues.append(
                Issue(
                    "duplicate",
                    "error",
                    analyte,
                    f"read {len(values)} times, differing: {printed}; "
                    "the current result cannot be told from a previous one",
                )
            )
    return issues


def lymphocyte_consistency(
    percent: Reading, count: Reading, white_cells: Reading
) -> Issue | None:
    """An error if the printed percent cannot equal count / white cells.

    count and white_cells in the same unit, as the conversion table gives
    them. The widest percent the counts allow runs from the lowest count over
    the highest white-cell count to the highest count over the lowest.
    """
    if white_cells.high <= 0:
        return None  # No ratio to compare; the plausibility check covers it.
    low = count.low / white_cells.high * 100
    high = count.high / white_cells.low * 100 if white_cells.low > 0 else float("inf")
    if _overlap((percent.low, percent.high), (low, high)):
        return None
    return Issue(
        "consistency",
        "error",
        "lymphocyte_percent",
        f"printed {percent.value:g}%, but count / white cells gives "
        f"{low:.4g} to {high:.4g}%",
    )

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

The metrics, over the nine markers of every report scored:

- value accuracy: the share of markers delivered correctly, or correctly
  withheld.
- stage-1 accuracy: the share of printed marker rows transcribed correctly,
  value and unit, as the real-world set is scored.
- report accuracy: the share of reports with all nine markers correct. One
  wrong input corrupts the clock, so this is what a user experiences.
- flag precision and recall: of the printed markers the pipeline withheld,
  the share that had to be, and of those that had to be, the share it
  withheld. A marker has to be withheld when its printed value is a planted
  slip, or when a planted slip breaks its cross-check.

Each comes with a Wilson 95% interval. Near 100% on a small sample, the usual
normal-approximation interval runs past 100%; Wilson's stays inside 0 to 100%.

Every marker that is not fully correct is attributed to the first stage that
went wrong, in pipeline order, so each error says which stage to fix:

- invalid: the response broke the stage-1 schema twice, so nothing was read.
- omitted: the printed row was not transcribed.
- value: its value was misread.
- unit: its unit was misread.
- mapping: its name did not map to its marker, or another row mapped to it.
- conversion: read and mapped correctly, but parsed, normalised or converted
  wrongly.
- flag: the checks withheld a correct value, or let a planted one through.

A misread can leave the clock input right, as a unit renamed from 10^9/L to
K/uL does, so a marker can carry an error and still be correct end to end.

The real reports have labels, not a truth, so they are scored twice. At stage
1, each labelled marker row against the item read from it. End to end, each
labelled marker against what the core delivered for it: right when it is the
labelled value in the clock's unit, wrong when it is not, missing when nothing
was delivered, and unverified when the label cannot say, having no unit. A
wrong delivery is the error that matters most, since it reaches the clock
looking like any other value; a missing one only leaves the clock without it.

    uv run python -m bench.score

scores every response in results/responses/<extractor>/<run>/ against its
render spec and writes results/results.csv, one row per marker per report per
run, then results/summary.md from that file alone, so every reported number is
computed from the CSV and never typed by hand.
"""

import csv
import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields, replace
from itertools import groupby
from pathlib import Path
from statistics import NormalDist
from typing import Any, Literal, NamedTuple, get_args

from bench import medrepbench, responses
from bench.responses import RESPONSES
from bench.spec import RENDER_SPEC, TRUTH, RenderSpec, Truth
from lab2clock.assemble import assemble
from lab2clock.clock_spec import MARKERS
from lab2clock.conversions import ConversionError, convert
from lab2clock.stage1 import RawItem, RawReport
from lab2clock.synonyms import LYMPHOCYTE_COUNT, match
from lab2clock.units import UnitError, normalise_unit
from lab2clock.values import ValueParseError, parse_value

# Relative tolerance for an end-to-end value.
TOLERANCE = 0.005

# A trailing abnormal-result flag. The stage-1 contract asks for the flag in
# the value, but most layouts print it in its own column, so a reader that
# copies it from there has not misread the value; the core discards it either
# way. Chinese reports also flag with + and -.
_FLAG = re.compile(r"(\((?:HH|LL|H|L)\)|HH|LL|H|L|[*!↑↓+-])$")

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

Stage = Literal["invalid", "omitted", "value", "unit", "mapping", "conversion", "flag"]

# Issues raised while reading a row into the clock's unit; the rest are checks.
_READING_CHECKS = {"value", "unit", "conversion"}

# Per marker, the rows the checks compare it with. A misread count can make
# the cross-check withhold a correctly read percent and white-cell count.
_CROSS_CHECKED: dict[str, tuple[str, ...]] = {
    "lymphocyte_percent": (LYMPHOCYTE_COUNT, "white_blood_cell_count"),
    "white_blood_cell_count": (LYMPHOCYTE_COUNT, "lymphocyte_percent"),
}


@dataclass(frozen=True)
class Outcome:
    """How one marker of one report came out.

    printed: whether the report prints a row for the marker.
    expected: the printed value in the clock's unit, or None when the marker
        must be withheld: missing, planted, or knocked out by a planted
        white-cell count.
    got: the clock input delivered, or None when withheld.
    correct: whether got is expected, within the tolerance, or both are None.
    error: the first stage that went wrong, or None.
    printed_value, printed_unit: the row as printed, when printed.
    read_value, read_unit: the row as transcribed, when transcribed.
    got_limit: "<" or ">" when what was delivered was printed as a limit.
    """

    report: str
    marker: str
    printed: bool
    expected: float | None
    got: float | None
    correct: bool
    error: Stage | None
    printed_value: str | None = None
    printed_unit: str | None = None
    read_value: str | None = None
    read_unit: str | None = None
    got_limit: str | None = None


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
    """Per printed row of an analyte, the index of the item read from it."""
    rows = {r: row for r, row in enumerate(spec.rows) if row.analyte is not None}
    return _align(rows, response.items)


def _align(
    rows: dict[int, Any], items: list[RawItem], loose: bool = False
) -> dict[int, int]:
    """Per printed row, by its index, the index of the item read from it.

    Matched without the core's synonyms, so a name the core maps wrongly is
    still found: first by name, value, unit and page together, so a second row
    under the same name cannot take a correct row's place; then by name on the
    same page; then by name anywhere; then by value and unit on the same page,
    for a misread name. A row whose page is None, as on a one-image report,
    matches any page. Loose alignment, for labels whose units are noisy, adds
    a last pass by value alone. Each item is used once; a row with no item was
    omitted.
    """

    def page(row, item):
        return row.page is None or item.page == row.page

    used: set[int] = set()
    aligned: dict[int, int] = {}
    passes = [
        lambda row, item: (
            _name(item.name) == _name(row.name)
            and same_value(item.value, row.value)
            and same_unit(item.unit, row.unit)
            and page(row, item)
        ),
        lambda row, item: _name(item.name) == _name(row.name) and page(row, item),
        lambda row, item: _name(item.name) == _name(row.name),
        lambda row, item: (
            same_value(item.value, row.value)
            and same_unit(item.unit, row.unit)
            and page(row, item)
        ),
    ]
    if loose:
        passes.append(lambda row, item: same_value(item.value, row.value))
    for same in passes:
        for r, row in rows.items():
            if r in aligned:
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
        outcomes.append(
            Outcome(
                spec.report,
                marker,
                row is not None,
                expected,
                got,
                correct,
                error,
                printed_value=row.value if row else None,
                printed_unit=row.unit if row else None,
                read_value=item.value if item else None,
                read_unit=item.unit if item else None,
                got_limit=delivered.get("limit") if delivered else None,
            )
        )
    return outcomes


def score_invalid(spec: RenderSpec, age: float) -> list[Outcome]:
    """Score a response that broke the schema twice: nothing was read, so
    every printed marker is lost to the invalid response, not omitted."""
    return [
        replace(o, error="invalid") if o.error == "omitted" else o
        for o in score_report(spec, RawReport(items=[]), age)
    ]


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


# Metrics.

_Z95 = NormalDist().inv_cdf(0.975)

_STAGE1: set[Stage] = {"omitted", "value", "unit"}


@dataclass(frozen=True)
class Rate:
    """k successes out of n, with a Wilson score interval."""

    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n)


def wilson(k: int, n: int, z: float = _Z95) -> tuple[float, float] | None:
    """The Wilson score interval for k out of n, or None when n is 0."""
    if n == 0:
        return None
    p = k / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def metrics(outcomes: Iterable[Outcome]) -> dict[str, Rate]:
    """Every metric over the outcomes of one run of one extractor."""
    outcomes = list(outcomes)
    printed = [o for o in outcomes if o.printed]
    by_report = [
        all(o.correct for o in group)
        for _, group in groupby(
            sorted(outcomes, key=lambda o: o.report), key=lambda o: o.report
        )
    ]
    # Printed markers only: a missing marker has no printed value to flag.
    must = [o for o in printed if o.expected is None]
    flagged = [o for o in printed if o.got is None]
    return {
        "value_accuracy": Rate(sum(o.correct for o in outcomes), len(outcomes)),
        "stage1_accuracy": Rate(
            sum(o.error not in _STAGE1 for o in printed), len(printed)
        ),
        "report_accuracy": Rate(sum(by_report), len(by_report)),
        "flag_precision": Rate(sum(o.expected is None for o in flagged), len(flagged)),
        "flag_recall": Rate(sum(o.got is None for o in must), len(must)),
    }


# The real set.


class Labelled(NamedTuple):
    """A labelled marker row of a real report; it carries no page."""

    marker: str
    name: str
    value: str
    unit: str | None
    page: None = None


def real_labels(path: Path = medrepbench.LABELLED) -> dict[str, list[Labelled]]:
    """Per real report, its labelled marker rows, with the hand-checked
    corrections applied: a label found wrong is scored as what is printed."""
    fixes = {}
    for row in medrepbench.read_audit():
        if row["verdict"] == "wrong":
            label = (
                row["image"],
                row["label_name"],
                row["label_value"],
                row["label_unit"],
            )
            fixes[label] = (row["printed_value"], row["printed_unit"])
    out = {}
    for report, rows in medrepbench.read_labelled(path).items():
        out[report] = []
        for row in rows:
            value, unit = fixes.get(
                (row["image"], row["name"], row["value"], row["unit"]),
                (row["value"], row["unit"]),
            )
            out[report].append(
                Labelled(row["marker"], row["name"], value, unit or None)
            )
    return out


def real_expected(row: Labelled) -> float | None:
    """A labelled row's value in the clock's unit, or None when the label
    cannot say: it has no unit, or a unit with no conversion, such as an RDW
    in fL, which is the RDW-SD and not the clock's RDW."""
    if row.unit is None:
        return None
    try:
        return convert(
            row.marker, parse_value(row.value).value, normalise_unit(row.unit)
        )
    except (ValueParseError, UnitError, ConversionError):
        return None


def score_real(
    report: str, rows: list[Labelled], response: RawReport | None
) -> list[Outcome]:
    """Score a real report: each labelled marker row against the item read
    from it, at stage 1, and against the clock input the core delivered.

    correct and error are the stage-1 score. expected is the labelled value in
    the clock's unit, when the label says enough to give it; got is what the
    core delivered for the row's marker. A marker the core delivered that no
    label row names gets a row of its own, unprinted, which the labels cannot
    verify.
    """
    items = response.items if response else []
    # The labels' units are noisy (g/1 for g/l, fl. for fL), so a row read
    # under another name is also found by its value alone.
    aligned = _align(dict(enumerate(rows)), items, loose=True)
    inputs = assemble(response)["inputs"] if response else {}
    outcomes = []
    for r, row in enumerate(rows):
        item = items[aligned[r]] if r in aligned else None
        error = "invalid" if response is None else _misread(row, item)
        delivered = inputs.get(row.marker)
        outcomes.append(
            Outcome(
                report,
                row.marker,
                True,
                real_expected(row),
                delivered["value"] if delivered else None,
                error is None,
                error,
                printed_value=row.value or None,
                printed_unit=row.unit,
                read_value=item.value if item else None,
                read_unit=item.unit if item else None,
                got_limit=delivered.get("limit") if delivered else None,
            )
        )
    labelled = {row.marker for row in rows}
    for marker in MARKERS:
        if marker in inputs and marker not in labelled:
            source = inputs[marker].get("source") or {}
            outcomes.append(
                Outcome(
                    report,
                    marker,
                    False,
                    None,
                    inputs[marker]["value"],
                    False,
                    None,
                    read_value=source.get("value"),
                    read_unit=source.get("unit"),
                    got_limit=inputs[marker].get("limit"),
                )
            )
    return outcomes


RealInput = Literal["right", "wrong", "missing", "unverified", "text", "limit"]


def _number(printed: str | None) -> bool:
    try:
        parse_value(printed or "")
    except ValueParseError:
        return False
    return True


def real_inputs(outcomes: Iterable[Outcome]) -> list[tuple[bool, RealInput]]:
    """Per marker of each real report, whether a label row names it, and
    what reached the clock.

    right: the delivered input is a labelled value of the marker, within the
    tolerance; a report may label two rows for one marker, such as CRP and
    hs-CRP. wrong: it is none of them, though the labels give at least one,
    or the labels print no number for it at all, as a urine test prints
    "Negative" under the name of a blood marker, so nothing should have been
    delivered. missing: nothing was delivered for a labelled number.
    unverified: something was delivered that no label can check. text: the
    labels print no number, and rightly nothing was delivered. limit: what
    was delivered was printed as a limit, such as CRP <5.00, so it is not the
    value, only a bound on it, whatever the label says.
    """
    by_marker: dict[tuple[str, str], list[Outcome]] = {}
    for o in outcomes:
        by_marker.setdefault((o.report, o.marker), []).append(o)
    out: list[tuple[bool, RealInput]] = []
    for group in by_marker.values():
        got = group[0].got
        expected = [o.expected for o in group if o.expected is not None]
        printed = group[0].printed
        text = printed and not any(_number(o.printed_value) for o in group)
        if text:
            kind: RealInput = "text" if got is None else "wrong"
        elif got is None:
            kind = "missing"
        elif group[0].got_limit:
            kind = "limit"
        elif not expected:
            kind = "unverified"
        elif any(same_input(got, e) for e in expected):
            kind = "right"
        else:
            kind = "wrong"
        out.append((printed, kind))
    return out


def real_metrics(outcomes: Iterable[Outcome]) -> dict[str, Rate]:
    """Per labelled marker row: value as printed, unit as labelled, both.

    The hand check found the labels right on every value it checked but wrong
    on 9% of units, so the value rate is the one to trust, and the unit rate
    is a lower bound on how often the unit was read correctly.
    """
    outcomes = [o for o in outcomes if o.printed]
    value = [
        o.read_value is not None and same_value(o.read_value, o.printed_value)
        for o in outcomes
    ]
    unit = [
        o.read_value is not None and same_unit(o.read_unit, o.printed_unit)
        for o in outcomes
    ]
    n = len(outcomes)
    return {
        "value": Rate(sum(value), n),
        "unit": Rate(sum(unit), n),
        "both": Rate(sum(v and u for v, u in zip(value, unit, strict=True)), n),
    }


# Results.

RESULTS = RESPONSES.parent / "results.csv"
SUMMARY = RESPONSES.parent / "summary.md"

# Per row, what produced it and the report's conditions, to slice errors by.
_CONTEXT = (
    "extractor",
    "prompt",
    "form",
    "run",
    "split",
    "layout",
    "language",
    "unit_system",
    "photo",
    "previous",
    "missing",
    "planted",
)
_OUTCOME = tuple(field.name for field in fields(Outcome))
COLUMNS = _CONTEXT + _OUTCOME


def score_responses(directory: Path = RESPONSES) -> list[dict[str, object]]:
    """One row per marker of every report of every run of every extractor;
    on a real report, one per labelled marker row.

    Every response of one extractor must come from the same prompt, its
    version and its text, or the extractor's results would mix two prompts.
    """
    rows = []
    prompts: dict[str, tuple[str | None, str | None]] = {}
    real = None
    for path in sorted(directory.glob("*/*/*.json")):
        extractor, run = path.parent.parent.name, path.parent.name
        response = responses.read(path)
        prompt = response.prompt, response.prompt_sha256
        if prompts.setdefault(extractor, prompt) != prompt:
            raise ValueError(
                f"{extractor} mixes prompts: {path} was read with {prompt[0]} "
                f"({prompt[1]}), others with {prompts[extractor][0]} "
                f"({prompts[extractor][1]})"
            )
        context = dict.fromkeys(_CONTEXT) | {
            "extractor": extractor,
            "prompt": response.prompt,
            "form": response.form,
            "run": run,
        }
        if path.stem.startswith(("M", "H")):
            if real is None:
                real = real_labels() | real_labels(medrepbench.HELDOUT_LABELLED)
            context["split"] = "real" if path.stem.startswith("M") else "heldout"
            outcomes = score_real(path.stem, real[path.stem], response.report)
        else:
            spec = RenderSpec.model_validate_json((RENDER_SPEC / path.name).read_text())
            truth = Truth.model_validate_json((TRUTH / path.name).read_text())
            context |= {"split": spec.split, **spec.conditions.model_dump()}
            if response.report is None:
                outcomes = score_invalid(spec, truth.age)
            else:
                outcomes = score_report(spec, response.report, truth.age)
        for outcome in outcomes:
            rows.append({**context, **asdict(outcome)})
    return rows


def write_results(rows: list[dict[str, object]], path: Path = RESULTS) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: "" if value is None else value for key, value in row.items()}
            )


def _outcome(row: dict[str, str]) -> Outcome:
    def optional(key: str) -> str | None:
        return row[key] or None

    def number(key: str) -> float | None:
        return float(row[key]) if row[key] else None

    return Outcome(
        report=row["report"],
        marker=row["marker"],
        printed=row["printed"] == "True",
        expected=number("expected"),
        got=number("got"),
        correct=row["correct"] == "True",
        error=optional("error"),
        printed_value=optional("printed_value"),
        printed_unit=optional("printed_unit"),
        read_value=optional("read_value"),
        read_unit=optional("read_unit"),
        got_limit=optional("got_limit"),
    )


def read_results(path: Path = RESULTS) -> list[tuple[dict[str, str], Outcome]]:
    """Per row of the results file, its context and its outcome."""
    with path.open(newline="", encoding="utf-8") as file:
        return [
            ({key: row[key] for key in _CONTEXT}, _outcome(row))
            for row in csv.DictReader(file)
        ]


# Summary.

_METRICS = {
    "value_accuracy": "Value accuracy",
    "stage1_accuracy": "Stage-1 accuracy",
    "report_accuracy": "Report accuracy",
    "flag_precision": "Flag precision",
    "flag_recall": "Flag recall",
}

# The scored set first; the development set only tuned the prompt; the real
# sets after them, the held-out one last.
_SPLITS = {"test": 0, "dev": 1, "real": 2, "heldout": 3}
_REAL_SPLITS = {"real", "heldout"}

_REAL_METRICS = {
    "value": "Value as printed",
    "unit": "Unit as labelled",
    "both": "Value and unit",
}

_REAL_INPUTS: dict[str, str] = {
    "right": "Right",
    "wrong": "Wrong",
    "missing": "Missing",
    "unverified": "Unverified",
    "limit": "Limit",
}


# The classes the pooled table shows beside right.
_POOLED = ("wrong", "limit", "missing")


def _numbers(runs: list[list[Outcome]], keep) -> list[RealInput]:
    """Per labelled marker with a number, over every run, what reached the
    clock, keeping only the outcomes `keep` accepts."""
    return [
        kind
        for outcomes in runs
        for printed, kind in real_inputs([o for o in outcomes if keep(o)])
        if printed and kind != "text"
    ]


def _rate(rate: Rate) -> str:
    if rate.n == 0:
        return "–"
    low, high = rate.interval
    return f"{rate.value:.1%} ({low:.1%}–{high:.1%}), {rate.k}/{rate.n}"


def _table(header: list[str], lines: list[list[str]]) -> str:
    rows = [header, ["---"] * len(header), *lines]
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def summary(results: list[tuple[dict[str, str], Outcome]]) -> str:
    """The markdown summary of a results file: metrics and errors by stage."""

    def key(result):
        context = result[0]
        return (
            context["extractor"],
            context["prompt"],
            _SPLITS[context["split"]],
            context["run"],
        )

    groups = [
        (k, [outcome for _, outcome in group])
        for k, group in groupby(sorted(results, key=key), key=key)
    ]
    names = {v: k for k, v in _SPLITS.items()}
    stages = list(get_args(Stage))
    accuracy, real, real_end, errors = [], [], [], []
    pooled: dict[tuple[str, str, str], list[list[Outcome]]] = {}
    for (extractor, prompt, split, run), outcomes in groups:
        label = [extractor, prompt or "–", names[split], run]
        if names[split] in _REAL_SPLITS:
            rates = real_metrics(outcomes)
            real.append(label + [_rate(rates[n]) for n in _REAL_METRICS])
            pooled.setdefault((extractor, prompt or "–", names[split]), []).append(
                outcomes
            )
            inputs = real_inputs(outcomes)
            labelled = [kind for printed, kind in inputs if printed]
            numbers = [kind for kind in labelled if kind != "text"]
            unlabelled = [kind for printed, kind in inputs if not printed]
            real_end.append(
                label
                + [_rate(Rate(numbers.count(k), len(numbers))) for k in _REAL_INPUTS]
                + [str(labelled.count("text")), str(len(unlabelled))]
            )
        else:
            rates = metrics(outcomes)
            accuracy.append(label + [_rate(rates[name]) for name in _METRICS])
        counts = [str(sum(o.error == stage for o in outcomes)) for stage in stages]
        errors.append(label + counts)
    label = ["Extractor", "Prompt", "Split", "Run"]
    pooled_lines = []
    for key, runs in pooled.items():
        every = _numbers(runs, lambda o: True)
        no_albumin = _numbers(runs, lambda o: o.marker != "albumin")
        pooled_lines.append(
            [
                *key,
                _rate(Rate(every.count("right"), len(every))),
                _rate(Rate(no_albumin.count("right"), len(no_albumin))),
                *(_rate(Rate(every.count(k), len(every))) for k in _POOLED),
            ]
        )
    real_section = []
    if real:
        real_section = [
            "## Real-world set",
            "Stage 1 on the MedRepBench reports, per labelled marker row: real is "
            "the scored set, heldout the reports set aside to test changes made "
            "after it was scored. The hand check found the labels right on every "
            "value but wrong on some units (see METHODS.md), so the unit rate is a "
            "lower bound.",
            _table([*label, *_REAL_METRICS.values()], real),
            "End to end on the same reports, per labelled marker: what reached the "
            "clock. Right and wrong are judged against the labelled value in the "
            "clock's unit; a value delivered for a marker whose label prints text, "
            "such as a urine test's Negative, is wrong. Unverified is a value "
            "delivered for a marker whose label has no unit, or an RDW labelled in "
            "fL, which no label can check. Limit is a value delivered as printed "
            "below a limit, such as CRP <5.00: a bound, not the value. "
            "The rates are over the markers labelled "
            "with a number, or delivered; the last two columns count markers "
            "labelled only with text and rightly not delivered, and values "
            "delivered for a marker no label names.",
            _table(
                [
                    *label,
                    *_REAL_INPUTS.values(),
                    "Text, rightly not delivered",
                    "Delivered, not labelled",
                ],
                real_end,
            ),
            "Pooled over the runs, per labelled marker with a number. Albumin is "
            "also left out in one column, because the dataset's de-identification "
            "blurs its name on most reports that print it. The intervals treat "
            "the three runs as independent, which they are not, so they are too "
            "narrow.",
            _table(
                [
                    "Extractor",
                    "Prompt",
                    "Split",
                    "Right",
                    "Right, leaving out albumin",
                    *(_REAL_INPUTS[k] for k in _POOLED),
                ],
                pooled_lines,
            ),
        ]
    return (
        "\n\n".join(
            [
                "# Results",
                "Generated by `uv run python -m bench.score` from `results.csv`; "
                "do not edit by hand. Each rate is followed by its Wilson 95% "
                "interval and its count.",
                "## Accuracy",
                _table(label + list(_METRICS.values()), accuracy),
                *real_section,
                "## Errors by stage",
                "Each marker that is not fully correct, counted at the first stage "
                "that went wrong.",
                _table(label + stages, errors),
            ]
        )
        + "\n"
    )


def main() -> None:
    rows = score_responses()
    write_results(rows)
    SUMMARY.write_text(summary(read_results()), encoding="utf-8")
    print(f"scored {len(rows)} values into {RESULTS} and {SUMMARY}")


if __name__ == "__main__":
    main()

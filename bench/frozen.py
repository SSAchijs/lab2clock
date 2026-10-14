"""The held-out score with the code as it was before that set was read.

The held-out reports were set aside to test the fixes made on the 39 scored
ones. After their results were seen, more changes were made to the code,
most because of what they showed, so scoring them with the current code
flatters it: the set has been used to tune it. This module scores the same
responses with every code change since then undone:

- a value of exactly 0 refused for markers that cannot be 0;
- + or - read as a flag only when set apart from the number, so 3+ is not 3;
- a value printed above a limit withheld, one below it warned about;
- a white-cell count below 0.05 x 10^9/L refused;
- a white-cell count printed below 1,000 per uL set aside as a urine count;
- an RDW above 35% refused as an RDW-SD.

Everything else is the current code, and the scorer is the current one, so
the classes match summary.md's. The result is the honest held-out number, and
the reason the held-out set is now used up: a further change needs new
reports to be tested on.

    uv run python -m bench.frozen

writes results/frozen.md; a test fails if it differs from a fresh run.
"""

import dataclasses
import re
from collections.abc import Iterator
from contextlib import contextmanager
from math import inf
from pathlib import Path

import lab2clock.assemble as assemble
import lab2clock.values as values
from bench import medrepbench, responses
from bench.score import (
    RESPONSES,
    Outcome,
    Rate,
    _rate,
    _table,
    real_inputs,
    real_labels,
    score_real,
)
from lab2clock.clock_spec import BY_NAME

FROZEN = RESPONSES.parent / "frozen.md"

# The trailing-flag pattern before + and - had to be set apart.
_OLD_FLAG = re.compile(r"\s*(\((?:HH|LL|H|L)\)|HH|LL|H|L|[*!↑↓+-])$")


@contextmanager
def frozen_code() -> Iterator[None]:
    """The current code with the held-out fixes undone, restored after."""
    fields = dict(BY_NAME)
    flag, check, urine = values._FLAG, assemble.limit, assemble._urine_count
    try:
        for name, field in fields.items():
            if field.error is not None:
                high = inf if name == "red_cell_distribution_width" else field.error[1]
                BY_NAME[name] = dataclasses.replace(
                    field, zero=True, error=(min(field.error[0], 0), high)
                )
        values._FLAG = _OLD_FLAG
        assemble.limit = lambda *args: None
        assemble._urine_count = lambda row: False
        yield
    finally:
        BY_NAME.update(fields)
        values._FLAG, assemble.limit, assemble._urine_count = flag, check, urine


def outcomes(directory: Path = RESPONSES) -> dict[str, list[list[Outcome]]]:
    """Per extractor, per run, the held-out outcomes under the frozen code.

    Only the pipeline runs frozen. The labels are read with the current
    parser, so a label of 3+ stays text, not the number 3.
    """
    labels = real_labels(medrepbench.HELDOUT_LABELLED)
    out: dict[str, list[list[Outcome]]] = {}
    for run_dir in sorted(directory.glob("*/*")):
        paths = sorted(run_dir.glob("H*.json"))
        if not paths:
            continue
        reports = {p.stem: responses.read(p).report for p in paths}
        with frozen_code():
            delivered = {
                stem: score_real(stem, labels[stem], report)
                for stem, report in reports.items()
            }
        current = {
            stem: score_real(stem, labels[stem], report)
            for stem, report in reports.items()
        }
        run = []
        for stem in reports:
            # Labelled rows come first in both, one per label: their expected
            # values from the current code, what was delivered from the frozen.
            n = len(labels[stem])
            for now, then in zip(current[stem][:n], delivered[stem][:n], strict=True):
                run.append(
                    dataclasses.replace(now, got=then.got, got_limit=then.got_limit)
                )
            run += delivered[stem][n:]
        out.setdefault(run_dir.parent.name, []).append(run)
    return out


def summary(results: dict[str, list[list[Outcome]]]) -> str:
    lines, wrong = [], []
    for extractor, runs in results.items():
        kinds = []
        for number, run in enumerate(runs, start=1):
            groups: dict[tuple[str, str], list[Outcome]] = {}
            for o in run:
                groups.setdefault((o.report, o.marker), []).append(o)
            for (report, marker), group in groups.items():
                [(printed, kind)] = real_inputs(group)
                if printed and kind != "not_blood":
                    kinds.append(kind)
                if kind == "wrong":
                    label = ", ".join(
                        f"{o.printed_value or ''} {o.printed_unit or ''}".strip()
                        for o in group
                    )
                    wrong.append(
                        [
                            extractor,
                            str(number),
                            report,
                            marker,
                            label,
                            f"{group[0].got:g}",
                        ]
                    )
        lines.append(
            [extractor]
            + [_rate(Rate(kinds.count(k), len(kinds))) for k in ("right", "wrong")]
            + [_rate(Rate(kinds.count(k), len(kinds))) for k in ("limit", "missing")]
        )
    return (
        "\n\n".join(
            [
                "# Held-out set, code frozen",
                "Generated by `uv run python -m bench.frozen`; do not edit by hand. "
                "The held-out reports scored with the code as it was before they "
                "were read, by the current scorer: per labelled marker with a blood "
                "value, pooled over the runs. See bench/frozen.py for what is undone.",
                _table(["Extractor", "Right", "Wrong", "Limit", "Missing"], lines),
                "Every input scored wrong, with its label and what was delivered, "
                "in the clock's unit:",
                _table(
                    ["Extractor", "Run", "Report", "Marker", "Label", "Delivered"],
                    wrong,
                ),
            ]
        )
        + "\n"
    )


def main() -> None:
    FROZEN.write_text(summary(outcomes()), encoding="utf-8")
    print(f"wrote {FROZEN}")


if __name__ == "__main__":
    main()

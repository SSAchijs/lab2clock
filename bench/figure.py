"""The README's results figure, drawn from results/results.csv.

One bar per set of reports: of the markers labelled with a number, the share
whose input reached the clock right, the share scored wrong, and the share
missing or unchecked. A tick marks the share of printed values the model
copied exactly, so the gap between the tick and the end of the blue is what
was lost between the page and the clock.

Every number is computed from the results file, as summary.md's are, and a
test fails if the committed figures differ from a fresh run. Two files, one
for each colour scheme, which the README picks between with <picture>.

    uv run python -m bench.figure
"""

from dataclasses import dataclass
from pathlib import Path

from bench.score import (
    RESULTS,
    Outcome,
    _number,
    metrics,
    read_results,
    real_inputs,
    same_value,
)

DOCS = Path(__file__).resolve().parent.parent / "docs"
FILES = {"light": DOCS / "results-light.svg", "dark": DOCS / "results-dark.svg"}

HAIKU = "claude-haiku-5-5_extract_v1"
OPUS = "claude-opus-5-5_extract_v1"

# Per bar: its name, the model, and which results it is drawn from.
BARS = [
    ("20 synthetic reports", "Claude Haiku 5.5", HAIKU, "test"),
    ("39 real reports", "Claude Haiku 5.5", HAIKU, "real"),
    ("39 real reports", "Claude Opus 5.5", OPUS, "real"),
    ("142 held-out real reports", "Claude Haiku 5.5", HAIKU, "heldout"),
]

# Validated with the dataviz skill's palette checks: blue and the status red
# pass every check in both modes. Grey is the neutral "nothing" colour, not a
# series hue, and carries a printed label.
COLOURS = {
    "light": {
        "ink": "#0b0b0b",
        "quiet": "#52514e",
        "right": "#2a78d6",
        "missing": "#c9c7bf",
        "wrong": "#d03b3b",
        "on_right": "#ffffff",
    },
    "dark": {
        "ink": "#f0efec",
        "quiet": "#c3c2b7",
        "right": "#3987e5",
        "missing": "#4a4945",
        "wrong": "#d03b3b",
        "on_right": "#ffffff",
    },
}

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Bar:
    name: str
    model: str
    right: float
    wrong: float
    copied: float
    wrong_count: int


def bars(results: list[tuple[dict[str, str], Outcome]]) -> list[Bar]:
    """Each bar's shares, pooled over every run."""
    out = []
    for name, model, extractor, split in BARS:
        chosen = [
            (context, o)
            for context, o in results
            if context["extractor"] == extractor and context["split"] == split
        ]
        if split == "test":
            rates = metrics(o for _, o in chosen)
            right, copied = rates["value_accuracy"], rates["stage1_accuracy"]
            out.append(Bar(name, model, right.value, 0.0, copied.value, 0))
            continue
        by_run: dict[str, list[Outcome]] = {}
        for context, o in chosen:
            by_run.setdefault(context["run"], []).append(o)
        kinds = [
            kind
            for outcomes in by_run.values()
            for printed, kind in real_inputs(outcomes)
            if printed and kind != "text"
        ]
        numbers = [o for _, o in chosen if o.printed and _number(o.printed_value)]
        copied = sum(
            o.read_value is not None and same_value(o.read_value, o.printed_value)
            for o in numbers
        )
        wrong = kinds.count("wrong")
        out.append(
            Bar(
                name,
                model,
                kinds.count("right") / len(kinds),
                wrong / len(kinds),
                copied / len(numbers),
                wrong,
            )
        )
    return out


def _pct(share: float) -> str:
    return f"{share * 100:.0f}%"


def svg(data: list[Bar], mode: str) -> str:
    c = COLOURS[mode]
    width, x0, span, height, top, gap = 760, 220, 440, 30, 128, 54
    rows = []
    for i, bar in enumerate(data):
        y = top + i * gap
        right = bar.right * span
        wrong = max(bar.wrong * span, 3) if bar.wrong else 0
        tick = x0 + bar.copied * span
        rows.append(
            f'<text x="24" y="{y + 13}" font-size="13" font-weight="600" '
            f'fill="{c["ink"]}">{bar.name}</text>'
            f'<text x="24" y="{y + 29}" font-size="11.5" fill="{c["quiet"]}">'
            f"{bar.model}</text>"
            f'<rect x="{x0}" y="{y}" width="{span}" height="{height}" rx="4" '
            f'fill="{c["missing"]}"/>'
            f'<rect x="{x0}" y="{y}" width="{right:.1f}" height="{height}" rx="4" '
            f'fill="{c["right"]}"/>'
        )
        if wrong:
            rows.append(
                f'<rect x="{x0 + right + 2:.1f}" y="{y}" width="{wrong:.1f}" '
                f'height="{height}" fill="{c["wrong"]}"/>'
            )
        rows.append(
            f'<text x="{x0 + 10}" y="{y + 20}" font-size="13" font-weight="600" '
            f'fill="{c["on_right"]}">{_pct(bar.right)}</text>'
        )
        missing = 1 - bar.right - bar.wrong
        if missing * span > 44:
            rows.append(
                f'<text x="{x0 + right + wrong + 10:.1f}" y="{y + 20}" '
                f'font-size="12" fill="{c["ink"]}">{_pct(missing)}</text>'
            )
        rows.append(
            f'<line x1="{tick:.1f}" x2="{tick:.1f}" y1="{y - 5}" y2="{y + height + 5}" '
            f'stroke="{c["ink"]}" stroke-width="2"/>'
            f'<text x="{x0 + span + 64}" y="{y + 20}" font-size="13" '
            f'text-anchor="end" fill="{c["ink"]}">{_pct(bar.copied)}</text>'
        )
    header = (
        f'<text x="{x0 + span + 64}" y="{top - 14}" font-size="11.5" '
        f'text-anchor="end" fill="{c["quiet"]}">Copied</text>'
    )
    bottom = top + (len(data) - 1) * gap + height
    wrong_total = sum(bar.wrong_count for bar in data)
    legend_y = 82
    legend = (
        f'<rect x="24" y="{legend_y - 10}" width="12" height="12" rx="2" '
        f'fill="{c["right"]}"/>'
        f'<text x="42" y="{legend_y}" font-size="12" fill="{c["ink"]}">'
        "Reached the clock correctly</text>"
        f'<rect x="222" y="{legend_y - 10}" width="12" height="12" rx="2" '
        f'fill="{c["missing"]}"/>'
        f'<text x="240" y="{legend_y}" font-size="12" fill="{c["ink"]}">'
        "Missing or unchecked</text>"
        f'<rect x="390" y="{legend_y - 10}" width="12" height="12" rx="2" '
        f'fill="{c["wrong"]}"/>'
        f'<text x="408" y="{legend_y}" font-size="12" fill="{c["ink"]}">'
        "Scored wrong</text>"
        f'<line x1="518" x2="518" y1="{legend_y - 12}" y2="{legend_y + 3}" '
        f'stroke="{c["ink"]}" stroke-width="2"/>'
        f'<text x="526" y="{legend_y}" font-size="12" fill="{c["ink"]}">'
        "Values copied exactly</text>"
    )
    note_y = bottom + 34
    lines = [
        f"Red: {wrong_total} inputs scored wrong. Checked against the report images, "
        "each time the pipeline was right",
        "and the dataset's label was not. Shares of labelled markers, three runs "
        "per set; real reports from MedRepBench.",
    ]
    note = "".join(
        f'<text x="24" y="{note_y + 17 * i}" font-size="11.5" '
        f'fill="{c["quiet"]}">{line}</text>'
        for i, line in enumerate(lines)
    )
    total = note_y + 17 * (len(lines) - 1) + 22
    real = [bar.copied for bar in data if bar.wrong_count or bar.right < 1]
    title = (
        f"Claude copies {min(real) * 100:.0f}–{max(real) * 100:.0f}% of real "
        "values exactly. Fewer reach the clock"
    )
    subtitle = (
        "What the code cannot verify is withheld, so the gap is missing values, "
        "not wrong ones"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total}" '
        f'width="{width}" height="{total}" font-family="{FONT}" role="img" '
        f'aria-label="{title}">'
        f"<title>{title}</title>"
        f'<text x="24" y="32" font-size="17" font-weight="700" fill="{c["ink"]}">'
        f"{title}</text>"
        f'<text x="24" y="54" font-size="13" fill="{c["quiet"]}">{subtitle}</text>'
        f"{legend}{header}{''.join(rows)}{note}</svg>\n"
    )


def main() -> None:
    data = bars(read_results(RESULTS))
    DOCS.mkdir(exist_ok=True)
    for mode, path in FILES.items():
        path.write_text(svg(data, mode), encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

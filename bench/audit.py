"""A hand check of MedRepBench's labels against their images.

The labels were produced by OCR and an LLM, and the dataset's authors report
about 97% agreement in their own audit. Before a model is blamed for
disagreeing with a label, we need to know how often the label itself is wrong.
So 10 of the 39 scored reports, drawn with a fixed seed, are checked by eye:
every labelled row that maps to a clock marker, its name, value and unit,
against the image, and any marker printed on the image but missing from the
labels.

The check is done by a person, not a model. The models scored are Claude
models, and a misreading a model shares with the checker would pass unseen.

    uv run python -m bench.audit

writes bench/data/medrepbench/audit.html, a page showing each image beside
its marker rows. The page keeps its answers in the browser as they are given
and downloads them as a CSV, saved as bench/medrepbench_audit.csv. Then

    uv run python -m bench.audit score

reads that file and prints the label error rate with its Wilson 95% interval.
"""

import csv
import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from bench import medrepbench
from bench.score import wilson
from lab2clock.clock_spec import MARKERS
from lab2clock.synonyms import match

SEED = 2017
SIZE = 10

PAGE = medrepbench.CACHE / "audit.html"
RESULTS = Path(__file__).resolve().parent / "medrepbench_audit.csv"

COLUMNS = (
    "image",
    "marker",
    "label_name",
    "label_value",
    "label_unit",
    "verdict",
    "printed_name",
    "printed_value",
    "printed_unit",
    "note",
)


def chosen(seed: int = SEED) -> list[str]:
    """The images checked: SIZE of the scored set, drawn with the seed."""
    images = sorted(row["image"] for row in medrepbench.read_set())
    picks = np.random.default_rng(seed).choice(images, size=SIZE, replace=False)
    return sorted(str(image) for image in picks)


def marker_rows(items: str) -> list[dict[str, str]]:
    """Every labelled row that maps to a clock marker, in printed order."""
    rows = []
    for item in json.loads(items):
        unit = item["item_unit"] or None
        marker = match(item["item_name"], unit)
        if marker in MARKERS:
            rows.append(
                {
                    "marker": marker,
                    "label_name": item["item_name"],
                    "label_value": item["item_value"],
                    "label_unit": item["item_unit"] or "",
                }
            )
    return rows


def reports(cache: Path = medrepbench.CACHE) -> list[tuple[str, list[dict]]]:
    labels = pd.read_csv(medrepbench.labels(cache)).set_index("image")
    return [(image, marker_rows(labels.at[image, "items"])) for image in chosen()]


_STYLE = """
:root { --bg: #fff; --fg: #1a1a1a; --muted: #666; --line: #ddd; --ok: #1a7f37;
  --bad: #cf222e; --card: #f6f8fa; }
@media (prefers-color-scheme: dark) { :root { --bg: #0d1117; --fg: #e6edf3;
  --muted: #8b949e; --line: #30363d; --ok: #3fb950; --bad: #f85149; --card: #161b22; } }
body { background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif;
  margin: 0 auto; max-width: 1400px; padding: 16px; }
header { position: sticky; top: 0; background: var(--bg); padding: 8px 0;
  border-bottom: 1px solid var(--line); display: flex; gap: 16px; align-items: center;
  flex-wrap: wrap; z-index: 1; }
section { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 16px; border-bottom: 1px solid var(--line); padding: 24px 0; }
@media (max-width: 900px) { section { grid-template-columns: 1fr; } }
section img { width: 100%; border: 1px solid var(--line); cursor: zoom-in; }
h2 { font-size: 15px; margin: 0 0 8px; word-break: break-all; }
.row { background: var(--card); border: 1px solid var(--line); border-radius: 6px;
  padding: 8px; margin-bottom: 8px; }
.label { font-family: ui-monospace, monospace; }
.muted { color: var(--muted); font-size: 13px; }
.row.correct { border-color: var(--ok); } .row.wrong { border-color: var(--bad); }
.fix { display: none; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.row.wrong .fix { display: flex; }
input[type=text] { font: inherit; padding: 4px; min-width: 0; flex: 1 1 120px;
  background: var(--bg); color: var(--fg); border: 1px solid var(--line); }
button { font: inherit; padding: 6px 12px; cursor: pointer; }
textarea { width: 100%; box-sizing: border-box; font: inherit; background: var(--bg);
  color: var(--fg); border: 1px solid var(--line); }
"""

_SCRIPT = """
const KEY = "lab2clock-audit";
const COLUMNS = %(columns)s;
let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
  const rows = document.querySelectorAll(".row");
  const done = [...rows].filter(r => (saved[r.id] || {}).verdict).length;
  document.getElementById("progress").textContent =
    done + " of " + rows.length + " rows checked";
}
document.querySelectorAll(".row").forEach(row => {
  const state = saved[row.id] || {};
  row.querySelectorAll("input").forEach(input => {
    if (input.type === "radio") {
      input.checked = state.verdict === input.value;
      input.addEventListener("change", () => {
        saved[row.id] = {...(saved[row.id] || {}), verdict: input.value};
        row.className = "row " + input.value; save();
      });
    } else {
      input.value = state[input.name] || "";
      input.addEventListener("input", () => {
        saved[row.id] = {...(saved[row.id] || {}), [input.name]: input.value}; save();
      });
    }
  });
  if (state.verdict) row.className = "row " + state.verdict;
});
document.querySelectorAll("textarea").forEach(area => {
  area.value = (saved[area.id] || {}).note || "";
  area.addEventListener("input", () => {
    saved[area.id] = {note: area.value}; save();
  });
});
function cell(value) {
  value = value == null ? "" : String(value);
  return /[",\\n]/.test(value) ? '"' + value.replace(/"/g, '""') + '"' : value;
}
document.getElementById("download").addEventListener("click", () => {
  const lines = [COLUMNS.join(",")];
  document.querySelectorAll(".row").forEach(row => {
    const s = saved[row.id] || {};
    const d = row.dataset;
    lines.push([d.image, d.marker, d.name, d.value, d.unit, s.verdict, s.printed_name,
      s.printed_value, s.printed_unit, s.note].map(cell).join(","));
  });
  document.querySelectorAll("textarea").forEach(area => {
    const note = (saved[area.id] || {}).note;
    if (note && note.trim()) lines.push([area.dataset.image, "", "", "", "", "missing",
      "", "", "", note.trim()].map(cell).join(","));
  });
  const blob = new Blob([lines.join("\\n") + "\\n"], {type: "text/csv"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "medrepbench_audit.csv";
  link.click();
});
save();
"""


def page(checked: list[tuple[str, list[dict]]]) -> str:
    """The review page: each image beside its marker rows to judge."""
    sections = []
    for r, (image, rows) in enumerate(checked):
        cards = []
        for i, row in enumerate(rows):
            data = {
                "image": image,
                "marker": row["marker"],
                "name": row["label_name"],
                "value": row["label_value"],
                "unit": row["label_unit"],
            }
            attributes = " ".join(
                f'data-{key}="{html.escape(value)}"' for key, value in data.items()
            )
            label = " ".join(
                html.escape(part)
                for part in (row["label_name"], row["label_value"], row["label_unit"])
                if part
            )
            cards.append(
                f'<div class="row" id="r{r}-{i}" {attributes}>'
                f'<div class="label">{label}</div>'
                f'<div class="muted">{html.escape(row["marker"])}</div>'
                f'<label><input type="radio" name="v{r}-{i}" value="correct"> '
                "Correct</label> "
                f'<label><input type="radio" name="v{r}-{i}" value="wrong"> '
                "Wrong</label>"
                '<div class="fix">'
                '<input type="text" name="printed_name" placeholder="name as printed">'
                '<input type="text" name="printed_value" '
                'placeholder="value as printed">'
                '<input type="text" name="printed_unit" placeholder="unit as printed">'
                '<input type="text" name="note" placeholder="note">'
                "</div></div>"
            )
        src = html.escape(f"censored/{image}")
        sections.append(
            f'<section><a href="{src}" target="_blank"><img src="{src}" '
            f'alt="{html.escape(image)}"></a><div><h2>{r + 1}. '
            f"{html.escape(image)}</h2>{''.join(cards)}"
            '<p class="muted">Clock markers printed on the image but missing '
            "above, one per line, as printed:</p>"
            f'<textarea id="m{r}" data-image="{html.escape(image)}" rows="2">'
            "</textarea></div></section>"
        )
    script = _SCRIPT % {"columns": json.dumps(COLUMNS)}
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Label check</title><style>{_STYLE}</style></head><body>"
        "<header><strong>MedRepBench label check</strong>"
        '<span id="progress" class="muted"></span>'
        '<button id="download">Download CSV</button></header>'
        "<p>For each row, compare the label's name, value and unit with what the "
        "image prints. Mark it correct only if all three match the printed text "
        "exactly, apart from spacing. If it is wrong, type what is printed. Click "
        "an image to open it full size. Answers are kept in this browser; when "
        "done, download the CSV and save it as "
        "<code>bench/medrepbench_audit.csv</code>.</p>"
        f"{''.join(sections)}<script>{script}</script></body></html>"
    )


def score(path: Path = RESULTS) -> dict[str, object]:
    """The label error rate: wrong rows over judged rows, which fields were
    wrong in them, and printed markers missing from the labels. A wrong row
    gives every field as printed, an empty unit where none is printed."""
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    judged = [row for row in rows if row["verdict"] in {"correct", "wrong"}]
    wrong = [row for row in judged if row["verdict"] == "wrong"]
    missing = [row for row in rows if row["verdict"] == "missing"]
    unjudged = [row for row in rows if row["marker"] and not row["verdict"]]
    if unjudged:
        raise ValueError(f"{len(unjudged)} rows in {path} have no verdict")
    return {
        "reports": len({row["image"] for row in rows}),
        "judged": len(judged),
        "wrong": len(wrong),
        "fields": {
            field: sum(
                row[f"printed_{field}"].strip() != row[f"label_{field}"].strip()
                for row in wrong
            )
            for field in ("name", "value", "unit")
        },
        "missing": len(missing),
        "interval": wilson(len(wrong), len(judged)),
    }


def main() -> None:
    if sys.argv[1:] == ["score"]:
        result = score()
        low, high = result["interval"]
        print(
            f"{result['wrong']} of {result['judged']} marker labels wrong in "
            f"{result['reports']} reports ({result['wrong'] / result['judged']:.1%}, "
            f"Wilson 95% {low:.1%} to {high:.1%}); "
            f"{result['missing']} printed markers missing from the labels"
        )
        fields = ", ".join(f"{n} {f}" for f, n in result["fields"].items())
        print(f"wrong fields: {fields}")
        return
    if sys.argv[1:]:
        raise SystemExit("usage: python -m bench.audit [score]")
    checked = reports()
    PAGE.write_text(page(checked), encoding="utf-8")
    rows = sum(len(rows) for _, rows in checked)
    print(f"wrote {PAGE}: {len(checked)} reports, {rows} marker rows to check")


if __name__ == "__main__":
    main()

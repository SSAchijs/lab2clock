"""Check that every printed PDF says exactly what its render spec says.

A generator bug would silently corrupt the ground truth, and the model would
get the blame. So the text layer of each PDF is read back with PyMuPDF and
every spec row must be printed as its own line, on its own page: name,
value, flag, previous result, unit and reference interval, in column order.
In the two-column layout the interval is the next line in the same column.
Finding each value somewhere on the page would not be enough: 4.2 appears in
many places, and a value printed in the wrong row must fail.

Words are grouped into lines by their top edge; in the two-column layout
each half of the page is grouped on its own. Photos are made from these
PDFs, so checking the PDFs covers them too.

Needs the PDFs from bench.pdf, which runs this check after printing. On its
own:

    uv run python -m bench.selfcheck
"""

import sys
from pathlib import Path

import pymupdf

from bench import render
from bench.spec import RENDER_SPEC, PrintedRow, RenderSpec

# Words whose top edges are this close, in points, share a line.
LINE_TOLERANCE = 2.5


def lines(page: pymupdf.Page, columns: int) -> list[list[str]]:
    """Each column's lines of text, top to bottom, each line's words joined."""
    width = page.rect.width / columns
    found: list[list[str]] = []
    for column in range(columns):
        words = [
            w
            for w in page.get_text("words")
            if column * width <= w[0] < (column + 1) * width
        ]
        words.sort(key=lambda w: (w[1], w[0]))
        rows: list[list[tuple]] = []
        for word in words:
            if rows and word[1] - rows[-1][0][1] <= LINE_TOLERANCE:
                rows[-1].append(word)
            else:
                rows.append([word])
        found.append(
            [" ".join(w[4] for w in sorted(row, key=lambda w: w[0])) for row in rows]
        )
    return found


def expected(spec: RenderSpec, row: PrintedRow) -> list[str]:
    """The line or lines `row` prints, as the layout arranges it."""
    if spec.conditions.layout == "two_column":
        label = render.LABELS[spec.conditions.language]["reference"]
        cells = [row.name, row.value, row.flag, row.unit]
        return [join(cells), f"{label}: {row.reference}"]
    cells = [row.name, row.value, row.flag, row.previous, row.unit, row.reference]
    return [join(cells)]


def join(cells: list[str | None]) -> str:
    return " ".join(cell for cell in cells if cell)


def check(spec: RenderSpec, pdf: Path) -> list[str]:
    """Every way the PDF at `pdf` differs from `spec`; empty when it matches."""
    columns = 2 if spec.conditions.layout == "two_column" else 1
    problems = []
    with pymupdf.open(pdf) as doc:
        pages = sorted({row.page for row in spec.rows})
        if len(doc) != len(pages):
            problems.append(f"{len(doc)} pages printed, {len(pages)} expected")
            return problems
        printed = {number: lines(doc[i], columns) for i, number in enumerate(pages)}
    for i, row in enumerate(spec.rows):
        want = expected(spec, row)
        if not any(
            column[j : j + len(want)] == want
            for column in printed[row.page]
            for j in range(len(column))
        ):
            problems.append(f"row {i} not printed on page {row.page}: {want}")
    return problems


def check_all(reports: Path = render.OUT) -> dict[str, list[str]]:
    """Each report's problems, for every render spec."""
    results = {}
    for path in sorted(RENDER_SPEC.glob("*.json")):
        spec = RenderSpec.model_validate_json(path.read_text())
        pdf = reports / f"{spec.report}.pdf"
        if not pdf.exists():
            results[spec.report] = [f"{pdf} is missing; run bench.pdf first"]
            continue
        results[spec.report] = check(spec, pdf)
    return results


def main() -> None:
    results = check_all()
    failed = {report: p for report, p in results.items() if p}
    for report, problems in failed.items():
        for problem in problems:
            print(f"{report}: {problem}")
    if failed:
        sys.exit(f"{len(failed)} of {len(results)} reports differ from their spec")
    print(f"all {len(results)} reports print every row of their spec")


if __name__ == "__main__":
    main()

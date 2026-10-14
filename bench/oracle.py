"""The oracle: a perfect reader, as a stage-1 extractor that never errs.

It reads each report's render spec and returns exactly what a flawless model
would transcribe from the printed page, in the stage-1 shape. bench.selfcheck
proves every PDF prints its spec row by row, so the spec is what the page says.

Run through the code stages and the scorer, the oracle must score 100%. Any
shortfall is a bug in the generator, the core or the scorer, found before a
paid model is called.

    uv run python -m bench.oracle

writes results/responses/oracle/R01.json and so on, one stage-1 report each,
where the scorer reads every extractor's responses.
"""

import json
from pathlib import Path

from bench.spec import RENDER_SPEC, RenderSpec
from lab2clock.stage1 import RawItem, RawReport

RESPONSES = Path(__file__).resolve().parent.parent / "results" / "responses"
OUT = RESPONSES / "oracle"


def extract(spec: RenderSpec) -> RawReport:
    """What a perfect reader returns for this report.

    Only what is printed in the current-result column reaches the reader: the
    name, value, unit and page. A two-column list prints the flag in the result
    cell (146 H), so it is part of the value as printed; the other layouts give
    it its own column.
    """
    items = []
    for row in spec.rows:
        item = RawItem(**row.model_dump(include=set(RawItem.model_fields)))
        if row.flag and spec.conditions.layout == "two_column":
            item.value = f"{row.value} {row.flag}"
        items.append(item)
    return RawReport(items=items)


def write(report: str, response: RawReport, out: Path = OUT) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{report}.json"
    text = json.dumps(response.model_dump(mode="json"), indent=2, ensure_ascii=False)
    path.write_text(text + "\n")
    return path


def main() -> None:
    paths = sorted(RENDER_SPEC.glob("*.json"))
    for path in paths:
        spec = RenderSpec.model_validate_json(path.read_text())
        write(spec.report, extract(spec))
    print(f"wrote {len(paths)} oracle responses to {OUT}")


if __name__ == "__main__":
    main()

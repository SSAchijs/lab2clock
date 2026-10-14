"""Command line: lab2clock REPORT... --age YEARS [--age-estimate]

REPORT is a lab report as a PDF, or one photo per page (PNG or JPEG) in page
order, which Claude reads first; or a stage-1 JSON file (- for standard
input), which is used as it is. Prints the output JSON.

--age-estimate adds the PhenoAge the clock inputs give, when all ten are
there, or the range they allow when one was printed below a limit. It is a
model estimate from one blood test, not a diagnosis.

Exit status: 0 when the report is ok, 1 when it has errors (the output is still
printed, listing them), 2 when the input could not be read.
"""

import argparse
import json
import sys
from itertools import product
from pathlib import Path
from typing import Any

from lab2clock.assemble import assemble
from lab2clock.clock_spec import BY_NAME
from lab2clock.config import load_env
from lab2clock.phenoage import phenoage
from lab2clock.stage1 import RawReport

ESTIMATE_NOTE = (
    "PhenoAge (Levine 2018) computed from these inputs: a statistical estimate "
    "from one blood test, not a diagnosis. Results vary between tests and labs."
)


def _stage1(paths: list[str], model: str | None) -> RawReport:
    """The stage-1 report: read from a JSON file, or by Claude from the files."""
    if len(paths) == 1 and (paths[0] == "-" or paths[0].endswith(".json")):
        if paths[0] == "-":
            text = sys.stdin.read()
        else:
            text = Path(paths[0]).read_text(encoding="utf-8")
        return RawReport.model_validate_json(text)
    # Imported here, so reading a stage-1 file needs no API client.
    from lab2clock.read import MODEL, read_report

    load_env()
    return read_report([Path(p) for p in paths], model or MODEL)


# The oldest verified human lived to 122.
MAX_AGE = 125


def _age(text: str) -> float:
    """An age in years, refused unless above 0 and at most MAX_AGE."""
    try:
        age = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 0 < age <= MAX_AGE:
        raise argparse.ArgumentTypeError(
            f"{text} is not an age in years (above 0, at most {MAX_AGE})"
        )
    return age


def estimate(output: dict[str, Any]) -> dict[str, Any] | None:
    """The PhenoAge of a complete output, with what it is; None if incomplete.

    An input printed below a limit, such as CRP <5.00 mg/L, lies anywhere from
    the clock's lowest possible value up to the limit, so the age is a range:
    PhenoAge moves one way with each input, so its ends are at the ends of
    those inputs' ranges.
    """
    if not output["ok"]:
        return None
    inputs = {name: field["value"] for name, field in output["inputs"].items()}
    below = [
        name for name, field in output["inputs"].items() if field.get("limit") == "<"
    ]
    if not below:
        return {"years": round(phenoage(**inputs), 1), "note": ESTIMATE_NOTE}
    ages = [
        phenoage(**{**inputs, **dict(zip(below, ends, strict=True))})
        for ends in product(*[(BY_NAME[name].error[0], inputs[name]) for name in below])
    ]
    printed = ", ".join(
        f"{output['inputs'][name]['source']['name']} "
        f"{output['inputs'][name]['source']['value']}"
        for name in below
    )
    return {
        "years": None,
        "range": [round(min(ages), 1), round(max(ages), 1)],
        "note": f"{ESTIMATE_NOTE} Printed below a limit ({printed}), so only a "
        "range can be given.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lab2clock",
        description="Turn a lab report into PhenoAge clock inputs.",
    )
    parser.add_argument(
        "report",
        nargs="+",
        help="a PDF, one image per page, or a stage-1 JSON file (- for stdin)",
    )
    parser.add_argument("--age", type=_age, help="the patient's age in years")
    parser.add_argument("--model", help="the Claude model that reads the report")
    parser.add_argument(
        "--age-estimate",
        action="store_true",
        help="also print the PhenoAge the inputs give, when all ten are there",
    )
    args = parser.parse_args(argv)

    try:
        report = _stage1(args.report, args.model)
    except (OSError, ValueError) as error:
        # ValueError covers a stage-1 file that fails validation and a report
        # Claude could not read into one.
        print(f"lab2clock: {error}", file=sys.stderr)
        return 2

    output = assemble(report, age=args.age)
    if args.age_estimate:
        output["phenoage"] = estimate(output)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

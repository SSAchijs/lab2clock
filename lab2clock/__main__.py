"""Command line: python -m lab2clock REPORT.json --age YEARS

Reads a stage-1 JSON file (- for standard input) and prints the output JSON.
Exit status: 0 when the report is ok, 1 when it has errors (the output is still
printed, listing them), 2 when the input is not a valid stage-1 report.
"""

import argparse
import json
import sys

from pydantic import ValidationError

from lab2clock.assemble import assemble
from lab2clock.stage1 import RawReport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lab2clock",
        description="Turn a stage-1 lab report into PhenoAge clock inputs.",
    )
    parser.add_argument("report", help="stage-1 JSON file, or - for standard input")
    parser.add_argument("--age", type=float, help="the patient's age in years")
    args = parser.parse_args(argv)

    try:
        if args.report == "-":
            text = sys.stdin.read()
        else:
            with open(args.report, encoding="utf-8") as file:
                text = file.read()
        report = RawReport.model_validate_json(text)
    except (OSError, ValidationError) as error:
        print(f"lab2clock: {error}", file=sys.stderr)
        return 2

    output = assemble(report, age=args.age)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

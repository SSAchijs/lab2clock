"""Stage 1 by a model: one call per report, its answer held to the stage-1 schema.

The API's structured-output mode constrains the answer to the stage-1 JSON
schema from lab2clock.stage1, so the model and the validator share one
definition. The API cannot enforce every rule in it: it drops the string and
number limits (a name of at least one character, a page from 1), and a refusal
or an answer cut off at the token limit need not fit the schema at all. So
every answer is validated again against the full model.

Each report is sent in its native form, as a real app would receive it: a
digital report as its PDF, so the model can use the text layer, and a
photographed one as its photos, one JPEG per page, each after a line naming
its page, as an app knows the order the photos were taken in. The response
records which form was sent and the files.

An answer that fails is retried once. A second failure is recorded, with what
the model wrote, and the report is scored as invalid. A model that cannot keep
to the schema is a failure mode worth counting; retrying until it does would
hide it.

Every response is saved where the scorer reads it, and the saved responses
are the cache. Each holds a key: the SHA-256 of every file sent, the model,
the prompt and its text, the settings and the run. A rerun skips a report
whose saved key matches, so it makes no API call. A saved response with a
different key was read from something else, such as a regenerated PDF or a
changed setting, and the run stops rather than mix it with new ones.

    uv run python -m bench.extract cheap --split dev --run 1

reads every development report with Claude Haiku 5.5 into
results/responses/claude-haiku-5-5_extract_v1/1/.
"""

import argparse
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from bench import degrade, prompts, render, responses
from bench.models import MODELS
from bench.prompts import Prompt
from bench.responses import RESPONSES, Failure, Form, Response, Usage
from bench.spec import RENDER_SPEC, RenderSpec
from lab2clock.config import load_env
from lab2clock.stage1 import RawReport, json_schema

# The stage-1 schema as the API accepts it: the limits it cannot enforce move
# into the field descriptions, and the full model still checks them.
SCHEMA = anthropic.transform_schema(json_schema())

# A report is a few dozen rows, far below this, but thinking counts toward it.
MAX_TOKENS = 16_000

# The first answer and one retry.
ATTEMPTS = 2


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Everything besides the model, prompt and files that can change an answer.
SETTINGS = {
    "max_tokens": MAX_TOKENS,
    "attempts": ATTEMPTS,
    "schema_sha256": _sha256(json.dumps(SCHEMA, sort_keys=True).encode()),
}


@dataclass(frozen=True)
class Input:
    """A report as sent to the model: its form, its files, the content blocks."""

    form: Form
    files: list[Path]
    content: list[dict[str, Any]]


def _base64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("ascii")


def report_input(spec: RenderSpec) -> Input:
    """The report in its native form: its photos if photographed, else its PDF."""
    if not spec.conditions.photo:
        pdf = render.OUT / f"{spec.report}.pdf"
        source = {"type": "base64", "media_type": "application/pdf"}
        block = {"type": "document", "source": source | {"data": _base64(pdf)}}
        return Input("pdf", [pdf], [block])
    files, content = [], []
    for page in sorted({row.page for row in spec.rows}):
        photo = degrade.OUT / f"{spec.report}-{page}.jpg"
        source = {"type": "base64", "media_type": "image/jpeg"}
        files.append(photo)
        content += [
            {"type": "text", "text": f"Page {page}"},
            {"type": "image", "source": source | {"data": _base64(photo)}},
        ]
    return Input("photo", files, content)


def _report(message: Any) -> RawReport:
    """The stage-1 report in a model's answer; ValueError if there is none."""
    if message.stop_reason != "end_turn":
        raise ValueError(f"the answer stopped with {message.stop_reason}")
    return RawReport.model_validate_json(_text(message))


def _text(message: Any) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def key(model: str, prompt: Prompt, sent: Input, run: int) -> str:
    """The SHA-256 of everything a response was read from."""
    identity = {
        "model": model,
        "prompt": prompt.version,
        "prompt_sha256": prompt.sha256,
        "settings": SETTINGS,
        "form": sent.form,
        "files": _hashes(sent),
        "run": run,
    }
    return _sha256(json.dumps(identity, sort_keys=True).encode())


def _hashes(sent: Input) -> dict[str, str]:
    return {path.name: _sha256(path.read_bytes()) for path in sent.files}


def read(
    client: anthropic.Anthropic,
    model: str,
    prompt: Prompt,
    sent: Input,
    run: int,
) -> Response:
    """One report read by a model: the prompt as the system message, the
    report as the user message, the answer held to the stage-1 schema."""
    failures, report = [], None
    input_tokens = output_tokens = 0
    for _ in range(ATTEMPTS):
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=prompt.text,
            messages=[{"role": "user", "content": sent.content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        input_tokens += message.usage.input_tokens
        output_tokens += message.usage.output_tokens
        try:
            report = _report(message)
            break
        except (ValueError, ValidationError) as error:
            failures.append(Failure(reason=str(error), output=_text(message)))
    return Response(
        key=key(model, prompt, sent, run),
        model=model,
        prompt=prompt.version,
        prompt_sha256=prompt.sha256,
        settings=SETTINGS,
        form=sent.form,
        files=_hashes(sent),
        report=report,
        failures=failures,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def extractor(model: str, prompt: Prompt) -> str:
    """The directory a model's responses with a prompt are saved in."""
    return f"{model}_{prompt.version}"


def run(
    client: anthropic.Anthropic,
    model: str,
    prompt: Prompt,
    specs: list[RenderSpec],
    number: int,
    root: Path = RESPONSES,
) -> tuple[int, int]:
    """Read every report not already saved; how many were read and cached."""
    out = root / extractor(model, prompt) / str(number)
    read_count = cached = 0
    for spec in specs:
        sent = report_input(spec)
        path = out / f"{spec.report}.json"
        if path.exists():
            if responses.read(path).key != key(model, prompt, sent, number):
                raise SystemExit(
                    f"{path} was read from different inputs; delete it to read "
                    "the report again"
                )
            cached += 1
            continue
        responses.write(spec.report, read(client, model, prompt, sent, number), out)
        read_count += 1
    return read_count, cached


def main() -> None:
    parser = argparse.ArgumentParser(description="Read the reports with a model.")
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args()
    load_env()
    model, prompt = MODELS[args.model].id, prompts.load()
    specs = [
        spec
        for path in sorted(RENDER_SPEC.glob("*.json"))
        if (spec := RenderSpec.model_validate_json(path.read_text())).split
        == args.split
    ]
    read_count, cached = run(anthropic.Anthropic(), model, prompt, specs, args.run)
    print(
        f"{extractor(model, prompt)} run {args.run}: read {read_count} reports, "
        f"{cached} from the cache"
    )


if __name__ == "__main__":
    main()

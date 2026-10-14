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
"""

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from bench import degrade, render
from bench.prompts import Prompt
from bench.responses import Failure, Form, Response
from bench.spec import RenderSpec
from lab2clock.stage1 import RawReport, json_schema

# The stage-1 schema as the API accepts it: the limits it cannot enforce move
# into the field descriptions, and the full model still checks them.
SCHEMA = anthropic.transform_schema(json_schema())

# A report is a few dozen rows, far below this, but thinking counts toward it.
MAX_TOKENS = 16_000

# The first answer and one retry.
ATTEMPTS = 2


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


def read(
    client: anthropic.Anthropic,
    model: str,
    prompt: Prompt,
    sent: Input,
) -> Response:
    """One report read by a model: the prompt as the system message, the
    report as the user message, the answer held to the stage-1 schema."""
    failures = []
    files = [path.name for path in sent.files]
    for _ in range(ATTEMPTS):
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=prompt.text,
            messages=[{"role": "user", "content": sent.content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        try:
            report = _report(message)
        except (ValueError, ValidationError) as error:
            failures.append(Failure(reason=str(error), output=_text(message)))
            continue
        return Response.of(report, prompt, failures, sent.form, files)
    return Response.of(None, prompt, failures, sent.form, files)

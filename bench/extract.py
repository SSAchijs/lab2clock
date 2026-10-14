"""Stage 1 by a model: one call per report, its answer held to the stage-1 schema.

The API's structured-output mode constrains the answer to the stage-1 JSON
schema from lab2clock.stage1, so the model and the validator share one
definition. The API cannot enforce every rule in it: it drops the string and
number limits (a name of at least one character, a page from 1), and a refusal
or an answer cut off at the token limit need not fit the schema at all. So
every answer is validated again against the full model.

An answer that fails is retried once. A second failure is recorded, with what
the model wrote, and the report is scored as invalid. A model that cannot keep
to the schema is a failure mode worth counting; retrying until it does would
hide it.
"""

from typing import Any

import anthropic
from pydantic import ValidationError

from bench.prompts import Prompt
from bench.responses import Failure, Response
from lab2clock.stage1 import RawReport, json_schema

# The stage-1 schema as the API accepts it: the limits it cannot enforce move
# into the field descriptions, and the full model still checks them.
SCHEMA = anthropic.transform_schema(json_schema())

# A report is a few dozen rows, far below this, but thinking counts toward it.
MAX_TOKENS = 16_000

# The first answer and one retry.
ATTEMPTS = 2


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
    content: list[dict[str, Any]],
) -> Response:
    """One report read by a model: the prompt as the system message, the
    report's pages as the user message, the answer held to the stage-1 schema."""
    failures = []
    for _ in range(ATTEMPTS):
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=prompt.text,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        try:
            return Response.of(_report(message), prompt, failures)
        except (ValueError, ValidationError) as error:
            failures.append(Failure(reason=str(error), output=_text(message)))
    return Response.of(None, prompt, failures)

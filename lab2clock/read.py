"""Stage 1 on a report of your own: a PDF or page images, read by Claude.

The call is the benchmark's: the frozen prompt as the system message, the
report as the user message, the answer held to the stage-1 schema by the API
and checked again in full here, with one retry. bench.extract imports these
settings from here, so a report read with this module is read as the scored
ones were. It needs ANTHROPIC_API_KEY, in the environment or in .env.

The default model is Claude Haiku 5.5: on the real reports it read as well
as Claude Opus 5.5 at about a thirtieth of the price.
"""

import base64
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from lab2clock.stage1 import RawReport, json_schema

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "extract_v1.txt"

MODEL = "claude-haiku-5-5"

# The stage-1 schema as the API accepts it: the limits it cannot enforce move
# into the field descriptions, and the full model still checks them.
SCHEMA = anthropic.transform_schema(json_schema())

# A report is a few dozen rows, far below this, but thinking counts toward it.
MAX_TOKENS = 16_000

# The first answer and one retry.
ATTEMPTS = 2

# Pinned, so a changed default cannot change an answer. Effort is not a
# randomness setting; medium is both models' default, kept rather than tuned.
EFFORT = "medium"
THINKING = {"type": "adaptive"}

# The API refuses an image over 10 MB once base64-encoded.
MAX_IMAGE = 10 * 1024 * 1024

# A file's type by its first bytes, not its name.
SIGNATURES = {
    b"%PDF": "application/pdf",
    b"\x89PNG": "image/png",
    b"\xff\xd8": "image/jpeg",
}


class ReadError(ValueError):
    """A report that could not be sent, or whose answer never fit the schema."""


def media_type(data: bytes) -> str:
    for signature, media in SIGNATURES.items():
        if data.startswith(signature):
            return media
    raise ReadError(f"not a PDF, PNG or JPEG file: {data[:8]!r}")


def content(paths: list[Path]) -> list[dict[str, Any]]:
    """The report as the user message: one PDF, or one image per page, each
    after a line naming its page, in the order given."""
    files = [(path, path.read_bytes()) for path in paths]
    kinds = [media_type(data) for _, data in files]
    if "application/pdf" in kinds:
        if len(files) > 1:
            raise ReadError("send one PDF, or one image per page")
        source = {"type": "base64", "media_type": kinds[0]}
        return [{"type": "document", "source": source | {"data": _b64(files[0][1])}}]
    blocks = []
    for page, ((path, data), media) in enumerate(
        zip(files, kinds, strict=True), start=1
    ):
        encoded = _b64(data)
        if len(encoded) > MAX_IMAGE:
            raise ReadError(f"{path} is over 10 MB once encoded; send a smaller image")
        source = {"type": "base64", "media_type": media, "data": encoded}
        blocks += [
            {"type": "text", "text": f"Page {page}"},
            {"type": "image", "source": source},
        ]
    return blocks


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")


def request(model: str, prompt: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """The arguments of one Messages API call that reads a report."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": prompt,
        "messages": [{"role": "user", "content": blocks}],
        "thinking": THINKING,
        "output_config": {
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
    }


def answer(message: Any) -> RawReport:
    """The stage-1 report in a model's answer; ValueError if there is none."""
    if message.stop_reason != "end_turn":
        raise ValueError(f"the answer stopped with {message.stop_reason}")
    return RawReport.model_validate_json(text(message))


def text(message: Any) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def read_report(paths: list[Path], model: str = MODEL, client: Any = None) -> RawReport:
    """Read a report with Claude into a stage-1 report."""
    call = request(model, PROMPT.read_text(encoding="utf-8"), content(paths))
    reasons = []
    try:
        client = client or anthropic.Anthropic()
        for _ in range(ATTEMPTS):
            message = client.messages.create(**call)
            try:
                return answer(message)
            except (ValueError, ValidationError) as error:
                reasons.append(str(error))
    except anthropic.AnthropicError as error:
        # Such as no API key, or the API refusing the call.
        raise ReadError(f"{type(error).__name__}: {error}") from error
    raise ReadError(f"no valid answer in {ATTEMPTS} attempts: {reasons[-1]}")

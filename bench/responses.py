"""A stage-1 response as saved on disk: what was read, and the prompt it was read with.

Each extractor's responses live in results/responses/<extractor>/<run>/, one
file per report, where the scorer reads them. The oracle reads without a
prompt, so it records none. A model's response also records what it was
read from: the model, the settings, the form the report was sent in, a PDF or
photos, and each file sent with its SHA-256, all folded into one key. The
saved responses are the cache: a rerun skips a report whose saved key matches,
so rescoring never calls the API. The oracle reads the render spec, so it
records none of these.

An answer that breaks the stage-1 schema is kept as a failure, with what the
model wrote, even when a retry then succeeds. After a second failure there is
no report, and the scorer counts the response as invalid.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from bench.prompts import Prompt
from lab2clock.stage1 import RawReport

RESPONSES = Path(__file__).resolve().parent.parent / "results" / "responses"

# A digital report goes as its PDF, a photographed one as its photos, and a
# real one as the image it came as, a photo or a screenshot.
Form = Literal["pdf", "photo", "image"]


class Failure(BaseModel):
    """One answer that did not fit the stage-1 schema, and why."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    output: str


class Usage(BaseModel):
    """Tokens billed for a response, over every attempt."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int
    output_tokens: int


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    model: str | None = None
    prompt: str | None
    prompt_sha256: str | None
    settings: dict[str, Any] = {}
    form: Form | None = None
    files: dict[str, str] = {}
    report: RawReport | None
    failures: list[Failure] = []
    usage: Usage | None = None

    @model_validator(mode="after")
    def _complete(self) -> "Response":
        if (self.prompt is None) != (self.prompt_sha256 is None):
            raise ValueError("a prompt version needs its hash, and a hash its version")
        if self.report is None and not self.failures:
            raise ValueError("a response without a report must say why it failed")
        return self

    @classmethod
    def of(
        cls,
        report: RawReport | None,
        prompt: Prompt | None = None,
        failures: list[Failure] | None = None,
    ) -> "Response":
        return cls(
            prompt=prompt.version if prompt else None,
            prompt_sha256=prompt.sha256 if prompt else None,
            report=report,
            failures=failures or [],
        )


def write(report: str, response: Response, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{report}.json"
    text = response.model_dump_json(indent=2)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read(path: Path) -> Response:
    return Response.model_validate_json(path.read_text(encoding="utf-8"))

"""A stage-1 response as saved on disk: what was read, and the prompt it was read with.

Each extractor's responses live in results/responses/<extractor>/<run>/, one
file per report, where the scorer reads them. The oracle reads without a
prompt, so it records none.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from bench.prompts import Prompt
from lab2clock.stage1 import RawReport

RESPONSES = Path(__file__).resolve().parent.parent / "results" / "responses"


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str | None
    prompt_sha256: str | None
    report: RawReport

    @model_validator(mode="after")
    def _prompt_and_hash_together(self) -> "Response":
        if (self.prompt is None) != (self.prompt_sha256 is None):
            raise ValueError("a prompt version needs its hash, and a hash its version")
        return self

    @classmethod
    def of(cls, report: RawReport, prompt: Prompt | None = None) -> "Response":
        if prompt is None:
            return cls(prompt=None, prompt_sha256=None, report=report)
        return cls(prompt=prompt.version, prompt_sha256=prompt.sha256, report=report)


def write(report: str, response: Response, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{report}.json"
    text = response.model_dump_json(indent=2)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read(path: Path) -> Response:
    return Response.model_validate_json(path.read_text(encoding="utf-8"))

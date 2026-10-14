"""The two models that read the reports at stage 1, and what was served on the day.

Two models give two points on the cost-versus-accuracy curve, and a failure
both share is one no model choice fixes:

- frontier: Claude Opus 5.5, the current Opus, at $4 / $20 per million input
  and output tokens.
- cheap: Claude Haiku 5.5, the current Haiku, at $0.10 / $0.50, about 40 times
  cheaper. Above 100K prompt tokens Haiku costs $0.50 / $2.50, but a report is
  a few pages, far below that.

Neither model has a dated snapshot ID; the alias is the whole name the API
takes. So the name alone does not say which model answered on a given day.
Before a run, this module asks the Models API for each model's record and
writes it, with the date and the SDK version, to results/models.json:

    uv run python -m bench.models

It fails if either model is not served, or cannot take a PDF or an image or
return output in a fixed JSON schema, since stage 1 needs all three.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from lab2clock.config import load_env

RECORD = Path(__file__).resolve().parent.parent / "results" / "models.json"


@dataclass(frozen=True)
class Model:
    id: str
    input_per_mtok: float
    output_per_mtok: float


MODELS = {
    "frontier": Model("claude-opus-5-5", input_per_mtok=4.00, output_per_mtok=20.00),
    "cheap": Model("claude-haiku-5-5", input_per_mtok=0.10, output_per_mtok=0.50),
}

# Stage 1 reads a PDF or a photo and must answer in the stage-1 JSON schema.
REQUIRED = ("pdf_input", "image_input", "structured_outputs")


def record(client: anthropic.Anthropic, model: Model) -> dict[str, object]:
    """The Models API's record of one model, failing if stage 1 cannot use it."""
    served = client.models.retrieve(model.id)
    missing = [c for c in REQUIRED if not getattr(served.capabilities, c).supported]
    if missing:
        raise SystemExit(f"{model.id} does not support {', '.join(missing)}")
    return {
        "id": served.id,
        "display_name": served.display_name,
        "created_at": served.created_at.isoformat(),
        "max_input_tokens": served.max_input_tokens,
        "max_tokens": served.max_tokens,
        "input_per_mtok": model.input_per_mtok,
        "output_per_mtok": model.output_per_mtok,
    }


def write(client: anthropic.Anthropic, path: Path = RECORD) -> dict[str, object]:
    models = {role: record(client, model) for role, model in MODELS.items()}
    out = {
        "retrieved": datetime.now(UTC).date().isoformat(),
        "sdk": f"anthropic {anthropic.__version__}",
        "models": models,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out


def main() -> None:
    load_env()
    out = write(anthropic.Anthropic())
    for role, model in out["models"].items():
        print(f"{role}: {model['id']} ({model['display_name']}, {model['created_at']})")
    print(f"wrote {RECORD}")


if __name__ == "__main__":
    main()

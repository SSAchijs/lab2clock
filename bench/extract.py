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

Neither model offers a setting that lowers randomness: both reject
temperature and top_k, and Opus 5.5 cannot turn thinking off. So every setting
the API does take is pinned, the same for both models, so a changed default
cannot change an answer between runs: medium effort, both models' default,
and adaptive thinking, the only mode Opus 5.5 allows. Each report is then read
three times. Repeats are the only way left to tell an error the model makes
every time from one it makes by chance.

    uv run python -m bench.extract cheap --split dev

reads every development report three times with Claude Haiku 5.5, into
results/responses/claude-haiku-5-5_extract_v1/1/ to 3/. With --split real it
reads the MedRepBench reports, M01 to M39, each sent as the one image it came
as, behind the same frozen-prompt lock as the test set; --split heldout reads
the held-out ones, H001 onwards, the same way.
"""

import argparse
import base64
import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import cv2
import numpy as np
from pydantic import ValidationError

from bench import degrade, medrepbench, prompts, render, responses
from bench.models import MODELS
from bench.prompts import Prompt
from bench.responses import RESPONSES, Failure, Form, Response, Usage
from bench.spec import RENDER_SPEC, RenderSpec
from lab2clock.config import load_env
from lab2clock.read import (
    ATTEMPTS,
    EFFORT,
    MAX_IMAGE,
    MAX_TOKENS,
    SCHEMA,
    THINKING,
    answer,
    request,
    text,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Everything besides the model, prompt and files that can change an answer.
# Each report is read this many times.
RUNS = 3

SETTINGS = {
    "max_tokens": MAX_TOKENS,
    "effort": EFFORT,
    "thinking": THINKING,
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


# An image's type by its first bytes, not its name: some of the dataset's
# .jpg files are PNGs, and the API checks.
SIGNATURES = {b"\x89PNG": "image/png", b"\xff\xd8": "image/jpeg"}


def _media_type(data: bytes) -> str:
    for signature, media in SIGNATURES.items():
        if data.startswith(signature):
            return media
    raise ValueError(f"not a PNG or JPEG image: {data[:8]!r}")


def _image(path: Path) -> tuple[bytes, str]:
    """An image's bytes and media type as sent. One too large for the API is
    re-encoded as a JPEG at the same size, less compressed each time, as a
    real app would have to."""
    data = path.read_bytes()
    media = _media_type(data)
    quality = 95
    while len(base64.b64encode(data)) > MAX_IMAGE:
        pixels = cv2.imdecode(
            np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR
        )
        _, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, quality])
        data, media, quality = encoded.tobytes(), "image/jpeg", quality - 5
    return data, media


def real_input(image: str) -> Input:
    """A real report, sent as the one image it came as."""
    path = medrepbench.CACHE / "censored" / image
    data, media = _image(path)
    source = {
        "type": "base64",
        "media_type": media,
        "data": base64.standard_b64encode(data).decode("ascii"),
    }
    content = [
        {"type": "text", "text": "Page 1"},
        {"type": "image", "source": source},
    ]
    return Input("image", [path], content)


@dataclass(frozen=True)
class Job:
    """One report to read: its ID, its split and how to build what is sent."""

    report: str
    split: str
    sent: Callable[[], Input]


def synthetic_jobs(specs: list[RenderSpec]) -> list[Job]:
    return [Job(s.report, s.split, lambda s=s: report_input(s)) for s in specs]


def real_jobs(split: str = "real") -> list[Job]:
    path = medrepbench.HELDOUT if split == "heldout" else medrepbench.SET
    return [
        Job(row["report"], split, lambda image=row["image"]: real_input(image))
        for row in medrepbench.read_set(path)
    ]


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
        message = client.messages.create(**request(model, prompt.text, sent.content))
        input_tokens += message.usage.input_tokens
        output_tokens += message.usage.output_tokens
        try:
            report = answer(message)
            break
        except (ValueError, ValidationError) as error:
            failures.append(Failure(reason=str(error), output=text(message)))
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
    jobs: list[Job],
    number: int,
    root: Path = RESPONSES,
    workers: int = 1,
) -> tuple[int, int]:
    """Read every report not already saved; how many were read and cached.

    A test or real report is read only with the frozen prompt, so neither set
    is seen while the prompt can still change. With more than one worker,
    reports are read side by side; each is still one call, saved on its own.
    """
    scored = any(job.split in {"test", "real", "heldout"} for job in jobs)
    if scored and not prompts.is_frozen(prompt):
        raise SystemExit(
            f"{prompt.version} is not frozen; tune it on the development reports, "
            "then freeze it with python -m bench.prompts freeze"
        )
    out = root / extractor(model, prompt) / str(number)
    pending = []
    for job in jobs:
        sent = job.sent()
        path = out / f"{job.report}.json"
        if not path.exists():
            pending.append((job, sent))
        elif responses.read(path).key != key(model, prompt, sent, number):
            raise SystemExit(
                f"{path} was read from different inputs; delete it to read "
                "the report again"
            )

    def one(item: tuple[Job, Input]) -> None:
        job, sent = item
        responses.write(job.report, read(client, model, prompt, sent, number), out)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, pending))
    return len(pending), len(jobs) - len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read the reports with a model.")
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument(
        "--split", choices=["dev", "test", "real", "heldout"], required=True
    )
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument(
        "--workers", type=int, default=1, help="reports read side by side"
    )
    args = parser.parse_args()
    load_env()
    model, prompt = MODELS[args.model].id, prompts.load()
    if args.split in ("real", "heldout"):
        jobs = real_jobs(args.split)
    else:
        specs = [
            RenderSpec.model_validate_json(path.read_text())
            for path in sorted(RENDER_SPEC.glob("*.json"))
        ]
        jobs = synthetic_jobs([s for s in specs if s.split == args.split])
    client = anthropic.Anthropic()
    for number in range(1, args.runs + 1):
        read_count, cached = run(
            client, model, prompt, jobs, number, workers=args.workers
        )
        print(
            f"{extractor(model, prompt)} run {number}: read {read_count} reports, "
            f"{cached} from the cache"
        )


if __name__ == "__main__":
    main()

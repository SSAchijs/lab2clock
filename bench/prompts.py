"""The stage-1 prompt, one versioned file per version in prompts/.

Results from different prompts are not comparable, so a prompt is never edited
in place once a response has been recorded with it: a change is a new file,
extract_v2.txt. Every response records the prompt's version and the SHA-256 of
its text, and the scorer refuses an extractor whose responses disagree on
either, so an edit made in place cannot mix two prompts' results silently.

A prompt is tuned on the development reports only. Once it is good enough it
is frozen: its version and SHA-256 are written to prompts/frozen.json and
committed. No test report is read until then, and only with exactly the frozen
prompt, so the git history shows the freeze came before any test response and
the test score is never inflated by tuning on the reports it scores.

    uv run python -m bench.prompts freeze
"""

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CURRENT = "extract_v1"
FROZEN = PROMPTS / "frozen.json"


@dataclass(frozen=True)
class Prompt:
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def load(version: str = CURRENT) -> Prompt:
    return Prompt(version, (PROMPTS / f"{version}.txt").read_text(encoding="utf-8"))


def is_frozen(prompt: Prompt, path: Path | None = None) -> bool:
    """Whether this exact prompt, version and text, is the frozen one."""
    path = path or FROZEN
    if not path.exists():
        return False
    frozen = json.loads(path.read_text())
    return (frozen["version"], frozen["sha256"]) == (prompt.version, prompt.sha256)


def freeze(prompt: Prompt, path: Path | None = None) -> None:
    path = path or FROZEN
    if path.exists():
        raise SystemExit(f"{path} already freezes a prompt; it is never refrozen")
    record = {
        "version": prompt.version,
        "sha256": prompt.sha256,
        "frozen": datetime.now(UTC).date().isoformat(),
    }
    path.write_text(json.dumps(record, indent=2) + "\n")


def main() -> None:
    if sys.argv[1:] != ["freeze"]:
        raise SystemExit("usage: python -m bench.prompts freeze")
    prompt = load()
    freeze(prompt)
    print(f"froze {prompt.version} ({prompt.sha256}) in {FROZEN}")


if __name__ == "__main__":
    main()

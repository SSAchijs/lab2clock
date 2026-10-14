"""The stage-1 prompt, one versioned file per version in prompts/.

Results from different prompts are not comparable, so a prompt is never edited
in place once a response has been recorded with it: a change is a new file,
extract_v2.txt. Every response records the prompt's version and the SHA-256 of
its text, and the scorer refuses an extractor whose responses disagree on
either, so an edit made in place cannot mix two prompts' results silently.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CURRENT = "extract_v1"


@dataclass(frozen=True)
class Prompt:
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def load(version: str = CURRENT) -> Prompt:
    return Prompt(version, (PROMPTS / f"{version}.txt").read_text(encoding="utf-8"))

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from bench import models


class FakeModels:
    def __init__(self, unsupported=()):
        self.unsupported = set(unsupported)

    def retrieve(self, model_id):
        caps = SimpleNamespace(
            **{
                c: SimpleNamespace(supported=c not in self.unsupported)
                for c in models.REQUIRED
            }
        )
        return SimpleNamespace(
            id=model_id,
            display_name=model_id.replace("-", " ").title(),
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
            max_input_tokens=1_000_000,
            max_tokens=128_000,
            capabilities=caps,
        )


def client(unsupported=()):
    return SimpleNamespace(models=FakeModels(unsupported))


def test_a_frontier_and_a_much_cheaper_model():
    frontier, cheap = models.MODELS["frontier"], models.MODELS["cheap"]
    assert (frontier.id, cheap.id) == ("claude-opus-5-5", "claude-haiku-5-5")
    assert frontier.input_per_mtok / cheap.input_per_mtok >= 10


def test_the_record_holds_what_was_served_and_when(tmp_path):
    path = tmp_path / "models.json"
    out = models.write(client(), path)
    assert json.loads(path.read_text()) == out
    assert out["retrieved"] == datetime.now(UTC).date().isoformat()
    assert out["sdk"].startswith("anthropic ")
    frontier = out["models"]["frontier"]
    assert frontier["id"] == "claude-opus-5-5"
    assert frontier["created_at"] == "2026-09-01T00:00:00+00:00"
    assert frontier["input_per_mtok"] == 4.00


@pytest.mark.parametrize("capability", models.REQUIRED)
def test_a_model_stage_1_cannot_use_stops_the_run(tmp_path, capability):
    with pytest.raises(SystemExit, match=capability):
        models.write(client([capability]), tmp_path / "models.json")

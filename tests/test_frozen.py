from bench import frozen
from lab2clock.assemble import assemble
from lab2clock.clock_spec import BY_NAME
from lab2clock.stage1 import RawReport


def test_committed_frozen_score_matches_a_fresh_run():
    # Catches a response or scorer change without rerunning bench.frozen.
    assert frozen.FROZEN.read_text(encoding="utf-8") == frozen.summary(
        frozen.outcomes()
    )


def urine_white_cells(value, unit):
    items = [{"name": "白细胞", "value": value, "unit": unit, "page": 1}]
    return assemble(RawReport.model_validate({"items": items}))["inputs"]


def test_the_frozen_code_lets_urine_counts_through_and_the_current_does_not():
    assert "white_blood_cell_count" not in urine_white_cells("17", "/ul")
    with frozen.frozen_code():
        assert urine_white_cells("17", "/ul")["white_blood_cell_count"]["value"] == (
            0.017
        )
        assert urine_white_cells("3+", "cell/ul")["white_blood_cell_count"]
    # Undone on the way out.
    assert "white_blood_cell_count" not in urine_white_cells("3+", "cell/ul")
    assert BY_NAME["white_blood_cell_count"].error[0] == 0.05

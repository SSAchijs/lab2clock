import json

import pytest

from bench import audit, medrepbench


def test_ten_reports_of_the_scored_set_are_drawn_with_a_seed():
    images = audit.chosen()
    assert len(images) == audit.SIZE == 10
    assert images == sorted(set(images))
    assert set(images) <= {row["image"] for row in medrepbench.read_set()}
    assert audit.chosen() == images
    assert audit.chosen(seed=1) != images


def test_only_rows_that_map_to_a_marker_are_checked():
    items = json.dumps(
        [
            {"item_name": "白细胞计数", "item_value": "7.95", "item_unit": "10^9/L"},
            {"item_name": "血小板分布宽度", "item_value": "16.1", "item_unit": "fL"},
            {"item_name": "葡萄糖", "item_value": "4.52", "item_unit": ""},
        ],
        ensure_ascii=False,
    )
    assert audit.marker_rows(items) == [
        {
            "marker": "white_blood_cell_count",
            "label_name": "白细胞计数",
            "label_value": "7.95",
            "label_unit": "10^9/L",
        },
        {
            "marker": "glucose",
            "label_name": "葡萄糖",
            "label_value": "4.52",
            "label_unit": "",
        },
    ]


def test_the_page_shows_each_image_beside_its_rows_escaped():
    rows = [
        {
            "marker": "c_reactive_protein",
            "label_name": "CRP",
            "label_value": ">5.0",
            "label_unit": "mg/L",
        }
    ]
    text = audit.page([("a<b>.png", rows)])
    assert 'src="censored/a&lt;b&gt;.png"' in text
    assert 'data-value="&gt;5.0"' in text
    assert 'id="r0-0"' in text and 'id="m0"' in text
    assert "a<b>.png" not in text


def write(tmp_path, *rows):
    path = tmp_path / "audit.csv"
    lines = [",".join(audit.COLUMNS)]
    for row in rows:
        lines.append(",".join(row.get(c, "") for c in audit.COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_error_rate_counts_wrong_rows_over_judged_rows(tmp_path):
    path = write(
        tmp_path,
        {"image": "a.png", "marker": "albumin", "verdict": "correct"},
        {
            "image": "a.png",
            "marker": "glucose",
            "verdict": "wrong",
            "printed_value": "5.2",
        },
        {"image": "b.png", "marker": "creatinine", "verdict": "correct"},
        {"image": "b.png", "verdict": "missing", "note": "白蛋白 40 g/L"},
    )
    result = audit.score(path)
    assert (
        result["reports"],
        result["judged"],
        result["wrong"],
        result["missing"],
    ) == (
        2,
        3,
        1,
        1,
    )
    low, high = result["interval"]
    assert 0 < low < 1 / 3 < high < 1


def test_a_row_left_unjudged_stops_the_score(tmp_path):
    path = write(tmp_path, {"image": "a.png", "marker": "albumin", "verdict": ""})
    with pytest.raises(ValueError, match="no verdict"):
        audit.score(path)

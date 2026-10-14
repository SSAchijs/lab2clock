import pytest

from lab2clock.clock_spec import MARKERS
from lab2clock.synonyms import (
    ANALYTES,
    LYMPHOCYTE_COUNT,
    SYNONYMS,
    match,
    normalise,
)


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        # As printed on MedRepBench reports, decorations and OCR spaces included.
        ("白蛋白", "albumin"),
        ("*白蛋白", "albumin"),
        ("★白蛋白(溴甲酚绿法)", "albumin"),
        ("白蛋白(溴甲 酚绿法)", "albumin"),
        ("肌酐", "creatinine"),
        ("肌酐(Cr)", "creatinine"),
        ("葡萄糖", "glucose"),
        ("空腹血糖(GLU)", "glucose"),
        ("C反应蛋白", "c_reactive_protein"),
        ("C-反应蛋白(CRP)", "c_reactive_protein"),
        ("超敏C-反应蛋白", "c_reactive_protein"),
        ("25.定量C-反应蛋白(CRP)", "c_reactive_protein"),
        ("3★全血超敏C反应蛋白", "c_reactive_protein"),
        ("C反应蛋白[CRP]", "c_reactive_protein"),
        ("淋巴细胞百分比", "lymphocyte_percent"),
        (" 淋巴细胞百分 比(LYMPH%)", "lymphocyte_percent"),
        ("淋巴细 胞%.", "lymphocyte_percent"),
        ("淋巴细胞绝对值", LYMPHOCYTE_COUNT),
        ("淋巴细 胞#", LYMPHOCYTE_COUNT),
        ("平均红细胞体积", "mean_cell_volume"),
        ("*MCV", "mean_cell_volume"),
        ("红细胞分布宽度变异系数", "red_cell_distribution_width"),
        ("23.红细胞分布宽度CV(RDW-CV)", "red_cell_distribution_width"),
        ("碱性磷酸酶", "alkaline_phosphatase"),
        (" 碱性磷酸 酶", "alkaline_phosphatase"),
        ("白细胞计数", "white_blood_cell_count"),
        ("#白细胞计数", "white_blood_cell_count"),
        ("白细胞(W BC)", "white_blood_cell_count"),
        # English layouts.
        ("Albumin", "albumin"),
        ("CREATININE", "creatinine"),
        ("Glucose, Fasting", "glucose"),
        ("hs-CRP", "c_reactive_protein"),
        ("C-Reactive Protein, Cardiac", "c_reactive_protein"),
        ("Lymphocyte %", "lymphocyte_percent"),
        ("Absolute Lymphocytes", LYMPHOCYTE_COUNT),
        ("Mean Corpuscular Volume", "mean_cell_volume"),
        ("RDW-CV", "red_cell_distribution_width"),
        ("Alk Phos", "alkaline_phosphatase"),
        ("White Blood Cell Count", "white_blood_cell_count"),
        # Full-width characters.
        ("ＣＲＰ", "c_reactive_protein"),
        ("淋巴细胞％", "lymphocyte_percent"),
    ],
)
def test_matches(printed, expected):
    assert match(printed) == expected


@pytest.mark.parametrize(
    "printed",
    [
        # Lookalikes from MedRepBench: a different analyte or specimen.
        "前白蛋白",
        "尿微量白蛋白",
        "糖化白蛋白",
        "白蛋白/球蛋白",
        "尿肌酐",
        "尿素氮/肌酐",
        "尿葡萄糖",
        "血糖(一小时)",
        "餐后2小时血 糖",
        "糖化血红蛋白",
        "红细胞分布宽度标准差",
        "红细胞分布宽度(RDW-SD)",
        "RDW-SD",
        "血小板分布宽度",
        "白细胞酯酶",
        "尿白细胞",
        "白细胞(LEU)",
        "异型淋巴细胞",
        "B淋巴细胞",
        # English.
        "Glucose, urine",
        "Prealbumin",
        "Bone Alkaline Phosphatase",
        "Leukocyte Esterase",
        "Cr",
        "",
    ],
)
def test_does_not_match(printed):
    assert match(printed) is None


@pytest.mark.parametrize("printed", ["LYM#", "淋巴细胞绝对值(LYM#)", "淋巴细胞计数"])
def test_absolute_lymphocytes_never_map_to_percent(printed):
    assert match(printed, "%") == LYMPHOCYTE_COUNT


@pytest.mark.parametrize(
    ("printed", "unit", "expected"),
    [
        ("淋巴细胞", "%", "lymphocyte_percent"),
        ("Lymphocytes", "%", "lymphocyte_percent"),
        ("LY", "%", "lymphocyte_percent"),
        ("淋巴细胞", "10^9/L", LYMPHOCYTE_COUNT),
        ("Lymphs", "x10E3/uL", LYMPHOCYTE_COUNT),
        ("淋巴细胞", "", None),
        ("Lymphocytes", None, None),
    ],
)
def test_unit_decides_bare_lymphocytes(printed, unit, expected):
    assert match(printed, unit) == expected


def test_percent_and_hash_survive_normalisation():
    assert normalise("LYM%") != normalise("LYM#") != normalise("LYM")


def test_every_analyte_has_english_and_chinese_names():
    assert set(SYNONYMS) == set(ANALYTES) == {*MARKERS, LYMPHOCYTE_COUNT}
    for names in SYNONYMS.values():
        assert any(name.isascii() for name in names)
        assert any(not name.isascii() for name in names)


@pytest.mark.parametrize(
    ("printed", "unit", "expected"),
    [
        # An abbreviation beside the full name, with or without a space.
        ("ALP 碱性磷酸酶", "U/L", "alkaline_phosphatase"),
        ("CRP C反应蛋白", "mg/l", "c_reactive_protein"),
        ("hs-CRP 超敏C反应蛋白", "mg/l", "c_reactive_protein"),
        ("MCV红细胞平均体积", "fL", "mean_cell_volume"),
        ("*MCV 红细胞平均体积", "fl", "mean_cell_volume"),
        ("LYMPH%淋巴细胞比率", "%", "lymphocyte_percent"),
        # A unit in brackets after the name is skipped.
        ("淋巴细胞百分比(LYM%)(%)", "%", "lymphocyte_percent"),
        ("白细胞(WBC)(*10^9/L)", "*10^9/L", "white_blood_cell_count"),
        # A part printed for both lymphocyte forms still follows the unit.
        ("LYMPH# 淋巴细胞", "10^9/L", LYMPHOCYTE_COUNT),
    ],
)
def test_compound_names_match_when_every_part_agrees(printed, unit, expected):
    assert match(printed, unit) == expected


@pytest.mark.parametrize(
    ("printed", "unit"),
    [
        # One unknown part leaves the name unmapped: urine creatinine.
        ("尿肌酐(CREA)", "umol/L"),
        ("前白蛋白(ALB)", "mg/L"),
        # RDW-SD stays out, however it is combined.
        ("RDW-SD 红细胞分布宽度", "%"),
        ("RDW 红细胞分布宽度SD", "fl"),
        ("红细胞分布宽度(SD)", "fl"),
        # Two parts naming different analytes.
        ("WBC 红细胞", "10^9/L"),
        # A bare lymphocyte name with no unit is still undecidable.
        ("LYM 淋巴细胞", None),
    ],
)
def test_compound_names_stay_unmapped_when_a_part_disagrees(printed, unit):
    assert match(printed, unit) is None

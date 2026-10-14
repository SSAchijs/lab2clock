"""The synonym dictionary: maps an analyte name as printed to a clock marker.

Names are normalised, then matched exactly. Fuzzy matching would map
"Glucose, urine" to blood glucose; a missed name shows up as a missing field,
while a false match silently corrupts the clock. So a name maps only if its
normalised form is listed here.

A name printed as an abbreviation beside the full name, as in "ALP 碱性磷酸酶"
or "MCV红细胞平均体积", maps when every part of it maps to the same analyte on
its own; a part that is a unit, as in "淋巴细胞百分比(LYM%)(%)", is skipped. One
unknown part is enough to leave the name unmapped, so "尿肌酐(CREA)", urine
creatinine, does not become creatinine.

Seeded from real names: the item labels of MedRepBench (Chinese) and common
English report layouts. Lookalikes that must stay unmapped, such as prealbumin
(前白蛋白), urine creatinine (尿肌酐) and RDW-SD, are left out on purpose and
pinned by tests.
"""

import re
import unicodedata

from lab2clock.clock_spec import MARKERS
from lab2clock.units import UnitError, normalise_unit

# Not a clock input, but needed to derive lymphocyte_percent when a report
# prints only absolute counts. Absolute counts must never map to the percent.
LYMPHOCYTE_COUNT = "lymphocyte_count"

# Names printed for both the percent and the absolute count. The unit decides.
_LYMPHOCYTES_EITHER = (
    "lymphocytes",
    "lymphocyte",
    "lymphs",
    "lym",
    "lymph",
    "ly",
    "淋巴细胞",
)

# Per analyte, names as printed. Parenthesised qualifiers are listed one by
# one, because "血糖(一小时)" (one-hour glucose) must not match "血糖".
SYNONYMS: dict[str, tuple[str, ...]] = {
    "albumin": (
        "Albumin",
        "ALB",
        "Albumin, Serum",
        "Serum Albumin",
        "Albumin (BCG)",
        "白蛋白",
        "白蛋白(ALB)",
        "白蛋白ALB",
        "白蛋白测定",
        "血清白蛋白",
        "血清白蛋白测定(Alb)",
        "白蛋白(急)",
        "白蛋白(BCG法)",
        "白蛋白(溴甲酚绿法)",
        "白蛋白(化学法)",
        "白蛋白(ALB生化)",
    ),
    "creatinine": (
        "Creatinine",
        "CREA",
        "CRE",
        "Creat",
        "Creatinine, Serum",
        "Serum Creatinine",
        # Not bare "Cr", which is also chromium.
        "肌酐",
        "肌酐(CREA)",
        "肌酐(Cr)",
        "血肌酐",
        "肌酐测定",
        "血清肌酐测定(CREA)",
        "肌酐(急)",
        "肌酐(酶法)",
        "肌酐(酶促动力学法)",
    ),
    "glucose": (
        "Glucose",
        "GLU",
        "Glucose, Serum",
        "Glucose, Plasma",
        "Plasma Glucose",
        "Glucose, Fasting",
        "Fasting Glucose",
        "Glucose (fasting)",
        "Fasting Plasma Glucose",
        "FPG",
        "葡萄糖",
        "葡萄糖(GLU)",
        "葡萄糖测定",
        "葡萄糖(急)",
        "葡萄糖(酶法)",
        "葡萄糖(空腹)",
        "空腹葡萄糖",
        "血糖",
        "血糖(GLU)",
        "血糖(空腹)",
        "空腹血糖",
        "空腹血糖(GLU)",
        "OGTT空腹血糖",
    ),
    "c_reactive_protein": (
        "C-Reactive Protein",
        "CRP",
        "C-Reactive Protein (CRP)",
        "hs-CRP",
        "hsCRP",
        "High Sensitivity CRP",
        "CRP, High Sensitivity",
        "C-Reactive Protein, Cardiac",
        "High-Sensitivity C-Reactive Protein",
        "C反应蛋白",
        "C反应蛋白(CRP)",
        "C反应蛋白测定",
        "C反应蛋白(急)",
        "C反应蛋白(单项)",
        "定量C反应蛋白(CRP)",
        "超敏C反应蛋白",
        "C反应蛋白(超敏)",
        "超敏C反应蛋白HsCRP",
        "超敏C反应蛋白(hs-CRP)",
        "全血超敏C反应蛋白",
        "全血Hs-CRP",
    ),
    "lymphocyte_percent": (
        "Lymphocyte %",
        "Lymphocytes %",
        "% Lymphocytes",
        "Lymphocyte Percent",
        "Lymphs %",
        "LYM%",
        "LYMPH%",
        "LY%",
        "淋巴细胞百分比",
        "淋巴细胞群相对值",
        "淋巴细胞百分数",
        "淋巴细胞百分率",
        "淋巴细胞比率",
        "淋巴细胞比值",
        "淋巴细胞%",
        "淋巴百分数",
        "淋巴细胞百分比(LYM%)",
        "淋巴细胞百分比LYM%",
        "LYM%淋巴细胞百分比",
        "淋巴细胞百分比(LYMPH%)",
        "淋巴细胞比率(LY%)",
        "淋巴细胞百分比LY",
    ),
    LYMPHOCYTE_COUNT: (
        "Lymphocytes (Absolute)",
        "Lymphocytes, Absolute",
        "Absolute Lymphocytes",
        "Lymphs (Absolute)",
        "Lymphocyte Count",
        "Absolute Lymphocyte Count",
        "ALC",
        "LYM#",
        "LYMPH#",
        "LY#",
        "淋巴细胞绝对值",
        "淋巴细胞群绝对值",
        "淋巴细胞计数",
        "淋巴细胞数",
        "淋巴细胞数目",
        "淋巴细胞绝对数",
        "淋巴细胞总数",
        "淋巴绝对值",
        "淋巴细胞#",
        "淋巴细胞绝对值(LYM#)",
        "淋巴细胞计数LY",
        "淋巴细胞浓度值LYM#",
        "淋巴细胞数(LYMPH)",
    ),
    "mean_cell_volume": (
        "MCV",
        "Mean Cell Volume",
        "Mean Corpuscular Volume",
        "平均红细胞体积",
        "平均红细胞容积",
        "红细胞平均容积",
        "红细胞平均体积",
        "平均红细胞体积(MCV)",
        "红细胞平均体积(MCV)",
        "平均红细胞体积MCV",
        "红细胞平均体积MCV",
        "MCV/平均红细胞体积",
    ),
    # RDW-CV only. Bare names are also printed for RDW-SD in fL; the conversion
    # table has no fL entry for this field, so those fail loudly there.
    "red_cell_distribution_width": (
        "RDW",
        "RDW-CV",
        "RDW CV",
        "Red Cell Distribution Width",
        "Red Cell Distribution Width (CV)",
        "Red Cell Distribution Width-CV",
        "红细胞分布宽度",
        "红细胞分布宽度CV",
        "红细胞分布CV值",
        "红细胞分布宽度(CV)",
        "红细胞分布宽度变异系数",
        "红细胞分布宽度RDW-CV",
        "红细胞分布宽度-CV(RDW-CV)",
        "红细胞分布宽度CV(RDW-CV)",
        "红细胞体积分布宽度",
        "红细胞体积分布宽度CV",
        "红细胞体积分布宽度-CV",
        "红细胞体积分布宽度RDW-CV",
        "红细胞体积分布宽度(变异系数)",
        "红细胞体积分布CV",
        "RBC分布宽度-CV值",
        "RBC体积分布宽度",
    ),
    "alkaline_phosphatase": (
        "Alkaline Phosphatase",
        "ALP",
        "Alk Phos",
        "Alk. Phosphatase",
        "AKP",
        "Alkaline Phosphatase, Serum",
        "碱性磷酸酶",
        "碱性磷酸酶(ALP)",
        "碱性磷酸酶测定",
        "血清碱性磷酸酶测定(ALP)",
        "碱性磷酸酶(急)",
        "碱性磷酸酶(速率法)",
    ),
    # Not "LEU" variants: on Chinese reports those are urine microscopy.
    "white_blood_cell_count": (
        "WBC",
        "WBC Count",
        "White Blood Cells",
        "White Blood Cell Count",
        "White Cell Count",
        "WCC",
        "Leukocytes",
        "Leukocyte Count",
        "Total WBC",
        "白细胞",
        "白细胞计数",
        "白细胞绝对值",
        "白细胞总数",
        "白细胞数",
        "白细胞数目",
        "白细胞(WBC)",
        "白细胞计数(WBC)",
        "白细胞计数WBC",
        "白细胞WBC",
        "WBC白细胞数目",
    ),
}


def normalise(name: str) -> str:
    """The form names are matched in.

    NFKC turns full-width characters into normal width, casefold lowercases,
    and punctuation, symbols and spaces go, so "C-反应蛋白" equals "C反应蛋白".
    % and # stay: they are what separates LYM% from LYM#. Leading digits and #
    go too: they are row numbers and marks, as in "25.定量C-反应蛋白(CRP)", and
    no marker name starts with a meaningful number.
    """
    text = unicodedata.normalize("NFKC", name).casefold()
    kept = "".join(
        char
        for char in text
        if char in "%#" or unicodedata.category(char)[0] not in "PSZC"
    )
    return re.sub(r"^[\d#]+", "", kept)


def _index() -> dict[str, str]:
    index: dict[str, str] = {}
    for analyte, names in SYNONYMS.items():
        for name in names:
            key = normalise(name)
            if index.setdefault(key, analyte) != analyte:
                raise ValueError(f"{name!r} is listed for {index[key]} and {analyte}")
    for name in _LYMPHOCYTES_EITHER:
        if normalise(name) in index:
            raise ValueError(f"{name!r} is listed as both ambiguous and exact")
    return index


_INDEX = _index()
_EITHER = frozenset(normalise(name) for name in _LYMPHOCYTES_EITHER)

ANALYTES: tuple[str, ...] = (*MARKERS, LYMPHOCYTE_COUNT)


def match(name: str, unit: str | None = None) -> str | None:
    """The analyte a printed name stands for, or None if it is not one of ours.

    `unit` is the unit as printed. It only matters for names printed for both
    lymphocyte percent and absolute count: a % unit means percent, any other
    unit means count, and no unit means the name stays unmapped.
    """
    return _exact(name, unit) or _compound(name, unit)


def _exact(name: str, unit: str | None) -> str | None:
    key = normalise(name)
    if key in _EITHER:
        if not unit or not unit.strip():
            return None
        return "lymphocyte_percent" if "%" in unit else LYMPHOCYTE_COUNT
    return _INDEX.get(key)


# Where a name splits into parts: spaces and brackets, and where an
# abbreviation runs into the Chinese name after it, as in "WBC白细胞".
_SEPARATORS = re.compile(r"[\s()（）\[\]【】]+")
_ABBREVIATION_END = re.compile(r"(?<=[A-Za-z%#])(?=[\u4e00-\u9fff])")


def _compound(name: str, unit: str | None) -> str | None:
    """The analyte every part of a compound name maps to, or None."""
    parts = [p for p in _SEPARATORS.split(name) if normalise(p)]
    for split in (parts, [q for p in parts for q in _ABBREVIATION_END.split(p)]):
        if len(split) < 2:
            continue
        found = set()
        for part in split:
            analyte = _exact(part, unit)
            if analyte is None and not _is_unit(part):
                break
            if analyte is not None:
                found.add(analyte)
        else:
            if len(found) == 1:
                return found.pop()
    return None


def _is_unit(text: str) -> bool:
    try:
        normalise_unit(text)
    except UnitError:
        return False
    return True

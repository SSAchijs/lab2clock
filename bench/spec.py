"""Two files per report: what is true about the patient, and what was printed.

truth/R07.json holds the patient: age and the nine markers in clock units, the
unrounded values from bench/patients.csv. The clock effect of an error is
computed from it.

render_spec/R07.json holds the report: its conditions (layout, language, unit
system, photo degradation, planted errors), the fake identity in its header,
and every row exactly as printed, in the stage-1 shape. Stage 1 is scored
against these rows, and the generator renders them, so the two cannot disagree.
The conditions also let errors be sliced by condition.

A printed value is the truth converted into the display unit with lab2clock's
own conversion table, then rounded half up to the display decimals, as a lab
rounds.

    uv run python -m bench.spec

regenerates both folders from bench/patients.csv. The variation matrix sets each
report's conditions; until it exists, every report gets BASELINE.
"""

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bench.identity import Identity, identity
from bench.sample import OUT as PATIENTS
from lab2clock.clock_spec import MARKERS
from lab2clock.conversions import convert
from lab2clock.stage1 import RawItem, RawReport
from lab2clock.synonyms import LYMPHOCYTE_COUNT
from lab2clock.units import normalise_unit

BENCH = Path(__file__).resolve().parent
TRUTH = BENCH / "truth"
RENDER_SPEC = BENCH / "render_spec"

Layout = Literal["table", "two_column", "multi_page"]
Language = Literal["en", "zh"]
UnitSystem = Literal["si", "us", "mixed"]


class Truth(BaseModel):
    """What is true about one patient."""

    model_config = ConfigDict(extra="forbid")

    report: str = Field(pattern=r"^R\d{2}$")
    split: Literal["dev", "test"]
    seqn: int = Field(description="The NHANES respondent the values come from.")
    age: int = Field(ge=20, le=79)
    values: dict[str, float] = Field(
        description="The nine markers in clock units, unrounded."
    )

    @field_validator("values")
    @classmethod
    def _nine_markers(cls, values: dict[str, float]) -> dict[str, float]:
        if set(values) != set(MARKERS):
            raise ValueError(f"values must hold exactly {MARKERS}")
        return values


class Conditions(BaseModel):
    """How one report is printed: the tags errors are sliced by."""

    model_config = ConfigDict(extra="forbid")

    layout: Layout
    language: Language
    unit_system: UnitSystem


class PrintedRow(RawItem):
    """One row as printed: the stage-1 fields, plus what the row really is.

    analyte: the clock marker the row feeds, lymphocyte_count for the absolute
        count the cross-check reads, or None for a distractor.
    decimals: digits printed after the decimal mark.
    planted: None, or why the printed value differs from the truth.
    """

    analyte: str | None
    decimals: int = Field(ge=0)
    planted: str | None = None


class Degradation(BaseModel):
    """A photo-like degradation of the rendered page; Phase 4 sets the steps."""

    model_config = ConfigDict(extra="forbid")

    seed: int


class RenderSpec(BaseModel):
    """What one report prints."""

    model_config = ConfigDict(extra="forbid")

    report: str = Field(pattern=r"^R\d{2}$")
    split: Literal["dev", "test"]
    conditions: Conditions
    degradation: Degradation | None = None
    identity: Identity
    rows: list[PrintedRow]

    def stage1(self) -> RawReport:
        """What a perfect reader returns for this report."""
        return RawReport(
            items=[
                RawItem(**row.model_dump(include=set(RawItem.model_fields)))
                for row in self.rows
            ]
        )


# Per marker, the name printed in each language. Each maps to its marker in
# lab2clock's synonym dictionary.
NAMES: dict[Language, dict[str, str]] = {
    "en": {
        "white_blood_cell_count": "WBC",
        "lymphocyte_percent": "Lymphocytes %",
        "mean_cell_volume": "MCV",
        "red_cell_distribution_width": "RDW-CV",
        "albumin": "Albumin",
        "creatinine": "Creatinine",
        "glucose": "Glucose",
        "alkaline_phosphatase": "Alkaline Phosphatase",
        "c_reactive_protein": "hs-CRP",
    },
    "zh": {
        "white_blood_cell_count": "白细胞计数",
        "lymphocyte_percent": "淋巴细胞百分比",
        "mean_cell_volume": "平均红细胞体积",
        "red_cell_distribution_width": "红细胞分布宽度",
        "albumin": "白蛋白",
        "creatinine": "肌酐",
        "glucose": "葡萄糖",
        "alkaline_phosphatase": "碱性磷酸酶",
        "c_reactive_protein": "超敏C反应蛋白",
    },
}

# Per marker, (unit as printed, decimals) in each unit system: SI as on a
# European or Chinese report, US as on an American one. The blood count prints
# the same in both, bar the white-cell unit.
DISPLAY: dict[str, dict[str, tuple[str, int]]] = {
    "si": {
        "white_blood_cell_count": ("10^9/L", 1),
        "lymphocyte_percent": ("%", 1),
        "mean_cell_volume": ("fL", 1),
        "red_cell_distribution_width": ("%", 1),
        "albumin": ("g/L", 0),
        "creatinine": ("µmol/L", 0),
        "glucose": ("mmol/L", 1),
        "alkaline_phosphatase": ("U/L", 0),
        "c_reactive_protein": ("mg/L", 1),
    },
    "us": {
        "white_blood_cell_count": ("x10^3/uL", 1),
        "lymphocyte_percent": ("%", 1),
        "mean_cell_volume": ("fL", 1),
        "red_cell_distribution_width": ("%", 1),
        "albumin": ("g/dL", 1),
        "creatinine": ("mg/dL", 2),
        "glucose": ("mg/dL", 0),
        "alkaline_phosphatase": ("IU/L", 0),
        "c_reactive_protein": ("mg/dL", 2),
    },
}

# A mixed report prints the blood count and albumin in SI, and the rest in US
# units, as some labs do after switching analysers for part of the panel.
MIXED_US = ("creatinine", "glucose", "c_reactive_protein")


@dataclass(frozen=True)
class Extra:
    """A printed result that is not a clock input, from the same NHANES person.

    names: the name printed in each language; us_name overrides English in US
        units, where the same test goes by another name.
    si, us: (patients.csv column, unit as printed, factor from the column's
        unit, decimals). Most columns are already in the printed unit.
    analyte: what the row maps to in lab2clock, or None for a distractor.
    """

    names: dict[Language, str]
    si: tuple[str, str, float, int]
    us: tuple[str, str, float, int]
    us_name: str | None = None
    analyte: str | None = None


EXTRAS: dict[str, Extra] = {
    "red_blood_cell_count": Extra(
        {"en": "RBC", "zh": "红细胞计数"},
        # 10^6/uL = 10^12/L.
        si=("red_blood_cell_count", "10^12/L", 1, 2),
        us=("red_blood_cell_count", "x10^6/uL", 1, 2),
    ),
    "hemoglobin": Extra(
        {"en": "Hemoglobin", "zh": "血红蛋白"},
        # 1 dL = 0.1 L.
        si=("hemoglobin", "g/L", 10, 0),
        us=("hemoglobin", "g/dL", 1, 1),
    ),
    "hematocrit": Extra(
        {"en": "Hematocrit", "zh": "红细胞压积"},
        si=("hematocrit", "%", 1, 1),
        us=("hematocrit", "%", 1, 1),
    ),
    "platelet_count": Extra(
        {"en": "Platelets", "zh": "血小板计数"},
        si=("platelet_count", "10^9/L", 1, 0),
        us=("platelet_count", "x10^3/uL", 1, 0),
    ),
    "neutrophil_percent": Extra(
        {"en": "Neutrophils %", "zh": "中性粒细胞百分比"},
        si=("neutrophil_percent", "%", 1, 1),
        us=("neutrophil_percent", "%", 1, 1),
    ),
    # Not a distractor: the cross-check compares it with the percent. NHANES
    # prints it to one decimal, as the percent and white cells, and all 7,523
    # NHANES blood counts pass the cross-check at that rounding.
    "lymphocyte_count": Extra(
        {"en": "Lymphocytes (Absolute)", "zh": "淋巴细胞绝对值"},
        si=("lymphocyte_count", "10^9/L", 1, 1),
        us=("lymphocyte_count", "x10^3/uL", 1, 1),
        analyte=LYMPHOCYTE_COUNT,
    ),
    "sodium": Extra(
        {"en": "Sodium", "zh": "钠"},
        si=("sodium", "mmol/L", 1, 0),
        us=("sodium", "mmol/L", 1, 0),
    ),
    "potassium": Extra(
        {"en": "Potassium", "zh": "钾"},
        si=("potassium", "mmol/L", 1, 1),
        us=("potassium", "mmol/L", 1, 1),
    ),
    # Urea nitrogen in mmol/L equals urea in mmol/L, one nitrogen pair per urea.
    "urea": Extra(
        {"en": "Urea", "zh": "尿素"},
        si=("urea_nitrogen_si", "mmol/L", 1, 1),
        us=("urea_nitrogen", "mg/dL", 1, 0),
        us_name="BUN",
    ),
    "total_protein": Extra(
        {"en": "Total Protein", "zh": "总蛋白"},
        si=("total_protein_si", "g/L", 1, 0),
        us=("total_protein", "g/dL", 1, 1),
    ),
    "total_bilirubin": Extra(
        {"en": "Total Bilirubin", "zh": "总胆红素"},
        si=("total_bilirubin_si", "µmol/L", 1, 1),
        us=("total_bilirubin", "mg/dL", 1, 1),
    ),
    "alanine_aminotransferase": Extra(
        {"en": "ALT", "zh": "丙氨酸氨基转移酶"},
        si=("alanine_aminotransferase", "U/L", 1, 0),
        us=("alanine_aminotransferase", "U/L", 1, 0),
    ),
}

# Printed order: the blood count, then the chemistry, which a multi-page report
# puts on page 2. Markers and extras are interleaved, as on a real panel.
CBC = (
    "white_blood_cell_count",
    "red_blood_cell_count",
    "hemoglobin",
    "hematocrit",
    "mean_cell_volume",
    "red_cell_distribution_width",
    "platelet_count",
    "neutrophil_percent",
    "lymphocyte_percent",
    "lymphocyte_count",
)
CHEMISTRY = (
    "sodium",
    "potassium",
    "urea",
    "creatinine",
    "glucose",
    "total_protein",
    "albumin",
    "total_bilirubin",
    "alkaline_phosphatase",
    "alanine_aminotransferase",
    "c_reactive_protein",
)

BASELINE = Conditions(layout="table", language="en", unit_system="si")


def display(marker: str, unit_system: UnitSystem) -> tuple[str, int]:
    """The (unit as printed, decimals) of `marker` in a unit system."""
    if unit_system == "mixed":
        unit_system = "us" if marker in MIXED_US else "si"
    return DISPLAY[unit_system][marker]


def rounded(value: float, decimals: int) -> str:
    """`value` rounded half up to `decimals`, as a lab rounds."""
    # Drop float noise (0.2259999999 is 0.226) before rounding.
    exact = Decimal(repr(round(float(value), 10)))
    text = str(exact.quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP))
    if Decimal(text) == 0:
        raise ValueError(f"{value} rounds to 0 at {decimals} decimals")
    return text


def printed_value(marker: str, value: float, unit: str, decimals: int) -> str:
    """`value`, in clock units, as a lab prints it in `unit`."""
    factor = convert(marker, 1.0, normalise_unit(unit))
    return rounded(float(value) / factor, decimals)


def extra_row(key: str, patient: pd.Series, conditions: Conditions) -> PrintedRow:
    """The printed row of an extra result. A mixed report prints extras in SI."""
    extra = EXTRAS[key]
    us = conditions.unit_system == "us"
    column, unit, factor, decimals = extra.us if us else extra.si
    name = extra.names[conditions.language]
    if us and conditions.language == "en" and extra.us_name:
        name = extra.us_name
    return PrintedRow(
        analyte=extra.analyte,
        name=name,
        value=rounded(patient[column] * factor, decimals),
        unit=unit,
        page=1,
        decimals=decimals,
    )


def truth(patient: pd.Series) -> Truth:
    return Truth(
        report=patient.name,
        split=patient["split"],
        seqn=int(patient["SEQN"]),
        age=int(patient["age"]),
        values={marker: float(patient[marker]) for marker in MARKERS},
    )


def render_spec(patient: pd.Series, conditions: Conditions) -> RenderSpec:
    rows = []
    for key in (*CBC, *CHEMISTRY):
        if key in EXTRAS:
            row = extra_row(key, patient, conditions)
        else:
            unit, decimals = display(key, conditions.unit_system)
            row = PrintedRow(
                analyte=key,
                name=NAMES[conditions.language][key],
                value=printed_value(key, patient[key], unit, decimals),
                unit=unit,
                page=1,
                decimals=decimals,
            )
        if conditions.layout == "multi_page" and key in CHEMISTRY:
            row.page = 2
        rows.append(row)
    return RenderSpec(
        report=patient.name,
        split=patient["split"],
        conditions=conditions,
        identity=identity(patient.name, int(patient["age"]), conditions.language),
        rows=rows,
    )


def write(model: BaseModel, folder: Path) -> None:
    folder.mkdir(exist_ok=True)
    text = json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False)
    (folder / f"{model.report}.json").write_text(text + "\n")


def main() -> None:
    patients = pd.read_csv(PATIENTS, index_col="report")
    for _, patient in patients.iterrows():
        write(truth(patient), TRUTH)
        write(render_spec(patient, BASELINE), RENDER_SPEC)
    print(f"wrote {len(patients)} reports to {TRUTH} and {RENDER_SPEC}")


if __name__ == "__main__":
    main()

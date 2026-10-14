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

regenerates both folders from bench/patients.csv, with each report's conditions
from the variation matrix, bench/matrix.csv.
"""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bench.identity import Identity, identity
from bench.sample import SEED
from bench.sample import load as load_patients
from lab2clock.clock_spec import MARKERS
from lab2clock.conversions import convert
from lab2clock.stage1 import RawItem
from lab2clock.synonyms import LYMPHOCYTE_COUNT
from lab2clock.units import normalise_unit

BENCH = Path(__file__).resolve().parent
TRUTH = BENCH / "truth"
RENDER_SPEC = BENCH / "render_spec"
MATRIX = BENCH / "matrix.csv"

Layout = Literal["table", "two_column", "multi_page"]
Language = Literal["en", "zh"]
UnitSystem = Literal["si", "us", "mixed"]

# Each planted error is a slip that puts the printed value outside the error
# tier, so the expected outcome is unambiguous: an error on that marker.
# Planted kind -> (marker, power of ten the printed decimal point moves by).
PLANTED: dict[str, tuple[str, int]] = {
    # 89.3 fL printed 8.93: below the 30 fL floor.
    "mcv_decimal": ("mean_cell_volume", -1),
    # 30.7 % printed 307: above 100 %.
    "lymphocyte_percent_x10": ("lymphocyte_percent", 1),
    # 9.8 x 10^9/L printed 9800, a count per uL under the 10^9/L unit: above
    # the 1500 ceiling.
    "wbc_per_ul": ("white_blood_cell_count", 3),
}
Planted = Literal["mcv_decimal", "lymphocyte_percent_x10", "wbc_per_ul"]


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
    """How one report is printed: the tags errors are sliced by.

    photo: rendered and then degraded like a phone photo.
    previous: a previous-results column beside the current one.
    missing: a marker left off the report.
    planted: a slip printed in place of one marker's value.
    """

    model_config = ConfigDict(extra="forbid")

    layout: Layout
    language: Language
    unit_system: UnitSystem
    photo: bool = False
    previous: bool = False
    missing: str | None = None
    planted: Planted | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "Conditions":
        # Chinese labs print SI units.
        if self.language == "zh" and self.unit_system != "si":
            raise ValueError("a Chinese report prints SI units")
        # A two-column list has no room for a second result column.
        if self.previous and self.layout == "two_column":
            raise ValueError("a two-column report has no previous column")
        if self.missing is not None and self.missing not in MARKERS:
            raise ValueError(f"missing must be a marker, not {self.missing!r}")
        if self.planted and PLANTED[self.planted][0] == self.missing:
            raise ValueError("cannot plant an error in a missing marker")
        return self


class PrintedRow(RawItem):
    """One row as printed: the stage-1 fields, plus what the row really is.

    analyte: the clock marker the row feeds, lymphocyte_count for the absolute
        count the cross-check reads, or None for a distractor.
    decimals: digits printed after the decimal mark.
    panel: the blood count or the chemistry, the section the row is printed in.
    reference: the reference interval as printed: "low-high", or "<high".
    flag: H or L when the printed value is outside the reference interval.
    planted: None, or the planted kind when the printed value is a slip.
    previous: the previous result, as printed, when the report has that column.
    """

    analyte: str | None
    decimals: int = Field(ge=0)
    panel: Literal["cbc", "chemistry"]
    reference: str
    flag: Literal["H", "L"] | None = None
    planted: Planted | None = None
    previous: str | None = None


class Degradation(BaseModel):
    """A photo-like degradation of the rendered page.

    bench.degrade draws every step from the seed, so the photo regenerates
    identically.
    """

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
    previous_collected: date | None = None
    rows: list[PrintedRow]


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

# Per printed row, its reference interval in each unit system: (low, high) as
# printed, low None for an upper limit only. Illustrative adult intervals of the
# kind large labs print, not clinical guidance: they decorate the report and set
# its H/L flags. One interval for both sexes, since no sex is printed, and the
# two unit systems agree after conversion.
REFERENCE: dict[str, dict[str, tuple[str | None, str]]] = {
    "white_blood_cell_count": {"si": ("4.0", "11.0"), "us": ("4.0", "11.0")},
    "red_blood_cell_count": {"si": ("4.20", "5.80"), "us": ("4.20", "5.80")},
    "hemoglobin": {"si": ("120", "170"), "us": ("12.0", "17.0")},
    "hematocrit": {"si": ("36.0", "50.0"), "us": ("36.0", "50.0")},
    "mean_cell_volume": {"si": ("80.0", "100.0"), "us": ("80.0", "100.0")},
    "red_cell_distribution_width": {"si": ("11.5", "14.5"), "us": ("11.5", "14.5")},
    "platelet_count": {"si": ("150", "400"), "us": ("150", "400")},
    "neutrophil_percent": {"si": ("40.0", "75.0"), "us": ("40.0", "75.0")},
    "lymphocyte_percent": {"si": ("20.0", "45.0"), "us": ("20.0", "45.0")},
    "lymphocyte_count": {"si": ("1.0", "4.0"), "us": ("1.0", "4.0")},
    "sodium": {"si": ("135", "145"), "us": ("135", "145")},
    "potassium": {"si": ("3.5", "5.1"), "us": ("3.5", "5.1")},
    # 7-20 mg/dL of urea nitrogen is 2.5-7.1 mmol/L.
    "urea": {"si": ("2.5", "7.1"), "us": ("7", "20")},
    # 0.60-1.30 mg/dL is 53-115 umol/L.
    "creatinine": {"si": ("53", "115"), "us": ("0.60", "1.30")},
    # 70-99 mg/dL is 3.9-5.5 mmol/L.
    "glucose": {"si": ("3.9", "5.5"), "us": ("70", "99")},
    "total_protein": {"si": ("64", "83"), "us": ("6.4", "8.3")},
    "albumin": {"si": ("35", "52"), "us": ("3.5", "5.2")},
    # 0.2-1.2 mg/dL is 3.4-20.5 umol/L.
    "total_bilirubin": {"si": ("3.4", "20.5"), "us": ("0.2", "1.2")},
    "alkaline_phosphatase": {"si": ("40", "130"), "us": ("40", "130")},
    "alanine_aminotransferase": {"si": ("7", "56"), "us": ("7", "56")},
    # hs-CRP for cardiovascular risk: below 3 mg/L.
    "c_reactive_protein": {"si": (None, "3.0"), "us": (None, "0.30")},
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
    return DISPLAY[system(marker, unit_system)][marker]


def shifted(printed: str, power: int) -> tuple[str, int]:
    """`printed` with its decimal point moved `power` places, and its decimals.

    The digits stay as printed, as in a real slip: 89.3 moved -1 is 8.93.
    """
    text = format(Decimal(printed).scaleb(power), "f")
    return text, len(text.partition(".")[2])


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


def system(key: str, unit_system: UnitSystem) -> Literal["si", "us"]:
    """The unit system one row is printed in. A mixed report prints extras in
    SI, and the markers in MIXED_US in US units."""
    if unit_system == "mixed":
        return "us" if key in MIXED_US else "si"
    return unit_system


def reference(key: str, unit_system: UnitSystem) -> str:
    """The reference interval of a row, as printed."""
    low, high = REFERENCE[key][system(key, unit_system)]
    return f"<{high}" if low is None else f"{low}-{high}"


def flag(value: str, key: str, unit_system: UnitSystem) -> Literal["H", "L"] | None:
    """H or L when the printed `value` is outside the reference interval."""
    low, high = REFERENCE[key][system(key, unit_system)]
    if Decimal(value) > Decimal(high):
        return "H"
    if low is not None and Decimal(value) < Decimal(low):
        return "L"
    return None


def extra_row(key: str, patient: pd.Series, conditions: Conditions) -> PrintedRow:
    """The printed row of an extra result."""
    extra = EXTRAS[key]
    us = system(key, conditions.unit_system) == "us"
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
        panel="cbc" if key in CBC else "chemistry",
        reference=reference(key, conditions.unit_system),
    )


def truth(patient: pd.Series) -> Truth:
    return Truth(
        report=patient.name,
        split=patient["split"],
        seqn=int(patient["SEQN"]),
        age=int(patient["age"]),
        values={marker: float(patient[marker]) for marker in MARKERS},
    )


# A previous result differs from the current one by up to this share.
PREVIOUS_DRIFT = 0.10
# And was collected this many days before it.
PREVIOUS_DAYS = (90, 365)


def report_rng(report: str) -> np.random.Generator:
    """A random generator for one report, the same on every run."""
    return np.random.default_rng([SEED, int(report[1:])])


def render_spec(patient: pd.Series, conditions: Conditions) -> RenderSpec:
    rng = report_rng(patient.name)
    who = identity(patient.name, int(patient["age"]), conditions.language)
    rows = []
    for key in (*CBC, *CHEMISTRY):
        if key == conditions.missing:
            continue
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
                panel="cbc" if key in CBC else "chemistry",
                reference=reference(key, conditions.unit_system),
            )
        if conditions.layout == "multi_page" and key in CHEMISTRY:
            row.page = 2
        if conditions.previous:
            # From the correct printed value, even where a slip is planted.
            drift = 1 + rng.uniform(-PREVIOUS_DRIFT, PREVIOUS_DRIFT)
            row.previous = rounded(float(row.value) * drift, row.decimals)
        if conditions.planted and PLANTED[conditions.planted][0] == key:
            row.value, row.decimals = shifted(row.value, PLANTED[conditions.planted][1])
            row.planted = conditions.planted
        row.flag = flag(row.value, key, conditions.unit_system)
        rows.append(row)
    previous_collected = None
    if conditions.previous:
        days = int(rng.integers(PREVIOUS_DAYS[0], PREVIOUS_DAYS[1] + 1))
        previous_collected = who.collected - timedelta(days=days)
    degradation = None
    if conditions.photo:
        degradation = Degradation(seed=int(rng.integers(2**31)))
    return RenderSpec(
        report=patient.name,
        split=patient["split"],
        conditions=conditions,
        degradation=degradation,
        identity=who,
        previous_collected=previous_collected,
        rows=rows,
    )


def load_matrix(path: Path = MATRIX) -> dict[str, Conditions]:
    """Per report, its conditions from the variation matrix."""
    matrix = pd.read_csv(path, index_col="report", dtype=str, keep_default_na=False)
    conditions = {}
    for report, row in matrix.iterrows():
        conditions[report] = Conditions(
            layout=row["layout"],
            language=row["language"],
            unit_system=row["unit_system"],
            photo=row["photo"] == "yes",
            previous=row["previous"] == "yes",
            missing=row["missing"] or None,
            planted=row["planted"] or None,
        )
    return conditions


def write(model: BaseModel, folder: Path) -> None:
    folder.mkdir(exist_ok=True)
    text = json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False)
    (folder / f"{model.report}.json").write_text(text + "\n")


def main() -> None:
    patients = load_patients()
    matrix = load_matrix()
    if list(matrix) != list(patients.index):
        raise ValueError("the matrix must list every report, in order")
    for report, patient in patients.iterrows():
        write(truth(patient), TRUTH)
        write(render_spec(patient, matrix[report]), RENDER_SPEC)
    print(f"wrote {len(patients)} reports to {TRUTH} and {RENDER_SPEC}")


if __name__ == "__main__":
    main()

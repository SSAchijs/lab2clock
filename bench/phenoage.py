"""Phenotypic Age, computed directly from the published formula.

Source: Levine ME et al. An epigenetic biomarker of aging for lifespan and
healthspan. Aging 2018;10(4):573-591, Table 1 and supplementary methods.

This is written from the paper, not from pyaging, so that agreement between the
two is evidence that the units below are the ones the coefficients expect.
"""

import math

# Coefficients of the Gompertz mortality model (Levine 2018, Table 1), keyed by
# input name and the unit the coefficient was fitted in.
INTERCEPT = -19.9067
COEFFICIENTS = {
    "albumin": -0.0336,  # g/L
    "creatinine": 0.0095,  # umol/L
    "glucose": 0.1953,  # mmol/L
    "log_crp": 0.0954,  # ln(CRP in mg/dL)
    "lymphocyte_percent": -0.0120,  # %
    "mean_cell_volume": 0.0268,  # fL
    "red_cell_distribution_width": 0.3306,  # %
    "alkaline_phosphatase": 0.00188,  # U/L
    "white_blood_cell_count": 0.0554,  # 1000 cells/uL
    "age": 0.0804,  # years
}

# Keyword arguments of `phenoage`, in pyaging's feature order. CRP is taken raw
# and logged here, as pyaging does.
INPUTS = (
    "albumin",
    "creatinine",
    "glucose",
    "c_reactive_protein",
    "lymphocyte_percent",
    "mean_cell_volume",
    "red_cell_distribution_width",
    "alkaline_phosphatase",
    "white_blood_cell_count",
    "age",
)

# Gompertz shape parameter (supplementary methods, p. 2).
GAMMA = 0.0076927
# Mortality horizon of the score, in months.
HORIZON_MONTHS = 120


def linear_predictor(
    *,
    albumin: float,
    creatinine: float,
    glucose: float,
    c_reactive_protein: float,
    lymphocyte_percent: float,
    mean_cell_volume: float,
    red_cell_distribution_width: float,
    alkaline_phosphatase: float,
    white_blood_cell_count: float,
    age: float,
) -> float:
    """Return xb, the log hazard. CRP is raw, in mg/dL, and is logged here."""
    if c_reactive_protein <= 0:
        raise ValueError(f"CRP must be positive to take its log: {c_reactive_protein}")
    inputs = {
        "albumin": albumin,
        "creatinine": creatinine,
        "glucose": glucose,
        "log_crp": math.log(c_reactive_protein),
        "lymphocyte_percent": lymphocyte_percent,
        "mean_cell_volume": mean_cell_volume,
        "red_cell_distribution_width": red_cell_distribution_width,
        "alkaline_phosphatase": alkaline_phosphatase,
        "white_blood_cell_count": white_blood_cell_count,
        "age": age,
    }
    return INTERCEPT + sum(COEFFICIENTS[name] * inputs[name] for name in inputs)


def mortality_score(xb: float) -> float:
    """Return the 10-year mortality probability for a log hazard xb."""
    cumulative = (math.exp(HORIZON_MONTHS * GAMMA) - 1) / GAMMA
    return 1 - math.exp(-math.exp(xb) * cumulative)


def phenoage(**inputs: float) -> float:
    """Return Phenotypic Age in years. Takes the keyword arguments of
    `linear_predictor`, in the units listed in `COEFFICIENTS`."""
    m = mortality_score(linear_predictor(**inputs))
    return 141.50225 + math.log(-0.00553 * math.log(1 - m)) / 0.090165

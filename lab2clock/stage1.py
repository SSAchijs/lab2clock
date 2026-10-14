"""The stage-1 contract: what the model hands to code.

Stage 1 transcribes; it does not interpret. Every field is a string exactly as
printed, so 5,6 and <0.5 and 1.2 H survive intact and code decides what they
mean. A model asked for numbers could silently turn 5,6 into 56, and the
evidence of what it saw would be lost.

`json_schema()` is the schema handed to the API's structured-output mode, so
the model and the validator share one definition.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawItem(BaseModel):
    """One analyte row as printed on the report."""

    # Forbid unknown keys, so the schema says additionalProperties: false, which
    # strict structured-output modes require, and a stray key fails validation.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        description="The analyte name exactly as printed, in its original language.",
    )
    value: str = Field(
        min_length=1,
        description=(
            "The current result exactly as printed, including any comma, "
            "'<' or '>' sign, and flag such as H or L. Do not convert or round."
        ),
    )
    # No default: the model must say null when no unit is printed, rather than
    # leave the key out, so a missing unit is a decision and not an omission.
    unit: str | None = Field(
        description="The unit exactly as printed, or null if none is printed.",
    )
    page: int = Field(
        ge=1,
        description="The page the row is printed on, counting from 1.",
    )


class RawReport(BaseModel):
    """Everything stage 1 read from one report."""

    model_config = ConfigDict(extra="forbid")

    items: list[RawItem] = Field(
        description="Every analyte in the current-result column, in printed order.",
    )


def json_schema() -> dict[str, Any]:
    """The JSON schema of a stage-1 report, for the API's structured output."""
    return RawReport.model_json_schema()

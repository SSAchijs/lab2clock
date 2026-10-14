from datetime import date, timedelta

import pytest

from bench.identity import (
    COLLECTED,
    MAX_TURNAROUND,
    age_on,
    identity,
    years_before,
)
from bench.spec import RENDER_SPEC, TRUTH, RenderSpec, Truth
from lab2clock.synonyms import match

REPORTS = [f"R{i:02d}" for i in range(1, 26)]
TEXT_FIELDS = ("name", "patient_id", "specimen_id", "physician", "facility")


def committed(report):
    spec = RenderSpec.model_validate_json((RENDER_SPEC / f"{report}.json").read_text())
    t = Truth.model_validate_json((TRUTH / f"{report}.json").read_text())
    return spec.identity, t


@pytest.mark.parametrize("report", REPORTS)
def test_committed_dates_fit_the_truth(report):
    who, t = committed(report)
    assert age_on(who.date_of_birth, who.collected) == t.age
    assert COLLECTED[0] <= who.collected <= COLLECTED[1]
    assert who.collected <= who.reported <= who.collected + timedelta(MAX_TURNAROUND)


def test_committed_identities_differ():
    names = {committed(report)[0].name for report in REPORTS}
    assert len(names) == len(REPORTS)


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("age", [20, 50, 79])
def test_any_age_fits_in_either_language(language, age):
    for report in REPORTS:
        who = identity(report, age, language)
        assert age_on(who.date_of_birth, who.collected) == age


def test_same_report_same_identity():
    assert identity("R07", 52, "en") == identity("R07", 52, "en")


def test_chinese_identity_is_chinese():
    who = identity("R07", 52, "zh")
    assert all("一" <= ch <= "鿿" for ch in who.name)
    assert who.facility.endswith("人民医院")
    assert who.patient_id.isdigit()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_no_identity_text_reads_as_a_marker(language):
    # Distractors must stay distractors: none may map to a clock marker.
    for report in REPORTS:
        who = identity(report, 52, language)
        for field in TEXT_FIELDS:
            assert match(getattr(who, field)) is None, getattr(who, field)


@pytest.mark.parametrize(
    ("day", "years", "expected"),
    [
        (date(2026, 5, 5), 75, date(1951, 5, 5)),
        (date(2024, 2, 29), 1, date(2023, 2, 28)),
    ],
)
def test_years_before(day, years, expected):
    assert years_before(day, years) == expected


@pytest.mark.parametrize(
    ("birth", "day", "expected"),
    [
        (date(1950, 10, 14), date(2026, 10, 14), 76),
        (date(1950, 10, 14), date(2026, 10, 13), 75),
        (date(1952, 2, 29), date(2026, 2, 28), 73),
        (date(1952, 2, 29), date(2026, 3, 1), 74),
    ],
)
def test_age_on(birth, day, expected):
    assert age_on(birth, day) == expected

"""Fake identities for the reports, made with Faker from a seed.

Names, ID numbers, dates and a physician are distractor text: a real report is
full of numbers and names that are not results, and a reader must skip them. No
real person is involved, and the same report always gets the same identity.

The date of birth is drawn so the patient is exactly the truth's age on the
collection date, so the printout never contradicts the truth.
"""

from datetime import date, timedelta

from faker import Faker
from pydantic import BaseModel, ConfigDict

from bench.sample import SEED

LOCALES = {"en": "en_US", "zh": "zh_CN"}

# Collection dates fall in this window.
COLLECTED = (date(2025, 1, 1), date(2026, 6, 30))
# A report is issued up to this many days after collection.
MAX_TURNAROUND = 2


class Identity(BaseModel):
    """Who and when, as printed in a report's header."""

    model_config = ConfigDict(extra="forbid")

    name: str
    patient_id: str
    specimen_id: str
    date_of_birth: date
    collected: date
    reported: date
    physician: str
    facility: str


def years_before(day: date, years: int) -> date:
    """The same calendar day `years` earlier; 29 February becomes the 28th."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def age_on(birth: date, day: date) -> int:
    """Completed years from `birth` to `day`."""
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def identity(report: str, age: int, language: str) -> Identity:
    """The identity printed on `report`, in its language, for a patient of `age`."""
    fake = Faker(LOCALES[language])
    fake.seed_instance(f"{SEED}-{report}")
    collected = fake.date_between_dates(*COLLECTED)
    # Born at most `age` years and at least `age` + 1 years minus a day before.
    born = fake.date_between_dates(
        years_before(collected, age + 1) + timedelta(days=1),
        years_before(collected, age),
    )
    reported = collected + timedelta(days=fake.random_int(0, MAX_TURNAROUND))
    if language == "zh":
        return Identity(
            name=fake.name(),
            patient_id=fake.numerify("##########"),
            specimen_id=fake.numerify("############"),
            date_of_birth=born,
            collected=collected,
            reported=reported,
            physician=fake.name(),
            facility=f"{fake.city_name()}市人民医院",
        )
    return Identity(
        name=f"{fake.first_name()} {fake.last_name()}",
        patient_id=fake.numerify("MRN-########"),
        specimen_id=fake.bothify("??#######", letters="ABCDEFGHJKLMNPRSTUVWXYZ"),
        date_of_birth=born,
        collected=collected,
        reported=reported,
        physician=f"Dr. {fake.first_name()} {fake.last_name()}",
        facility=f"{fake.last_name()} Medical Laboratory",
    )

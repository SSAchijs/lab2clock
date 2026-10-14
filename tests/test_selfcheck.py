import pytest
from conftest import PRINTED, load_spec

from bench.selfcheck import check, check_all, expected


def row_with(spec, test):
    return next(i for i, row in enumerate(spec.rows) if test(row))


@pytest.mark.parametrize("report", PRINTED)
def test_every_printed_report_matches_its_spec(printed, report):
    assert check(load_spec(report), printed / f"{report}.pdf") == []


@pytest.mark.parametrize("report", PRINTED)
def test_two_values_swapped_between_rows_fail(printed, report):
    spec = load_spec(report)
    a, b = 0, len(spec.rows) - 1
    spec.rows[a].value, spec.rows[b].value = spec.rows[b].value, spec.rows[a].value
    problems = check(spec, printed / f"{report}.pdf")
    assert [p.split(" not")[0] for p in problems] == [f"row {a}", f"row {b}"]


@pytest.mark.parametrize("report", ["R01", "R02", "R04"])
def test_a_flag_the_pdf_prints_but_the_spec_lacks_fails(printed, report):
    spec = load_spec(report)
    i = row_with(spec, lambda row: row.flag)
    spec.rows[i].flag = None
    assert check(spec, printed / f"{report}.pdf") == [
        f"row {i} not printed on page {spec.rows[i].page}: "
        f"{expected(spec, spec.rows[i])}"
    ]


@pytest.mark.parametrize("report", ["R01", "R08"])
def test_a_wrong_previous_result_fails(printed, report):
    spec = load_spec(report)
    spec.rows[3].previous = "999"
    assert len(check(spec, printed / f"{report}.pdf")) == 1


def test_a_row_expected_on_another_page_fails(printed):
    spec = load_spec("R08")
    i = row_with(spec, lambda row: row.page == 1)
    spec.rows[i].page = 2
    assert len(check(spec, printed / "R08.pdf")) == 1


@pytest.mark.parametrize("report", ["R02", "R07"])
def test_a_two_column_interval_belongs_under_its_own_row(printed, report):
    spec = load_spec(report)
    # Swapping two rows' intervals keeps both strings on the page.
    spec.rows[0].reference, spec.rows[1].reference = (
        spec.rows[1].reference,
        spec.rows[0].reference,
    )
    assert len(check(spec, printed / f"{report}.pdf")) == 2


def test_a_missing_page_fails(printed):
    spec = load_spec("R01")
    spec.rows[-1].page = 2
    assert check(spec, printed / "R01.pdf") == ["1 pages printed, 2 expected"]


def test_a_missing_pdf_says_what_to_run(tmp_path):
    results = check_all(tmp_path)
    assert all("run bench.pdf first" in p[0] for p in results.values())

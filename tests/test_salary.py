from datetime import date

from app.services.salary import current_month_period, current_salary_period, current_week_period


def test_salary_period_first_half() -> None:
    assert current_salary_period(date(2026, 8, 11)) == (date(2026, 8, 1), date(2026, 8, 15))


def test_salary_period_second_half() -> None:
    assert current_salary_period(date(2026, 8, 20)) == (date(2026, 8, 16), date(2026, 8, 31))


def test_week_and_month_periods() -> None:
    assert current_week_period(date(2026, 8, 11)) == (date(2026, 8, 10), date(2026, 8, 16))
    assert current_month_period(date(2026, 8, 11)) == (date(2026, 8, 1), date(2026, 8, 31))

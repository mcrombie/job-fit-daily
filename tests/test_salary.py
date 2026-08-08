from __future__ import annotations

import unittest

from jobfit.salary import parse_salary_text, salary_display, structured_salary


class SalaryTests(unittest.TestCase):
    def test_parses_annual_range_with_k_suffix(self) -> None:
        salary = parse_salary_text("Compensation: $80k–$110k annually plus benefits")
        self.assertEqual(salary.annual_minimum_usd, 80_000)
        self.assertEqual(salary.annual_maximum_usd, 110_000)
        self.assertEqual(salary_display(salary), "$80,000–$110,000 / year")

    def test_annualizes_hourly_range(self) -> None:
        salary = parse_salary_text("Pay range is $35-$45/hour")
        self.assertEqual(salary.annual_minimum_usd, 72_800)
        self.assertEqual(salary.annual_maximum_usd, 93_600)

    def test_non_usd_structured_salary_is_not_assumed_usd(self) -> None:
        salary = structured_salary(70_000, 90_000, "EUR", "annual")
        self.assertFalse(salary.known_usd)
        self.assertIsNone(salary.annual_minimum_usd)

    def test_parses_single_annual_minimum(self) -> None:
        salary = parse_salary_text("Starting salary: $82,000 per year")
        self.assertEqual(salary.annual_minimum_usd, 82_000)
        self.assertIsNone(salary.annual_maximum_usd)


if __name__ == "__main__":
    unittest.main()

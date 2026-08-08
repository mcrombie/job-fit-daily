from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from jobfit.config import load_json
from jobfit.models import Job, Salary
from jobfit.ranking import deduplicate_jobs, rank_jobs
from tests.helpers import demo_jobs


ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_json(ROOT / "config" / "profile.json")
NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


class RankingTests(unittest.TestCase):
    def test_candidate_specific_demo_ranking(self) -> None:
        ranked, rejected = rank_jobs(demo_jobs(NOW), PROFILE, now=NOW)
        self.assertEqual(len(ranked), 8)
        self.assertEqual(len(rejected), 4)
        self.assertEqual(ranked[0].job.company, "ArchiveWorks")
        self.assertGreaterEqual(ranked[0].score, 90)
        self.assertIn("RAG", ranked[0].matched_skills)

        staff = next(item for item in ranked if item.job.company == "Scale Harbor")
        self.assertLess(staff.score, PROFILE["candidate"]["dashboard_min_score"])
        self.assertTrue(any("10 years" in concern for concern in staff.concerns))

        rejected_by_company = {item.job.company: item.rejection_reason for item in rejected}
        self.assertIn("salary ceiling", rejected_by_company["Small Pixel Studio"].lower())
        self.assertIn("outside", rejected_by_company["Rhine Data GmbH"].lower())
        self.assertIn("part-time", rejected_by_company["Night Owl Software"].lower())
        self.assertIn("internship", rejected_by_company["Model Orchard"].lower())

    def test_unknown_salary_is_concern_not_rejection(self) -> None:
        job = Job(
            source="Test",
            source_id="unknown-salary",
            title="Python Backend Engineer",
            company="Example",
            location="Remote — United States",
            url="https://example.com/job",
            description="Build FastAPI services in Python with SQL, APIs, tests, and Git. Two years experience.",
            employment_type="Full-time",
            remote=True,
            salary=Salary(),
            posted_at=NOW,
        )
        ranked, rejected = rank_jobs([job], PROFILE, now=NOW)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(len(ranked), 1)
        self.assertTrue(any("Salary is not listed" in concern for concern in ranked[0].concerns))

    def test_deduplicates_remote_cross_postings_and_keeps_richer_record(self) -> None:
        first = Job(
            source="Remotive",
            source_id="1",
            title="Python Engineer",
            company="Same Co",
            location="Remote",
            url="https://example.com/a",
            description="Short",
        )
        second = Job(
            source="Greenhouse",
            source_id="2",
            title="Python Engineer",
            company="Same Co",
            location="Remote — United States",
            url="https://example.com/b",
            description="A much richer description with Python, FastAPI, testing, APIs, and SQL.",
            salary=Salary(90_000, 120_000, "USD", "annual", annual_minimum_usd=90_000, annual_maximum_usd=120_000),
        )
        unique = deduplicate_jobs([first, second])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0].source, "Greenhouse")
        self.assertEqual(unique[0].raw["also_seen_on"], ["Greenhouse", "Remotive"])


if __name__ == "__main__":
    unittest.main()

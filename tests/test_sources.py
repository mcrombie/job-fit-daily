from __future__ import annotations

import unittest
from unittest.mock import patch

from jobfit.sources import fetch_arbeitnow, fetch_greenhouse, fetch_himalayas, fetch_lever, fetch_remotive


BASE = {
    "http": {"timeout_seconds": 1, "retries": 1, "user_agent": "test"},
}


class SourceNormalizationTests(unittest.TestCase):
    @patch("jobfit.sources.get_json")
    def test_himalayas_normalization(self, get_json) -> None:
        get_json.return_value = {
            "totalCount": 1,
            "jobs": [{
                "guid": "h1",
                "title": "Python Engineer",
                "companyName": "Himalaya Co",
                "locationRestrictions": [{"alpha2": "US", "name": "United States"}],
                "applicationLink": "https://example.com/h1",
                "description": "<p>Python and FastAPI</p>",
                "pubDate": "2026-08-06T00:00:00Z",
                "employmentType": "Full-time",
                "minSalary": 90000,
                "maxSalary": 120000,
                "currency": "USD",
                "salaryPeriod": "annual",
            }],
        }
        jobs = fetch_himalayas({**BASE, "himalayas": {"enabled": True, "max_pages": 1, "page_size": 20}})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "Remote — United States")
        self.assertEqual(jobs[0].description, "Python and FastAPI")
        self.assertEqual(jobs[0].salary.annual_minimum_usd, 90_000)

    @patch("jobfit.sources.get_json")
    def test_remotive_normalization(self, get_json) -> None:
        get_json.return_value = {"jobs": [{
            "id": 5,
            "title": "Technical Writer",
            "company_name": "Docs Co",
            "candidate_required_location": "USA",
            "url": "https://example.com/r5",
            "description": "<p>API documentation</p>",
            "publication_date": "2026-08-06T00:00:00Z",
            "job_type": "full_time",
            "salary": "$80k-$100k/year",
            "category": "Writing",
        }]}
        jobs = fetch_remotive({**BASE, "remotive": {"enabled": True, "limit": 50}})
        self.assertEqual(jobs[0].company, "Docs Co")
        self.assertEqual(jobs[0].salary.annual_maximum_usd, 100_000)

    @patch("jobfit.sources.get_json")
    def test_arbeitnow_follows_next_link(self, get_json) -> None:
        get_json.side_effect = [
            {"data": [{
                "slug": "one", "title": "Data Analyst", "company_name": "One", "location": "Virginia",
                "url": "https://example.com/one", "description": "SQL", "remote": False,
                "created_at": "2026-08-06", "job_types": ["Full-time"], "tags": ["Data"],
            }], "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"}},
            {"data": [{
                "slug": "two", "title": "QA Engineer", "company_name": "Two", "location": "Remote",
                "url": "https://example.com/two", "description": "pytest", "remote": True,
                "created_at": "2026-08-06", "job_types": ["Full-time"], "tags": ["QA"],
            }], "links": {"next": None}},
        ]
        jobs = fetch_arbeitnow({**BASE, "arbeitnow": {"enabled": True, "max_pages": 3}})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(get_json.call_count, 2)
        self.assertEqual(get_json.call_args_list[1].args[0], "https://www.arbeitnow.com/api/job-board-api?page=2")

    @patch("jobfit.sources.get_json")
    def test_greenhouse_normalization(self, get_json) -> None:
        get_json.return_value = {"jobs": [{
            "id": 9,
            "title": "Software Engineer",
            "location": {"name": "Remote, US"},
            "absolute_url": "https://example.com/g9",
            "content": "<p>Python $90,000-$120,000 per year</p>",
            "updated_at": "2026-08-06T00:00:00Z",
            "departments": [{"name": "Engineering"}],
            "offices": [],
        }]}
        jobs = fetch_greenhouse({**BASE, "greenhouse": {"enabled": True, "boards": [{"token": "demo", "company": "Demo Co"}]}})
        self.assertEqual(jobs[0].company, "Demo Co")
        self.assertTrue(jobs[0].remote)
        self.assertEqual(jobs[0].categories, ["Engineering"])

    @patch("jobfit.sources.get_json")
    def test_lever_normalization(self, get_json) -> None:
        get_json.return_value = [{
            "id": "l1",
            "text": "Solutions Engineer",
            "hostedUrl": "https://example.com/l1",
            "descriptionPlain": "APIs and Python",
            "additionalPlain": "Customer implementation",
            "createdAt": 1786032000000,
            "workplaceType": "remote",
            "categories": {"location": "United States", "commitment": "Full-time", "team": "Solutions"},
            "salaryRange": {"min": 95000, "max": 125000, "currency": "USD", "interval": "annual"},
        }]
        jobs = fetch_lever({**BASE, "lever": {"enabled": True, "sites": [{"site": "demo", "company": "Demo Lever"}]}})
        self.assertEqual(jobs[0].company, "Demo Lever")
        self.assertTrue(jobs[0].remote)
        self.assertEqual(jobs[0].salary.annual_minimum_usd, 95_000)


if __name__ == "__main__":
    unittest.main()

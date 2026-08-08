from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jobfit.config import load_json
from jobfit.models import SourceStatus
from jobfit.ranking import rank_jobs
from jobfit.render import build_payload, render_site
from jobfit.state import annotate_and_update_seen
from tests.helpers import demo_jobs


ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_json(ROOT / "config" / "profile.json")
NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


class StateAndRenderTests(unittest.TestCase):
    def test_seen_state_marks_first_run_new_and_second_run_old(self) -> None:
        ranked, _ = rank_jobs(demo_jobs(NOW), PROFILE, now=NOW)
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            annotate_and_update_seen(ranked, state_path, now=NOW)
            self.assertTrue(all(item.is_new for item in ranked))
            ranked_again, _ = rank_jobs(demo_jobs(NOW), PROFILE, now=NOW)
            annotate_and_update_seen(ranked_again, state_path, now=NOW)
            self.assertTrue(all(not item.is_new for item in ranked_again))

    def test_static_dashboard_and_json_are_written(self) -> None:
        ranked, rejected = rank_jobs(demo_jobs(NOW), PROFILE, now=NOW)
        selected = [item for item in ranked if item.score >= 42]
        annotate_and_update_seen(selected, Path("/does/not/matter"), now=NOW, persist=False)
        payload = build_payload(
            selected,
            [SourceStatus("Fixture", True, fetched=12, kept=8)],
            PROFILE,
            generated_at=NOW,
            fetched_count=12,
            eligible_count=len(ranked),
            rejected_count=len(rejected),
            below_threshold_count=1,
            demo=True,
        )
        with TemporaryDirectory() as directory:
            output = Path(directory)
            render_site(payload, output)
            html = (output / "index.html").read_text(encoding="utf-8")
            jobs_json = json.loads((output / "jobs.json").read_text(encoding="utf-8"))
            self.assertIn("Michael's Daily Job Fits", html)
            self.assertIn("ArchiveWorks", html)
            self.assertIn("Demonstration data", html)
            self.assertEqual(len(jobs_json["jobs"]), len(selected))
            self.assertTrue((output / ".nojekyll").exists())


if __name__ == "__main__":
    unittest.main()

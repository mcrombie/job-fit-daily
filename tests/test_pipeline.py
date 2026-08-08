from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from jobfit.config import Paths
from jobfit.models import SourceStatus
from jobfit.pipeline import run_pipeline
from tests.helpers import demo_jobs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def temporary_paths(directory: str) -> Paths:
    root = Path(directory)
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "config" / "profile.json", config_dir / "profile.json")
    shutil.copy2(PROJECT_ROOT / "config" / "sources.json", config_dir / "sources.json")
    data_dir = root / "data"
    site_dir = root / "site"
    data_dir.mkdir()
    site_dir.mkdir()
    return Paths(
        root=root,
        profile=config_dir / "profile.json",
        sources=config_dir / "sources.json",
        data_dir=data_dir,
        site_dir=site_dir,
    )


class PipelineReliabilityTests(unittest.TestCase):
    def test_all_zero_with_source_failure_preserves_previous_dashboard(self) -> None:
        with TemporaryDirectory() as directory:
            paths = temporary_paths(directory)
            dashboard = paths.site_dir / "index.html"
            dashboard.write_text("known-good-dashboard", encoding="utf-8")
            statuses = [SourceStatus("Broken feed", False, fetched=0, message="temporary outage")]

            with patch("jobfit.pipeline.fetch_all_sources", return_value=([], statuses)):
                with self.assertRaisesRegex(RuntimeError, "preserving the previous dashboard"):
                    run_pipeline(paths, now=NOW, send_email=False)

            self.assertEqual(dashboard.read_text(encoding="utf-8"), "known-good-dashboard")
            self.assertFalse((paths.data_dir / "state.json").exists())

    def test_partial_source_failure_still_publishes_available_jobs(self) -> None:
        with TemporaryDirectory() as directory:
            paths = temporary_paths(directory)
            jobs = demo_jobs(NOW)[:2]
            statuses = [
                SourceStatus(jobs[0].source, True, fetched=2, message="ok"),
                SourceStatus("Broken feed", False, fetched=0, message="temporary outage"),
            ]

            with patch("jobfit.pipeline.fetch_all_sources", return_value=(jobs, statuses)):
                result = run_pipeline(paths, now=NOW, send_email=False)

            self.assertGreaterEqual(result["shown"], 1)
            self.assertTrue((paths.site_dir / "index.html").exists())
            self.assertTrue((paths.data_dir / "state.json").exists())
            payload = json.loads((paths.site_dir / "jobs.json").read_text(encoding="utf-8"))
            broken = next(source for source in payload["sources"] if source["source"] == "Broken feed")
            self.assertFalse(broken["ok"])


if __name__ == "__main__":
    unittest.main()

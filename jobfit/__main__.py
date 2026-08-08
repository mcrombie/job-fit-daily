from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import load_configuration, resolve_paths
from .pipeline import run_pipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobfit",
        description="Collect, rank, and publish candidate-specific daily job matches.",
    )
    parser.add_argument("--profile", help="Path to profile JSON")
    parser.add_argument("--sources", help="Path to source configuration JSON")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Fetch live feeds and build the dashboard")
    run.add_argument("--no-email", action="store_true", help="Do not send the optional digest email")

    demo = subparsers.add_parser("demo", help="Build a dashboard from synthetic fixture data")
    demo.add_argument("--fixture", help="Path to a normalized fixture JSON file")

    subparsers.add_parser("validate", help="Validate configuration and exit")

    gate = subparsers.add_parser("should-run", help="Print a GitHub Actions-compatible DST schedule gate")
    gate.add_argument("--hour", type=int, default=8, help="Required local hour (0-23)")
    gate.add_argument("--timezone", default="America/New_York", help="IANA time zone")
    gate.add_argument("--now", help="Override current UTC time with an ISO-8601 timestamp")
    return parser


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Invalid --now timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        paths = resolve_paths(args.profile, args.sources)
        if args.command == "validate":
            profile, sources = load_configuration(paths)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "candidate": profile.get("candidate", {}).get("name"),
                        "role_families": len(profile.get("role_families", [])),
                        "configured_sources": [
                            key
                            for key, value in sources.items()
                            if isinstance(value, dict) and "enabled" in value
                        ],
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "should-run":
            if not 0 <= args.hour <= 23:
                raise RuntimeError("--hour must be between 0 and 23")
            try:
                zone = ZoneInfo(args.timezone)
            except ZoneInfoNotFoundError as exc:
                raise RuntimeError(f"Unknown time zone: {args.timezone}") from exc
            local = _parse_now(args.now).astimezone(zone)
            should_run = local.hour == args.hour
            print(f"run={'true' if should_run else 'false'}")
            print(f"local_time={local.isoformat()}")
            return 0
        if args.command == "demo":
            fixture = Path(args.fixture) if args.fixture else paths.root / "tests" / "fixtures" / "demo_jobs.json"
            result = run_pipeline(paths, fixture_path=fixture, demo=True, send_email=False)
        else:
            result = run_pipeline(paths, send_email=not args.no_email)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("Job-fit pipeline failed")
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

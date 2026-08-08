from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
import html
import os
import smtplib
import ssl
from typing import Any, Iterable

from .models import RankedJob
from .salary import salary_display
from .text import excerpt


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _email_ready() -> tuple[bool, str]:
    required = ["SMTP_HOST", "SMTP_FROM", "DIGEST_TO"]
    missing = [name for name in required if not _env(name)]
    if missing:
        return False, "Email skipped; missing " + ", ".join(missing)
    return True, ""


def _job_html(item: RankedJob) -> str:
    job = item.job
    reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in item.reasons[:4])
    concerns = "".join(f"<li>{html.escape(concern)}</li>" for concern in item.concerns[:3])
    concern_block = f"<p><strong>Check:</strong></p><ul>{concerns}</ul>" if concerns else ""
    return f"""
      <div style="border:1px solid #d9e0e8;border-radius:12px;padding:18px;margin:0 0 14px;background:#ffffff">
        <div style="font-size:13px;color:#54707a;font-weight:700">FIT SCORE {item.score:.0f} · {html.escape(item.family_label)}</div>
        <h2 style="margin:5px 0 2px;font-size:21px;line-height:1.2"><a href="{html.escape(job.url, quote=True)}" style="color:#123f4b">{html.escape(job.title)}</a></h2>
        <div style="font-weight:700;color:#267067">{html.escape(job.company)}</div>
        <p style="margin:9px 0;color:#4f5f6d">{html.escape(job.location)} · {html.escape(salary_display(job.salary))} · {html.escape(job.employment_type or 'Type not listed')}</p>
        <p style="color:#324452">{html.escape(excerpt(job.description, 300))}</p>
        <p><strong>Why it fits:</strong></p><ul>{reasons}</ul>
        {concern_block}
        <p style="font-size:12px;color:#71808b">Found via {html.escape(job.source)}. Verify all details on the original posting.</p>
      </div>
    """


def send_digest(
    ranked_jobs: Iterable[RankedJob],
    profile: dict[str, Any],
    source_config: dict[str, Any],
    *,
    generated_at: datetime,
    dashboard_url: str = "",
) -> tuple[bool, str]:
    notifications = source_config.get("notifications", {})
    if not notifications.get("email_enabled", True):
        return False, "Email disabled in config/sources.json"
    ready, message = _email_ready()
    if not ready:
        return False, message

    candidate = profile.get("candidate", {})
    threshold = float(candidate.get("email_min_score", 58))
    maximum = int(candidate.get("max_email_results", 12))
    jobs = [item for item in ranked_jobs if item.score >= threshold and item.is_new][:maximum]
    if not jobs and not notifications.get("send_when_no_new_matches", True):
        return False, "Email skipped because there were no new matches above the email threshold"

    subject_date = generated_at.strftime("%b %-d, %Y") if os.name != "nt" else generated_at.strftime("%b %d, %Y").replace(" 0", " ")
    subject = f"Daily job fits: {len(jobs)} new match{'es' if len(jobs) != 1 else ''} — {subject_date}"
    if jobs:
        body = "".join(_job_html(item) for item in jobs)
        intro = f"<p>Here are the strongest new roles scoring at least {threshold:.0f} today.</p>"
    else:
        body = "<p>No new roles cleared the email threshold today. The dashboard still contains the current ranked set.</p>"
        intro = ""
    dashboard = (
        f'<p><a href="{html.escape(dashboard_url, quote=True)}" style="display:inline-block;background:#70d0bd;color:#07232a;padding:10px 14px;border-radius:8px;text-decoration:none;font-weight:700">Open the full dashboard</a></p>'
        if dashboard_url
        else ""
    )
    html_body = f"""
    <!doctype html><html><body style="margin:0;background:#eef3f6;font-family:Arial,sans-serif;color:#1c2d36">
      <div style="max-width:760px;margin:0 auto;padding:28px 18px">
        <h1 style="margin:0 0 8px;color:#0d3c48">{html.escape(str(candidate.get('dashboard_title', 'Daily Job Fits')))}</h1>
        {intro}{dashboard}{body}
        <p style="font-size:12px;color:#71808b">The fit score is a deterministic triage aid, not a hiring probability. Job data can change after collection.</p>
      </div>
    </body></html>
    """

    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = _env("SMTP_FROM")
    email["To"] = _env("DIGEST_TO")
    email.set_content("Open the HTML version of this message to view the daily job-fit digest.")
    email.add_alternative(html_body, subtype="html")

    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "465" if _env("SMTP_SECURITY", "starttls").lower() == "ssl" else "587"))
    username = _env("SMTP_USERNAME")
    password = _env("SMTP_PASSWORD")
    security = _env("SMTP_SECURITY", "starttls").lower()
    context = ssl.create_default_context()

    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
            if username:
                server.login(username, password)
            server.send_message(email)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            if security != "none":
                server.starttls(context=context)
                server.ehlo()
            if username:
                server.login(username, password)
            server.send_message(email)
    return True, f"Email sent to {_env('DIGEST_TO')} with {len(jobs)} new matches"

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from .models import RankedJob, SourceStatus, iso_or_none
from .salary import salary_display
from .state import write_json_atomic
from .text import excerpt


_SOURCE_ATTRIBUTION = {
    "Himalayas": ("Jobs sourced through Himalayas", "https://himalayas.app/jobs"),
    "Remotive": ("Jobs sourced through Remotive", "https://remotive.com/remote-jobs"),
    "Arbeitnow": ("Jobs sourced through Arbeitnow", "https://www.arbeitnow.com/"),
    "Greenhouse": ("Employer job board powered by Greenhouse", "https://www.greenhouse.com/"),
    "Lever": ("Employer job board powered by Lever", "https://www.lever.co/"),
    "USAJOBS": ("Federal jobs sourced through USAJOBS", "https://www.usajobs.gov/"),
}


def safe_url(value: str | None, fallback: str = "#") -> str:
    if not value:
        return fallback
    parts = urlsplit(str(value).strip())
    if parts.scheme in {"http", "https"} and parts.netloc:
        return str(value).strip()
    return fallback


def _posted_label(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "Date not listed"
    days = max(0, int((now - value).total_seconds() // 86400))
    if days == 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    return f"Posted {days} days ago"


def _compact_job(ranked: RankedJob, now: datetime) -> dict[str, Any]:
    job = ranked.job
    attribution_text, attribution_url = _SOURCE_ATTRIBUTION.get(
        job.source,
        (f"Sourced through {job.source}", job.source_url),
    )
    return {
        "id": job.fingerprint,
        "key": job.canonical_key,
        "score": round(ranked.score, 1),
        "is_new": ranked.is_new,
        "first_seen": ranked.first_seen,
        "title": job.title,
        "company": job.company,
        "location": job.location or "Location not listed",
        "url": safe_url(job.url),
        "description": excerpt(job.description, 520),
        "posted_at": iso_or_none(job.posted_at),
        "posted_label": _posted_label(job.posted_at, now),
        "expires_at": iso_or_none(job.expires_at),
        "employment_type": job.employment_type or "Employment type not listed",
        "remote": bool(job.remote) or "remote" in job.location.lower(),
        "salary": salary_display(job.salary),
        "salary_known": job.salary.known_usd,
        "salary_minimum_usd": job.salary.annual_minimum_usd,
        "salary_maximum_usd": job.salary.annual_maximum_usd,
        "family_id": ranked.family_id,
        "family_label": ranked.family_label,
        "reasons": ranked.reasons,
        "concerns": ranked.concerns,
        "skills": ranked.matched_skills,
        "breakdown": ranked.breakdown,
        "source": job.source,
        "source_url": safe_url(job.source_url, safe_url(attribution_url)),
        "attribution_text": attribution_text,
        "attribution_url": safe_url(attribution_url),
    }


def _source_statuses(statuses: Iterable[SourceStatus]) -> list[dict[str, Any]]:
    return [status.to_dict() for status in statuses]


def _statistics(jobs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "shown": len(jobs),
        "new": sum(1 for job in jobs if job["is_new"]),
        "remote": sum(1 for job in jobs if job["remote"]),
        "salary_known": sum(1 for job in jobs if job["salary_known"]),
        "high_confidence": sum(1 for job in jobs if job["score"] >= 70),
    }


def build_payload(
    ranked_jobs: Iterable[RankedJob],
    statuses: Iterable[SourceStatus],
    profile: dict[str, Any],
    *,
    generated_at: datetime,
    fetched_count: int,
    eligible_count: int,
    rejected_count: int,
    below_threshold_count: int,
    demo: bool = False,
) -> dict[str, Any]:
    generated_at = generated_at.astimezone(timezone.utc)
    jobs = [_compact_job(item, generated_at) for item in ranked_jobs]
    families = [
        {"id": str(item.get("id", "")), "label": str(item.get("label", ""))}
        for item in profile.get("role_families", [])
    ]
    candidate = profile.get("candidate", {})
    return {
        "schema_version": 1,
        "generated_at": iso_or_none(generated_at),
        "demo": demo,
        "candidate": {
            "name": candidate.get("name", "Candidate"),
            "dashboard_title": candidate.get("dashboard_title", "Daily Job Fits"),
            "home_location": candidate.get("home_location", ""),
            "search_scope": candidate.get("search_scope", ""),
            "minimum_salary_usd": candidate.get("minimum_salary_usd", 0),
            "dashboard_min_score": candidate.get("dashboard_min_score", 0),
        },
        "families": families,
        "jobs": jobs,
        "statistics": _statistics(jobs),
        "pipeline": {
            "fetched": fetched_count,
            "eligible": eligible_count,
            "rejected": rejected_count,
            "below_threshold": below_threshold_count,
        },
        "sources": _source_statuses(statuses),
    }


def _dashboard_html(payload: dict[str, Any]) -> str:
    title = html.escape(str(payload["candidate"]["dashboard_title"]))
    generated = html.escape(str(payload["generated_at"]))
    json_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    demo_banner = (
        '<div class="demo-banner"><strong>Demonstration data:</strong> run <code>python -m jobfit run</code> '
        "or trigger the GitHub workflow to replace these examples with live jobs.</div>"
        if payload.get("demo")
        else ""
    )

    template = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta name="description" content="A private, candidate-specific daily job fit dashboard.">
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: dark;
      --background: #08111f;
      --surface: #101d2f;
      --surface-raised: #14243a;
      --surface-soft: #0d1929;
      --border: rgba(176, 200, 229, 0.18);
      --border-strong: rgba(176, 200, 229, 0.35);
      --text: #edf4ff;
      --muted: #9eb0c6;
      --faint: #6f839d;
      --accent: #83d9c5;
      --accent-strong: #b1f1df;
      --gold: #f0cf7b;
      --danger: #ff9a9a;
      --success: #9ce6b4;
      --shadow: 0 22px 70px rgba(0, 0, 0, 0.24);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 15% -10%, rgba(67, 137, 154, 0.24), transparent 34rem),
        radial-gradient(circle at 95% 3%, rgba(147, 100, 57, 0.16), transparent 30rem),
        var(--background);
      line-height: 1.5;
    }
    a { color: inherit; }
    button, input, select { font: inherit; }
    button, select, input[type="checkbox"] { cursor: pointer; }
    code {
      padding: .1rem .35rem;
      border: 1px solid var(--border);
      border-radius: .35rem;
      background: rgba(255,255,255,.05);
      font-size: .9em;
    }
    .page-shell { width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding-bottom: 72px; }
    .hero { padding: 56px 0 28px; }
    .eyebrow {
      display: flex; align-items: center; gap: 9px; margin-bottom: 12px;
      color: var(--accent); font-size: .76rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase;
    }
    .eyebrow::before { content: ""; width: 28px; height: 1px; background: var(--accent); }
    h1 { margin: 0; max-width: 900px; font-size: clamp(2.2rem, 5vw, 4.7rem); line-height: .98; letter-spacing: -.055em; }
    .hero-copy { max-width: 790px; margin: 20px 0 0; color: var(--muted); font-size: clamp(1rem, 1.6vw, 1.2rem); }
    .hero-meta { display: flex; flex-wrap: wrap; gap: 10px 20px; margin-top: 20px; color: var(--faint); font-size: .88rem; }
    .hero-meta strong { color: var(--text); font-weight: 650; }
    .demo-banner {
      margin: 6px 0 24px; padding: 12px 15px; border: 1px solid rgba(240,207,123,.38);
      border-radius: 12px; background: rgba(240,207,123,.08); color: #f7e5b7;
    }
    .stats-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 10px 0 24px; }
    .stat {
      padding: 17px; border: 1px solid var(--border); border-radius: 14px;
      background: linear-gradient(145deg, rgba(255,255,255,.055), rgba(255,255,255,.018));
    }
    .stat-value { font-size: 1.55rem; font-weight: 800; letter-spacing: -.035em; }
    .stat-label { margin-top: 2px; color: var(--faint); font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }
    .toolbar {
      position: sticky; top: 10px; z-index: 10; display: grid;
      grid-template-columns: minmax(210px, 1.7fr) repeat(3, minmax(130px, .7fr)); gap: 11px;
      padding: 14px; border: 1px solid var(--border-strong); border-radius: var(--radius);
      background: rgba(9, 20, 34, .91); box-shadow: var(--shadow); backdrop-filter: blur(20px);
    }
    .control { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
    .control label { color: var(--faint); font-size: .7rem; font-weight: 750; text-transform: uppercase; letter-spacing: .09em; }
    input[type="search"], select {
      width: 100%; min-height: 42px; padding: 9px 11px; color: var(--text);
      border: 1px solid var(--border); border-radius: 10px; background: var(--surface-soft); outline: none;
    }
    input[type="search"]:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(131,217,197,.12); }
    .toolbar-row {
      grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap; gap: 9px 18px;
      padding-top: 2px; color: var(--muted); font-size: .85rem;
    }
    .check { display: inline-flex; align-items: center; gap: 7px; }
    .score-control { display: inline-flex; align-items: center; gap: 8px; min-width: min(380px, 100%); flex: 1; }
    input[type="range"] { flex: 1; accent-color: var(--accent); }
    .score-readout { min-width: 30px; color: var(--accent-strong); font-weight: 800; }
    .toolbar-button {
      border: 1px solid var(--border); border-radius: 9px; background: rgba(255,255,255,.04);
      color: var(--muted); padding: 7px 10px;
    }
    .toolbar-button:hover { color: var(--text); border-color: var(--border-strong); }
    .results-bar { display: flex; justify-content: space-between; align-items: center; gap: 18px; margin: 26px 2px 12px; color: var(--muted); }
    .results-bar strong { color: var(--text); }
    .job-list { display: grid; gap: 15px; }
    .job-card {
      display: grid; grid-template-columns: 88px minmax(0, 1fr); overflow: hidden;
      border: 1px solid var(--border); border-radius: var(--radius); background: linear-gradient(145deg, var(--surface-raised), var(--surface));
      box-shadow: 0 12px 36px rgba(0,0,0,.13); transition: border-color .16s ease, transform .16s ease;
    }
    .job-card:hover { transform: translateY(-1px); border-color: var(--border-strong); }
    .job-card[data-status="applied"] { border-color: rgba(156,230,180,.5); }
    .job-card[data-status="saved"] { border-color: rgba(240,207,123,.48); }
    .score-column {
      padding: 22px 12px; border-right: 1px solid var(--border); background: rgba(3, 11, 21, .24); text-align: center;
    }
    .score-number { font-size: 1.75rem; font-weight: 900; letter-spacing: -.055em; color: var(--accent-strong); }
    .score-label { color: var(--faint); font-size: .64rem; letter-spacing: .1em; text-transform: uppercase; }
    .score-tier { margin-top: 9px; font-size: .68rem; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }
    .score-tier.high { color: var(--success); }
    .score-tier.good { color: var(--gold); }
    .score-tier.possible { color: var(--muted); }
    .job-body { min-width: 0; padding: 21px 22px 18px; }
    .job-top { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
    .title-wrap { min-width: 0; }
    .badges { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 7px; }
    .badge {
      display: inline-flex; align-items: center; min-height: 22px; padding: 3px 8px;
      border-radius: 999px; color: var(--muted); background: rgba(255,255,255,.055); font-size: .68rem; font-weight: 750;
    }
    .badge.new { color: #07151b; background: var(--accent); }
    .badge.family { color: #f4dfad; background: rgba(240,207,123,.13); }
    .badge.status { color: var(--success); background: rgba(156,230,180,.11); }
    .job-title { margin: 0; font-size: clamp(1.25rem, 2.3vw, 1.72rem); line-height: 1.18; letter-spacing: -.025em; }
    .job-title a { text-decoration: none; }
    .job-title a:hover { text-decoration: underline; text-decoration-color: var(--accent); text-underline-offset: 4px; }
    .company { margin-top: 5px; color: var(--accent-strong); font-weight: 720; }
    .meta { display: flex; flex-wrap: wrap; gap: 7px 16px; margin: 14px 0 0; color: var(--muted); font-size: .86rem; }
    .meta span { display: inline-flex; align-items: center; gap: 5px; }
    .description { margin: 16px 0 0; color: #c4d0df; }
    .fit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }
    .fit-box { padding: 13px 14px; border: 1px solid var(--border); border-radius: 12px; background: rgba(2,10,20,.18); }
    .fit-box h3 { margin: 0 0 7px; font-size: .72rem; color: var(--faint); letter-spacing: .1em; text-transform: uppercase; }
    .fit-box ul { margin: 0; padding-left: 18px; }
    .fit-box li { margin: 4px 0; color: #ccd8e6; font-size: .87rem; }
    .fit-box.concerns li { color: #d7c3be; }
    .skills { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
    .skill { padding: 3px 7px; border: 1px solid rgba(131,217,197,.22); border-radius: 7px; color: var(--accent-strong); font-size: .72rem; }
    .job-footer { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }
    .source { color: var(--faint); font-size: .76rem; }
    .source a { color: var(--muted); text-underline-offset: 3px; }
    .actions { display: flex; flex-wrap: wrap; gap: 7px; }
    .action {
      min-height: 36px; padding: 7px 11px; border: 1px solid var(--border); border-radius: 9px;
      background: rgba(255,255,255,.035); color: var(--muted); font-weight: 680; font-size: .8rem;
    }
    .action:hover, .action.active { color: var(--text); border-color: var(--border-strong); background: rgba(255,255,255,.075); }
    .action.saved.active { color: var(--gold); border-color: rgba(240,207,123,.45); }
    .action.applied.active { color: var(--success); border-color: rgba(156,230,180,.45); }
    .action.hide.active { color: var(--danger); border-color: rgba(255,154,154,.38); }
    .view-role { color: #07151b; background: var(--accent); border-color: var(--accent); text-decoration: none; }
    .view-role:hover { color: #07151b; background: var(--accent-strong); }
    details.breakdown { margin-top: 13px; color: var(--faint); font-size: .76rem; }
    details.breakdown summary { cursor: pointer; width: max-content; }
    .breakdown-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .breakdown-grid span { padding: 3px 7px; border: 1px solid var(--border); border-radius: 7px; }
    .empty { padding: 56px 24px; border: 1px dashed var(--border-strong); border-radius: var(--radius); text-align: center; color: var(--muted); }
    .methodology, .source-health {
      margin-top: 24px; padding: 18px 20px; border: 1px solid var(--border); border-radius: 14px; background: rgba(255,255,255,.025);
    }
    .methodology summary, .source-health summary { cursor: pointer; font-weight: 760; }
    .methodology p, .source-health p { color: var(--muted); }
    .source-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .source-pill { padding: 6px 9px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: .75rem; }
    .source-pill.ok::before { content: "●"; margin-right: 6px; color: var(--success); }
    .source-pill.failed::before { content: "●"; margin-right: 6px; color: var(--danger); }
    footer { margin-top: 34px; color: var(--faint); font-size: .76rem; text-align: center; }
    @media (max-width: 900px) {
      .stats-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .toolbar { position: static; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .control.search { grid-column: 1 / -1; }
    }
    @media (max-width: 650px) {
      .page-shell { width: min(100% - 20px, 1280px); }
      .hero { padding-top: 34px; }
      .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .toolbar { grid-template-columns: 1fr; }
      .control.search, .toolbar-row { grid-column: 1; }
      .toolbar-row { align-items: flex-start; flex-direction: column; }
      .job-card { grid-template-columns: 1fr; }
      .score-column { display: flex; align-items: baseline; gap: 7px; padding: 11px 18px; border-right: 0; border-bottom: 1px solid var(--border); text-align: left; }
      .score-number { font-size: 1.3rem; }
      .score-tier { margin: 0 0 0 auto; }
      .job-body { padding: 18px 16px 16px; }
      .fit-grid { grid-template-columns: 1fr; }
      .job-top { display: block; }
    }
  </style>
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div class="eyebrow">Candidate-specific daily search</div>
      <h1>__TITLE__</h1>
      <p class="hero-copy">A ranked shortlist across software, AI applications, developer support, QA, technical writing, data, and research-software roles. Scores are transparent triage signals—not claims about hiring probability.</p>
      <div class="hero-meta">
        <span>Updated <strong id="updated-at">__GENERATED__</strong></span>
        <span>Salary floor <strong id="salary-floor"></strong></span>
        <span>Scope <strong id="search-scope"></strong></span>
      </div>
    </header>
    __DEMO_BANNER__
    <section class="stats-grid" aria-label="Digest summary">
      <div class="stat"><div class="stat-value" id="stat-shown">0</div><div class="stat-label">ranked jobs</div></div>
      <div class="stat"><div class="stat-value" id="stat-new">0</div><div class="stat-label">new today</div></div>
      <div class="stat"><div class="stat-value" id="stat-high">0</div><div class="stat-label">70+ score</div></div>
      <div class="stat"><div class="stat-value" id="stat-remote">0</div><div class="stat-label">remote</div></div>
      <div class="stat"><div class="stat-value" id="stat-salary">0</div><div class="stat-label">salary listed</div></div>
    </section>

    <section class="toolbar" aria-label="Job filters">
      <div class="control search">
        <label for="search">Search results</label>
        <input id="search" type="search" placeholder="Title, company, skill, location…" autocomplete="off">
      </div>
      <div class="control">
        <label for="family">Role family</label>
        <select id="family"><option value="all">All role families</option></select>
      </div>
      <div class="control">
        <label for="status-filter">Review status</label>
        <select id="status-filter">
          <option value="active">Active (hide hidden)</option>
          <option value="all">All</option>
          <option value="unreviewed">Unreviewed</option>
          <option value="saved">Saved</option>
          <option value="applied">Applied</option>
          <option value="hidden">Hidden</option>
        </select>
      </div>
      <div class="control">
        <label for="sort">Sort</label>
        <select id="sort">
          <option value="score">Best fit</option>
          <option value="newest">Newest posting</option>
          <option value="salary">Highest published salary</option>
          <option value="company">Company</option>
        </select>
      </div>
      <div class="toolbar-row">
        <div class="score-control">
          <label for="min-score">Minimum score</label>
          <input id="min-score" type="range" min="0" max="95" step="1">
          <span class="score-readout" id="score-readout"></span>
        </div>
        <label class="check"><input id="new-only" type="checkbox"> New only</label>
        <label class="check"><input id="remote-only" type="checkbox"> Remote only</label>
        <label class="check"><input id="salary-only" type="checkbox"> Salary listed</label>
        <button class="toolbar-button" id="export-feedback" type="button">Export review data</button>
      </div>
    </section>

    <div class="results-bar">
      <span><strong id="visible-count">0</strong> roles shown</span>
      <span id="review-counts"></span>
    </div>
    <main id="job-list" class="job-list"></main>

    <details class="methodology">
      <summary>How the fit score works</summary>
      <p>The 0–100 score combines role-family alignment, explicit skill overlap, résumé-language similarity, salary, location eligibility, freshness, employment type, and seniority. It subtracts points for likely blockers such as an active clearance requirement, management duties, advanced-degree requirements, excessive experience, or senior leadership titles. A role with a published salary ceiling below the configured floor, an explicit non-U.S. restriction, an expired posting, or a disallowed employment type is removed before ranking.</p>
      <p>Unknown salary or location does not automatically eliminate a promising role; it appears as a concern so you can decide. Adjust the rules in <code>config/profile.json</code>. Saved, applied, and hidden states live only in this browser unless you export them.</p>
    </details>

    <details class="source-health">
      <summary>Source health and pipeline coverage</summary>
      <div class="source-pills" id="source-pills"></div>
      <p id="pipeline-summary"></p>
    </details>

    <footer>
      Open-source, deterministic ranking. Job details can change after collection; verify salary, eligibility, and requirements on the original posting before applying.
    </footer>
  </div>

  <script id="job-data" type="application/json">__JSON_PAYLOAD__</script>
  <script>
    "use strict";
    const payload = JSON.parse(document.getElementById("job-data").textContent);
    const storageKey = "job-fit-daily-review-v1";
    const controlKey = "job-fit-daily-controls-v1";
    let review = loadJSON(storageKey, {});
    let controls = loadJSON(controlKey, {});

    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
    const safeURL = (value) => {
      try {
        const url = new URL(String(value));
        return (url.protocol === "https:" || url.protocol === "http:") ? url.href : "#";
      } catch { return "#"; }
    };
    function loadJSON(key, fallback) {
      try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
      catch { return fallback; }
    }
    function saveReview() {
      try { localStorage.setItem(storageKey, JSON.stringify(review)); } catch { /* Direct-file previews can have opaque storage origins. */ }
    }
    function saveControls() {
      controls = {
        search: $("search").value,
        family: $("family").value,
        status: $("status-filter").value,
        sort: $("sort").value,
        minScore: Number($("min-score").value),
        newOnly: $("new-only").checked,
        remoteOnly: $("remote-only").checked,
        salaryOnly: $("salary-only").checked,
      };
      try { localStorage.setItem(controlKey, JSON.stringify(controls)); } catch { /* Keep the dashboard usable without persistent browser storage. */ }
    }
    function statusFor(job) { return review[job.key]?.status || "unreviewed"; }
    function setStatus(jobKey, status) {
      if (status === "unreviewed") delete review[jobKey];
      else review[jobKey] = { status, updatedAt: new Date().toISOString() };
      saveReview(); render();
    }
    function currency(value) {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);
    }
    function dateSortValue(value) { return value ? Date.parse(value) || 0 : 0; }
    function scoreTier(score) {
      if (score >= 70) return ["high", "strong"];
      if (score >= 55) return ["good", "good"];
      return ["possible", "possible"];
    }
    function statusBadge(status) {
      if (status === "unreviewed") return "";
      const label = status.charAt(0).toUpperCase() + status.slice(1);
      return `<span class="badge status">${esc(label)}</span>`;
    }
    function fitList(items, emptyText) {
      const values = items?.length ? items : [emptyText];
      return values.map((item) => `<li>${esc(item)}</li>`).join("");
    }
    function card(job) {
      const status = statusFor(job);
      const [tierClass, tierText] = scoreTier(job.score);
      const badges = [
        job.is_new ? '<span class="badge new">New</span>' : "",
        `<span class="badge family">${esc(job.family_label)}</span>`,
        statusBadge(status),
      ].join("");
      const skills = (job.skills || []).slice(0, 8).map((skill) => `<span class="skill">${esc(skill)}</span>`).join("");
      const breakdown = Object.entries(job.breakdown || {})
        .filter(([, value]) => Math.abs(Number(value)) >= .01)
        .sort((a, b) => Number(b[1]) - Number(a[1]))
        .map(([name, value]) => `<span>${esc(name.replaceAll("_", " "))}: ${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(1)}</span>`)
        .join("");
      return `<article class="job-card" data-status="${esc(status)}">
        <div class="score-column">
          <div class="score-number">${Number(job.score).toFixed(0)}</div>
          <div class="score-label">fit score</div>
          <div class="score-tier ${tierClass}">${tierText}</div>
        </div>
        <div class="job-body">
          <div class="job-top">
            <div class="title-wrap">
              <div class="badges">${badges}</div>
              <h2 class="job-title"><a href="${safeURL(job.url)}" target="_blank" rel="noopener noreferrer">${esc(job.title)}</a></h2>
              <div class="company">${esc(job.company)}</div>
            </div>
          </div>
          <div class="meta">
            <span>⌖ ${esc(job.location)}</span>
            <span>◷ ${esc(job.posted_label)}</span>
            <span>▣ ${esc(job.employment_type)}</span>
            <span>＄ ${esc(job.salary)}</span>
          </div>
          ${job.description ? `<p class="description">${esc(job.description)}</p>` : ""}
          <div class="fit-grid">
            <section class="fit-box"><h3>Why it fits</h3><ul>${fitList(job.reasons, "No strong positive explanation was generated.")}</ul></section>
            <section class="fit-box concerns"><h3>Check before applying</h3><ul>${fitList(job.concerns, "No major concerns detected from the posting text.")}</ul></section>
          </div>
          ${skills ? `<div class="skills">${skills}</div>` : ""}
          <details class="breakdown"><summary>Score breakdown</summary><div class="breakdown-grid">${breakdown}</div></details>
          <div class="job-footer">
            <div class="source"><a href="${safeURL(job.attribution_url)}" target="_blank" rel="noopener noreferrer">${esc(job.attribution_text)}</a></div>
            <div class="actions">
              <button type="button" class="action saved ${status === "saved" ? "active" : ""}" data-action="saved" data-key="${esc(job.key)}">Save</button>
              <button type="button" class="action applied ${status === "applied" ? "active" : ""}" data-action="applied" data-key="${esc(job.key)}">Applied</button>
              <button type="button" class="action hide ${status === "hidden" ? "active" : ""}" data-action="hidden" data-key="${esc(job.key)}">Hide</button>
              ${status !== "unreviewed" ? `<button type="button" class="action" data-action="unreviewed" data-key="${esc(job.key)}">Clear</button>` : ""}
              <a class="action view-role" href="${safeURL(job.url)}" target="_blank" rel="noopener noreferrer">View role ↗</a>
            </div>
          </div>
        </div>
      </article>`;
    }

    function filteredJobs() {
      const query = $("search").value.trim().toLowerCase();
      const terms = query.split(/\s+/).filter(Boolean);
      const family = $("family").value;
      const statusFilter = $("status-filter").value;
      const minScore = Number($("min-score").value);
      let jobs = payload.jobs.filter((job) => {
        const status = statusFor(job);
        if (job.score < minScore) return false;
        if (family !== "all" && job.family_id !== family) return false;
        if (statusFilter === "active" && status === "hidden") return false;
        if (!["active", "all"].includes(statusFilter) && status !== statusFilter) return false;
        if ($("new-only").checked && !job.is_new) return false;
        if ($("remote-only").checked && !job.remote) return false;
        if ($("salary-only").checked && !job.salary_known) return false;
        if (terms.length) {
          const haystack = [job.title, job.company, job.location, job.family_label, job.description, ...(job.skills || [])].join(" ").toLowerCase();
          if (!terms.every((term) => haystack.includes(term))) return false;
        }
        return true;
      });
      const sort = $("sort").value;
      jobs.sort((a, b) => {
        if (sort === "newest") return dateSortValue(b.posted_at) - dateSortValue(a.posted_at) || b.score - a.score;
        if (sort === "salary") return (b.salary_maximum_usd || b.salary_minimum_usd || 0) - (a.salary_maximum_usd || a.salary_minimum_usd || 0) || b.score - a.score;
        if (sort === "company") return a.company.localeCompare(b.company) || b.score - a.score;
        return b.score - a.score || dateSortValue(b.posted_at) - dateSortValue(a.posted_at);
      });
      return jobs;
    }

    function render() {
      saveControls();
      $("score-readout").textContent = $("min-score").value;
      const jobs = filteredJobs();
      $("visible-count").textContent = jobs.length;
      $("job-list").innerHTML = jobs.length
        ? jobs.map(card).join("")
        : '<div class="empty"><strong>No jobs match these filters.</strong><br>Lower the score threshold or clear one of the filters.</div>';
      const counts = { saved: 0, applied: 0, hidden: 0 };
      for (const job of payload.jobs) {
        const status = statusFor(job);
        if (counts[status] !== undefined) counts[status] += 1;
      }
      $("review-counts").textContent = `${counts.saved} saved · ${counts.applied} applied · ${counts.hidden} hidden`;
    }

    function initialize() {
      $("updated-at").textContent = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(payload.generated_at));
      $("salary-floor").textContent = currency(payload.candidate.minimum_salary_usd);
      $("search-scope").textContent = payload.candidate.search_scope;
      $("stat-shown").textContent = payload.statistics.shown;
      $("stat-new").textContent = payload.statistics.new;
      $("stat-high").textContent = payload.statistics.high_confidence;
      $("stat-remote").textContent = payload.statistics.remote;
      $("stat-salary").textContent = payload.statistics.salary_known;
      for (const family of payload.families) {
        const option = document.createElement("option");
        option.value = family.id; option.textContent = family.label; $("family").append(option);
      }
      $("search").value = controls.search || "";
      $("family").value = controls.family || "all";
      $("status-filter").value = controls.status || "active";
      $("sort").value = controls.sort || "score";
      $("min-score").value = Number.isFinite(controls.minScore) ? controls.minScore : payload.candidate.dashboard_min_score;
      $("new-only").checked = Boolean(controls.newOnly);
      $("remote-only").checked = Boolean(controls.remoteOnly);
      $("salary-only").checked = Boolean(controls.salaryOnly);

      const sourceHTML = payload.sources.map((source) => {
        const status = source.ok ? "ok" : "failed";
        const counts = `${source.fetched} fetched${source.kept ? `, ${source.kept} eligible` : ""}`;
        const detail = source.ok
          ? ((source.message && source.fetched === 0) ? source.message : `${counts}${source.message ? ` · ${source.message}` : ""}`)
          : (source.message || "failed");
        return `<span class="source-pill ${status}" title="${esc(detail)}">${esc(source.source)}: ${esc(detail)}</span>`;
      }).join("");
      $("source-pills").innerHTML = sourceHTML;
      const p = payload.pipeline;
      const truncated = p.truncated ? `; ${p.truncated} additional qualifying roles were omitted by the display cap` : "";
      $("pipeline-summary").textContent = `${p.fetched} source records collected; ${p.eligible} remained after hard filters; ${p.below_threshold} scored below the dashboard threshold; ${p.rejected} were rejected${truncated}.`;

      ["search", "family", "status-filter", "sort", "min-score", "new-only", "remote-only", "salary-only"].forEach((id) => {
        $(id).addEventListener(id === "search" || id === "min-score" ? "input" : "change", render);
      });
      $("job-list").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const action = button.dataset.action;
        const key = button.dataset.key;
        const current = review[key]?.status || "unreviewed";
        setStatus(key, current === action ? "unreviewed" : action);
      });
      $("export-feedback").addEventListener("click", () => {
        const jobsByKey = Object.fromEntries(payload.jobs.map((job) => [job.key, { title: job.title, company: job.company, url: job.url }]));
        const exported = {
          schema_version: 1,
          exported_at: new Date().toISOString(),
          review,
          jobs: Object.fromEntries(Object.keys(review).map((key) => [key, jobsByKey[key] || null])),
        };
        const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `job-fit-review-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(link.href);
      });
      render();
    }
    initialize();
  </script>
</body>
</html>
'''
    return (
        template.replace("__TITLE__", title)
        .replace("__GENERATED__", generated)
        .replace("__DEMO_BANNER__", demo_banner)
        .replace("__JSON_PAYLOAD__", json_payload)
    )


def render_site(payload: dict[str, Any], site_dir: Path) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(site_dir / "jobs.json", payload)
    (site_dir / "index.html").write_text(_dashboard_html(payload), encoding="utf-8", newline="\n")
    (site_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8", newline="\n")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

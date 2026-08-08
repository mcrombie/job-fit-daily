# Job Fit Daily

A personal job-search pipeline that fetches public postings every morning, removes obvious non-fits, ranks the rest against Michael Crombie's actual résumé and portfolio profile, publishes an interactive dashboard, remembers what is new, and can send a compact email digest.

The project is deliberately **deterministic, inspectable, and free to operate**. It does not require an LLM call, a paid ranking API, a database, or a server that stays awake all day.

## What is already personalized

`config/profile.json` is built around the current search:

- United States nationwide, with extra weight for Northern Virginia and the Washington region
- target compensation of at least **$75,000**
- early-to-mid-career roles rather than internships or leadership positions
- primary families: backend/Python and AI applications, full-stack/frontend, developer support and solutions engineering, QA automation, technical writing/documentation, data/analytics, and research software/digital humanities
- strengths from the current résumé and portfolio: Python, TypeScript, React/React Native, FastAPI, SQL, RAG, embeddings, hybrid retrieval, testing, technical writing, requirements translation, and public deployment

No résumé file, personal email address, API key, or password is published by the dashboard. The profile does contain a prose career summary and skill list, so read the privacy section before putting the repository on GitHub.

## What the daily run does

1. Pulls current jobs from the enabled feeds.
2. Normalizes titles, descriptions, dates, locations, employment type, and salary.
3. Deduplicates cross-posted roles.
4. Rejects jobs with a conclusive blocker, including:
   - a published salary ceiling below the configured floor
   - an explicit non-U.S.-only applicant restriction
   - part-time, internship, apprenticeship, volunteer, or unpaid status
   - an expired or stale posting
   - a blocked company or term
5. Scores each remaining job from 0–100.
6. Explains the strongest positive signals and the concerns to check.
7. Marks jobs that have not appeared in a prior run as **New**.
8. Writes a static dashboard to `site/`, state and run history to `data/`, and optionally sends email.
9. GitHub Actions commits the updated state and deploys the dashboard to GitHub Pages.

A failed feed is isolated from the others. If all useful feeds return zero jobs while any feed has failed, the run stops rather than overwriting the prior dashboard with an empty page.

## Live sources

Enabled without credentials:

- [Himalayas public jobs API](https://himalayas.app/jobs/api)
- [Remotive public remote-jobs API](https://remotive.com/api/remote-jobs)
- [Arbeitnow job-board API](https://www.arbeitnow.com/api/job-board-api)

Supported optional connectors:

- public employer boards hosted by [Greenhouse](https://developers.greenhouse.io/job-board.html)
- public employer boards hosted by [Lever](https://github.com/lever/postings-api)
- [USAJOBS](https://developer.usajobs.gov/) with a free API key

The rendered cards visibly attribute Himalayas and Remotive and link back to the original source. This is a private candidate dashboard, not a republished commercial job board or a signup funnel.

LinkedIn and Indeed scraping are intentionally absent. It is brittle, often contrary to platform restrictions, and unnecessary for a useful first system. Alerts from those services can later be routed into a separate, authorized ingestion path.

## Preview it immediately on Windows

No packages need to be installed beyond Python 3.11 or newer.

```powershell
cd path\to\job-fit-daily
.\scripts\preview.ps1
```

That command runs the tests, builds a synthetic demonstration dashboard, and opens `site\index.html`.

Equivalent individual commands:

```powershell
py -m jobfit validate
py -m unittest discover -s tests -v
py -m jobfit demo
start site\index.html
```

The demonstration postings use fictional companies and `example.com` links. A live run replaces them:

```powershell
py -m jobfit run --no-email
start site\index.html
```

## Put it online and make it run every day

### 1. Create an empty GitHub repository

Create a repository named `job-fit-daily` under the `mcrombie` account. A public repository is the simplest free Pages setup. A private repository avoids exposing the profile and job history but requires a GitHub plan that supports Pages for private repositories.

From PowerShell inside this folder:

```powershell
git init
git add .
git commit -m "Initialize daily job-fit system"
git branch -M main
git remote add origin https://github.com/mcrombie/job-fit-daily.git
git push -u origin main
```

### 2. Enable GitHub Pages

In the repository:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, choose **GitHub Actions** as the source.
3. Open **Actions → Daily Job Fits → Run workflow**.
4. Leave “Send the optional email digest” off for the first test run.

The workflow is scheduled for **8:17 a.m. America/New_York every day**. The timezone is explicit, so daylight-saving changes do not require two UTC schedules. The minute is intentionally away from `:00`, when scheduled Actions runs are more likely to be delayed.

The first successful run publishes the dashboard and commits `data/state.json`, which is how later runs know whether a job is new.

### 3. Confirm the generated address

For a repository named `job-fit-daily`, the default address will normally be:

```text
https://mcrombie.github.io/job-fit-daily/
```

Set that exact address as a repository variable named `DASHBOARD_URL` under **Settings → Secrets and variables → Actions → Variables**. The email digest uses it for its dashboard button. Without the variable, the workflow derives the standard GitHub Pages address automatically.

## Optional email digest

The dashboard always works without email. To enable email, add these as **Actions secrets**:

| Secret | Purpose |
|---|---|
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_PORT` | Usually `587` for STARTTLS or `465` for SSL |
| `SMTP_SECURITY` | `starttls`, `ssl`, or `none` |
| `SMTP_USERNAME` | SMTP login, when required |
| `SMTP_PASSWORD` | SMTP password or provider app password |
| `SMTP_FROM` | Sender address, optionally with a display name |
| `DIGEST_TO` | Recipient address |

Scheduled runs send only new jobs at or above `candidate.email_min_score`. Manual workflow runs default to no email; the checkbox allows a deliberate test.

A local example is in `.env.example`, but the program does not automatically load `.env`. Export the variables in the shell or use GitHub secrets.

## Optional USAJOBS coverage

1. Request credentials through the [USAJOBS developer portal](https://developer.usajobs.gov/).
2. Add `USAJOBS_API_KEY` and `USAJOBS_EMAIL` as Actions secrets.
3. Change `usajobs.enabled` to `true` in `config/sources.json`.
4. Edit the keyword list as needed.

The default keywords cover software engineering, Python, technical writing, systems analysis, and data analysis.

## Add direct Greenhouse and Lever company feeds

Direct employer feeds improve coverage and reduce dependence on aggregators. They are empty by default because the target-company list should be intentional.

Greenhouse example:

```json
"greenhouse": {
  "enabled": true,
  "boards": [
    {"token": "company-board-token", "company": "Company Name"}
  ]
}
```

Lever example:

```json
"lever": {
  "enabled": true,
  "sites": [
    {"site": "company-site-token", "company": "Company Name", "region": "global"}
  ]
}
```

Use `"region": "eu"` only for a Lever board served from Lever's EU API. A bad or retired board token fails independently and is shown in the source-health panel.

## How the score works

The score is a triage system, not a statistical probability of receiving an interview.

| Component | What it rewards |
|---|---|
| Role alignment | Exact title matches and responsibility keywords in the seven target families |
| Skill overlap | Weighted matches to the résumé and portfolio stack |
| Profile similarity | Dependency-free TF-IDF similarity between the candidate profile and posting |
| Salary | Published annual USD compensation that clears or reaches the floor |
| Location | Northern Virginia/DC, U.S.-eligible remote, worldwide remote, or U.S. location |
| Freshness | Recently posted roles |
| Employment | Full-time preference; contract roles are allowed but discounted |
| Seniority | Associate/junior/Engineer I–II and attainable experience requirements |
| Risk and feedback | Penalties for likely blockers; explicit boosts or blocks from the profile |

Every card exposes the component breakdown. Unknown salary and ambiguous remote eligibility produce warnings rather than automatic rejection, because otherwise many plausible roles would disappear.

## Teach the system from your search

Edit `config/profile.json`:

- `candidate.minimum_salary_usd`: hard compensation floor
- `candidate.dashboard_min_score`: how selective the dashboard is
- `candidate.email_min_score`: stricter threshold for email
- `skills`: aliases and weights
- `role_families`: target titles, responsibility terms, and family weights
- `seniority.title_penalties`: how aggressively to demote senior roles
- `feedback.boost_companies`: companies to favor
- `feedback.block_companies`: companies to remove
- `feedback.boost_terms`: technologies, domains, or responsibilities to favor
- `feedback.block_terms`: conclusive deal breakers

The dashboard's **Save**, **Applied**, and **Hide** buttons are stored in that browser's `localStorage`; they are not committed publicly. **Export review data** downloads a JSON file that can be used to update the profile deliberately.

## Main files

```text
config/profile.json       candidate, role families, scoring preferences
config/sources.json       feed settings and output behavior
jobfit/sources.py         API adapters and normalization
jobfit/ranking.py         filters, deduplication, scoring, explanations
jobfit/state.py           first-seen and last-seen tracking
jobfit/render.py          static interactive dashboard
jobfit/notify.py          optional SMTP digest
jobfit/pipeline.py        daily orchestration and failure handling
.github/workflows/        schedule, tests, persistence, Pages deployment
tests/                    offline unit tests and synthetic fixture
site/                     generated dashboard
data/                     generated state and run history
```

## Privacy and operational choices

- A public Pages site is not genuinely private, even with `noindex` and `robots.txt`. Anyone with the address can open it.
- The dashboard contains job titles, companies, links, short description excerpts, fit explanations, and Michael's name. It does not expose credentials or a résumé document.
- Browser review status stays local. GitHub only receives machine-generated seen-state hashes and aggregate run history.
- Secrets belong in GitHub Actions secrets, never in JSON, `.env` committed to Git, or workflow YAML.
- The source feeds and their terms can change. Source failures appear in the dashboard and logs; update adapters when providers change schemas.
- Salary parsing is conservative but still heuristic. Always confirm pay and applicant location on the live posting.

## Commands

```text
python -m jobfit validate       validate both JSON configuration files
python -m jobfit demo           build the synthetic preview
python -m jobfit run            fetch live jobs, render, and try email
python -m jobfit run --no-email fetch live jobs without SMTP
python -m unittest discover -s tests -v
```

## License

MIT. See `LICENSE`.

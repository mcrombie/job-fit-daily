# Architecture

## Design goals

Job Fit Daily is built around five constraints:

1. It must run unattended once per day.
2. The user must be able to understand why one role outranks another.
3. One broken source must not destroy the whole digest.
4. It should cost nothing before optional email or private hosting choices.
5. It must not require scraping sites that prohibit or aggressively resist automated access.

## Data flow

```text
Public APIs / employer boards
          │
          ▼
 source-specific normalizers
          │
          ▼
 normalized Job objects
          │
          ├── validation and hard filters
          ├── cross-source deduplication
          ├── candidate-specific scoring
          └── reasons and concerns
          │
          ▼
 ranked jobs + rejected counts
          │
          ├── state.json (first/last seen hashes)
          ├── latest.json and daily history
          ├── static HTML/JSON dashboard
          └── optional SMTP digest
```

## Ranking model

The scorer is intentionally an additive rules engine rather than an opaque model. Each job receives component points for role family, skills, profile similarity, salary, location, freshness, employment type, and seniority. Configured risks and feedback adjust the total. Scores are clamped to 0–100.

This makes errors debuggable. A user can inspect a card, see that “Staff” imposed an 18-point penalty or that unknown salary added a concern, and change the policy in JSON.

TF-IDF similarity is implemented in the standard library. It is a useful broad-language signal but never determines the score alone.

## State model

`data/state.json` stores only a canonical job hash with `first_seen` and `last_seen` timestamps. It does not store browser review decisions. Cross-posted remote jobs use a normalized remote canonical key so changing feeds does not make an old job appear new.

The workflow commits state after every successful run. Generated commits use `[skip ci]`, and pushes made with `GITHUB_TOKEN` do not recursively trigger the scheduled workflow.

## Failure behavior

Each source is wrapped independently and produces a status record. Partial results are allowed. When no jobs are fetched and at least one source failed, the pipeline exits unsuccessfully before replacing the site. Optional SMTP failures are logged but do not block dashboard generation.

## Static dashboard

The dashboard embeds its compact payload in `index.html`, so it can be opened directly from disk and does not need a server or database. Filtering and review statuses happen in the browser. Job strings are escaped before being inserted into card markup, and outbound links accept only HTTP or HTTPS URLs.

## Extension points

A new source needs one function that maps its response into `Job` objects and one entry in `_FETCHERS`. A new ranking policy normally belongs in `config/profile.json`; code changes are reserved for new kinds of evidence or hard constraints.

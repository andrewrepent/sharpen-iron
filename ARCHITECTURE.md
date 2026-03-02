# Architecture Plan: Bible Knowledge Dashboard

## Overview
A Python script fetches data from a public Google Sheet, generates a static `index.html` with a rich UI, and GitHub Actions deploys it daily to GitHub Pages.

## Pipeline

```
Google Sheet (gviz JSON endpoint)
        |
        v
  main.py (Python)
  - Fetch & parse JSON
  - Generate index.html
        |
        v
  index.html (static site)
        |
        v
  GitHub Actions (.github/workflows/update.yml)
  - Runs daily (cron)
  - Commits updated index.html to repo
        |
        v
  GitHub Pages
  - Serves index.html as public URL
```

## Data Source

- **URL**: `https://docs.google.com/spreadsheets/d/1MGVNAW1nkRyMA0N05XZhgSXAr4lXudxPx4J1I4agGWo/gviz/tq?tqx=out:json`
- **Format**: Google Visualization API JSON (wrapped in a callback, needs stripping before parsing)
- **Shape**:
  - Column A: Timestamp (datetime)
  - Column B: Name (string)
  - Columns C–GQ: ~477 biblical topic columns (string)
- **Response values** (3 possible per cell):
  - `"Yes (I can teach with relevant scriptures)"`
  - `"Sorta (I partly understand it or need a refresher of the scriptures)"`
  - `"No (I have no idea what this means or refers to)"`
- **Current rows**: 8 respondents (Feb 2026), will grow over time

## Files

| File | Purpose |
|------|---------|
| `main.py` | Fetch sheet → parse → generate `index.html` |
| `index.html` | Output static site (committed to repo) |
| `.github/workflows/update.yml` | GitHub Actions workflow (daily cron + manual trigger) |
| `ARCHITECTURE.md` | This file |

## GitHub Actions Workflow (to be created)

```yaml
name: Update Dashboard
on:
  schedule:
    - cron: '0 6 * * *'  # Daily at 6am UTC
  workflow_dispatch:       # Manual trigger button

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install requests
      - run: python main.py
      - name: Commit & push if changed
        run: |
          git config user.name "github-actions"
          git config user.email "actions@github.com"
          git add index.html
          git diff --staged --quiet || git commit -m "Auto-update dashboard $(date -u +%Y-%m-%d)"
          git push
```

## GitHub Pages Setup

1. Push repo to GitHub
2. Go to repo Settings → Pages
3. Set source to: **Deploy from branch** → `main` → `/ (root)`
4. Site will be live at: `https://<username>.github.io/<repo-name>/`

## UI Implementation (index.html)

Three tabs — dark theme, fully self-contained except Chart.js CDN.

### Home Tab
- Site title hero, quick stats (respondents, topics, avg score)
- Links: Main Website, Video Search Tool, Notes Search Tool
- How-to guide for new visitors

### Overview Tab
- **5 bar charts**: top 5 topics, bottom 5 topics, most polarising (variance), top 5 people, bottom 5 people
- **Correlation cards**: "X% of people who didn't know A also didn't know B" (auto-computed for high-gap topics)
- **Sortable, searchable table**: Topic | Understanding Score (color-coded) | Yes % | Sorta % | No %

### Sharpen Iron Tab
- **Search by Topic**: searchable dropdown → 3-column table (Knows / Sorta knows / Doesn't know)
- **Search by Person**: searchable dropdown → 3-column table (What they know / sorta / don't know)

## Understanding Score Formula
`score = (yes_count * 100 + sorta_count * 50) / (total_respondents * 100) * 100`
- 100 = all Yes, 0 = all No, 50 = all Sorta

## Python Dependencies

- `requests` — HTTP fetch
- Standard library only after that (`json`, `re`, `datetime`)
- No build step, no npm, no frameworks

## Verified Working
- 51 respondents, 197 topics parsed correctly
- Output: `index.html` (~150KB, self-contained)
- Run: `python main.py`

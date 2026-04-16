# Job Application Bot

An autonomous job search pipeline that scrapes LinkedIn and Seek, scores every listing against your resume using Claude AI, then generates a tailored resume and cover letter for the roles worth pursuing.

---

## What it does

```
Run once daily (or on a schedule)
        │
        ▼
┌───────────────────┐     ┌──────────────────────┐
│  Search           │────▶│  Score (Claude AI)    │
│  LinkedIn + Seek  │     │  A–F grade, 0–100 pts │
│  Playwright       │     │  10 weighted dims     │
└───────────────────┘     └──────────┬───────────┘
                                     │
              ┌──────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│  Dashboard  (FastAPI)                           │
│  Browse all scored jobs · filter by grade       │
│  Click "Prepare Docs" on any role               │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
     ┌─────────────────────────┐
     │  Tailor (Claude AI)     │
     │  • Tailored resume PDF  │
     │  • Cover letter PDF     │
     └─────────────┬───────────┘
                   │
                   ▼
     ┌─────────────────────────┐
     │  Apply (Playwright)     │
     │  LinkedIn Easy Apply /  │
     │  Seek — pauses for your │
     │  confirmation first     │
     └─────────────────────────┘
```

---

## Features

- **Multi-source scraping** — LinkedIn and Seek.com.au via Playwright with human-like behaviour (gradual scrolling, mouse movement, randomised delays) to avoid bot detection
- **AI scoring** — Claude grades every job A–F across 10 dimensions: tech stack, seniority, location, visa friendliness, company quality, salary, growth, culture, commercial fit, and role clarity
- **Smart filtering** — auto-filters visa-blocked roles, keyword exclusions, and low-match scores
- **Tailored documents** — per-job resume and cover letter rewritten by Claude to match the specific JD
- **Application dashboard** — FastAPI web UI to browse scored jobs, review tailored docs, and trigger applications
- **Confirmation gate** — Playwright fills the entire form then pauses; you review and confirm before anything is submitted
- **Email notifications** — daily digest + per-application confirmation via Gmail
- **Scheduler** — APScheduler runs the full pipeline daily at 7am, digest at 8pm

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Scraping | Playwright (persistent browser context) |
| AI | Anthropic Claude API (`claude-opus-4-5`) |
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | Jinja2 templates + vanilla CSS |
| PDF | xhtml2pdf |
| Scheduling | APScheduler |
| Notifications | smtplib / Gmail |
| Portfolio | GitHub REST API |

---

## Project Structure

```
job-application-bot/
├── main.py                  # CLI entry point (click)
├── config.py                # Settings via pydantic-settings + .env
├── preferences.yaml         # Job titles, locations, keywords, salary
│
├── search/
│   ├── base.py              # BaseScraper with human-like helpers
│   ├── linkedin.py          # LinkedIn Playwright scraper
│   ├── seek.py              # Seek.com.au Playwright scraper
│   └── aggregator.py        # Orchestrates scrapers, deduplicates, saves
│
├── match/
│   ├── scorer.py            # Claude: score + grade each job
│   └── reporter.py          # Generate daily markdown + email report
│
├── tailor/
│   ├── resume.py            # Claude: rewrite resume for role → PDF
│   └── cover_letter.py      # Claude: write cover letter → PDF
│
├── apply/
│   ├── linkedin.py          # Playwright: fill LinkedIn Easy Apply
│   └── seek.py              # Playwright: fill Seek application
│
├── dashboard/
│   ├── app.py               # FastAPI app + all routes
│   ├── static/style.css
│   └── templates/           # Jinja2 HTML pages
│
├── notify/
│   ├── emailer.py           # Gmail SMTP
│   └── templates/           # HTML email templates
│
├── portfolio/
│   ├── generator.py         # Claude: design + generate project code
│   └── github_pusher.py     # GitHub REST API: create repo + push
│
└── scheduler/
    └── jobs.py              # APScheduler daily jobs
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure secrets

```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD, GITHUB_TOKEN, etc.
```

### 3. Set your preferences

Edit `preferences.yaml` — job titles, locations, salary minimum, excluded keywords.

### 4. Add your resume

Place your master resume at `assets/resume_base.md`.

### 5. Login to LinkedIn

```bash
python main.py login linkedin
# Browser opens — log in manually, press Enter when done
```

### 6. Run

```bash
# One-off search + score + report
python main.py run

# Start the dashboard
python main.py dashboard
# → http://localhost:8001

# Run 24/7 on a schedule
python main.py scheduler
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py run` | Full pipeline: search → score → report |
| `python main.py search-only` | Scrape only, no scoring |
| `python main.py report` | Regenerate today's report from DB |
| `python main.py prepare <job_id>` | Tailor resume + cover letter for a job |
| `python main.py dashboard` | Start web dashboard |
| `python main.py scheduler` | Start 24/7 scheduled runner |
| `python main.py login linkedin` | Save LinkedIn session |
| `python main.py digest` | Send daily digest email manually |

---

## Scoring System

Each job is scored 0–100 across 10 dimensions and assigned a grade:

| Grade | Score | Action |
|-------|-------|--------|
| A | 85–100 | Apply today |
| B | 70–84 | Strong match |
| C | 50–69 | Worth considering |
| D | 35–49 | Weak match |
| F | 0–34 | Auto-filtered |

Visa-blocked roles (requiring permanent residency or citizenship) are flagged and excluded from the report. 485-visa-friendly roles are highlighted.

---

## Environment Variables

See `.env.example` for the full list. Key variables:

```
ANTHROPIC_API_KEY=        # Claude API key
GMAIL_ADDRESS=            # Sender email
GMAIL_APP_PASSWORD=       # Gmail App Password (not account password)
GITHUB_TOKEN=             # For portfolio project creation
GITHUB_USERNAME=
NOTIFY_EMAIL=             # Where to send reports
MIN_MATCH_SCORE=50        # Filter threshold
MAX_APPLICATIONS_PER_RUN=10
```

---

## Notes

- **No auto-submit** — the bot always pauses before submitting any application. You review first.
- **Secrets excluded** — `.env`, `playwright_data/`, `job_tracker.db`, and resume files are all in `.gitignore`
- **Windows compatible** — uses xhtml2pdf instead of WeasyPrint; UTF-8 stdout configured at startup

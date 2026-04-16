"""
Job Application Bot — Strategic Career Agent
============================================
Kevin's semi-automated, high-conversion pipeline.
AI scouts and drafts. Kevin decides and submits.

Commands:
  python main.py run           Scout + score new jobs → send Apply Report email
  python main.py report        Re-generate & re-send today's Apply Report
  python main.py prepare <id>  Tailor resume + cover letter for a specific job ID
  python main.py dashboard     Start the review dashboard at localhost:8000
  python main.py digest        Send daily summary email now
  python main.py login seek    First-time Seek login (prompts for OTP)
  python main.py login linkedin  First-time LinkedIn login
"""

import asyncio
import json
import sys
import threading
import warnings
from datetime import date, datetime, timezone

# Force UTF-8 output on Windows so Claude's responses (which contain Unicode)
# don't crash the CP1252 terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
import uvicorn
from rich.console import Console
from rich.table import Table

# Suppress harmless "unclosed transport" ResourceWarning on Windows
# (Playwright requires ProactorEventLoop — do NOT change the policy)
warnings.filterwarnings("ignore", category=ResourceWarning)

from config import settings, PLAYWRIGHT_DATA_DIR
from db.database import init_db, get_session
from db.models import Application, Job

console = Console()


# ─── Dashboard ──────────────────────────────────────────────────────────────

def start_dashboard(port: int = 8000, block: bool = True):
    config = uvicorn.Config("dashboard.app:app", host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    if block:
        console.print(f"[cyan]Dashboard running at http://localhost:{port}[/]")
        server.run()
    else:
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        console.print(f"[cyan]Dashboard:[/] http://localhost:{port}")


# ─── Daily digest email ─────────────────────────────────────────────────────

def send_digest_email():
    from notify.emailer import Emailer, DigestData

    db = get_session()
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    all_apps = db.query(Application).all()
    applied_today = [a for a in all_apps if a.applied_at and a.applied_at >= today_start]
    pending = [a for a in all_apps if a.status == "awaiting_confirmation"]

    def _app_dict(a):
        job = a.job
        score = job.match_score if job else None
        sc = "high" if score and score >= 80 else "medium" if score and score >= 65 else "low"
        cl_md = a.cover_letter_doc.content_md if a.cover_letter_doc else ""
        return {
            "id": a.id,
            "job_title": job.title if job else "—",
            "company": job.company if job else "—",
            "match_score": score,
            "score_class": sc,
            "cover_letter_snippet": cl_md[:120].replace("\n", " ") if cl_md else "",
        }

    # Include skill gap alerts for pending/recent apps
    skill_gaps = []
    for a in all_apps[-20:]:
        if a.job and a.job.match_recommendation:
            try:
                meta = json.loads(a.job.match_recommendation)
                if meta.get("tech_score", 100) < 30:
                    skill_gaps.append({
                        "job_title": a.job.title,
                        "company": a.job.company,
                        "recommendation": meta.get("recommendation", ""),
                    })
            except Exception:
                pass

    data = DigestData(
        date=today.strftime("%d %b %Y"),
        applied_today=[_app_dict(a) for a in applied_today],
        pending_confirmation=[_app_dict(a) for a in pending],
        skill_gap_alerts=skill_gaps[:3],
        total_applied=sum(1 for a in all_apps if a.status == "applied"),
        total_interviewing=sum(1 for a in all_apps if a.status == "interviewing"),
    )
    db.close()

    Emailer().send_daily_digest(data)
    console.print("[green]Digest sent[/]")


# ─── Apply Report email ──────────────────────────────────────────────────────

def send_apply_report_email(report: dict):
    """Send the strategic Apply Report as an email."""
    from notify.emailer import Emailer
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from config import BASE_DIR

    jinja = Environment(
        loader=FileSystemLoader(str(BASE_DIR / "notify" / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    html = jinja.get_template("apply_report.html").render(
        report=report,
        dashboard_url=f"http://localhost:{settings.DASHBOARD_PORT}",
    )

    total = report["total_jobs"]
    a_count = len(report["grade_a"])
    subject = f"Apply Report {report['date']} - {a_count} Grade A jobs, {total} total"

    emailer = Emailer()
    msg = emailer._build_message(subject=subject, html_body=html)

    # Attach the markdown report if it exists
    from config import BASE_DIR, OUTPUT_DIR
    today = date.today().strftime("%Y-%m-%d")
    md_path = OUTPUT_DIR / "reports" / f"report_{today}.md"
    if md_path.exists():
        emailer._attach_file(msg, md_path)

    emailer._send(msg)
    console.print(f"[green]Apply Report sent - {total} jobs, {a_count} Grade A[/]")


# ─── Core workflow ───────────────────────────────────────────────────────────

async def run_scout_and_score():
    """Stage 1+2: Search → Score → Generate Apply Report."""
    init_db()

    console.rule("[bold]Stage 1: Scouting jobs")
    from search.aggregator import JobAggregator
    aggregator = JobAggregator()
    new_job_ids = await aggregator.search_all(verbose=True)

    if not new_job_ids:
        console.print("[yellow]No new jobs found.[/]")
        return None

    console.rule("[bold]Stage 2: Scoring (A–F)")
    from match.scorer import JobScorer
    scorer = JobScorer()
    scorer.batch_score(new_job_ids)

    console.rule("[bold]Stage 3: Generating Apply Report")
    from match.reporter import generate_daily_report
    report = generate_daily_report(min_grade="C")

    _print_report_table(report)
    return report


def _print_report_table(report: dict):
    table = Table(title=f"Apply Report — {report['date']}", show_lines=True)
    table.add_column("Grade", style="bold", width=6)
    table.add_column("Role", style="cyan")
    table.add_column("Company")
    table.add_column("Score", justify="center")
    table.add_column("Why Apply")

    colors = {"A": "green", "B": "blue", "C": "yellow"}
    for grade in ("A", "B", "C"):
        for j in report[f"grade_{grade.lower()}"]:
            color = colors.get(grade, "white")
            table.add_row(
                f"[{color}]{grade}[/{color}]",
                j["title"],
                j["company"],
                str(j["score"]),
                j["why_apply"][:60],
            )
    console.print(table)
    console.print(
        f"\n[bold]Total qualifying jobs: {report['total_jobs']}[/]  "
        f"Grade A: {len(report['grade_a'])}  "
        f"Grade B: {len(report['grade_b'])}  "
        f"Grade C: {len(report['grade_c'])}"
    )


async def prepare_job_assets(job_id: int):
    """Stage 3: Generate tailored resume + cover letter for a specific job."""
    init_db()
    db = get_session()
    job = db.query(Job).filter_by(id=job_id).first()
    if not job:
        console.print(f"[red]Job ID {job_id} not found[/]")
        db.close()
        return

    console.print(f"\n[bold]Preparing assets for:[/] {job.title} @ {job.company}")

    # Build scoring result from saved data
    from match.scorer import ScoringResult, DimensionScores
    meta = {}
    try:
        meta = json.loads(job.match_recommendation or "{}")
    except Exception:
        pass

    dims = DimensionScores(
        visa_ok=meta.get("visa_ok", True),
        visa_485_friendly=meta.get("visa_485_friendly", False),
        tech=meta.get("dim_tech", 50),
        experience=meta.get("dim_experience", 50),
        commercial=meta.get("dim_commercial", 50),
        location=meta.get("dim_location", 50),
        growth=meta.get("dim_growth", 50),
        company_type=meta.get("dim_company", 50),
        salary=meta.get("dim_salary", 50),
        ai_bonus=meta.get("dim_ai", 0),
        grad_friendly=meta.get("dim_grad", 0),
    )
    score_result = ScoringResult(
        job_id=job.id,
        score=job.match_score or 0,
        grade=meta.get("grade", "C"),
        dimensions=dims,
        strengths=json.loads(job.match_strengths or "[]"),
        gaps=json.loads(job.match_gaps or "[]"),
        why_apply=meta.get("why_apply", ""),
        recommendation=meta.get("recommendation", ""),
    )

    # Tailor resume
    from tailor.resume import ResumeTailor
    from tailor.cover_letter import CoverLetterWriter
    tailor = ResumeTailor()
    cover_writer = CoverLetterWriter()

    resume_doc = tailor.tailor(job, score_result)
    cover_doc = cover_writer.write(job, score_result)

    # Skill gap check
    from portfolio.skill_advisor import SkillAdvisor
    advisor = SkillAdvisor()
    gap_report = advisor.analyse(job)

    # Create/update application record
    existing = db.query(Application).filter_by(job_id=job.id).first()
    if existing:
        existing.resume_doc_id = resume_doc.id
        existing.cover_letter_doc_id = cover_doc.id
        existing.status = "awaiting_confirmation"
        existing.updated_at = datetime.now(timezone.utc)
        app_obj = existing
    else:
        app_obj = Application(
            job_id=job.id,
            status="awaiting_confirmation",
            resume_doc_id=resume_doc.id,
            cover_letter_doc_id=cover_doc.id,
        )
        db.add(app_obj)

    db.commit()
    db.refresh(app_obj)
    # Cache job fields before closing session
    job_title = job.title
    job_company = job.company
    job_score = job.match_score or 0
    app_id = app_obj.id
    db.close()

    console.print(f"\n[green]Assets ready![/]")
    console.print(f"  Resume PDF:  {resume_doc.file_path}")
    console.print(f"  Cover Letter: {cover_doc.file_path}")
    if gap_report.needs_new_project:
        console.print(f"\n[yellow]{gap_report.recommendation}[/]")
    console.print(f"\n[cyan]Review at:[/] http://localhost:{settings.DASHBOARD_PORT}/confirm/{app_id}")

    # Send notification email with documents attached
    from notify.emailer import Emailer
    emailer = Emailer()
    emailer.send_application_notification(
        job_title=job_title,
        company=job_company,
        match_score=job_score,
        cover_letter_md=cover_doc.content_md or "",
        resume_pdf_path=resume_doc.file_path,
        cover_letter_pdf_path=cover_doc.file_path,
        strengths=score_result.strengths,
        gaps=score_result.gaps,
        app_id=app_id,
        skill_gap_report=gap_report.recommendation if gap_report.needs_new_project else "",
    )
    console.print("[green]Documents emailed to you[/]")


# ─── CLI ────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    pass


@cli.command()
@click.option("--email/--no-email", default=True, help="Send Apply Report email")
def run(email):
    """Scout + score jobs → generate Apply Report → email to Kevin."""
    report = asyncio.run(run_scout_and_score())
    if report and email:
        try:
            send_apply_report_email(report)
        except Exception as e:
            console.print(f"[yellow]Email failed: {e}[/]")
    if report:
        console.print(
            f"\n[bold]Next step:[/] Run [cyan]python main.py prepare <job_id>[/] "
            f"for any job you want to pursue."
        )


@cli.command()
@click.argument("job_id", type=int)
def prepare(job_id):
    """Tailor resume + cover letter for a specific job, then email documents."""
    asyncio.run(prepare_job_assets(job_id))


@cli.command()
def report():
    """Re-generate and re-send today's Apply Report from already-scored jobs."""
    init_db()
    from match.reporter import generate_daily_report
    r = generate_daily_report(min_grade="C")
    _print_report_table(r)
    try:
        send_apply_report_email(r)
    except Exception as e:
        console.print(f"[yellow]Email failed: {e}[/]")


@cli.command()
def dashboard():
    """Start the review dashboard at http://localhost:8000"""
    init_db()
    start_dashboard(port=settings.DASHBOARD_PORT, block=True)


@cli.command()
def digest():
    """Send daily digest email now."""
    init_db()
    send_digest_email()


@cli.command()
@click.argument("site", type=click.Choice(["linkedin", "seek"]))
def login(site):
    """First-time login — saves browser session for future runs."""
    asyncio.run(_do_login(site))


@cli.command()
@click.option("--search-hour", default=8, help="Hour (24h) to run daily job search (default: 8am)")
@click.option("--digest-hour", default=20, help="Hour (24h) to send digest email (default: 8pm)")
def scheduler(search_hour, digest_hour):
    """Run continuously: searches at 8am daily, digest email at 8pm. Also starts dashboard."""
    from apscheduler.schedulers.background import BackgroundScheduler
    import time

    init_db()
    start_dashboard(port=settings.DASHBOARD_PORT, block=False)

    def _run_job():
        console.print(f"\n[bold cyan]Scheduler: running job search...[/]")
        try:
            report = asyncio.run(run_scout_and_score())
            if report:
                try:
                    send_apply_report_email(report)
                except Exception as e:
                    console.print(f"[yellow]Email failed: {e}[/]")
        except Exception as e:
            console.print(f"[red]Scheduler search error: {e}[/]")

    def _send_digest():
        console.print(f"\n[bold cyan]Scheduler: sending digest...[/]")
        try:
            send_digest_email()
        except Exception as e:
            console.print(f"[yellow]Digest email failed: {e}[/]")

    sched = BackgroundScheduler()
    sched.add_job(_run_job, "cron", hour=search_hour, minute=0, id="daily_search")
    sched.add_job(_send_digest, "cron", hour=digest_hour, minute=0, id="daily_digest")
    sched.start()

    console.print(f"[green]Scheduler started[/]")
    console.print(f"  Daily search: {search_hour:02d}:00")
    console.print(f"  Daily digest: {digest_hour:02d}:00")
    console.print(f"  Dashboard:    http://localhost:{settings.DASHBOARD_PORT}")
    console.print(f"\nPress Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        console.print("\n[yellow]Scheduler stopped.[/]")


async def _do_login(site: str):
    from playwright.async_api import async_playwright
    loop = asyncio.get_event_loop()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PLAYWRIGHT_DATA_DIR / site),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        if site == "linkedin":
            from search.linkedin import LinkedInScraper
            scraper = LinkedInScraper(context)
            await scraper.do_login()

        elif site == "seek":
            from search.seek import SeekScraper
            scraper = SeekScraper(context)

            # run_in_executor so input() doesn't freeze the browser
            async def get_otp_async():
                return await loop.run_in_executor(
                    None, lambda: input("\n>>> Enter the Seek OTP from your email: ")
                )

            await scraper.do_login(settings.SEEK_EMAIL, otp_callback=get_otp_async)

        await context.close()
    console.print(f"[green]{site.capitalize()} session saved[/]")


if __name__ == "__main__":
    cli()

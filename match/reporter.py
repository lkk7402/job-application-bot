"""
Generates the daily Strategic Apply Report.
Includes: A/B/C graded jobs, market trends, filter stats, 485-friendly flags.
"""

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import List

from config import BASE_DIR, OUTPUT_DIR
from db.database import get_session
from db.models import Job, Application, SearchRun

REPORT_DIR = OUTPUT_DIR / "reports"

# Tech trend keywords to count in today's new JDs
TREND_TECH = [
    ".net", "c#", "dotnet", "asp.net",
    "react", "next.js", "typescript",
    "python", "fastapi", "django",
    "java", "spring boot",
    "aws", "azure", "gcp",
    "kubernetes", "k8s",
    "ai", "llm", "machine learning",
]


def generate_daily_report(min_grade: str = "C") -> dict:
    GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    min_order = GRADE_ORDER.get(min_grade.upper(), 2)

    db = get_session()

    # All scored jobs (no date filter — search has no date limit either)
    todays_jobs = db.query(Job).filter(Job.match_score.isnot(None)).all()

    # Already-applied job IDs
    applied_ids = {a.job_id for a in db.query(Application).all()}

    # Filter stats
    total_scraped = len(todays_jobs)
    visa_blocked  = [j for j in todays_jobs if not _meta(j).get("visa_ok", True)]
    low_score     = [j for j in todays_jobs if j.match_score and j.match_score < 40 and _meta(j).get("visa_ok", True)]
    friendly_485  = [j for j in todays_jobs if _meta(j).get("visa_485_friendly", False)]

    # Qualifying jobs (not applied, not filtered, above grade threshold)
    qualifying = []
    for job in todays_jobs:
        if job.id in applied_ids:
            continue
        if job.match_score is None:
            continue
        if job.is_filtered_out:
            continue
        grade = _meta(job).get("grade", "F")
        if GRADE_ORDER.get(grade, 4) > min_order:
            continue
        qualifying.append(job)

    qualifying.sort(key=lambda j: j.match_score or 0, reverse=True)

    # Build job dicts
    job_dicts = [_job_to_dict(j) for j in qualifying]

    # Group by grade
    by_grade = {"A": [], "B": [], "C": []}
    for j in job_dicts:
        g = j["grade"]
        if g in by_grade:
            by_grade[g].append(j)

    # Market trends — count tech keywords in today's scraped JDs
    trends = _compute_trends(todays_jobs)

    # Top companies today
    companies = Counter(j.company for j in todays_jobs if j.company)
    top_companies = companies.most_common(5)

    db.close()

    report = {
        "date": date.today().strftime("%d %b %Y"),
        "total_jobs": len(qualifying),
        "grade_a": by_grade["A"],
        "grade_b": by_grade["B"],
        "grade_c": by_grade["C"],
        "all_jobs": job_dicts,
        "stats": {
            "total_scraped": total_scraped,
            "visa_blocked": len(visa_blocked),
            "low_score_filtered": len(low_score),
            "total_filtered": len(visa_blocked) + len(low_score),
            "friendly_485_count": len(friendly_485),
        },
        "trends": trends,
        "top_companies": top_companies,
    }

    _save_markdown(report)
    return report


def _meta(job: Job) -> dict:
    try:
        return json.loads(job.match_recommendation or "{}")
    except Exception:
        return {}


def _job_to_dict(job: Job) -> dict:
    meta = _meta(job)
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "source": job.source,
        "score": job.match_score,
        "grade": meta.get("grade", "?"),
        "visa_ok": meta.get("visa_ok", True),
        "visa_485_friendly": meta.get("visa_485_friendly", False),
        "dim_tech": meta.get("dim_tech", 0),
        "dim_commercial": meta.get("dim_commercial", 0),
        "dim_experience": meta.get("dim_experience", 0),
        "dim_location": meta.get("dim_location", 0),
        "strengths": json.loads(job.match_strengths or "[]"),
        "gaps": json.loads(job.match_gaps or "[]"),
        "why_apply": meta.get("why_apply", ""),
        "recommendation": meta.get("recommendation", ""),
        "salary": job.salary_text or "Not listed",
        "posted": job.posted_date or "—",
    }


def _compute_trends(jobs: List[Job]) -> list:
    """Count how many of today's scraped JDs mention each tech keyword."""
    counts = {}
    for kw in TREND_TECH:
        count = sum(1 for j in jobs if kw in ((j.description or "") + (j.title or "")).lower())
        if count > 0:
            counts[kw] = count

    # Sort by count, return top 8
    sorted_trends = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
    return [{"tech": t[0], "count": t[1]} for t in sorted_trends]


def _save_markdown(report: dict):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y-%m-%d")
    path = REPORT_DIR / f"report_{today}.md"

    s = report["stats"]
    lines = [
        f"# Daily Apply Report — {report['date']}",
        "",
        f"**Scraped:** {s['total_scraped']} jobs today",
        f"**Filtered out:** {s['total_filtered']} "
        f"({s['visa_blocked']} visa-blocked, {s['low_score_filtered']} low score)",
        f"**485-Friendly jobs found:** {s['friendly_485_count']}",
        f"**Qualifying for review:** {report['total_jobs']}",
        "",
    ]

    if report["trends"]:
        lines += ["## Market Trends (today's new JDs)", ""]
        for t in report["trends"]:
            lines.append(f"- **{t['tech']}**: {t['count']} new job{'s' if t['count'] != 1 else ''}")
        lines.append("")

    for grade, label in [("A", "Grade A — Apply Today"), ("B", "Grade B — Strong"), ("C", "Grade C — Consider")]:
        jobs = report[f"grade_{grade.lower()}"]
        if not jobs:
            continue
        icons = {"A": "🟢", "B": "🔵", "C": "🟡"}
        lines += [f"## {icons[grade]} {label}", ""]
        for j in jobs:
            visa_note = " [485-FRIENDLY]" if j["visa_485_friendly"] else ""
            lines += [
                f"### {j['title']} @ {j['company']}{visa_note}",
                f"**Score:** {j['score']}/100 | **Salary:** {j['salary']} | {j['location']}",
                f"[View Job]({j['url']})",
                "",
                f"**Why apply:** {j['why_apply']}",
                "",
            ]
            if j["strengths"]:
                lines.append("**Strengths:** " + " · ".join(j["strengths"][:3]))
            if j["gaps"]:
                lines.append("**Gaps:** " + " · ".join(j["gaps"][:2]))
            if j["recommendation"]:
                lines.append(f"**Cover letter tip:** {j['recommendation']}")
            lines += ["", "---", ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[Reporter] Report saved: {path}")

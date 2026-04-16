"""FastAPI web dashboard for the job application tracker."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from config import settings, BASE_DIR
from db.database import get_db, init_db
from db.models import Job, Application, TailoredDocument, PortfolioProject

app = FastAPI(title="Kevin's Job Tracker")

STATIC_DIR = BASE_DIR / "dashboard" / "static"
TEMPLATE_DIR = BASE_DIR / "dashboard" / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.on_event("startup")
def startup():
    init_db()


# ─── Helpers ────────────────────────────────────────────────────────────────

def score_class(score: Optional[int]) -> str:
    if not score:
        return "low"
    return "high" if score >= 80 else "medium" if score >= 65 else "low"


def app_to_dict(app_obj: Application) -> dict:
    job = app_obj.job
    meta = {}
    if job and job.match_recommendation:
        try:
            meta = json.loads(job.match_recommendation)
        except Exception:
            pass
    return {
        "id": app_obj.id,
        "job_title": job.title if job else "—",
        "company": job.company if job else "—",
        "source": job.source if job else "—",
        "url": job.url if job else "#",
        "location": job.location if job else "—",
        "match_score": job.match_score if job else None,
        "score_class": score_class(job.match_score if job else None),
        "status": app_obj.status,
        "applied_at": app_obj.applied_at.strftime("%d %b %Y %H:%M") if app_obj.applied_at else "—",
        "notes": app_obj.notes or "",
        "strengths": json.loads(job.match_strengths or "[]") if job else [],
        "gaps": json.loads(job.match_gaps or "[]") if job else [],
        "recommendation": meta.get("recommendation", ""),
        "why_apply": meta.get("why_apply", ""),
        "grade": meta.get("grade", "—"),
        "resume_path": app_obj.resume_doc.file_path if app_obj.resume_doc else None,
        "cover_letter_path": app_obj.cover_letter_doc.file_path if app_obj.cover_letter_doc else None,
        "cover_letter_md": app_obj.cover_letter_doc.content_md if app_obj.cover_letter_doc else "",
        "visa_485_friendly": meta.get("visa_485_friendly", False),
        "dim_tech": meta.get("dim_tech", 0),
        "dim_experience": meta.get("dim_experience", 0),
        "dim_commercial": meta.get("dim_commercial", 0),
        "dim_location": meta.get("dim_location", 0),
        "dim_growth": meta.get("dim_growth", 0),
        "dim_company": meta.get("dim_company", 0),
        "dim_salary": meta.get("dim_salary", 0),
        "dim_ai": meta.get("dim_ai", 0),
        "dim_grad": meta.get("dim_grad", 0),
    }


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    apps = db.query(Application).order_by(Application.created_at.desc()).all()

    stats = {
        "total": len(apps),
        "applied": sum(1 for a in apps if a.status == "applied"),
        "interviewing": sum(1 for a in apps if a.status == "interviewing"),
        "pending": sum(1 for a in apps if a.status == "awaiting_confirmation"),
        "offer": sum(1 for a in apps if a.status == "offer"),
    }
    pending = [app_to_dict(a) for a in apps if a.status == "awaiting_confirmation"]
    recent = [app_to_dict(a) for a in apps[:10]]

    return templates.TemplateResponse(request, "index.html", {
        "stats": stats,
        "pending": pending,
        "recent": recent,
    })


@app.get("/jobs", response_class=HTMLResponse)
def jobs_list(request: Request, grade: str = "", db: Session = Depends(get_db)):
    query = db.query(Job).filter(Job.match_score.isnot(None)).order_by(Job.match_score.desc())
    all_jobs = query.all()

    # Build app_id lookup (job_id → app_id)
    from db.models import Application
    app_lookup = {a.job_id: a.id for a in db.query(Application).all()}

    def job_to_dict(job):
        meta = {}
        if job.match_recommendation:
            try:
                meta = json.loads(job.match_recommendation)
            except Exception:
                pass
        return {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location or "—",
            "url": job.url,
            "source": job.source,
            "score": job.match_score or 0,
            "grade": meta.get("grade", "F"),
            "visa_ok": meta.get("visa_ok", True),
            "visa_485_friendly": meta.get("visa_485_friendly", False),
            "why_apply": meta.get("why_apply", ""),
            "dim_tech": meta.get("dim_tech", 0),
            "dim_experience": meta.get("dim_experience", 0),
            "dim_commercial": meta.get("dim_commercial", 0),
            "dim_location": meta.get("dim_location", 0),
            "strengths": json.loads(job.match_strengths or "[]"),
            "gaps": json.loads(job.match_gaps or "[]"),
            "salary": job.salary_text or "Not listed",
            "posted": job.posted_date or "—",
            "app_id": app_lookup.get(job.id),
        }

    jobs = [job_to_dict(j) for j in all_jobs]
    if grade:
        jobs = [j for j in jobs if j["grade"] == grade.upper()]

    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": jobs,
        "filter_grade": grade.upper() if grade else "",
    })


@app.post("/jobs/{job_id}/prepare")
def prepare_job(job_id: int, db: Session = Depends(get_db)):
    """Trigger asset preparation for a job directly from the dashboard."""
    import subprocess, sys
    subprocess.Popen([sys.executable, "main.py", "prepare", str(job_id)],
                     cwd=str(BASE_DIR))
    return RedirectResponse(url=f"/jobs", status_code=303)


@app.get("/applications", response_class=HTMLResponse)
def applications_list(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Application).order_by(Application.created_at.desc())
    if status:
        query = query.filter(Application.status == status)
    apps = [app_to_dict(a) for a in query.all()]

    return templates.TemplateResponse(request, "applications.html", {
        "applications": apps,
        "filter_status": status,
    })


@app.get("/applications/{app_id}", response_class=HTMLResponse)
def application_detail(request: Request, app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")
    return templates.TemplateResponse(request, "application_detail.html", {
        "app": app_to_dict(app_obj),
    })


@app.get("/confirm/{app_id}", response_class=HTMLResponse)
def confirm_page(request: Request, app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Not found")
    return templates.TemplateResponse(request, "confirm_apply.html", {
        "app": app_to_dict(app_obj),
    })


@app.post("/applications/{app_id}/confirm")
def confirm_apply(app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Not found")
    app_obj.status = "applying"
    app_obj.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/applications/{app_id}", status_code=303)


@app.post("/applications/{app_id}/skip")
def skip_apply(app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Not found")
    app_obj.status = "skipped"
    app_obj.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/applications/{app_id}/status")
def update_status(app_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Not found")
    app_obj.status = status
    app_obj.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/applications/{app_id}", status_code=303)


@app.post("/applications/{app_id}/notes")
def update_notes(app_id: int, notes: str = Form(""), db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Not found")
    app_obj.notes = notes
    app_obj.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.get("/files/resume/{app_id}")
def download_resume(app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj or not app_obj.resume_doc:
        raise HTTPException(status_code=404)
    path = Path(app_obj.resume_doc.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path, filename=path.name, media_type="application/pdf")


@app.get("/files/cover/{app_id}")
def download_cover(app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(Application).filter_by(id=app_id).first()
    if not app_obj or not app_obj.cover_letter_doc:
        raise HTTPException(status_code=404)
    path = Path(app_obj.cover_letter_doc.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path, filename=path.name, media_type="application/pdf")


@app.get("/api/stats")
def api_stats(db: Session = Depends(get_db)):
    apps = db.query(Application).all()
    status_counts = {}
    for a in apps:
        status_counts[a.status] = status_counts.get(a.status, 0) + 1
    return {"status_counts": status_counts, "total": len(apps)}

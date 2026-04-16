"""Sends HTML emails via Gmail SMTP — application confirmations and daily digests."""

import smtplib
import ssl
from datetime import date, datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

from jinja2 import Environment, FileSystemLoader, select_autoescape
from config import settings, BASE_DIR
from db.models import Application


TEMPLATE_DIR = BASE_DIR / "notify" / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


@dataclass
class DigestData:
    date: str
    applied_today: List[dict] = field(default_factory=list)        # list of app dicts
    pending_confirmation: List[dict] = field(default_factory=list)
    skill_gap_alerts: List[dict] = field(default_factory=list)     # jobs with gaps
    total_applied: int = 0
    total_interviewing: int = 0


class Emailer:
    def __init__(self):
        self.from_addr = settings.GMAIL_ADDRESS
        self.password = settings.GMAIL_APP_PASSWORD
        self.to_addr = settings.NOTIFY_EMAIL
        self.dashboard_url = f"http://localhost:{settings.DASHBOARD_PORT}"

    def send_application_notification(
        self,
        job_title: str,
        company: str,
        match_score: int,
        cover_letter_md: str,
        resume_pdf_path: Optional[str],
        cover_letter_pdf_path: Optional[str],
        strengths: List[str],
        gaps: List[str],
        app_id: int,
        skill_gap_report: str = "",
    ):
        score_class = "high" if match_score >= 80 else "medium" if match_score >= 65 else "low"
        html = jinja_env.get_template("application_done.html").render(
            job_title=job_title,
            company=company,
            match_score=match_score,
            score_class=score_class,
            cover_letter_md=cover_letter_md,
            strengths=strengths,
            gaps=gaps,
            app_id=app_id,
            dashboard_url=self.dashboard_url,
            skill_gap_report=skill_gap_report,
            now=datetime.now().strftime("%d %b %Y %H:%M"),
        )

        msg = self._build_message(
            subject=f"✅ Applied: {job_title} @ {company} (Score: {match_score}/100)",
            html_body=html,
        )

        # Attach PDFs
        for pdf_path in [resume_pdf_path, cover_letter_pdf_path]:
            if pdf_path and Path(pdf_path).exists():
                self._attach_file(msg, Path(pdf_path))

        self._send(msg)

    def send_daily_digest(self, data: DigestData):
        html = jinja_env.get_template("daily_digest.html").render(
            data=data,
            dashboard_url=self.dashboard_url,
        )
        subject = f"📋 Daily Digest {data.date} — {len(data.applied_today)} applied"
        if data.pending_confirmation:
            subject += f", {len(data.pending_confirmation)} need your confirmation"
        msg = self._build_message(subject=subject, html_body=html)
        self._send(msg)

    def _build_message(self, subject: str, html_body: str) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return msg

    def _attach_file(self, msg: MIMEMultipart, path: Path):
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
        msg.attach(part)

    def _send(self, msg: MIMEMultipart):
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
                server.login(self.from_addr, self.password)
                server.sendmail(self.from_addr, self.to_addr, msg.as_string())
            print(f"[Email] Sent to {self.to_addr}: {msg['Subject'][:60]}")
        except Exception as e:
            print(f"[Email] Failed: {e}")

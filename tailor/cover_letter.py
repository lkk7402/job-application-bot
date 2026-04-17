"""Generates a tailored cover letter for each job using Claude AI.
Output: properly formatted LaTeX PDF with letterhead, date, recipient block,
Re: subject line, justified body, and signed-off contact details.
"""

import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, OUTPUT_DIR
from db.database import get_session
from db.models import Job, TailoredDocument
from match.scorer import ScoringResult

RESUME_TEX_PATH = Path(__file__).parent.parent / "assets" / "resume_base.tex"


class CoverLetterWriter:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def write(self, job: Job, score: ScoringResult) -> TailoredDocument:
        print(f"[Cover Letter] Writing for: {job.title} @ {job.company}")
        body_paragraphs = self._generate(job, score)

        slug = re.sub(r"[^\w]", "_", job.company)[:30]
        out_dir = OUTPUT_DIR / "cover_letters"
        out_dir.mkdir(parents=True, exist_ok=True)

        tex_path = out_dir / f"{job.id}_{slug}_cover.tex"
        tex_content = self._build_latex(job, body_paragraphs)
        tex_path.write_text(tex_content, encoding="utf-8")

        pdf_path = tex_path.with_suffix(".pdf")
        compiled = self._compile_latex(tex_path, pdf_path)
        final_path = pdf_path if compiled else tex_path

        if not compiled:
            print(f"  [Cover Letter] LaTeX saved (no pdflatex). Open in Overleaf: {tex_path.name}")

        db = get_session()
        doc = TailoredDocument(
            job_id=job.id,
            doc_type="cover_letter",
            content_md=body_paragraphs,
            file_path=str(final_path),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        db.close()

        print(f"  Saved: {final_path.name}")
        return doc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _generate(self, job: Job, score: ScoringResult) -> str:
        """Ask Claude for 3 plain paragraphs of cover letter body — no headers, no salutation."""
        strengths_text = "\n".join(f"- {s}" for s in score.strengths[:3]) if score.strengths else ""

        prompt = f"""You are a professional cover letter writer helping a candidate apply for a job in Melbourne, Australia.

CANDIDATE BACKGROUND:
- Full-stack developer, UniMelb CS grad (2023)
- Tech stack: Python, TypeScript, React, FastAPI, Node.js, PostgreSQL, Docker, Claude API
- Built an autonomous job search bot (Playwright scraping, Claude AI scoring, FastAPI dashboard)
- Built a production AI REST API microservice (JWT, Docker, CI/CD, 80%+ test coverage)
- Ran a $300,000/year sneaker resale business — strong commercial and data-driven background
- On a 485 Graduate visa — available immediately

TARGET JOB:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description:
{job.description[:2500]}

KEY STRENGTHS TO HIGHLIGHT:
{strengths_text}

Write exactly 3 paragraphs of cover letter body in professional Australian English:
- Paragraph 1: Genuine interest in this specific role and company. Mention the role title. No clichés like "I am writing to express my interest".
- Paragraph 2: 2–3 most relevant achievements mapped directly to job requirements. Be specific with outcomes/numbers where possible.
- Paragraph 3: Enthusiasm for an interview, mention availability for immediate start.

STRICT RULES:
- Output ONLY the 3 paragraphs — no salutation, no sign-off, no heading, no extra text
- Do NOT mention lack of experience, years on a CV, or anything that highlights being junior
- Do NOT use the phrase "I am writing to"
- Keep total length 250–300 words
- Australian English spelling (organise, recognise, colour, etc.)

OUTPUT THE 3 PARAGRAPHS NOW:"""

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    def _build_latex(self, job: Job, body: str) -> str:
        """Wrap the body paragraphs in a properly formatted LaTeX letter."""
        today = date.today().strftime("%-d %B %Y") if not __import__("sys").platform.startswith("win") \
            else date.today().strftime("%d %B %Y").lstrip("0")

        # Escape special LaTeX characters in dynamic fields
        def esc(s: str) -> str:
            for ch, rep in [("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                            ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"),
                            ("^", r"\textasciicircum{}"), ("\\", r"\textbackslash{}"),]:
                s = s.replace(ch, rep)
            return s

        company = esc(job.company)
        title   = esc(job.title)

        # Convert body paragraphs — split on blank lines, wrap each in \par
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        body_tex = "\n\n".join(esc(p) for p in paras)

        return rf"""\documentclass[12pt,a4paper]{{letter}}

\usepackage[a4paper, top=2cm, bottom=2cm, left=2.5cm, right=2.5cm]{{geometry}}
\usepackage{{microtype}}
\usepackage[hidelinks]{{hyperref}}
\usepackage{{parskip}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.8em}}

% No page numbers
\pagestyle{{empty}}

\begin{{document}}

% ---- Sender block ----
{{\large \textbf{{Kevin Shih (Chun-Yu)}}}}\\
Melbourne CBD, VIC 3000\\
+61 422 222 489\\
\href{{mailto:KevinShih@lkk7402.com}}{{KevinShih@lkk7402.com}}\\
\href{{https://linkedin.com/in/kevin-shih-590425266}}{{linkedin.com/in/kevin-shih-590425266}}\\
\href{{https://github.com/lkk7402}}{{github.com/lkk7402}}

\vspace{{1em}}
{today}

\vspace{{1em}}
% ---- Recipient block ----
Hiring Manager\\
{company}

\vspace{{0.5em}}
\textbf{{Re: {title}}}

\vspace{{0.5em}}
Dear Hiring Manager,

{body_tex}

Kind regards,

\vspace{{2em}}
\textbf{{Kevin Shih (Chun-Yu)}}\\
+61 422 222 489 $|$ \href{{mailto:KevinShih@lkk7402.com}}{{KevinShih@lkk7402.com}}

\end{{document}}
"""

    def _compile_latex(self, tex_path: Path, pdf_path: Path) -> bool:
        miktex_bin = Path.home() / "AppData/Local/Programs/MiKTeX/miktex/bin/x64"
        pdflatex = shutil.which("pdflatex") or (
            str(miktex_bin / "pdflatex.exe") if (miktex_bin / "pdflatex.exe").exists() else None
        )
        if not pdflatex:
            return False
        try:
            subprocess.run(
                [pdflatex, "-interaction=nonstopmode",
                 "-output-directory", str(tex_path.parent), str(tex_path)],
                capture_output=True, timeout=120
            )
            return pdf_path.exists()
        except Exception:
            return False

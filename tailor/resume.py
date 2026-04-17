"""Tailors Kevin's resume for each specific job using Claude AI.
Output format: LaTeX (.tex) compiled to PDF via latexmk/pdflatex if available,
otherwise .tex file is saved and a note printed.
"""

import re
import subprocess
import shutil
from pathlib import Path

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, OUTPUT_DIR
from db.database import get_session
from db.models import Job, TailoredDocument
from match.scorer import ScoringResult

# Base LaTeX template path
RESUME_TEX_PATH = Path(__file__).parent.parent / "assets" / "resume_base.tex"


class ResumeTailor:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.base_resume_tex = RESUME_TEX_PATH.read_text(encoding="utf-8")

    def tailor(self, job: Job, score: ScoringResult) -> TailoredDocument:
        print(f"[Resume] Tailoring for: {job.title} @ {job.company}")
        tex_content = self._generate_tailored_resume(job, score)

        slug = re.sub(r"[^\w]", "_", job.company)[:30]
        out_dir = OUTPUT_DIR / "resumes"
        out_dir.mkdir(parents=True, exist_ok=True)

        tex_path = out_dir / f"{job.id}_{slug}_resume.tex"
        tex_path.write_text(tex_content, encoding="utf-8")

        # Try to compile to PDF
        pdf_path = tex_path.with_suffix(".pdf")
        compiled = self._compile_latex(tex_path, pdf_path)
        final_path = pdf_path if compiled else tex_path

        if not compiled:
            print(f"  [Resume] LaTeX saved (no pdflatex found). Open in Overleaf: {tex_path.name}")

        db = get_session()
        doc = TailoredDocument(
            job_id=job.id,
            doc_type="resume",
            content_md=tex_content,
            file_path=str(final_path),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        db.close()

        print(f"  Saved: {final_path.name}")
        return doc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _generate_tailored_resume(self, job: Job, score: ScoringResult) -> str:
        gaps_text = "\n".join(f"- {g}" for g in score.gaps) if score.gaps else "None identified"

        prompt = f"""You are a professional resume writer. Tailor the LaTeX resume below for a specific job.

BASE LATEX RESUME:
{self.base_resume_tex}

TARGET JOB:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description:
{job.description[:3000]}

IDENTIFIED GAPS TO ADDRESS:
{gaps_text}

INSTRUCTIONS:
1. Rewrite resume content to emphasize skills and experience most relevant to this role
2. Use keywords from the job description naturally in bullet points
3. Reorder bullet points to prioritize what matters most for this role
4. Do NOT invent experience — only reframe and emphasize existing experience
5. Keep the EXACT same LaTeX structure, commands, and preamble — only change the text content
6. Reorder Technical Skills to put most relevant skills first
7. Output ONLY the complete valid LaTeX document — no explanation, no markdown fences

OUTPUT THE TAILORED LATEX RESUME NOW:"""

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        tex = message.content[0].text.strip()
        # Strip any accidental markdown fences
        tex = re.sub(r"^```(?:latex)?\n?", "", tex)
        tex = re.sub(r"\n?```$", "", tex)
        return tex

    def _compile_latex(self, tex_path: Path, pdf_path: Path) -> bool:
        """Try to compile .tex to .pdf using pdflatex. Returns True on success."""
        # Look in standard MiKTeX install path on Windows as well as PATH
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

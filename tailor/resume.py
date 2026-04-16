"""Tailors Kevin's resume for each specific job using Claude AI."""

import json
from pathlib import Path

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, RESUME_MD_PATH, OUTPUT_DIR
from db.database import get_session
from db.models import Job, TailoredDocument
from match.scorer import ScoringResult


class ResumeTailor:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.base_resume = RESUME_MD_PATH.read_text(encoding="utf-8")

    def tailor(self, job: Job, score: ScoringResult) -> TailoredDocument:
        print(f"[Resume] Tailoring for: {job.title} @ {job.company}")
        md_content = self._generate_tailored_resume(job, score)

        # Save markdown
        output_path = OUTPUT_DIR / "resumes" / f"{job.id}_{job.company.replace(' ', '_')}_resume.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md_content, encoding="utf-8")

        # Convert to PDF
        pdf_path = output_path.with_suffix(".pdf")
        try:
            self._md_to_pdf(md_content, pdf_path)
        except Exception as e:
            print(f"  [Resume] PDF generation failed: {e} — markdown saved only")
            pdf_path = output_path

        # Save to DB
        db = get_session()
        doc = TailoredDocument(
            job_id=job.id,
            doc_type="resume",
            content_md=md_content,
            file_path=str(pdf_path),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        db.close()

        print(f"  Saved: {pdf_path.name}")
        return doc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _generate_tailored_resume(self, job: Job, score: ScoringResult) -> str:
        gaps_text = "\n".join(f"- {g}" for g in score.gaps) if score.gaps else "None identified"

        prompt = f"""You are a professional resume writer helping a candidate tailor their resume.

BASE RESUME:
{self.base_resume}

TARGET JOB:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description:
{job.description[:3000]}

IDENTIFIED GAPS TO ADDRESS:
{gaps_text}

INSTRUCTIONS:
1. Rewrite the resume to emphasize skills and experience most relevant to this specific role
2. Use keywords from the job description naturally throughout
3. Reorder sections and bullet points to prioritize what matters most for this role
4. Do NOT invent experience — only reframe and emphasize existing experience
5. Keep the same overall structure (header, experience, projects, education, skills)
6. For the skills section, reorder to put most relevant skills first
7. Output ONLY the complete resume in Markdown format — no explanation, no preamble

OUTPUT THE TAILORED RESUME NOW:"""

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    def _md_to_pdf(self, md_content: str, output_path: Path):
        import markdown
        from xhtml2pdf import pisa
        import io

        html_body = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
        full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5; color: #222; margin: 20px; }}
  h1 {{ color: #1a1a2e; font-size: 20px; margin-bottom: 4px; }}
  h2 {{ color: #2c3e50; font-size: 14px; border-bottom: 1px solid #ccc; padding-bottom: 3px; margin-top: 16px; }}
  h3 {{ color: #34495e; font-size: 12px; margin-bottom: 2px; }}
  ul {{ margin: 4px 0; padding-left: 18px; }}
  li {{ margin-bottom: 2px; }}
  p {{ margin: 4px 0; }}
  a {{ color: #2980b9; text-decoration: none; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 10px 0; }}
  strong {{ color: #1a1a2e; }}
</style></head><body>{html_body}</body></html>"""

        with open(output_path, "wb") as f:
            result = pisa.CreatePDF(io.StringIO(full_html), dest=f)
        if result.err:
            raise RuntimeError(f"xhtml2pdf error: {result.err}")

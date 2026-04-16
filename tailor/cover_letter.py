"""Generates a tailored cover letter for each job using Claude AI."""

from pathlib import Path

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, RESUME_MD_PATH, OUTPUT_DIR
from db.database import get_session
from db.models import Job, TailoredDocument
from match.scorer import ScoringResult


class CoverLetterWriter:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.base_resume = RESUME_MD_PATH.read_text(encoding="utf-8")

    def write(self, job: Job, score: ScoringResult) -> TailoredDocument:
        print(f"[Cover Letter] Writing for: {job.title} @ {job.company}")
        content = self._generate(job, score)

        output_path = OUTPUT_DIR / "cover_letters" / f"{job.id}_{job.company.replace(' ', '_')}_cover.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

        pdf_path = output_path.with_suffix(".pdf")
        try:
            self._md_to_pdf(content, pdf_path)
        except Exception as e:
            print(f"  [Cover Letter] PDF failed: {e}")
            pdf_path = output_path

        db = get_session()
        doc = TailoredDocument(
            job_id=job.id,
            doc_type="cover_letter",
            content_md=content,
            file_path=str(pdf_path),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        db.close()

        print(f"  Saved: {pdf_path.name}")
        return doc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _generate(self, job: Job, score: ScoringResult) -> str:
        strengths_text = "\n".join(f"- {s}" for s in score.strengths[:3]) if score.strengths else ""

        prompt = f"""You are a professional cover letter writer helping a candidate apply for a job in Melbourne, Australia.

CANDIDATE RESUME:
{self.base_resume}

TARGET JOB:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description:
{job.description[:2500]}

KEY STRENGTHS TO HIGHLIGHT:
{strengths_text}

Write a professional cover letter in Australian English following this structure:
- Opening paragraph: Express genuine interest in this specific role and company. Mention the role title.
- Middle paragraph: Highlight 2-3 most relevant achievements mapped directly to the job requirements. Be specific with numbers/outcomes where possible.
- Closing paragraph: Call to action — express enthusiasm for an interview, mention availability for immediate start.

IMPORTANT:
- Keep it to 3 paragraphs, ~250-300 words total
- Professional but warm Australian English tone
- Do NOT use clichés like "I am writing to express my interest"
- Output in Markdown format with the header: "# Cover Letter — {job.title} at {job.company}"
- Include "Dear Hiring Manager," as salutation
- Sign off with: "Kind regards,\\nKevin Shih"

OUTPUT THE COVER LETTER NOW:"""

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    def _md_to_pdf(self, md_content: str, output_path: Path):
        import markdown
        from xhtml2pdf import pisa
        import io

        html_body = markdown.markdown(md_content, extensions=["tables"])
        full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: Arial, sans-serif; font-size: 12px; line-height: 1.7; color: #222; margin: 40px; }}
  h1 {{ color: #1a1a2e; font-size: 15px; margin-bottom: 18px; }}
  p {{ margin-bottom: 12px; }}
</style></head><body>{html_body}</body></html>"""

        with open(output_path, "wb") as f:
            result = pisa.CreatePDF(io.StringIO(full_html), dest=f)
        if result.err:
            raise RuntimeError(f"xhtml2pdf error: {result.err}")

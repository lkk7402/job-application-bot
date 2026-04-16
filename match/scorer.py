"""
10-Dimension Weighted Scoring Engine
=====================================
Dimensions:
  1.  Visa Eligibility          (blocker — hard filter)
  2.  Tech Stack Alignment      25%
  3.  Experience Level Fit      20%
  4.  Commercial/Domain Synergy 15%
  5.  Location                  10%
  6.  Growth Opportunity        10%
  7.  Company Type              5%
  8.  Salary Alignment          5%
  9.  AI / Modern Tech Bonus    5%
  10. Graduate-Friendly Signal  5%

Final score = weighted average of dims 2-10 (0–100)
Grade: A=85+, B=70-84, C=55-69, D=40-54, F<40
Visa-blocked jobs get score=0, grade=F, is_filtered_out=True
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, RESUME_MD_PATH
from db.database import get_session
from db.models import Job

# ─── Dimension 1: Visa ───────────────────────────────────────────────────────

VISA_BLOCKLIST = [
    "australian citizen only", "citizens only", "citizen only",
    "permanent resident only", "pr only", "must be a citizen",
    "must hold australian citizenship", "australian residency required",
    "security clearance", "baseline clearance", "nv1", "nv2",
    "must have the right to work in australia permanently",
]

VISA_485_FRIENDLY = [
    "485", "graduate visa", "temporary graduate", "work rights",
    "sponsorship available", "visa sponsorship", "all visa types welcome",
    "open to all nationalities", "right to work", "working holiday",
]

# ─── Dimension 2: Tech Stack ──────────────────────────────────────────────────

TECH_TIERS = {
    # Tier 1 — Kevin's daily stack (highest weight)
    "python": 8, "fastapi": 8, "typescript": 8, "next.js": 8, "nextjs": 8,
    "react": 7, "node.js": 7, "nodejs": 7, "postgresql": 7, "docker": 7,
    "tailwind": 6, "prisma": 6, "sqlalchemy": 6,
    # Tier 2 — known but less frequent
    "javascript": 5, "express": 5, "mongodb": 5, "jest": 5, "pytest": 5,
    "github actions": 5, "ci/cd": 5, "rest api": 4, "restful": 4,
    "jwt": 4, "vercel": 4, "streamlit": 4, "groq": 3,
    # Tier 3 — knows basics
    "graphql": 3, "java": 3, "sql": 3,
}

# ─── Dimension 3: Experience Level ───────────────────────────────────────────

JUNIOR_SIGNALS = [
    "junior", "graduate", "grad role", "entry level", "entry-level",
    "0-2 years", "1-2 years", "1+ year", "less than 2", "new grad",
    "associate", "trainee", "cadetship", "internship",
]
SENIOR_BLOCKERS = [
    "10+ years", "8+ years", "7+ years", "6+ years",
    "senior principal", "staff engineer", "engineering manager",
    "head of engineering", "tech lead", "lead developer",
]
MID_SIGNALS = [
    "2-4 years", "2-3 years", "3+ years", "3 years experience",
    "mid-level", "mid level", "intermediate",
]

# ─── Dimension 4: Commercial/Domain Synergy ───────────────────────────────────

COMMERCIAL_TIERS = {
    "e-commerce": 10, "ecommerce": 10, "marketplace": 10,
    "retail tech": 9, "retail": 8, "fintech": 9, "payments": 8,
    "shopify": 8, "woocommerce": 7, "stripe": 7,
    "inventory": 7, "supply chain": 6, "logistics": 6,
    "saas": 6, "b2b saas": 7, "b2c": 6,
    "revenue": 5, "growth": 5, "platform": 4,
}

# ─── Dimension 5: Location ────────────────────────────────────────────────────

CBD_SIGNALS = ["melbourne cbd", "cbd", "docklands", "southbank", "st kilda rd"]
INNER_SUBURBS = ["richmond", "fitzroy", "collingwood", "south yarra", "cremorne",
                 "hawthorn", "st kilda", "prahran", "abbotsford", "carlton"]
REMOTE_SIGNALS = ["remote", "work from home", "wfh", "hybrid", "flexible"]
OUTER_SIGNALS  = ["dandenong", "frankston", "ringwood", "box hill", "sunshine",
                  "geelong", "ballarat", "bendigo"]
INTERSTATE     = ["sydney", "brisbane", "perth", "adelaide", "canberra",
                  "new south wales", "queensland", "western australia"]

# ─── Dimension 7: Company Type ────────────────────────────────────────────────

BIG_CORP = ["woolworths", "coles", "anz", "cba", "nab", "westpac", "telstra",
            "bhp", "atlassian", "canva", "seek", "realestate.com", "rea group",
            "xero", "afterpay", "zip", "bendigo bank", "medibank"]
STARTUP  = ["startup", "start-up", "scale-up", "scaleup", "seed", "series a",
            "series b", "early stage", "founded in 20"]

# ─── Dimension 9: AI/Modern Tech ─────────────────────────────────────────────

AI_SIGNALS = ["ai", "machine learning", "ml", "llm", "gpt", "openai", "anthropic",
              "generative", "nlp", "computer vision", "data science", "langchain",
              "vector", "embedding", "rag", "recommendation"]

# ─── Dimension 10: Graduate-Friendly ─────────────────────────────────────────

GRAD_FRIENDLY = ["graduate program", "grad program", "university", "unimelb",
                 "melbourne university", "acs", "professional year",
                 "mentoring", "mentorship", "learning & development",
                 "career development", "graduate scheme"]


# ─── Result dataclass ────────────────────────────────────────────────────────

@dataclass
class DimensionScores:
    visa_ok: bool = True
    visa_485_friendly: bool = False
    tech: int = 0           # 0-100
    experience: int = 0     # 0-100
    commercial: int = 0     # 0-100
    location: int = 0       # 0-100
    growth: int = 0         # 0-100
    company_type: int = 0   # 0-100
    salary: int = 0         # 0-100
    ai_bonus: int = 0       # 0-100
    grad_friendly: int = 0  # 0-100


@dataclass
class ScoringResult:
    job_id: int
    score: int
    grade: str
    dimensions: DimensionScores = field(default_factory=DimensionScores)
    strengths: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    why_apply: str = ""
    recommendation: str = ""


# ─── Weights (must sum to 1.0) ───────────────────────────────────────────────

WEIGHTS = {
    "tech":         0.25,
    "experience":   0.20,
    "commercial":   0.15,
    "location":     0.10,
    "growth":       0.10,
    "company_type": 0.05,
    "salary":       0.05,
    "ai_bonus":     0.05,
    "grad_friendly":0.05,
}


def _grade(score: int) -> str:
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "F"


# ─── Rule-based scorers ──────────────────────────────────────────────────────

def _score_visa(text: str) -> tuple[bool, bool]:
    """Returns (visa_ok, visa_485_friendly)"""
    visa_ok = not any(kw in text for kw in VISA_BLOCKLIST)
    friendly = any(kw in text for kw in VISA_485_FRIENDLY)
    return visa_ok, friendly


def _score_tech(text: str) -> int:
    total = sum(v for kw, v in TECH_TIERS.items() if kw in text)
    return min(100, int(total * 2.5))   # normalise


def _score_experience(text: str) -> int:
    if any(kw in text for kw in SENIOR_BLOCKERS):
        return 20
    if any(kw in text for kw in JUNIOR_SIGNALS):
        return 100
    if any(kw in text for kw in MID_SIGNALS):
        return 65
    return 55   # unknown → neutral


def _score_commercial(text: str) -> int:
    total = sum(v for kw, v in COMMERCIAL_TIERS.items() if kw in text)
    return min(100, total * 4)


def _score_location(text: str) -> int:
    if any(kw in text for kw in INTERSTATE):
        return 10
    if any(kw in text for kw in OUTER_SIGNALS):
        return 40
    if any(kw in text for kw in REMOTE_SIGNALS):
        return 85
    if any(kw in text for kw in INNER_SUBURBS):
        return 90
    if any(kw in text for kw in CBD_SIGNALS):
        return 100
    return 60   # unknown location → neutral


def _score_growth(text: str) -> int:
    signals = ["mentor", "learn", "training", "development", "grow",
               "exposure", "progression", "career path", "upskill"]
    hits = sum(1 for kw in signals if kw in text)
    return min(100, 50 + hits * 15)


def _score_company(text: str) -> int:
    if any(kw in text for kw in BIG_CORP):
        return 90
    if any(kw in text for kw in STARTUP):
        return 75
    return 60


def _score_salary(text: str, salary_field: str) -> int:
    combined = text + " " + (salary_field or "")
    numbers = re.findall(r'\$?([\d,]+)k?', combined)
    parsed = []
    for n in numbers:
        try:
            val = int(n.replace(",", ""))
            if val > 200:   # already in full dollars
                parsed.append(val)
            elif val > 0:
                parsed.append(val * 1000)
        except Exception:
            pass
    if not parsed:
        return 60   # unknown → neutral
    avg = sum(parsed) / len(parsed)
    if 65000 <= avg <= 110000:
        return 100
    if 50000 <= avg < 65000:
        return 50
    if avg > 110000:
        return 70   # likely over-level but still interesting
    return 30


def _score_ai(text: str) -> int:
    hits = sum(1 for kw in AI_SIGNALS if kw in text)
    return min(100, hits * 20)


def _score_grad(text: str) -> int:
    hits = sum(1 for kw in GRAD_FRIENDLY if kw in text)
    return min(100, 40 + hits * 20)


def _compute_weighted(d: DimensionScores) -> int:
    raw = (
        d.tech          * WEIGHTS["tech"] +
        d.experience    * WEIGHTS["experience"] +
        d.commercial    * WEIGHTS["commercial"] +
        d.location      * WEIGHTS["location"] +
        d.growth        * WEIGHTS["growth"] +
        d.company_type  * WEIGHTS["company_type"] +
        d.salary        * WEIGHTS["salary"] +
        d.ai_bonus      * WEIGHTS["ai_bonus"] +
        d.grad_friendly * WEIGHTS["grad_friendly"]
    )
    # Bonus: 485-friendly jobs get +5
    if d.visa_485_friendly:
        raw = min(100, raw + 5)
    return int(raw)


# ─── Main Scorer class ───────────────────────────────────────────────────────

class JobScorer:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.resume_text = RESUME_MD_PATH.read_text(encoding="utf-8")

    def batch_score(self, job_ids: List[int], verbose: bool = True) -> List[ScoringResult]:
        db = get_session()
        jobs = db.query(Job).filter(Job.id.in_(job_ids)).all()
        results = []
        filtered_count = 0

        for i, job in enumerate(jobs, 1):
            if verbose:
                print(f"[Scorer] {i}/{len(jobs)}: {job.title} @ {job.company}")
            try:
                result = self._score_one(job)
                results.append(result)
                self._save_to_db(db, job, result)

                if not result.dimensions.visa_ok:
                    filtered_count += 1
                    flag = "[VISA BLOCKED]"
                elif result.grade == "F":
                    filtered_count += 1
                    flag = "[F - filtered]"
                else:
                    icons = {"A": "A+", "B": "B ", "C": "C ", "D": "D "}
                    flag = icons.get(result.grade, "?")

                if verbose:
                    visa_note = " [485-friendly]" if result.dimensions.visa_485_friendly else ""
                    print(f"  Grade {flag} Score {result.score}/100{visa_note} | {result.why_apply[:55]}")
            except Exception as e:
                print(f"  Scoring failed: {e}")

        db.close()
        if verbose and filtered_count:
            print(f"\n[Scorer] Filtered out {filtered_count} unsuitable jobs")
        return results

    def _score_one(self, job: Job) -> ScoringResult:
        text = ((job.description or "") + " " + (job.title or "") + " " + (job.company or "")).lower()

        d = DimensionScores()
        d.visa_ok, d.visa_485_friendly = _score_visa(text)
        d.tech          = _score_tech(text)
        d.experience    = _score_experience(text)
        d.commercial    = _score_commercial(text)
        d.location      = _score_location(text)
        d.growth        = _score_growth(text)
        d.company_type  = _score_company(text)
        d.salary        = _score_salary(text, job.salary_text or "")
        d.ai_bonus      = _score_ai(text)
        d.grad_friendly = _score_grad(text)

        if not d.visa_ok:
            return ScoringResult(
                job_id=job.id, score=0, grade="F",
                dimensions=d,
                why_apply="Visa not eligible",
                recommendation="Filtered: requires PR/Citizen",
            )

        score = _compute_weighted(d)
        grade = _grade(score)

        # Only call Claude for B-grade and above (save API cost for low scores)
        if score >= 55:
            why, strengths, gaps, rec = self._claude_synthesis(job, d, score)
        else:
            why = f"Score {score}/100 — low tech/level alignment"
            strengths, gaps, rec = [], [], ""

        return ScoringResult(
            job_id=job.id,
            score=score,
            grade=grade,
            dimensions=d,
            strengths=strengths,
            gaps=gaps,
            why_apply=why,
            recommendation=rec,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _claude_synthesis(self, job: Job, d: DimensionScores, score: int):
        """Use Claude to generate the human-readable 'why apply' and gap analysis."""
        prompt = f"""You are reviewing a job for Kevin Shih, a Melbourne junior full-stack developer.

Kevin's key facts:
- Stack: Python/FastAPI, TypeScript/Next.js, React, PostgreSQL, Docker, CI/CD
- Owns sole trader business: $300k+ revenue, $100k+ profit (commercial/e-commerce edge)
- ACS Positive Assessment, UniMelb grad 2023, PTE 83, available immediately
- On a 485 Graduate visa — prefers visa-friendly or sponsoring employers

JOB:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Salary: {job.salary_text or 'not listed'}
{(job.description or '')[:2000]}

Pre-computed dimension scores (out of 100):
- Tech alignment: {d.tech}
- Experience fit: {d.experience}
- Commercial synergy: {d.commercial}
- Location: {d.location}
- 485 friendly: {d.visa_485_friendly}

Write 3 strengths, 2 gaps, a 1-sentence "why apply" from Kevin's perspective, and a 1-sentence cover letter tip.

Return ONLY valid JSON:
{{
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "gaps": ["gap 1", "gap 2"],
  "why_apply": "One sentence tailored to Kevin — reference his specific background",
  "recommendation": "One sentence tip for the cover letter"
}}"""

        msg = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            raw = raw.rstrip("`").strip()
        data = json.loads(raw)
        return (
            data.get("why_apply", ""),
            data.get("strengths", []),
            data.get("gaps", []),
            data.get("recommendation", ""),
        )

    def _save_to_db(self, db, job: Job, result: ScoringResult):
        job.match_score = result.score
        job.match_strengths = json.dumps(result.strengths)
        job.match_gaps = json.dumps(result.gaps)
        job.match_recommendation = json.dumps({
            "grade": result.grade,
            "why_apply": result.why_apply,
            "recommendation": result.recommendation,
            "visa_ok": result.dimensions.visa_ok,
            "visa_485_friendly": result.dimensions.visa_485_friendly,
            "dim_tech": result.dimensions.tech,
            "dim_experience": result.dimensions.experience,
            "dim_commercial": result.dimensions.commercial,
            "dim_location": result.dimensions.location,
            "dim_growth": result.dimensions.growth,
            "dim_company": result.dimensions.company_type,
            "dim_salary": result.dimensions.salary,
            "dim_ai": result.dimensions.ai_bonus,
            "dim_grad": result.dimensions.grad_friendly,
        })
        if not result.dimensions.visa_ok or result.score < settings.MIN_MATCH_SCORE:
            job.is_filtered_out = True
        db.merge(job)
        db.commit()

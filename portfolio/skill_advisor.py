"""
Detects if a job requires skills not covered by Kevin's current GitHub projects.
Instead of auto-generating projects, it flags gaps and recommends what to build.
"""

import json
from dataclasses import dataclass, field
from typing import List

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

# Kevin's current GitHub portfolio — update this list as new repos are added
CURRENT_PORTFOLIO = [
    {
        "repo": "smart-ai-api",
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "JWT", "pytest",
                   "SQLAlchemy", "CI/CD", "GitHub Actions", "REST API", "AI/LLM",
                   "Groq API", "bcrypt", "rate limiting", "microservices"],
    },
    {
        "repo": "job-tracker",
        "skills": ["TypeScript", "Next.js", "React", "PostgreSQL", "Prisma",
                   "Tailwind CSS", "Jest", "Vercel", "Server Actions", "Zod",
                   "drag-and-drop", "full-stack", "CI/CD"],
    },
    {
        "repo": "ai-cover-letter-helper",
        "skills": ["Python", "Streamlit", "Groq API", "LLM", "prompt engineering",
                   "AI", "NLP"],
    },
    {
        "repo": "task-manager-app",
        "skills": ["Node.js", "Express.js", "MongoDB", "EJS", "authentication",
                   "CRUD", "session management"],
    },
]

# Skills NOT in portfolio (flag if job asks for these)
KNOWN_GAPS = [
    "C#", ".NET", "ASP.NET", "Blazor",
    "Java", "Spring", "Spring Boot", "Maven", "Gradle",
    "Go", "Golang",
    "Ruby", "Rails",
    "PHP", "Laravel",
    "AWS", "Azure", "GCP", "Kubernetes", "Terraform",
    "React Native", "Flutter", "Swift", "Kotlin",
    "GraphQL",  # Kevin has "basics" only
    "Redis", "Elasticsearch",
    "Scala", "Rust",
]


@dataclass
class SkillGapReport:
    job_id: int
    missing_skills: List[str] = field(default_factory=list)
    covered_skills: List[str] = field(default_factory=list)
    recommendation: str = ""
    needs_new_project: bool = False
    suggested_project: str = ""


class SkillAdvisor:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.portfolio_skills = self._flatten_portfolio()

    def _flatten_portfolio(self) -> set:
        skills = set()
        for repo in CURRENT_PORTFOLIO:
            for s in repo["skills"]:
                skills.add(s.lower())
        return skills

    def analyse(self, job) -> SkillGapReport:
        """Check if any required skills are missing from Kevin's portfolio."""
        desc = (job.description or "").lower()
        title = (job.title or "").lower()
        combined = desc + " " + title

        missing = []
        for gap_skill in KNOWN_GAPS:
            if gap_skill.lower() in combined:
                missing.append(gap_skill)

        covered = []
        for skill in self.portfolio_skills:
            if skill in combined:
                covered.append(skill.title())

        report = SkillGapReport(
            job_id=job.id,
            missing_skills=missing,
            covered_skills=covered[:8],  # top 8 for display
            needs_new_project=len(missing) > 0,
        )

        if missing:
            report.recommendation = self._suggest_project(job, missing)

        return report

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=4, max=15))
    def _suggest_project(self, job, missing_skills: List[str]) -> str:
        skills_str = ", ".join(missing_skills[:5])
        prompt = f"""A candidate is applying for this job:
Title: {job.title}
Company: {job.company}
Missing skills from their portfolio: {skills_str}

In 2-3 sentences, suggest ONE small portfolio project they could build to demonstrate
these skills. Keep it concise and practical (buildable in a weekend).
Do NOT include any preamble — just the suggestion."""

        msg = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        suggestion = msg.content[0].text.strip()
        report_text = f"⚠️ Missing: {skills_str}\n💡 Suggestion: {suggestion}"
        return report_text

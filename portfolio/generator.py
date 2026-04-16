"""Generates a portfolio project tailored to a job using Claude AI."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, OUTPUT_DIR
from db.models import Job


@dataclass
class ProjectSpec:
    name: str           # kebab-case repo name
    title: str          # Human readable
    description: str    # One-sentence GitHub description
    tech_stack: List[str]
    files: List[Dict]   # [{"filename": "...", "purpose": "..."}]
    readme_highlights: str


@dataclass
class GeneratedProject:
    spec: ProjectSpec
    files: Dict[str, str]   # {filename: content}
    local_dir: Path


class ProjectGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def generate(self, job: Job, existing_repos: List[str] = None) -> GeneratedProject:
        print(f"[Portfolio] Designing project for: {job.title} @ {job.company}")
        existing_repos = existing_repos or []

        spec = self._design_project(job, existing_repos)
        print(f"  → Project: {spec.title} ({spec.name})")

        files = self._generate_all_files(spec, job)
        print(f"  → Generated {len(files)} files")

        local_dir = OUTPUT_DIR / "projects" / spec.name
        local_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            file_path = local_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        return GeneratedProject(spec=spec, files=files, local_dir=local_dir)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _design_project(self, job: Job, existing_repos: List[str]) -> ProjectSpec:
        existing_text = ", ".join(existing_repos) if existing_repos else "none"

        prompt = f"""You are a software engineer designing a portfolio project to impress a hiring manager.

JOB DESCRIPTION:
Title: {job.title}
Company: {job.company}
{job.description[:2000]}

CANDIDATE'S EXISTING GITHUB REPOS (avoid duplicating these):
{existing_text}

Design a small but impressive portfolio project that:
1. Directly demonstrates the top 2-3 skills required by this job
2. Solves a practical, real-world problem
3. Can be fully implemented in ~200 lines of code total
4. Uses the tech stack mentioned in the job posting

Return ONLY valid JSON:
{{
  "name": "kebab-case-repo-name",
  "title": "Human Readable Title",
  "description": "One sentence description for GitHub",
  "tech_stack": ["Python", "FastAPI"],
  "files": [
    {{"filename": "main.py", "purpose": "FastAPI app entry point"}},
    {{"filename": "README.md", "purpose": "Project documentation"}},
    {{"filename": "requirements.txt", "purpose": "Python dependencies"}},
    {{"filename": ".gitignore", "purpose": "Python gitignore"}},
    {{"filename": "tests/test_main.py", "purpose": "Basic tests"}}
  ],
  "readme_highlights": "- Feature 1\\n- Feature 2\\n- Feature 3"
}}"""

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        return ProjectSpec(
            name=data["name"],
            title=data["title"],
            description=data["description"],
            tech_stack=data.get("tech_stack", []),
            files=data.get("files", []),
            readme_highlights=data.get("readme_highlights", ""),
        )

    def _generate_all_files(self, spec: ProjectSpec, job: Job) -> Dict[str, str]:
        files = {}
        for file_info in spec.files:
            filename = file_info["filename"]
            purpose = file_info["purpose"]
            try:
                content = self._generate_file(spec, job, filename, purpose)
                files[filename] = content
            except Exception as e:
                print(f"  [Portfolio] Failed to generate {filename}: {e}")
        return files

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=20))
    def _generate_file(self, spec: ProjectSpec, job: Job, filename: str, purpose: str) -> str:
        tech = ", ".join(spec.tech_stack)

        if filename == "README.md":
            return self._generate_readme(spec, job)

        if filename == ".gitignore":
            return self._python_gitignore()

        prompt = f"""Generate the complete contents of `{filename}` for this portfolio project.

PROJECT: {spec.title}
DESCRIPTION: {spec.description}
TECH STACK: {tech}
FILE PURPOSE: {purpose}

REQUIREMENTS:
- Complete, runnable code (no TODO placeholders, no stub functions)
- Clean, well-commented code
- Keep it concise but complete (aim for under 100 lines for this file)
- Include proper error handling where appropriate
- Output ONLY the file contents — no explanation, no markdown fences

FILE CONTENTS:"""

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text.strip()
        # Remove markdown fences if Claude added them
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return content

    def _generate_readme(self, spec: ProjectSpec, job: Job) -> str:
        tech = ", ".join(spec.tech_stack)
        return f"""# {spec.title}

{spec.description}

## Features

{spec.readme_highlights}

## Tech Stack

{tech}

## Getting Started

```bash
git clone https://github.com/{settings.GITHUB_USERNAME}/{spec.name}.git
cd {spec.name}
pip install -r requirements.txt
python main.py
```

## About

Built as a portfolio project to demonstrate {tech} skills for {job.title} roles.
"""

    def _python_gitignore(self) -> str:
        return """__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
env/
venv/
.env
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
*.log
"""

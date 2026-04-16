"""Creates a GitHub repo and pushes generated project files via GitHub REST API."""

import base64
import json
import time
from datetime import datetime
from typing import Optional

import requests

from config import settings
from db.database import get_session
from db.models import Job, PortfolioProject
from portfolio.generator import GeneratedProject


class GitHubPusher:
    BASE = "https://api.github.com"

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def create_and_push(self, project: GeneratedProject, job: Job) -> PortfolioProject:
        print(f"[GitHub] Pushing: {project.spec.name}")

        repo_name = self._unique_name(project.spec.name)
        repo_url = self._create_repo(repo_name, project.spec.description)

        if not repo_url:
            raise RuntimeError(f"Failed to create repo: {repo_name}")

        time.sleep(2)  # Give GitHub time to initialise

        for filename, content in project.files.items():
            self._push_file(repo_name, filename, content)
            time.sleep(0.5)

        # Add topics
        try:
            topics = [t.lower().replace(" ", "-").replace(".", "") for t in project.spec.tech_stack[:10]]
            self._set_topics(repo_name, topics)
        except Exception:
            pass

        print(f"  → Repo: {repo_url}")

        db = get_session()
        record = PortfolioProject(
            job_id=job.id,
            repo_name=repo_name,
            repo_url=repo_url,
            title=project.spec.title,
            description=project.spec.description,
            tech_stack=json.dumps(project.spec.tech_stack),
            pushed_at=datetime.utcnow(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        db.close()

        return record

    def _create_repo(self, name: str, description: str) -> Optional[str]:
        resp = requests.post(
            f"{self.BASE}/user/repos",
            headers=self.headers,
            json={
                "name": name,
                "description": description,
                "private": False,
                "auto_init": False,
            },
        )
        if resp.status_code == 201:
            return resp.json().get("html_url")
        print(f"  [GitHub] Create repo failed: {resp.status_code} {resp.text[:200]}")
        return None

    def _push_file(self, repo: str, filepath: str, content: str):
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        resp = requests.put(
            f"{self.BASE}/repos/{settings.GITHUB_USERNAME}/{repo}/contents/{filepath}",
            headers=self.headers,
            json={
                "message": f"Add {filepath}",
                "content": encoded,
            },
        )
        if resp.status_code not in (200, 201):
            print(f"  [GitHub] Push {filepath} failed: {resp.status_code}")

    def _set_topics(self, repo: str, topics: list):
        requests.put(
            f"{self.BASE}/repos/{settings.GITHUB_USERNAME}/{repo}/topics",
            headers={**self.headers, "Accept": "application/vnd.github.mercy-preview+json"},
            json={"names": topics[:20]},
        )

    def _unique_name(self, name: str) -> str:
        existing = self._get_existing_repos()
        candidate = name
        suffix = 2
        while candidate in existing:
            candidate = f"{name}-{suffix}"
            suffix += 1
        return candidate

    def _get_existing_repos(self) -> set:
        repos = set()
        page = 1
        while True:
            resp = requests.get(
                f"{self.BASE}/user/repos",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            for r in data:
                repos.add(r["name"])
            page += 1
        return repos

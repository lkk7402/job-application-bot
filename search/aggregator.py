"""Aggregates results from all scrapers, deduplicates, filters, and saves to DB."""

import asyncio
import json
from datetime import datetime
from typing import List

from playwright.async_api import async_playwright

from config import settings, preferences, PLAYWRIGHT_DATA_DIR
from db.database import get_session
from db.models import Job, SearchRun
from search.base import RawJob
from search.linkedin import LinkedInScraper
from search.seek import SeekScraper
from search.indeed import IndeedScraper


class JobAggregator:
    def __init__(self):
        self.prefs = preferences

    async def search_all(self, verbose: bool = True) -> List[Job]:
        db = get_session()
        run = SearchRun(started_at=datetime.utcnow(), sources_used=json.dumps([]))
        db.add(run)
        db.commit()

        all_raw: List[RawJob] = []
        sources_used = []

        async with async_playwright() as p:
            tasks = []

            if self.prefs.get("sites", {}).get("linkedin", True):
                li_context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(PLAYWRIGHT_DATA_DIR / "linkedin"),
                    headless=False,   # LinkedIn detects headless — keep visible
                    slow_mo=50,       # 50ms between Playwright actions — more human-like
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                    ignore_default_args=["--enable-automation"],
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                li_scraper = LinkedInScraper(li_context)
                # Verify session ONCE before any concurrent searches
                session_ok = await li_scraper.verify_session()
                if not session_ok:
                    print("[LinkedIn] Session expired — run: python main.py login linkedin")
                    await li_context.close()
                else:
                    tasks.append(("linkedin", li_context, li_scraper))
                    sources_used.append("linkedin")

            if self.prefs.get("sites", {}).get("seek", True):
                seek_context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(PLAYWRIGHT_DATA_DIR / "seek"),
                    headless=True,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                seek_scraper = SeekScraper(seek_context)
                tasks.append(("seek", seek_context, seek_scraper))
                sources_used.append("seek")

            if self.prefs.get("sites", {}).get("indeed", False):
                indeed_context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(PLAYWRIGHT_DATA_DIR / "indeed"),
                    headless=True,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                indeed_scraper = IndeedScraper(indeed_context)
                tasks.append(("indeed", indeed_context, indeed_scraper))
                sources_used.append("indeed")

            # Run all scrapers concurrently per job title
            coroutines = []
            for name, ctx, scraper in tasks:
                for title in self.prefs.get("job_titles", [])[:6]:  # top 6 titles
                    for location in self.prefs.get("locations", ["Melbourne VIC"])[:2]:
                        coroutines.append(
                            self._safe_search(scraper, name, title, location, 25)
                        )

            results = await asyncio.gather(*coroutines)
            for batch in results:
                all_raw.extend(batch)

            # Close all contexts
            for _, ctx, _ in tasks:
                await ctx.close()

        if verbose:
            print(f"[Search] Found {len(all_raw)} raw results across {len(sources_used)} sites")

        # Deduplicate
        unique = self._deduplicate(all_raw)
        if verbose:
            print(f"[Search] {len(unique)} unique jobs after dedup")

        # Filter by preferences
        filtered = [j for j in unique if self._passes_filters(j)]
        if verbose:
            print(f"[Search] {len(filtered)} jobs pass filters")

        # Save new ones to DB
        new_jobs: List[Job] = []
        for raw in filtered:
            existing = db.query(Job).filter_by(
                external_id=raw.external_id, source=raw.source
            ).first()
            if not existing:
                job = Job(
                    external_id=raw.external_id,
                    source=raw.source,
                    title=raw.title,
                    company=raw.company,
                    location=raw.location,
                    url=raw.url,
                    description=raw.description,
                    salary_text=raw.salary_text,
                    job_type=raw.job_type,
                    posted_date=raw.posted_date,
                )
                db.add(job)
                new_jobs.append(job)

        db.commit()
        for j in new_jobs:
            db.refresh(j)

        # Update run log
        run.finished_at = datetime.utcnow()
        run.jobs_found = len(all_raw)
        run.jobs_new = len(new_jobs)
        run.sources_used = json.dumps(sources_used)
        new_job_ids = [j.id for j in new_jobs]
        db.commit()
        db.close()

        if verbose:
            print(f"[Search] {len(new_jobs)} new jobs saved to database")

        return new_job_ids

    async def _safe_search(self, scraper, name, query, location, max_results) -> List[RawJob]:
        try:
            return await scraper.search(query, location, max_results)
        except Exception as e:
            print(f"[{name}] Error searching '{query}' in '{location}': {e}")
            return []

    def _deduplicate(self, jobs: List[RawJob]) -> List[RawJob]:
        seen_ids = set()
        seen_titles = set()
        result = []
        for job in jobs:
            key_id = (job.external_id, job.source)
            key_title = (job.title.lower(), job.company.lower())
            if key_id in seen_ids or key_title in seen_titles:
                continue
            seen_ids.add(key_id)
            seen_titles.add(key_title)
            result.append(job)
        return result

    def _passes_filters(self, job: RawJob) -> bool:
        desc_lower = (job.description + " " + job.title).lower()

        for kw in self.prefs.get("keywords_excluded", []):
            if kw.lower() in desc_lower:
                return False

        allowed_types = [t.lower() for t in self.prefs.get("job_types", [])]
        if allowed_types and job.job_type:
            if not any(t in job.job_type.lower() for t in allowed_types):
                pass  # Don't filter — job_type data is inconsistent across sites

        return True

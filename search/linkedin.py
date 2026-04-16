"""LinkedIn job scraper using Playwright persistent context (headless=False)."""

import asyncio
import random
import re
from typing import List
from urllib.parse import urlencode

from search.base import BaseScraper, RawJob


class LinkedInScraper(BaseScraper):
    BASE_URL = "https://www.linkedin.com"

    async def verify_session(self) -> bool:
        """Check session by loading root and waiting for the authenticated redirect to /feed/."""
        page = await self.context.new_page()
        try:
            # Logged-in users get redirected from root → /feed/ by LinkedIn's JS
            await page.goto(f"{self.BASE_URL}/", wait_until="domcontentloaded", timeout=25000)
            # Wait up to 6s for JS redirect to /feed/
            try:
                await page.wait_for_url("**/feed/**", timeout=6000)
            except Exception:
                pass

            url = page.url
            if "login" in url or "authwall" in url or "checkpoint" in url:
                return False
            if "/feed" in url or "/mynetwork" in url or "/in/" in url:
                return True
            # Still on root or unknown — not authenticated
            return False
        except Exception:
            return False
        finally:
            await page.close()

    async def search(self, query: str, location: str, max_results: int = 25) -> List[RawJob]:
        page = await self.context.new_page()
        jobs: List[RawJob] = []

        try:

            params = {
                "keywords": query,
                "location": location,
                "sortBy": "R",
            }
            search_url = f"{self.BASE_URL}/jobs/search/?{urlencode(params)}"

            # Navigate via /jobs/ landing page first — more natural than jumping to search URL
            await page.goto(f"{self.BASE_URL}/jobs/", wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(1, 2)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 4)

            # Scroll to load more results — gradual movement, not a single jump
            for _ in range(min(max_results // 10 + 2, 5)):
                await self._gradual_scroll(page, steps=4)
                try:
                    await page.click("button:has-text('See more jobs')", timeout=2000)
                    await self._human_delay(1, 2)
                except Exception:
                    pass

            # Extract job cards
            cards = await page.query_selector_all(
                ".jobs-search__results-list li, "
                ".job-card-container, "
                "[data-job-id]"
            )

            for card in cards[:max_results]:
                try:
                    job = await self._extract_card(page, card)
                    if job:
                        jobs.append(job)
                    await self._human_delay(0.8, 1.5)
                except Exception:
                    continue

        except Exception as e:
            print(f"[LinkedIn] Search error for '{query}': {e}")
        finally:
            try:
                await page.close()
            except Exception:
                pass

        return jobs

    async def _ensure_logged_in(self, page):
        """Light check on an already-open page — just verify URL hasn't drifted to login."""
        url = page.url
        if "login" in url or "authwall" in url or "checkpoint" in url:
            raise RuntimeError("LinkedIn session expired. Run: python main.py login linkedin")

    async def _extract_card(self, page, card) -> RawJob | None:
        # Get job ID from attribute or link
        job_id = await card.get_attribute("data-job-id") or ""
        if not job_id:
            link = await card.query_selector("a[href*='/jobs/view/']")
            if link:
                href = await link.get_attribute("href") or ""
                m = re.search(r"/jobs/view/(\d+)", href)
                if m:
                    job_id = m.group(1)
        if not job_id:
            return None

        # Click card to open detail sidebar — use human-like mouse movement
        try:
            clicked = await self._move_and_click(page, card)
            if not clicked:
                return None
            await self._human_delay(1.5, 2.5)
        except Exception:
            return None

        # Extract details from sidebar
        selectors = {
            "title": (
                ".job-details-jobs-unified-top-card__job-title h1, "
                ".jobs-unified-top-card__job-title h1, "
                ".jobs-unified-top-card__job-title"
            ),
            "company": (
                ".job-details-jobs-unified-top-card__company-name, "
                ".jobs-unified-top-card__company-name"
            ),
            "location": (
                ".job-details-jobs-unified-top-card__primary-description-container span, "
                ".jobs-unified-top-card__bullet"
            ),
            "salary": (
                ".job-details-jobs-unified-top-card__job-insight--highlight, "
                ".compensation-salary-range, "
                ".jobs-unified-top-card__salary-main-rail"
            ),
            "posted": (
                ".jobs-unified-top-card__posted-date, "
                ".job-details-jobs-unified-top-card__posted-date"
            ),
            "desc": (
                ".jobs-description-content__text, "
                "#job-details, "
                ".jobs-box__html-content"
            ),
        }

        data = {}
        for key, sel in selectors.items():
            data[key] = await self._safe_text(page, sel)

        if not data["title"] or not data["company"]:
            return None

        return RawJob(
            title=data["title"].strip(),
            company=data["company"].strip(),
            location=data["location"].strip(),
            url=f"{self.BASE_URL}/jobs/view/{job_id}/",
            description=data["desc"].strip(),
            source="linkedin",
            external_id=job_id,
            salary_text=data["salary"].strip(),
            job_type="",
            posted_date=data["posted"].strip(),
        )

    async def do_login(self):
        """Manual login — opens browser so user can log in themselves, then saves session."""
        page = await self.context.new_page()
        try:
            await page.goto(f"{self.BASE_URL}/login", wait_until="domcontentloaded")
            print("\n[LinkedIn] Browser is open at the login page.")
            print("[LinkedIn] Please log in manually (including any 2FA/verification).")
            print("[LinkedIn] Once you see your LinkedIn feed, press Enter here to save the session.")
            await asyncio.get_event_loop().run_in_executor(None, input, ">>> Press Enter when logged in: ")
            url = page.url
            if "feed" in url or "mynetwork" in url or "linkedin.com/in/" in url:
                print("[LinkedIn] Session saved successfully.")
            else:
                print(f"[LinkedIn] Warning: current URL is {url} — session may not be saved correctly.")
        finally:
            await page.close()

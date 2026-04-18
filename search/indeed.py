"""Indeed Australia job scraper using Playwright."""

import re
from typing import List
from urllib.parse import quote_plus

from search.base import BaseScraper, RawJob


class IndeedScraper(BaseScraper):
    BASE_URL = "https://au.indeed.com"

    async def search(self, query: str, location: str, max_results: int = 25) -> List[RawJob]:
        page = await self.context.new_page()
        jobs: List[RawJob] = []

        try:
            q   = quote_plus(query)
            loc = quote_plus(location)
            url = f"{self.BASE_URL}/jobs?q={q}&l={loc}&sort=date&fromage=14"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 4)

            # Dismiss any sign-in / cookie modal
            for btn_text in ["No thanks", "Accept", "Dismiss", "Close"]:
                try:
                    await page.click(f"button:has-text('{btn_text}')", timeout=2000)
                    await self._human_delay(0.5, 1)
                except Exception:
                    pass

            page_num = 0
            while len(jobs) < max_results and page_num <= 2:
                # Job cards
                cards = await page.query_selector_all(
                    ".job_seen_beacon, .resultContent, [data-testid='slider_item'], li[class*='css-']"
                )
                if not cards:
                    break

                for card in cards:
                    if len(jobs) >= max_results:
                        break
                    try:
                        job = await self._extract_card(page, card)
                        if job:
                            jobs.append(job)
                        await self._human_delay(0.8, 1.5)
                    except Exception:
                        continue

                # Next page
                page_num += 1
                try:
                    next_btn = await page.query_selector("[data-testid='pagination-page-next'], a[aria-label='Next Page']")
                    if next_btn:
                        await next_btn.click()
                        await self._human_delay(2, 4)
                    else:
                        break
                except Exception:
                    break

        except Exception as e:
            print(f"[Indeed] Search error for '{query}': {e}")
        finally:
            await page.close()

        return jobs

    async def _extract_card(self, page, card) -> RawJob | None:
        # Get job ID from data-jk attribute or link
        job_id = await card.get_attribute("data-jk") or ""
        if not job_id:
            link = await card.query_selector("a[data-jk], a[id*='job_']")
            if link:
                job_id = await link.get_attribute("data-jk") or ""
                if not job_id:
                    href = await link.get_attribute("href") or ""
                    m = re.search(r"jk=([a-f0-9]+)", href)
                    if m:
                        job_id = m.group(1)
        if not job_id:
            return None

        # Extract summary from card
        title   = await self._card_text(card, "[data-testid='jobTitle'] span, h2[class*='jobTitle'] span, .jobTitle span")
        company = await self._card_text(card, "[data-testid='company-name'], .companyName")
        location= await self._card_text(card, "[data-testid='text-location'], .companyLocation")
        salary  = await self._card_text(card, "[data-testid='attribute_snippet_testid'], .salary-snippet-container, .metadata.salary-snippet-container")
        listed  = await self._card_text(card, "[data-testid='myJobsStateDate'], .date, span[class*='date']")

        if not title or not company:
            return None

        job_url = f"{self.BASE_URL}/viewjob?jk={job_id}"

        # Click card to load description in the right panel
        desc = await self._fetch_description(page, card, job_id)

        return RawJob(
            title=title.strip(),
            company=company.strip(),
            location=location.strip(),
            url=job_url,
            description=desc,
            source="indeed",
            external_id=job_id,
            salary_text=salary.strip(),
            job_type="",
            posted_date=listed.strip(),
        )

    async def _fetch_description(self, page, card, job_id: str) -> str:
        """Click the card to load the description panel, then extract text."""
        try:
            await self._move_and_click(page, card)
            await self._human_delay(1.5, 2.5)

            # Description appears in right-side panel
            desc = await self._safe_text(
                page,
                "#jobDescriptionText, [data-testid='jobDescriptionText'], "
                ".jobsearch-jobDescriptionText, #job-content"
            )
            if desc:
                return desc
        except Exception:
            pass

        # Fallback: open detail page directly
        detail_page = await self.context.new_page()
        try:
            await detail_page.goto(
                f"{self.BASE_URL}/viewjob?jk={job_id}",
                wait_until="domcontentloaded", timeout=20000
            )
            await self._human_delay(1, 2)
            return await self._safe_text(
                detail_page,
                "#jobDescriptionText, [data-testid='jobDescriptionText']"
            )
        except Exception:
            return ""
        finally:
            await detail_page.close()

    async def _card_text(self, card, selector: str) -> str:
        try:
            el = await card.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return ""

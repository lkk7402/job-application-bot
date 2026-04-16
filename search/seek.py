"""Seek.com.au job scraper using Playwright."""

import asyncio
import re
from typing import List
from urllib.parse import quote_plus

from search.base import BaseScraper, RawJob


class SeekScraper(BaseScraper):
    BASE_URL = "https://www.seek.com.au"

    async def search(self, query: str, location: str, max_results: int = 25) -> List[RawJob]:
        page = await self.context.new_page()
        jobs: List[RawJob] = []

        try:
            # Build search URL
            q = quote_plus(query)
            loc = quote_plus(location.replace(",", "").replace("VIC", "").strip())
            url = f"{self.BASE_URL}/{q}-jobs/in-{loc}?sortmode=ListedDate"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 4)

            page_num = 1
            while len(jobs) < max_results and page_num <= 3:
                # Get job cards on current page
                cards = await page.query_selector_all("[data-testid='job-card'], article[data-card-type='JobCard']")

                if not cards:
                    # Try alternative selectors
                    cards = await page.query_selector_all("article[class*='job-card'], div[class*='jobCard']")

                for card in cards:
                    if len(jobs) >= max_results:
                        break
                    try:
                        job = await self._extract_card_with_detail(page, card)
                        if job:
                            jobs.append(job)
                        await self._human_delay(1, 2.5)
                    except Exception:
                        continue

                # Go to next page
                page_num += 1
                try:
                    next_btn = await page.query_selector(f"a[aria-label='Next'], [data-testid='pagination-next']")
                    if next_btn:
                        await next_btn.click()
                        await self._human_delay(2, 4)
                    else:
                        break
                except Exception:
                    break

        except Exception as e:
            print(f"[Seek] Search error for '{query}': {e}")
        finally:
            await page.close()

        return jobs

    async def _extract_card_with_detail(self, page, card) -> RawJob | None:
        # Extract summary from card — selectors based on live Seek HTML (data-automation attrs)
        title_el = await card.query_selector("[data-automation='jobTitle'], [data-testid='job-card-title']")
        if not title_el:
            return None

        title = (await title_el.inner_text()).strip()
        company = await self._card_text(card, "[data-automation='jobCompany']")
        location = await self._card_text(card, "[data-automation='jobCardLocation'], [data-automation='jobLocation']")
        salary = await self._card_text(card, "[data-automation='jobSalary']")
        listed = await self._card_text(card, "[data-automation='jobListingDate']")
        job_type = await self._card_text(card, "[data-testid='work-arrangement']")

        # Get job URL and ID
        link_el = await card.query_selector("a[data-automation='jobTitle'], a[href*='/job/']")
        if not link_el:
            return None

        href = await link_el.get_attribute("href") or ""
        if not href.startswith("http"):
            href = self.BASE_URL + href

        m = re.search(r"/job/(\d+)", href)
        if not m:
            return None
        job_id = m.group(1)

        # Visit job detail page for full description
        desc = await self._fetch_description(page, href)

        return RawJob(
            title=title,
            company=company,
            location=location,
            url=href,
            description=desc,
            source="seek",
            external_id=job_id,
            salary_text=salary,
            job_type=job_type,
            posted_date=listed,
        )

    async def _fetch_description(self, page, url: str) -> str:
        detail_page = await self.context.new_page()
        try:
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._human_delay(1, 2)
            desc = await self._safe_text(
                detail_page,
                "[data-automation='jobAdDetails']"
            )
            return desc
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

    async def do_login(self, email: str, otp_callback=None):
        """Login to Seek via email OTP. otp_callback is called to get the OTP from user."""
        page = await self.context.new_page()
        try:
            await page.goto(f"{self.BASE_URL}/sign-in", wait_until="domcontentloaded")
            await self._human_delay(1, 2)

            await page.fill("input[type='email'], input[name='email']", email)
            await self._human_delay(0.5, 1)
            await page.click("button[type='submit'], button:has-text('Continue')")
            await self._human_delay(2, 3)

            # If password field appears
            pwd_field = await page.query_selector("input[type='password']")
            if pwd_field:
                print("[Seek] Password field detected — enter password in the browser or provide SEEK_PASSWORD in .env")
                await asyncio.sleep(15)

            # If OTP field appears
            otp_field = await page.query_selector("input[autocomplete='one-time-code'], input[name*='code'], input[name*='otp']")
            if otp_field:
                print("[Seek] OTP required — check your email and enter the code.")
                if otp_callback:
                    # Support both sync and async callbacks
                    import inspect
                    if inspect.iscoroutinefunction(otp_callback):
                        otp = await otp_callback()
                    else:
                        otp = otp_callback()
                else:
                    otp = input("Enter Seek OTP code: ")
                await otp_field.fill(str(otp).strip())
                await page.click("button[type='submit'], button:has-text('Verify')")
                await self._human_delay(2, 3)

            if "seek.com.au" in page.url and "sign-in" not in page.url:
                print("[Seek] Login successful — session saved.")
            else:
                print(f"[Seek] Login may have failed. URL: {page.url}")
        finally:
            await page.close()

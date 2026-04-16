"""Seek.com.au application automation using Playwright."""

import asyncio
import random
from pathlib import Path

from apply.base import BaseApplicator, ApplicationResult
from config import settings


class SeekApplicator(BaseApplicator):

    async def apply(
        self,
        job_url: str,
        resume_pdf: Path,
        cover_letter_text: str,
        confirmation_callback,
    ) -> ApplicationResult:
        page = await self.context.new_page()
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await self._delay(2, 3)

            # Click Apply button
            apply_btn = await page.query_selector(
                "a:has-text('Apply'), button:has-text('Apply'), [data-automation='job-detail-apply']"
            )
            if not apply_btn:
                return ApplicationResult(success=False, error="No Apply button found")

            await apply_btn.click()
            await self._delay(2, 4)

            # Check if redirected to external site
            if "seek.com.au" not in page.url:
                return ApplicationResult(
                    success=False,
                    error=f"EXTERNAL_ATS:{page.url}",
                    confirmation_text="Redirected to company website",
                )

            # Handle Seek's multi-step application form
            return await self._fill_seek_form(page, resume_pdf, cover_letter_text, confirmation_callback)

        except Exception as e:
            return ApplicationResult(success=False, error=str(e))
        finally:
            await page.close()

    async def _fill_seek_form(self, page, resume_pdf: Path, cover_letter_text: str, confirmation_callback) -> ApplicationResult:
        step = 0
        max_steps = 8

        while step < max_steps:
            step += 1
            await self._delay(1, 2)

            # Success detection
            if await page.query_selector("[data-automation='apply-success'], h1:has-text('Application submitted')"):
                return ApplicationResult(success=True, confirmation_text="Application submitted on Seek")

            # Resume upload
            file_input = await page.query_selector("input[type='file'][accept*='pdf'], input[type='file']")
            if file_input and resume_pdf.exists():
                await file_input.set_input_files(str(resume_pdf))
                await self._delay(1.5, 2.5)

            # Cover letter
            cover_area = await page.query_selector(
                "textarea[data-automation*='cover'], textarea[placeholder*='cover'], textarea[id*='cover']"
            )
            if cover_area:
                await cover_area.fill(cover_letter_text[:3000])
                await self._delay(0.5, 1)

            # Fill text inputs (name, email, phone)
            await self._fill_basic_fields(page)

            # Fill questionnaire yes/no answers
            await self._answer_questions(page)

            # Look for Review/Submit button
            review_btn = await page.query_selector(
                "button:has-text('Review'), button:has-text('Preview application')"
            )
            submit_btn = await page.query_selector(
                "button:has-text('Submit'), button[data-automation*='submit']"
            )

            if submit_btn:
                # Wait for user confirmation
                await confirmation_callback()
                await submit_btn.click()
                await self._delay(2, 4)
                continue

            if review_btn:
                # Show preview — wait for confirmation before submitting
                await review_btn.click()
                await self._delay(1.5, 2.5)
                continue

            # Next step
            next_btn = await page.query_selector(
                "button:has-text('Next'), button:has-text('Continue'), button[data-automation*='next']"
            )
            if next_btn:
                await next_btn.click()
            else:
                break

        return ApplicationResult(success=False, error="Could not complete Seek application form")

    async def _fill_basic_fields(self, page):
        mappings = {
            "input[name*='firstName'], input[id*='firstName']": "Kevin",
            "input[name*='lastName'], input[id*='lastName']": "Shih",
            "input[type='email']": settings.SEEK_EMAIL,
            "input[type='tel'], input[name*='phone']": "0422222489",
        }
        for selector, value in mappings.items():
            try:
                el = await page.query_selector(selector)
                if el:
                    current = await el.input_value()
                    if not current:
                        await el.fill(value)
                        await self._delay(0.3, 0.6)
            except Exception:
                pass

    async def _answer_questions(self, page):
        # Answer "Yes" to work authorisation questions
        labels = await page.query_selector_all("label")
        for label in labels:
            try:
                text = (await label.inner_text()).lower()
                if any(k in text for k in ["right to work", "work in australia", "authorised", "eligible"]):
                    radio_id = await label.get_attribute("for")
                    if radio_id:
                        radio = await page.query_selector(f"#{radio_id}[value*='yes'], #{radio_id}[value*='Yes']")
                        if radio:
                            await radio.click()
                            await self._delay(0.3, 0.6)
            except Exception:
                pass

    async def _delay(self, min_s: float = 1.0, max_s: float = 2.5):
        await asyncio.sleep(random.uniform(min_s, max_s))

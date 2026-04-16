"""LinkedIn Easy Apply automation using Playwright."""

import asyncio
import random
from pathlib import Path
from typing import Optional

from apply.base import BaseApplicator, ApplicationResult
from config import settings


class LinkedInApplicator(BaseApplicator):

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

            # Detect application type
            apply_btn = await page.query_selector(
                "button:has-text('Easy Apply'), .jobs-apply-button--top-card"
            )
            external_btn = await page.query_selector(
                "button:has-text('Apply'), a:has-text('Apply on company website')"
            )

            if apply_btn:
                return await self._easy_apply(page, resume_pdf, cover_letter_text, confirmation_callback)
            elif external_btn:
                href = await external_btn.get_attribute("href") or ""
                if href and "linkedin.com" not in href:
                    return ApplicationResult(
                        success=False,
                        error=f"EXTERNAL_ATS:{href}",
                        confirmation_text="Requires application on company website",
                    )
                return ApplicationResult(success=False, error="No Easy Apply button found")
            else:
                return ApplicationResult(success=False, error="No apply button found")

        except Exception as e:
            return ApplicationResult(success=False, error=str(e))
        finally:
            await page.close()

    async def _easy_apply(self, page, resume_pdf: Path, cover_letter_text: str, confirmation_callback) -> ApplicationResult:
        # Click Easy Apply
        await page.click("button:has-text('Easy Apply'), .jobs-apply-button--top-card")
        await self._delay(2, 3)

        step = 0
        max_steps = 10

        while step < max_steps:
            step += 1

            # Check for success
            if await page.query_selector(".jobs-post-apply-confirmation, [data-test-apply-confirmation]"):
                conf_text = await self._safe_text(page, ".jobs-post-apply-confirmation")
                return ApplicationResult(success=True, confirmation_text=conf_text or "Application submitted")

            # Check for submit/review button
            submit_btn = await page.query_selector(
                "button:has-text('Submit application'), button[aria-label*='Submit']"
            )
            if submit_btn:
                # PAUSE — wait for user confirmation
                await confirmation_callback()
                await submit_btn.click()
                await self._delay(2, 4)
                continue

            # Fill contact info if present
            await self._fill_contact_info(page)

            # Handle resume upload
            upload = await page.query_selector("input[type='file']")
            if upload and resume_pdf.exists():
                await upload.set_input_files(str(resume_pdf))
                await self._delay(1, 2)

            # Handle cover letter text area
            cover_area = await page.query_selector(
                "textarea[id*='cover'], textarea[placeholder*='cover'], textarea[aria-label*='cover']"
            )
            if cover_area:
                await cover_area.fill(cover_letter_text[:2000])
                await self._delay(0.5, 1)

            # Answer simple screening questions
            await self._answer_screening_questions(page)

            # Click Next / Continue
            next_btn = await page.query_selector(
                "button:has-text('Next'), button:has-text('Continue'), button:has-text('Review')"
            )
            if next_btn:
                await next_btn.click()
                await self._delay(1.5, 2.5)
            else:
                # No next button and no submit — something unexpected
                break

        return ApplicationResult(success=False, error="Could not complete Easy Apply form")

    async def _fill_contact_info(self, page):
        fields = {
            "input[id*='firstName'], input[name*='firstName']": "Kevin",
            "input[id*='lastName'], input[name*='lastName']": "Shih",
            "input[type='email']": settings.LINKEDIN_EMAIL,
            "input[type='tel'], input[id*='phone']": "0422222489",
        }
        for selector, value in fields.items():
            try:
                el = await page.query_selector(selector)
                if el:
                    current = await el.input_value()
                    if not current:
                        await el.fill(value)
                        await self._delay(0.3, 0.7)
            except Exception:
                pass

    async def _answer_screening_questions(self, page):
        # Handle yes/no radio buttons for common questions
        yes_radios = await page.query_selector_all(
            "input[type='radio'][value*='Yes'], input[type='radio'][id*='yes']"
        )
        for radio in yes_radios[:3]:
            try:
                label_text = ""
                label = await page.query_selector(f"label[for='{await radio.get_attribute(\"id\")}']")
                if label:
                    label_text = (await label.inner_text()).lower()
                # Answer "yes" to work authorisation questions
                if any(k in label_text for k in ["authoris", "eligible", "right to work", "legally"]):
                    await radio.click()
                    await self._delay(0.3, 0.6)
            except Exception:
                pass

        # Fill numeric experience fields with reasonable defaults
        number_inputs = await page.query_selector_all("input[type='number'], input[inputmode='numeric']")
        for inp in number_inputs[:5]:
            try:
                val = await inp.input_value()
                if not val:
                    await inp.fill("2")
            except Exception:
                pass

    async def _safe_text(self, page, selector: str) -> str:
        try:
            el = await page.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return ""

    async def _delay(self, min_s: float = 1.0, max_s: float = 2.5):
        await asyncio.sleep(random.uniform(min_s, max_s))

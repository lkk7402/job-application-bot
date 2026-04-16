"""Base scraper interface and shared data structures."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
import asyncio
import random


@dataclass
class RawJob:
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str                 # 'linkedin' | 'seek'
    external_id: str
    salary_text: str = ""
    job_type: str = ""
    posted_date: str = ""


class BaseScraper(ABC):
    def __init__(self, browser_context):
        self.context = browser_context

    @abstractmethod
    async def search(self, query: str, location: str, max_results: int) -> List[RawJob]:
        pass

    async def _human_delay(self, min_s: float = 1.5, max_s: float = 3.5):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _gradual_scroll(self, page, steps: int = 6):
        """Scroll down in small increments with pauses — avoids bot-detection on scroll."""
        for i in range(1, steps + 1):
            frac = i / steps
            try:
                await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {frac})")
            except Exception:
                break
            await self._human_delay(0.3, 0.8)

    async def _move_and_click(self, page, element) -> bool:
        """Move mouse to element before clicking — mimics human cursor movement."""
        try:
            box = await element.bounding_box()
            if box:
                x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                await page.mouse.move(x, y, steps=random.randint(8, 20))
                await self._human_delay(0.15, 0.4)
            await element.click()
            return True
        except Exception:
            return False

    async def _safe_text(self, page, selector: str, default: str = "") -> str:
        try:
            el = await page.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return default

    async def _safe_attr(self, page, selector: str, attr: str, default: str = "") -> str:
        try:
            el = await page.query_selector(selector)
            if el:
                val = await el.get_attribute(attr)
                return val.strip() if val else default
        except Exception:
            pass
        return default

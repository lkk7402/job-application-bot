"""Base applicator interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ApplicationResult:
    success: bool
    confirmation_text: str = ""
    error: str = ""
    applied_url: str = ""


class BaseApplicator(ABC):
    def __init__(self, browser_context):
        self.context = browser_context

    @abstractmethod
    async def apply(
        self,
        job_url: str,
        resume_pdf: Path,
        cover_letter_text: str,
        confirmation_callback,
    ) -> ApplicationResult:
        """
        Fill and submit a job application.
        confirmation_callback: async function that waits for user to confirm in dashboard.
        Returns ApplicationResult.
        """
        pass

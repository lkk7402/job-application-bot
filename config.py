"""Central configuration — loaded from .env and preferences.yaml."""

import yaml
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # AI
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-opus-4-5"

    # GitHub
    GITHUB_TOKEN: str
    GITHUB_USERNAME: str

    # Email
    GMAIL_ADDRESS: str
    GMAIL_APP_PASSWORD: str
    NOTIFY_EMAIL: str

    # LinkedIn
    LINKEDIN_EMAIL: str
    LINKEDIN_PASSWORD: str

    # Seek
    SEEK_EMAIL: str = ""
    SEEK_PASSWORD: str = ""

    # Behaviour
    MIN_MATCH_SCORE: int = 65
    MAX_APPLICATIONS_PER_RUN: int = 10
    GENERATE_PROJECTS: bool = True
    AUTO_APPLY: bool = False

    # Dashboard
    DASHBOARD_PORT: int = 8000
    DASHBOARD_SECRET_KEY: str = "changeme"

    model_config = {"env_file": ".env", "case_sensitive": True}


def load_preferences() -> dict:
    prefs_path = Path(__file__).parent / "preferences.yaml"
    with open(prefs_path) as f:
        return yaml.safe_load(f)


settings = Settings()
preferences = load_preferences()

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR = BASE_DIR / "output"
PLAYWRIGHT_DATA_DIR = BASE_DIR / "playwright_data"

RESUME_MD_PATH = ASSETS_DIR / "resume_base.md"

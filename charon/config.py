"""
Charon configuration. Loaded from answers.yaml + APPLICANT.md.
"""

from pathlib import Path
import yaml

BASE_DIR = Path(__file__).parent.parent
CHARON_DIR = Path(__file__).parent
RESUME_DIR = BASE_DIR / "resume"
ANSWERS_FILE = BASE_DIR / "answers.yaml"
APPLICANT_FILE = RESUME_DIR / "APPLICANT.md"
DB_FILE = CHARON_DIR / "jobs.db"

# Stealth settings
MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 7.0
TYPING_DELAY_MS = 50  # ms between keystrokes
PAGE_LOAD_WAIT_SEC = 3.0

# Browser settings
HEADLESS = False  # set True for daemon mode
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def load_answers() -> dict:
    """Load screening question answers from answers.yaml."""
    if not ANSWERS_FILE.exists():
        return {}
    with open(ANSWERS_FILE) as f:
        return yaml.safe_load(f) or {}

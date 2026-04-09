"""Project configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TBA_API_KEY = os.getenv("TBA_API_KEY", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
DB_PATH = "robotics_leads.db"
DASHBOARD_PORT = 5002
TARGET_COUNTRIES = [
    "USA",
    "Canada",
    "Israel",
    "Australia",
    "Turkey",
    "Brazil",
    "Mexico",
]
MIN_ACTIVE_YEAR = 2022

"""
Preqin / WRDS configuration.

Scope mirrors Crunchbase pipeline:
  - US-based AI / technology companies
  - Founded (or deal date) 2015-2025
  - At least one fundraising event
"""

import os
from pathlib import Path

# WRDS credentials — password handled by ~/.pgpass or interactive prompt
WRDS_USERNAME = os.getenv("WRDS_USERNAME", "")

# Scope filters (applied in SQL WHERE clauses)
DEAL_DATE_MIN = "2015-01-01"
DEAL_DATE_MAX = "2025-12-31"

# Preqin sector keywords to match AI companies.
# Preqin uses its own taxonomy — we'll search for these terms in sector columns.
AI_SECTOR_KEYWORDS = [
    "artificial intelligence",
    "machine learning",
    "ai",
    "deep learning",
    "natural language processing",
    "computer vision",
    "robotics",
    "generative ai",
]

GEOGRAPHY_KEYWORDS = [
    "united states",
    "us",
    "usa",
    "north america",
]

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCHEMA_REPORT_PATH = DATA_DIR / "schema_report.txt"

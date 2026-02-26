import os
from pathlib import Path

# -- API --
API_KEY    = os.getenv("CB_API_KEY", "33c812e7ccbd8ccb628926236d902989")
BASE_URL   = "https://api.crunchbase.com/v4/data"
AUTH_PARAM = {"user_key": API_KEY}

# Rate limits (requests / minute). Overridden at runtime by Phase 0 probe.
RATE_LIMIT_RPM_BASIC      = 60
RATE_LIMIT_RPM_ENTERPRISE = 200
RATE_LIMIT_RPM            = RATE_LIMIT_RPM_BASIC

# Retry
MAX_RETRIES       = 5
BACKOFF_BASE_SECS = 2   # sleep = BACKOFF_BASE_SECS ** attempt

# Pagination
DEFAULT_PAGE_SIZE = 1000   # max for search endpoints
CARD_PAGE_SIZE    = 100    # hard max for entity cards

# -- Paths --
ROOT_DIR       = Path(__file__).parent
DATA_DIR       = ROOT_DIR / "data"
RAW_DIR        = DATA_DIR / "raw"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
EXPORT_DIR     = DATA_DIR / "export"
DB_PATH        = DATA_DIR / "db" / "crunchbase.db"
LOG_PATH       = ROOT_DIR / "logs" / "pipeline.log"

# Create runtime dirs if missing
for _d in [DATA_DIR, RAW_DIR, CHECKPOINT_DIR, EXPORT_DIR,
           DATA_DIR / "db", ROOT_DIR / "logs"]:
    _d.mkdir(parents=True, exist_ok=True)

# -- Scope --
# United States location UUID (Crunchbase internal)
# Resolved via: GET /autocompletes?query=united+states&collection_ids=locations
TARGET_COUNTRY_UUID = "f110fca2-1055-99f6-996d-011c198b3928"  # United States
FOUNDING_YEAR_MIN   = 2015
FOUNDING_YEAR_MAX   = 2025

# "Artificial Intelligence (AI)" parent category GROUP UUID.
# Using category_groups (parent) is stricter than individual category tags —
# it correctly scopes the search to companies whose primary domain is AI.
# Resolved via: GET /autocompletes?query=artificial+intelligence&collection_ids=category_groups
AI_CATEGORY_GROUP_UUID = "e5514a50-8200-7f6b-de87-b07990670800"

# Minimum number of funding rounds a company must have.
# Companies with 0 funding rounds have no investor network data to analyze.
MIN_FUNDING_ROUNDS = 1

# Legacy: individual AI category slugs (kept for reference, no longer used in Phase 1)
AI_CATEGORY_SLUGS = [
    "artificial-intelligence",
    "machine-learning",
    "generative-ai",
    "deep-learning",
    "natural-language-processing",
    "computer-vision",
    "robotics",
    "predictive-analytics",
    "ai-infrastructure",
    "computer-vision-ai",
]

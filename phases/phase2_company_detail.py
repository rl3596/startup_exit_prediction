"""
Phase 2 — Company Detail Collection

For each company discovered in Phase 1, fetch a detailed entity profile
including cards for funding rounds, founders, investors, IPOs, and
acquisitions.

NOTE: Crunchbase v4 entity cards return FLAT LISTS of dicts — NOT the
{"entities": [...]} wrapper used by search endpoints. Each dict is the
record directly (no 'properties' wrapper).

Derives three exit labels:
  is_ipo      — ipos card non-empty OR ipo_status == "public"
  is_acquired — acquiree_acquisitions card non-empty OR operating_status == "acquired"
  is_unicorn  — any round post_money_valuation_usd >= $1 billion

Checkpoint: data/checkpoints/phase2_company_detail.json
  {"completed": ["uuid1", "uuid2", ...]}
"""

import logging
from datetime import date
from api.endpoints import CrunchbaseEndpoints
from api.client import AccessTierError
from storage.checkpoint import Checkpoint
from storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

ENTITY_FIELD_IDS = [
    "identifier",
    "short_description",
    "founded_on",
    "operating_status",
    "funding_total",
    "num_funding_rounds",
    "last_funding_type",
    "last_funding_at",
    "num_employees_enum",
    "ipo_status",
    "website",
    "linkedin",
    "stock_symbol",
]

ENTITY_CARD_IDS = [
    "founders",
    "investors",
    "raised_funding_rounds",
    "ipos",
    "acquiree_acquisitions",
    "headquarters_address",
]

UNICORN_THRESHOLD_USD = 1_000_000_000

# -- Success label --
# Age measured from founded_on to Dec 31, 2025.
# Eligible funding = SUM of rounds with announced_on <= 2025-12-31.
REFERENCE_DATE = date(2025, 12, 31)
SUCCESS_TIERS = [
    (24,    5_000_000),
    (48,   25_000_000),
    (72,   60_000_000),
    (96,  100_000_000),
    (120, 140_000_000),
]


def _compute_success_label(founded_on_str, eligible_funding_usd) -> int | None:
    """
    Returns 1 (success), 0 (not success), or None (missing data).

    Tiers (age in months as of 2025-12-31):
      ≤ 24  → need ≥  $5 M
      ≤ 48  → need ≥ $25 M
      ≤ 72  → need ≥ $60 M
      ≤ 96  → need ≥ $100 M
      ≤ 120 → need ≥ $140 M

    Returns None when founded_on_str is missing/unparseable or
    eligible_funding_usd is None (no dated round data).
    """
    if not founded_on_str or eligible_funding_usd is None:
        return None
    try:
        founded = date.fromisoformat(founded_on_str[:10])
    except ValueError:
        return None
    months_age = (
        (REFERENCE_DATE.year - founded.year) * 12
        + (REFERENCE_DATE.month - founded.month)
    )
    months_age = max(1, min(months_age, 120))
    for max_months, threshold in SUCCESS_TIERS:
        if months_age <= max_months:
            return 1 if eligible_funding_usd >= threshold else 0
    # Fallback for ages exactly at 120 (already capped above, but keep explicit)
    return 1 if eligible_funding_usd >= 140_000_000 else 0


def _get_date_value(d) -> str | None:
    """Extract string date value from Crunchbase date objects or plain strings."""
    if isinstance(d, dict):
        return d.get("value")
    return d


def _get_money_usd(m) -> float | None:
    """Extract USD value from Crunchbase money objects."""
    if isinstance(m, dict):
        return m.get("value_usd")
    return None


def _extract_exit_labels(props: dict, cards: dict, company_uuid: str = None) -> dict:
    """
    Derive exit labels from entity properties + flat-list cards.

    cards values are plain lists of dicts (no 'entities' wrapper).

    NOTE: The 'acquiree_acquisitions' card returns acquisitions *made by*
    this company (it is the acquirer). To detect if THIS company was acquired,
    we check operating_status == "acquired" OR if any acquisition record has
    acquiree_identifier.uuid == company_uuid.
    """
    is_ipo = (
        bool(cards.get("ipos"))
        or props.get("ipo_status") == "public"
    )
    # Check if this company was itself acquired
    was_acquired_via_card = False
    if company_uuid:
        for acq in cards.get("acquiree_acquisitions", []):
            acqe = acq.get("acquiree_identifier", {})
            if isinstance(acqe, dict) and acqe.get("uuid") == company_uuid:
                was_acquired_via_card = True
                break
    is_acquired = (
        was_acquired_via_card
        or props.get("operating_status") == "acquired"
    )
    # Unicorn: check any round for post_money_valuation >= $1B
    is_unicorn = False
    for round_rec in cards.get("raised_funding_rounds", []):
        val_usd = _get_money_usd(round_rec.get("post_money_valuation"))
        if val_usd and val_usd >= UNICORN_THRESHOLD_USD:
            is_unicorn = True
            break

    return {"is_ipo": is_ipo, "is_acquired": is_acquired, "is_unicorn": is_unicorn}


def run(api: CrunchbaseEndpoints, store: SQLiteStore, companies: list):
    ckpt = Checkpoint("phase2_company_detail")
    done = ckpt.get_completed_set()

    for i, company in enumerate(companies):
        permalink = company.get("permalink")
        uuid      = company.get("uuid")

        if not permalink or not uuid:
            continue
        if uuid in done:
            logger.debug("Skipping %s (already collected)", permalink)
            continue

        logger.info("[%d/%d] Fetching: %s", i + 1, len(companies), permalink)
        try:
            resp  = api.get_organization(permalink, ENTITY_FIELD_IDS, ENTITY_CARD_IDS)
            if not resp:
                ckpt.mark_done(uuid)
                continue

            props = resp.get("properties", {})
            cards = resp.get("cards", {})

            exits = _extract_exit_labels(props, cards, company_uuid=uuid)

            # Write rounds FIRST so get_eligible_funding_usd can query them
            store.upsert_funding_rounds_flat(uuid, cards.get("raised_funding_rounds", []))
            store.upsert_org_investors_flat(uuid, cards.get("investors", []))
            store.upsert_org_founders_flat(uuid, cards.get("founders", []))
            store.upsert_ipo_flat(uuid, cards.get("ipos", []))
            store.upsert_acquisition_flat(uuid, cards.get("acquiree_acquisitions", []))
            store.upsert_hq_flat(uuid, cards.get("headquarters_address", []))

            # Compute age-tiered success label from eligible funding
            founded_on_str   = _get_date_value(props.get("founded_on"))
            eligible_funding = store.get_eligible_funding_usd(uuid)
            is_success       = _compute_success_label(founded_on_str, eligible_funding)

            store.upsert_company_detail(uuid, props, exits, is_success=is_success)

            ckpt.mark_done(uuid)

        except AccessTierError as exc:
            logger.warning("Access tier insufficient for %s: %s", permalink, exc)
            ckpt.mark_done(uuid)
        except Exception as exc:
            logger.error("Error fetching %s: %s", permalink, exc)
            # Do NOT mark done — will retry on next run

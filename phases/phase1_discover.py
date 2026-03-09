"""
Phase 1 — AI Company Discovery

Uses the Crunchbase 'category_groups' field to filter by the parent
"Artificial Intelligence (AI)" group (UUID: e5514a50-8200-7f6b-de87-b07990670800).
This is stricter than filtering by 9 individual AI category tags and produces
a cleaner, more focused dataset (~6,800 companies vs 18,099).

Additional filter: num_funding_rounds >= 1 ensures every company has at least
one investor relationship — a prerequisite for network analysis.

Checkpoint: data/checkpoints/phase1_discover.json
  {"after_id": "<last_entity_uuid>", "collected_count": N}
"""

import logging
from api.endpoints import CrunchbaseEndpoints
from storage.checkpoint import Checkpoint
from storage.sqlite_store import SQLiteStore
import config

logger = logging.getLogger(__name__)

FIELD_IDS = [
    "identifier",
    "short_description",
    "founded_on",
    "operating_status",
    "num_funding_rounds",
    "funding_total",
    "last_funding_type",
    "categories",
    "location_identifiers",
]


def build_predicates() -> list:
    """
    Returns the AND-chain of search predicates.

    Filter logic:
    - facet_ids = "company"          → only company entities (not investors, schools)
    - location_identifiers = US UUID → USA only
    - category_groups = AI group UUID → parent "Artificial Intelligence (AI)" group
                                        (matches all AI sub-categories)
    - num_funding_rounds >= 1        → must have at least one funding round
                                        (ensures network data exists)
    - founded_on >= 2015-01-01       → within study window
    - founded_on <= 2025-12-31       → within study window

    Exact POST body structure:
    {
      "query": [
        {"type":"predicate","field_id":"facet_ids",
         "operator_id":"includes","values":["company"]},
        {"type":"predicate","field_id":"location_identifiers",
         "operator_id":"includes","values":["<US_UUID>"]},
        {"type":"predicate","field_id":"category_groups",
         "operator_id":"includes","values":["<AI_GROUP_UUID>"]},
        {"type":"predicate","field_id":"num_funding_rounds",
         "operator_id":"gte","values":["1"]},
        {"type":"predicate","field_id":"founded_on",
         "operator_id":"gte","values":["2015-01-01"]},
        {"type":"predicate","field_id":"founded_on",
         "operator_id":"lte","values":["2025-12-31"]}
      ]
    }
    """
    return [
        {
            "type":        "predicate",
            "field_id":    "facet_ids",
            "operator_id": "includes",
            "values":      ["company"],
        },
        {
            "type":        "predicate",
            "field_id":    "location_identifiers",
            "operator_id": "includes",
            "values":      [config.TARGET_COUNTRY_UUID],
        },
        {
            "type":        "predicate",
            "field_id":    "category_groups",
            "operator_id": "includes",
            "values":      [config.AI_CATEGORY_GROUP_UUID],
        },
        {
            "type":        "predicate",
            "field_id":    "num_funding_rounds",
            "operator_id": "gte",
            "values":      [str(config.MIN_FUNDING_ROUNDS)],
        },
        {
            "type":        "predicate",
            "field_id":    "founded_on",
            "operator_id": "gte",
            "values":      [f"{config.FOUNDING_YEAR_MIN}-01-01"],
        },
        {
            "type":        "predicate",
            "field_id":    "founded_on",
            "operator_id": "lte",
            "values":      [f"{config.FOUNDING_YEAR_MAX}-12-31"],
        },
    ]


def _parse_entity(ent: dict) -> dict:
    props = ent.get("properties", {})
    ident = props.get("identifier", {})
    if not isinstance(ident, dict):
        return {}

    funding     = props.get("funding_total", {})
    funding_usd = funding.get("value_usd") if isinstance(funding, dict) else None

    founded     = props.get("founded_on", {})
    founded_val = founded.get("value") if isinstance(founded, dict) else founded

    return {
        "uuid":               ident.get("uuid"),
        "permalink":          ident.get("permalink"),
        "name":               ident.get("value"),
        "description":        props.get("short_description"),
        "founded_on":         founded_val,
        "operating_status":   props.get("operating_status"),
        "num_funding_rounds": props.get("num_funding_rounds"),
        "funding_total_usd":  funding_usd,
        "last_funding_type":  props.get("last_funding_type"),
    }


def run(api: CrunchbaseEndpoints, store: SQLiteStore) -> list:
    """
    Discover all US AI companies in scope. Returns list of company dicts.
    Fully paginated and checkpoint-resumable.
    """
    ckpt       = Checkpoint("phase1_discover")
    after_id   = ckpt.get_after_id()
    predicates = build_predicates()

    logger.info(
        "Phase 1: AI category group UUID = %s | min_funding_rounds = %d",
        config.AI_CATEGORY_GROUP_UUID, config.MIN_FUNDING_ROUNDS
    )
    logger.info("Phase 1: Searching (resuming after_id=%s)", after_id)

    collected: list = []
    total = 0

    while True:
        resp     = api.search_organizations(predicates, FIELD_IDS,
                                             limit=1000, after_id=after_id)
        entities = resp.get("entities", [])
        if not entities:
            logger.info("No more entities returned — search complete.")
            break

        for ent in entities:
            record = _parse_entity(ent)
            if not record.get("uuid") or not record.get("permalink"):
                continue
            store.upsert_company(record)
            collected.append(record)

        total += len(entities)

        # Crunchbase v4 keyset pagination: derive after_id from last entity UUID.
        # The API does not return after_id as a top-level response field.
        if len(entities) == 1000:
            last_props = entities[-1].get("properties", {})
            after_id   = last_props.get("identifier", {}).get("uuid")
        else:
            after_id = None

        ckpt.set_after_id(after_id, total)
        logger.info("  %d companies collected so far...", total)

        if not after_id:
            break

    logger.info("Phase 1 complete: %d AI companies found.", total)
    return collected

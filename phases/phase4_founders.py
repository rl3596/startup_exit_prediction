"""
Phase 4 — Founder Profiles + Education

For each founder collected in Phase 2, fetch:
  - Basic person profile (name, title, linkedin)
  - Education history (degrees card) — Enterprise only
  - Employment history (jobs card) — Enterprise only

Gracefully handles Basic tier: catches AccessTierError per card and
logs missing data without aborting.

Checkpoint: data/checkpoints/phase4_founders.json
  {"completed": ["uuid1", ...]}
"""

import logging
from api.endpoints import CrunchbaseEndpoints
from api.client import AccessTierError
from storage.checkpoint import Checkpoint
from storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

PERSON_FIELD_IDS = [
    "identifier",
    "first_name",
    "last_name",
    "primary_job_title",
    "primary_organization",
    "linkedin",
    "gender",
]

DEGREE_CARD_FIELD_IDS = [
    "school_identifier",
    "subject",
    "type_name",
    "started_on",
    "completed_on",
]

JOB_CARD_FIELD_IDS = [
    "organization_identifier",
    "title",
    "started_on",
    "ended_on",
    "is_current",
]


def run(api: CrunchbaseEndpoints, store: SQLiteStore, access_report: dict):
    """
    Fetch founder profiles and education via entity lookup.

    The Crunchbase v4 API returns `degrees` and `jobs` cards as flat
    lists (not {"entities": [...]} dicts) when fetched via card_ids.
    """
    ckpt     = Checkpoint("phase4_founders")
    done     = ckpt.get_completed_set()
    founders = store.get_all_founders()

    is_enterprise = access_report.get("inferred_tier") == "enterprise"
    if not is_enterprise:
        logger.info(
            "Phase 4: Basic tier detected. Education/job cards may return 403 and will be skipped."
        )

    logger.info("Phase 4: Processing %d founders", len(founders))

    for i, founder in enumerate(founders):
        f_uuid      = founder.get("uuid")
        f_permalink = founder.get("permalink")

        if not f_uuid or not f_permalink:
            continue
        if f_uuid in done:
            continue

        logger.info("[%d/%d] Founder: %s", i + 1, len(founders), f_permalink)

        try:
            # Fetch person profile + degrees + jobs in a single call
            resp  = api.get_person(f_permalink, PERSON_FIELD_IDS,
                                    card_ids=["degrees", "jobs"])
            if not resp:
                ckpt.mark_done(f_uuid)
                continue

            props = resp.get("properties", {})
            cards = resp.get("cards", {})

            if props:
                store.upsert_founder_detail(f_uuid, props)

            # degrees card: flat list of degree dicts
            degrees = cards.get("degrees", [])
            if isinstance(degrees, list) and degrees:
                store.upsert_education(f_uuid, degrees)
                logger.info("  %d degrees", len(degrees))

            # jobs card: flat list of job dicts
            jobs = cards.get("jobs", [])
            if isinstance(jobs, list) and jobs:
                store.upsert_jobs(f_uuid, jobs)

            ckpt.mark_done(f_uuid)

        except AccessTierError:
            logger.warning("Person entity 403 for %s", f_permalink)
            ckpt.mark_done(f_uuid)
        except Exception as exc:
            logger.error("Error on founder %s: %s", f_permalink, exc)

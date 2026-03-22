"""
Phase 8 --- Investor Organization Team Discovery

Two sub-tasks:

  A) For each organization-type investor, search for all people whose
     primary_organization matches the investor org via POST /searches/people.
     Each person is classified by role and inserted into the `founders` table
     (universal person registry).  An `investor_team` junction row links each
     person to the investor org.

  B) For each person-type investor not already in the `founders` table,
     insert them so Phase 4 can fetch their education/jobs.

Phase 4 (education/jobs) should run AFTER this phase to pick up all
newly discovered people.

Checkpoint: data/checkpoints/phase8_investor_team.json
  {"completed": ["investor_uuid1", ...]}
"""

import logging
from api.endpoints import CrunchbaseEndpoints
from api.client import AccessTierError
from storage.checkpoint import Checkpoint
from storage.sqlite_store import SQLiteStore
from phases.phase4b_team import (
    classify_role,
    PEOPLE_SEARCH_FIELD_IDS,
    _search_people_for_company as _search_people_for_org,
)

logger = logging.getLogger(__name__)


def _ensure_person_investors_in_founders(store: SQLiteStore) -> int:
    """
    Sub-task B: Insert person-type investors (angels) into the founders
    table if they aren't already there.  No API calls — just SQL.
    Returns count of newly added people.
    """
    people = store.get_person_investors_not_in_founders()
    if not people:
        logger.info("All person-type investors already in founders table.")
        return 0

    count = 0
    for p in people:
        name = p.get("name") or ""
        parts = name.split(None, 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""
        person = {
            "uuid": p["uuid"],
            "permalink": p.get("permalink"),
            "first_name": first_name,
            "last_name": last_name,
            "primary_job_title": None,
            "linkedin": None,
            "gender": None,
        }
        # Insert into founders only (no investor_team row — they ARE the investor)
        store.upsert_investor_team_member(p["uuid"], person, "investor", "angel_investor")
        count += 1

    logger.info("Added %d person-type investors to founders table.", count)
    return count


def run(api: CrunchbaseEndpoints, store: SQLiteStore, sample: int = None):
    """
    Main entry point for Phase 8.
    """
    # Sub-task B first (no API calls)
    _ensure_person_investors_in_founders(store)

    # Sub-task A: search people for organization-type investors
    org_investors = store.get_org_investors()
    if sample is not None:
        org_investors = org_investors[:sample]

    ckpt = Checkpoint("phase8_investor_team")
    done = ckpt.get_completed_set()

    logger.info(
        "Phase 8: Searching team members for %d org investors (%d already done)",
        len(org_investors), len([u for u in org_investors if u["uuid"] in done])
    )

    total_found = 0

    for i, inv in enumerate(org_investors):
        inv_uuid = inv.get("uuid")
        inv_name = inv.get("name") or inv.get("permalink", "?")

        if not inv_uuid:
            continue
        if inv_uuid in done:
            continue

        logger.info("[%d/%d] Investor team search: %s", i + 1, len(org_investors), inv_name)

        try:
            people = _search_people_for_org(api, inv_uuid)
            total_found += len(people)

            for person in people:
                title = person.get("primary_job_title")
                role = classify_role(title)
                store.upsert_investor_team_member(inv_uuid, person, role, title)

            if people:
                roles = [classify_role(p.get("primary_job_title")) for p in people]
                role_summary = {}
                for r in roles:
                    role_summary[r] = role_summary.get(r, 0) + 1
                summary_str = ", ".join(f"{v} {k}" for k, v in sorted(role_summary.items()))
                logger.info("  %d people: %s", len(people), summary_str)

            ckpt.mark_done(inv_uuid)

        except AccessTierError:
            logger.warning("People search 403 for investor %s", inv_name)
            ckpt.mark_done(inv_uuid)
        except Exception as exc:
            logger.error("Error searching team for investor %s: %s", inv_name, exc)
            # Do NOT mark done — will retry on next run

    logger.info("Phase 8 complete: %d people found across investor orgs.", total_found)

"""
Phase 7 (4b) --- Board Members & Management Team Discovery

For each company discovered in Phase 1, search for all people currently
associated with the company via POST /searches/people with the
`primary_organization` filter.  Each person is classified by role
(board_member, c_suite, vp, director, advisor, founder, other) based on
keyword matching against primary_job_title.

New people are inserted into the `founders` table (used as a universal
person registry).  A `company_team` junction row is created for each
company-person pair with the classified role and raw title.

Phase 4 (education/jobs) runs AFTER this phase, so it automatically picks
up all newly discovered people and fetches their degrees + employment.

Checkpoint: data/checkpoints/phase4b_team.json
  {"completed": ["company_uuid1", ...]}
"""

import logging
from api.endpoints import CrunchbaseEndpoints
from api.client import AccessTierError
from storage.checkpoint import Checkpoint
from storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Fields to request from POST /searches/people
PEOPLE_SEARCH_FIELD_IDS = [
    "identifier",
    "first_name",
    "last_name",
    "primary_job_title",
    "primary_organization",
    "linkedin",
    "gender",
]

# Role classification rules (checked in priority order — first match wins).
ROLE_RULES = [
    ("c_suite", [
        "ceo", "cto", "cfo", "coo", "cmo", "cpo", "cro", "cso",
        "chief executive", "chief technology", "chief financial",
        "chief operating", "chief marketing", "chief product",
        "chief revenue", "chief science", "chief data",
        "chief information", "chief ai", "chief strategy",
        "chief research", "chief commercial", "chief medical",
        "chief people", "chief legal", "chief compliance",
        "chief architect", "chief engineer",
    ]),
    ("board_member", [
        "board member", "board of director", "board director",
        "chairman", "chairwoman", "chairperson",
        "non-executive director", "independent director",
    ]),
    ("advisor", [
        "advisor", "adviser", "venture partner", "mentor",
        "board observer",
    ]),
    ("founder", [
        "founder", "co-founder", "cofounder",
    ]),
    ("vp", [
        "vice president", "vp ", "vp,", " vp", "svp", "evp",
        "head of",
    ]),
    ("director", [
        "director",
    ]),
]


def classify_role(title: str | None) -> str:
    """
    Classify a person's role from their primary_job_title string.
    Returns one of: 'c_suite', 'board_member', 'advisor', 'vp',
    'director', 'founder', 'other'.
    """
    if not title:
        return "other"
    title_lower = title.lower()
    for role, keywords in ROLE_RULES:
        for kw in keywords:
            if kw in title_lower:
                return role
    return "other"


def _search_people_for_company(
    api: CrunchbaseEndpoints,
    company_uuid: str,
) -> list[dict]:
    """
    Search for all people whose primary_organization matches this company.
    Uses keyset pagination (after_id) for results exceeding one page.
    Returns flat list of person dicts.
    """
    predicates = [
        {
            "type":        "predicate",
            "field_id":    "primary_organization",
            "operator_id": "includes",
            "values":      [company_uuid],
        }
    ]

    all_people: list = []
    after_id: str | None = None

    while True:
        resp = api.search_people(
            predicates,
            PEOPLE_SEARCH_FIELD_IDS,
            limit=1000,
            after_id=after_id,
        )
        entities = resp.get("entities", [])
        if not entities:
            break

        for ent in entities:
            props = ent.get("properties", {})
            ident = props.get("identifier", {})
            if not isinstance(ident, dict) or not ident.get("uuid"):
                continue

            linkedin = props.get("linkedin")
            if isinstance(linkedin, dict):
                linkedin = linkedin.get("value")

            all_people.append({
                "uuid":              ident["uuid"],
                "permalink":         ident.get("permalink"),
                "first_name":        props.get("first_name"),
                "last_name":         props.get("last_name"),
                "primary_job_title": props.get("primary_job_title"),
                "linkedin":          linkedin,
                "gender":            props.get("gender"),
            })

        # Keyset pagination: full page means more results may exist
        if len(entities) >= 1000:
            last_props = entities[-1].get("properties", {})
            last_ident = last_props.get("identifier", {})
            after_id = last_ident.get("uuid") if isinstance(last_ident, dict) else None
            if not after_id:
                break
        else:
            break

    return all_people


def run(api: CrunchbaseEndpoints, store: SQLiteStore, companies: list):
    """
    Main entry point.  Iterates all companies, searches for team members,
    classifies roles, and persists to the database.
    """
    ckpt = Checkpoint("phase4b_team")
    done = ckpt.get_completed_set()

    logger.info("Phase 7: Searching team members for %d companies", len(companies))

    total_found = 0

    for i, company in enumerate(companies):
        c_uuid = company.get("uuid")
        c_name = company.get("name") or company.get("permalink", "?")

        if not c_uuid:
            continue
        if c_uuid in done:
            continue

        logger.info("[%d/%d] Team search: %s", i + 1, len(companies), c_name)

        try:
            people = _search_people_for_company(api, c_uuid)
            total_found += len(people)

            for person in people:
                title = person.get("primary_job_title")
                role  = classify_role(title)
                store.upsert_team_member(c_uuid, person, role, title)

            if people:
                roles = [classify_role(p.get("primary_job_title")) for p in people]
                role_summary = {}
                for r in roles:
                    role_summary[r] = role_summary.get(r, 0) + 1
                summary_str = ", ".join(f"{v} {k}" for k, v in sorted(role_summary.items()))
                logger.info("  %d people: %s", len(people), summary_str)

            ckpt.mark_done(c_uuid)

        except AccessTierError:
            logger.warning("People search 403 for %s", c_name)
            ckpt.mark_done(c_uuid)
        except Exception as exc:
            logger.error("Error searching team for %s: %s", c_name, exc)
            # Do NOT mark done — will retry on next run

    logger.info("Phase 7 complete: %d people found across all companies.", total_found)

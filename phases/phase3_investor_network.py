"""
Phase 3 — Investor Network (1-hop + 2-hop)

1-hop: For each unique investor collected in Phase 2, fetch their profile.
2-hop: For VC firm investors, fetch their full portfolio via the
       'participated_investments' card to build the 2-hop network.

Card response format: {"cards": {"participated_investments": [...]}}
Each investment record: {organization_identifier, funding_round_identifier,
                         announced_on, funding_round_money_raised, ...}

Checkpoint: data/checkpoints/phase3_investor_network.json
  {"completed": ["uuid1", ...]}
"""

import logging
from api.endpoints import CrunchbaseEndpoints
from api.client import AccessTierError
from storage.checkpoint import Checkpoint
from storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

INVESTOR_ORG_FIELD_IDS = [
    "identifier",
    "short_description",
    "investor_type",
    "investment_count",
    "num_portfolio_organizations",
    "website",
]

INVESTOR_PERSON_FIELD_IDS = [
    "identifier",
    "first_name",
    "last_name",
    "primary_job_title",
]


def _paginate_portfolio(api: CrunchbaseEndpoints, permalink: str) -> list:
    """
    Fetch all investment records from the participated_investments card.
    Must be called WITHOUT card_field_ids (the API rejects them for this card).
    Response: {"cards": {"participated_investments": [...]}}
    Each record: {organization_identifier, announced_on,
                  funding_round_money_raised, funding_round_investment_type, ...}
    Paginate using the uuid of the last item as after_id.
    """
    all_items: list = []
    after_id: str | None = None

    while True:
        resp = api.get_org_card_page(
            permalink, "participated_investments",
            card_field_ids=None, after_id=after_id
        )
        # Response: {"cards": {"participated_investments": [...]}}
        cards = resp.get("cards", {}) if isinstance(resp, dict) else {}
        items = cards.get("participated_investments", [])
        if not items:
            break
        all_items.extend(items)

        # Paginate if we got a full page (100 items)
        if len(items) == 100:
            last  = items[-1]
            ident = last.get("identifier", {})
            after_id = ident.get("uuid") if isinstance(ident, dict) else None
        else:
            after_id = None

        if not after_id:
            break

    return all_items


def run(api: CrunchbaseEndpoints, store: SQLiteStore):
    ckpt      = Checkpoint("phase3_investor_network")
    done      = ckpt.get_completed_set()
    investors = store.get_all_investors()

    logger.info("Phase 3: Processing %d investors", len(investors))

    for i, inv in enumerate(investors):
        inv_uuid      = inv.get("uuid")
        inv_permalink = inv.get("permalink")
        entity_type   = inv.get("entity_def_id", "organization")

        if not inv_uuid or not inv_permalink:
            continue
        if inv_uuid in done:
            continue

        logger.info("[%d/%d] Investor: %s (%s)", i + 1, len(investors),
                    inv_permalink, entity_type)

        try:
            if entity_type == "organization":
                # 1-hop: investor org profile
                resp = api.get_organization(inv_permalink, INVESTOR_ORG_FIELD_IDS)
                if resp:
                    props    = resp.get("properties", {})
                    inv_type = props.get("investor_type")
                    if isinstance(inv_type, list):
                        inv_type = ",".join(inv_type)
                    store.upsert_investor_detail(inv_uuid, {
                        **props,
                        "investor_type": inv_type,
                    })

                # 2-hop: VC portfolio companies
                try:
                    portfolio = _paginate_portfolio(api, inv_permalink)
                    if portfolio:
                        store.upsert_portfolio_edges_flat(inv_uuid, portfolio)
                        logger.info("  2-hop: %d portfolio investments", len(portfolio))
                except Exception as exc:
                    logger.warning("  Portfolio fetch failed for %s: %s", inv_permalink, exc)

            else:
                # Angel / individual investor
                try:
                    resp = api.get_person(inv_permalink, INVESTOR_PERSON_FIELD_IDS)
                    if resp:
                        store.upsert_investor_person(inv_uuid, resp.get("properties", {}))
                except AccessTierError:
                    logger.debug("Person entity access restricted for %s", inv_permalink)

            ckpt.mark_done(inv_uuid)

        except AccessTierError as exc:
            logger.warning("Access restricted for investor %s: %s", inv_permalink, exc)
            ckpt.mark_done(inv_uuid)
        except Exception as exc:
            logger.error("Error on investor %s: %s", inv_permalink, exc)

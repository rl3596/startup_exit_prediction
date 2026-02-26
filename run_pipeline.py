"""
run_pipeline.py — Top-level orchestrator.

Run:
    python run_pipeline.py

Phases:
    0  Access probe  — detect API tier, set rate limit
    1  Discover      — find all US AI companies (2015-2025)
    2  Detail        — per-company entity + cards + exit labels
    3  Investors     — 1-hop investor profiles, 2-hop VC portfolios
    4  Founders      — person profiles + education (Enterprise only)
    5  Export        — flat CSVs + graph JSON/CSV
    6  Validate      — statistics report

Resume behaviour:
    Each phase saves a JSON checkpoint. Re-running the script resumes
    from where it left off — already-processed entities are skipped.

Selective phases:
    python run_pipeline.py --phases 0 1 2

Sample mode (for pipeline testing):
    python run_pipeline.py --phases 2 3 4 5 6 --sample 500
    Limits Phases 2/3/4 to the first N companies so you can verify the
    full pipeline end-to-end before running on the complete dataset.
"""

import argparse
import logging
import sys

import config  # noqa — creates data dirs at import time

# Configure logging before any other imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(config.LOG_PATH), encoding="utf-8"),
    ],
)
logger = logging.getLogger("pipeline")

from api.client import CrunchbaseClient
from api.endpoints import CrunchbaseEndpoints
from api import access_probe
from phases import (
    phase1_discover,
    phase2_company_detail,
    phase3_investor_network,
    phase4_founders,
    phase6_validate,
)
from storage.sqlite_store import SQLiteStore
from storage.graph_builder import build_graph, export_graph


def parse_args():
    parser = argparse.ArgumentParser(description="Crunchbase AI Startup Pipeline")
    parser.add_argument(
        "--phases", nargs="+", type=int,
        default=[0, 1, 2, 3, 4, 5, 6],
        help="Which phases to run (default: all). E.g. --phases 0 1 2"
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        metavar="N",
        help="Limit Phases 2/3/4 to the first N companies. Useful for "
             "end-to-end testing before running on the full dataset. "
             "Example: --sample 500"
    )
    return parser.parse_args()


def main():
    args   = parse_args()
    phases = set(args.phases)
    sample = args.sample   # None = all companies; int = limit to first N

    client = CrunchbaseClient()
    api    = CrunchbaseEndpoints(client)
    store  = SQLiteStore(config.DB_PATH)

    access_report = {"inferred_tier": "unknown", "rpm": config.RATE_LIMIT_RPM_BASIC}

    # ------------------------------------------------------------------ #
    #  Phase 0: API Access Probe                                          #
    # ------------------------------------------------------------------ #
    if 0 in phases:
        logger.info("=== PHASE 0: API ACCESS PROBE ===")
        access_report = access_probe.run_access_probe(client)
        if access_report["inferred_tier"] == "no_access":
            logger.critical("API key has no access. Aborting.")
            sys.exit(1)

    # ------------------------------------------------------------------ #
    #  Phase 1: AI Company Discovery                                      #
    # ------------------------------------------------------------------ #
    companies = []
    if 1 in phases:
        logger.info("=== PHASE 1: AI COMPANY DISCOVERY ===")
        companies = phase1_discover.run(api, store)
    else:
        companies = store.get_all_companies()

    if not companies:
        logger.warning("No companies loaded. Run Phase 1 first.")

    # Apply sample limit for Phases 2/3/4 (testing mode)
    companies_for_detail = companies
    if sample is not None:
        companies_for_detail = companies[:sample]
        logger.info(
            "Sample mode: limiting Phases 2/3/4 to first %d of %d companies.",
            len(companies_for_detail), len(companies)
        )

    # ------------------------------------------------------------------ #
    #  Phase 2: Company Detail + Exit Labels                              #
    # ------------------------------------------------------------------ #
    if 2 in phases:
        logger.info("=== PHASE 2: COMPANY DETAIL ===")
        phase2_company_detail.run(api, store, companies_for_detail)

    # ------------------------------------------------------------------ #
    #  Phase 3: Investor Network (1-hop + 2-hop)                         #
    # ------------------------------------------------------------------ #
    if 3 in phases:
        logger.info("=== PHASE 3: INVESTOR NETWORK ===")
        phase3_investor_network.run(api, store)

    # ------------------------------------------------------------------ #
    #  Phase 4: Founder Profiles + Education                             #
    # ------------------------------------------------------------------ #
    if 4 in phases:
        logger.info("=== PHASE 4: FOUNDER DATA ===")
        phase4_founders.run(api, store, access_report)

    # ------------------------------------------------------------------ #
    #  Phase 5: Export flat CSVs + graph                                 #
    # ------------------------------------------------------------------ #
    if 5 in phases:
        logger.info("=== PHASE 5: EXPORTING DATA ===")
        for table in ["companies", "funding_rounds", "investors",
                       "founders", "education", "jobs", "ipos", "acquisitions",
                       "portfolio_edges"]:
            store.export_table_to_csv(
                table, str(config.EXPORT_DIR / f"{table}.csv")
            )
        graph = build_graph(store)
        export_graph(graph, config.EXPORT_DIR)
        logger.info("Export complete -> %s", config.EXPORT_DIR)
    else:
        graph = build_graph(store)

    # ------------------------------------------------------------------ #
    #  Phase 6: Validation Report                                         #
    # ------------------------------------------------------------------ #
    if 6 in phases:
        logger.info("=== PHASE 6: VALIDATION ===")
        phase6_validate.run(store, graph, access_report)


if __name__ == "__main__":
    main()

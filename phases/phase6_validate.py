"""
Phase 6 — Validation & Statistics Report

Prints a summary of:
  - API access tier detected
  - Data completeness across all tables
  - Exit label coverage (IPO / Acquisition / Unicorn)
  - Graph node/edge breakdown by type
"""

import logging

logger = logging.getLogger(__name__)


def run(store, graph: dict, access_report: dict):
    stats = store.get_stats()

    lines = [
        "",
        "=" * 60,
        "  PIPELINE VALIDATION REPORT",
        "=" * 60,
        f"  API tier detected : {access_report.get('inferred_tier', 'unknown')}",
        f"  Rate limit        : {access_report.get('rpm', '?')} RPM",
        "",
        "  --- Data Completeness ---",
        f"  Companies collected          : {stats['num_companies']}",
        f"  with funding rounds          : {stats['companies_with_rounds']}",
        f"  with investors               : {stats['companies_with_investors']}",
        f"  with founders                : {stats['companies_with_founders']}",
        f"  with education data          : {stats['companies_with_education']}",
        "",
        "  --- Success Label (ML target: is_success) ---",
        f"  Success     (is_success=1)   : {stats['num_success']}",
        f"  Not success (is_success=0)   : {stats['num_not_success']}",
        f"  Missing data (NULL)          : {stats['num_success_null']}",
        f"  Label coverage               : {stats['success_coverage_pct']:.1f}%",
        "",
        "  --- Supplemental Exit Reference ---",
        f"  IPO                          : {stats['num_ipo']}",
        f"  Acquired / M&A               : {stats['num_acquired']}",
        f"  Unicorn ($1B+ valuation)     : {stats['num_unicorn']}",
        "",
        "  --- Network Entities ---",
        f"  Investors                    : {stats['num_investors']}",
        f"  Founders                     : {stats['num_founders']}",
        f"  Universities                 : {stats['num_universities']}",
        f"  Funding rounds               : {stats['num_rounds']}",
        f"  Job records                  : {stats['num_jobs']}",
        "",
        "  --- Graph Summary ---",
        f"  Total nodes                  : {len(graph['nodes'])}",
        f"  Total edges                  : {len(graph['edges'])}",
    ]

    node_counts: dict = {}
    for n in graph["nodes"]:
        node_counts[n["type"]] = node_counts.get(n["type"], 0) + 1
    for ntype, cnt in sorted(node_counts.items()):
        lines.append(f"    {ntype:<30}: {cnt}")

    lines.append("")
    edge_counts: dict = {}
    for e in graph["edges"]:
        edge_counts[e["type"]] = edge_counts.get(e["type"], 0) + 1
    for etype, cnt in sorted(edge_counts.items()):
        lines.append(f"    {etype:<30}: {cnt} edges")

    lines += ["=" * 60, ""]

    report_text = "\n".join(lines)
    print(report_text)
    logger.info(
        "Validation complete. %d companies (%d success / %d not / %d null), "
        "%d nodes, %d edges.",
        stats["num_companies"], stats["num_success"], stats["num_not_success"],
        stats["num_success_null"], len(graph["nodes"]), len(graph["edges"])
    )

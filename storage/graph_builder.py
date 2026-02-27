"""
Builds a heterogeneous network graph from the SQLite data and exports it
as both CSV (nodes + edges) and JSON (node-link format).

Node types : company | investor_org | investor_person | founder | person | university
Edge types : invested_in | founded | educated_at | co_invested_in
             | board_member_of | executive_of | advisor_to | team_member_of
"""

import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_graph(store) -> dict:
    """
    Constructs and returns a graph dict:
    {
      "nodes": [{"id": uuid, "type": ..., "label": ..., "properties": {...}}, ...],
      "edges": [{"source": uuid, "target": uuid, "type": ..., "properties": {...}}, ...]
    }
    """
    nodes: dict = {}
    edges: list = []
    seen_edges:  set = set()

    def add_node(uuid, node_type, label, props=None):
        if uuid and uuid not in nodes:
            nodes[uuid] = {
                "id":         uuid,
                "type":       node_type,
                "label":      label or uuid,
                "properties": props or {},
            }

    def add_edge(src, tgt, edge_type, props=None):
        key = (src, tgt, edge_type)
        if key not in seen_edges and src and tgt:
            seen_edges.add(key)
            edges.append({
                "source":     src,
                "target":     tgt,
                "type":       edge_type,
                "properties": props or {},
            })

    # -- Company nodes ------------------------------------------------ #
    for c in store.get_all_companies():
        add_node(
            c["uuid"], "company", c["name"],
            {
                "is_ipo":      bool(c["is_ipo"]),
                "is_acquired": bool(c["is_acquired"]),
                "is_unicorn":  bool(c["is_unicorn"]),
                "is_success":  c.get("is_success"),   # int 0/1 or None
                "founded_on":  c["founded_on"],
                "operating_status": c["operating_status"],
            }
        )

    # -- Investor nodes + invested_in edges --------------------------- #
    for inv in store.get_all_investors():
        node_type = (
            "investor_org"
            if inv.get("entity_def_id") == "organization"
            else "investor_person"
        )
        add_node(inv["uuid"], node_type, inv.get("name"))

    for ci in store.get_company_investor_edges():
        add_edge(
            ci["investor_uuid"], ci["company_uuid"],
            "invested_in",
            {"round_uuid": ci.get("round_uuid")},
        )

    # -- Founder nodes + founded edges -------------------------------- #
    # Only add people who actually founded a company as "founder" nodes.
    # Team-only people (board members, executives, etc.) will be added
    # later as "person" nodes in the team edges section.
    founder_edges = store.get_company_founder_edges()
    actual_founder_uuids = {cf["founder_uuid"] for cf in founder_edges}

    for f in store.get_all_founders():
        if f["uuid"] in actual_founder_uuids:
            full_name = " ".join(filter(None, [f.get("first_name"), f.get("last_name")]))
            add_node(f["uuid"], "founder", full_name or f.get("permalink"))

    for cf in founder_edges:
        add_edge(cf["founder_uuid"], cf["company_uuid"], "founded")

    # -- Team member edges (board, c-suite, advisors) ----------------- #
    ROLE_EDGE_MAP = {
        "board_member": "board_member_of",
        "c_suite":      "executive_of",
        "vp":           "executive_of",
        "director":     "executive_of",
        "advisor":      "advisor_to",
        "founder":      "founded",        # deduped by seen_edges
        "other":        "team_member_of",
    }
    for ct in store.get_company_team_edges():
        person_uuid  = ct["person_uuid"]
        company_uuid = ct["company_uuid"]
        role         = ct.get("role", "other")

        # Add person node if not already present (e.g. not in company_founders)
        if person_uuid not in nodes:
            add_node(person_uuid, "person", ct.get("title") or person_uuid)

        edge_type = ROLE_EDGE_MAP.get(role, "team_member_of")
        add_edge(
            person_uuid, company_uuid, edge_type,
            {"role": role, "title": ct.get("title")},
        )

    # -- University nodes + educated_at edges ------------------------- #
    for edu in store.get_all_education():
        if edu.get("institution_uuid"):
            add_node(
                edu["institution_uuid"], "university",
                edu.get("institution_name"),
            )
            add_edge(
                edu["founder_uuid"],
                edu["institution_uuid"],
                "educated_at",
                {
                    "degree_type": edu.get("degree_type"),
                    "subject":     edu.get("subject"),
                },
            )

    # -- 2-hop: VC portfolio invested_in edges ------------------------ #
    for pe in store.get_portfolio_edges():
        # VC firm -> portfolio company (may or may not be in our company set)
        pc_uuid = pe["portfolio_company_uuid"]
        if pc_uuid not in nodes:
            add_node(pc_uuid, "company", pe.get("portfolio_company_name"))
        add_edge(
            pe["vc_uuid"], pc_uuid,
            "invested_in",
            {"announced_on": pe.get("announced_on")},
        )

    # -- Co-investor edges ------------------------------------------- #
    for pair in store.get_co_investor_pairs():
        add_edge(
            pair["investor_a_uuid"], pair["investor_b_uuid"],
            "co_invested_in",
            {"round_uuid": pair.get("round_uuid")},
        )

    graph = {"nodes": list(nodes.values()), "edges": edges}
    logger.info(
        "Graph built: %d nodes, %d edges", len(graph["nodes"]), len(graph["edges"])
    )
    return graph


def export_graph(graph: dict, export_dir) -> None:
    """
    Export graph to:
    - graph.json        (full node-link format with properties)
    - graph_nodes.csv   (id, type, label)
    - graph_edges.csv   (source, target, type)
    """
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = export_dir / "graph.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    logger.info("Exported graph.json (%d nodes, %d edges)",
                len(graph["nodes"]), len(graph["edges"]))

    # Nodes CSV
    nodes_path = export_dir / "graph_nodes.csv"
    with open(nodes_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "type", "label"])
        writer.writeheader()
        for n in graph["nodes"]:
            writer.writerow({"id": n["id"], "type": n["type"], "label": n["label"]})

    # Edges CSV
    edges_path = export_dir / "graph_edges.csv"
    with open(edges_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "target", "type"])
        writer.writeheader()
        for e in graph["edges"]:
            writer.writerow({"source": e["source"], "target": e["target"],
                              "type": e["type"]})

    logger.info("Graph CSVs written to %s", export_dir)

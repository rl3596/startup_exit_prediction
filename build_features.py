"""
build_features.py — Graph-derived and tabular feature engineering.

Reads from SQLite DB, constructs NetworkX graphs, computes per-company
network features (centrality, PageRank, co-investment clustering) plus
tabular features, and outputs data/model/feature_matrix.csv.

Usage:
    python build_features.py
"""

import sqlite3
import logging
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import numpy as np

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("build_features")

MODEL_DIR = config.DATA_DIR / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

DB = str(config.DB_PATH)
MIN_FUNDING = 1_000_000


def load_filtered_uuids(conn):
    """Return set of company UUIDs with funding >= $1M."""
    df = pd.read_sql_query(
        "SELECT uuid FROM companies WHERE funding_total_usd >= ?",
        conn, params=(MIN_FUNDING,),
    )
    return set(df["uuid"])


def load_companies(conn, uuids):
    """Load company-level tabular data."""
    df = pd.read_sql_query("SELECT * FROM companies", conn)
    df = df[df["uuid"].isin(uuids)].copy()
    return df


def load_edges(conn, uuids):
    """Load junction tables filtered to in-scope companies."""
    # company-investor edges (deduplicated to unique pairs)
    ci = pd.read_sql_query(
        "SELECT DISTINCT company_uuid, investor_uuid FROM company_investors",
        conn,
    )
    ci = ci[ci["company_uuid"].isin(uuids)]

    # company-founder edges
    cf = pd.read_sql_query("SELECT * FROM company_founders", conn)
    cf = cf[cf["company_uuid"].isin(uuids)]

    # round-investor edges (for co-investment graph)
    ri = pd.read_sql_query(
        """SELECT ri.round_uuid, ri.investor_uuid, ri.is_lead,
                  fr.company_uuid
           FROM round_investors ri
           JOIN funding_rounds fr ON ri.round_uuid = fr.uuid""",
        conn,
    )
    ri = ri[ri["company_uuid"].isin(uuids)]

    # company_team
    ct = pd.read_sql_query("SELECT * FROM company_team", conn)
    ct = ct[ct["company_uuid"].isin(uuids)]

    # education and jobs (for founder features)
    edu = pd.read_sql_query("SELECT * FROM education", conn)
    jobs = pd.read_sql_query("SELECT * FROM jobs", conn)

    return ci, cf, ri, ct, edu, jobs


# ------------------------------------------------------------------ #
#  Graph construction                                                  #
# ------------------------------------------------------------------ #

def build_bipartite_graph(ci):
    """Build investor-company bipartite graph."""
    G = nx.Graph()
    for _, row in ci.iterrows():
        c, i = row["company_uuid"], row["investor_uuid"]
        G.add_node(c, bipartite="company")
        G.add_node(i, bipartite="investor")
        G.add_edge(c, i)
    logger.info("Bipartite graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def build_coinvestment_graph(ri):
    """Build investor-investor co-investment graph (weighted by shared rounds)."""
    # Group investors by round, then create edges between all pairs in each round
    G = nx.Graph()
    round_groups = ri.groupby("round_uuid")["investor_uuid"].apply(list)
    for investors in round_groups:
        for i in range(len(investors)):
            for j in range(i + 1, len(investors)):
                a, b = investors[i], investors[j]
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1)
    logger.info("Co-investment graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


# ------------------------------------------------------------------ #
#  Network feature computation                                         #
# ------------------------------------------------------------------ #

def compute_network_features(ci, ri, company_uuids):
    """Compute per-company network features from bipartite and co-investment graphs."""
    logger.info("Building graphs...")
    G_bip = build_bipartite_graph(ci)
    G_coinv = build_coinvestment_graph(ri)

    logger.info("Computing PageRank...")
    pagerank = nx.pagerank(G_bip, alpha=0.85)

    logger.info("Computing betweenness centrality (approximate, k=500)...")
    betweenness = nx.betweenness_centrality(G_bip, k=min(500, G_bip.number_of_nodes()))

    logger.info("Computing degree centrality...")
    degree_cent = nx.degree_centrality(G_bip)

    logger.info("Precomputing co-investment clustering coefficients...")
    coinv_clustering = nx.clustering(G_coinv, weight="weight")

    # Map: company -> list of its investors
    company_investors_map = ci.groupby("company_uuid")["investor_uuid"].apply(list).to_dict()

    # Lead investor counts per company
    lead_counts = (
        ri[ri["is_lead"] == 1]
        .groupby("company_uuid")["investor_uuid"]
        .nunique()
        .to_dict()
    )

    logger.info("Computing per-company features for %d companies...", len(company_uuids))
    records = []
    for c_uuid in company_uuids:
        row = {"company_uuid": c_uuid}
        investors = company_investors_map.get(c_uuid, [])

        # Company-level graph metrics
        row["company_degree"] = G_bip.degree(c_uuid) if c_uuid in G_bip else 0
        row["company_degree_centrality"] = degree_cent.get(c_uuid, 0)
        row["company_pagerank"] = pagerank.get(c_uuid, 0)
        row["company_betweenness"] = betweenness.get(c_uuid, 0)

        # Investor-level aggregated metrics
        if investors:
            inv_degrees = [G_bip.degree(i) for i in investors if i in G_bip]
            inv_pr = [pagerank.get(i, 0) for i in investors]
            inv_bw = [betweenness.get(i, 0) for i in investors]

            row["avg_investor_degree"] = np.mean(inv_degrees) if inv_degrees else 0
            row["max_investor_degree"] = np.max(inv_degrees) if inv_degrees else 0
            row["avg_investor_pagerank"] = np.mean(inv_pr)
            row["max_investor_pagerank"] = np.max(inv_pr)
            row["avg_investor_betweenness"] = np.mean(inv_bw)

            # Co-investment clustering: mean local clustering coeff of investors
            inv_in_coinv = [i for i in investors if i in G_coinv]
            if inv_in_coinv:
                row["investor_clustering_coeff"] = np.mean(
                    [coinv_clustering.get(i, 0) for i in inv_in_coinv]
                )
                # Syndicate density: density of subgraph induced by this company's investors
                sub = G_coinv.subgraph(inv_in_coinv)
                row["investor_coinv_density"] = nx.density(sub) if len(inv_in_coinv) > 1 else 0
            else:
                row["investor_clustering_coeff"] = 0
                row["investor_coinv_density"] = 0
        else:
            row["avg_investor_degree"] = 0
            row["max_investor_degree"] = 0
            row["avg_investor_pagerank"] = 0
            row["max_investor_pagerank"] = 0
            row["avg_investor_betweenness"] = 0
            row["investor_clustering_coeff"] = 0
            row["investor_coinv_density"] = 0

        row["num_lead_investors"] = lead_counts.get(c_uuid, 0)
        records.append(row)

    return pd.DataFrame(records)


# ------------------------------------------------------------------ #
#  Tabular feature computation                                         #
# ------------------------------------------------------------------ #

EMPLOYEE_ORDINAL = {
    "c_00001_00010": 1,
    "c_00011_00050": 2,
    "c_00051_00100": 3,
    "c_00101_00250": 4,
    "c_00251_00500": 5,
    "c_00501_01000": 6,
    "c_01001_05000": 7,
    "c_05001_10000": 8,
    "c_10001_max": 9,
}


def compute_tabular_features(companies_df, cf, ct, edu, jobs):
    """Compute non-graph tabular features per company."""
    records = []

    # Pre-compute founder-level aggregates
    founder_companies = cf.groupby("company_uuid")["founder_uuid"].apply(list).to_dict()

    # Education: PhD and MBA flags per person
    edu_lower = edu.copy()
    edu_lower["degree_lower"] = edu_lower["degree_type"].fillna("").str.lower()
    has_phd = set(edu_lower[edu_lower["degree_lower"].str.contains("ph\\.?d|doctor", regex=True)]["founder_uuid"])
    has_mba = set(edu_lower[edu_lower["degree_lower"].str.contains("mba|m\\.b\\.a", regex=True)]["founder_uuid"])

    # Jobs count per person
    jobs_per_person = jobs.groupby("founder_uuid").size().to_dict()

    # Team aggregates per company
    team_size = ct.groupby("company_uuid").size().to_dict()
    c_suite_count = ct[ct["role"] == "c_suite"].groupby("company_uuid").size().to_dict()
    board_count = ct[ct["role"] == "board_member"].groupby("company_uuid").size().to_dict()
    advisor_count = ct[ct["role"] == "advisor"].groupby("company_uuid").size().to_dict()

    for _, c in companies_df.iterrows():
        uuid = c["uuid"]
        row = {"company_uuid": uuid}

        # Company-level features
        row["funding_total_usd"] = c["funding_total_usd"]
        row["log_funding"] = np.log1p(c["funding_total_usd"]) if pd.notna(c["funding_total_usd"]) else np.nan
        row["num_funding_rounds"] = c["num_funding_rounds"]
        row["last_funding_type"] = c["last_funding_type"]
        row["employees_ordinal"] = EMPLOYEE_ORDINAL.get(c["num_employees_enum"], np.nan)

        # Age in months
        if pd.notna(c["founded_on"]) and c["founded_on"]:
            try:
                founded = pd.Timestamp(c["founded_on"])
                row["company_age_months"] = (pd.Timestamp("2025-12-31") - founded).days / 30.44
            except Exception:
                row["company_age_months"] = np.nan
        else:
            row["company_age_months"] = np.nan

        # Founder features
        founders = founder_companies.get(uuid, [])
        row["num_founders"] = len(founders)

        if founders:
            row["founder_has_phd"] = int(any(f in has_phd for f in founders))
            row["founder_has_mba"] = int(any(f in has_mba for f in founders))
            prior_jobs = [jobs_per_person.get(f, 0) for f in founders]
            row["max_founder_prior_jobs"] = max(prior_jobs)
            row["avg_founder_prior_jobs"] = np.mean(prior_jobs)
        else:
            row["founder_has_phd"] = 0
            row["founder_has_mba"] = 0
            row["max_founder_prior_jobs"] = 0
            row["avg_founder_prior_jobs"] = 0

        # Team features
        row["team_size"] = team_size.get(uuid, 0)
        row["c_suite_count"] = c_suite_count.get(uuid, 0)
        row["board_count"] = board_count.get(uuid, 0)
        row["advisor_count"] = advisor_count.get(uuid, 0)

        # Target
        row["is_success"] = c["is_success"]

        records.append(row)

    return pd.DataFrame(records)


# ------------------------------------------------------------------ #
#  Main                                                                #
# ------------------------------------------------------------------ #

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    logger.info("Loading filtered company UUIDs (funding >= $1M)...")
    uuids = load_filtered_uuids(conn)
    logger.info("Filtered companies: %d", len(uuids))

    logger.info("Loading companies and edge tables...")
    companies_df = load_companies(conn, uuids)
    ci, cf, ri, ct, edu, jobs = load_edges(conn, uuids)
    conn.close()

    logger.info("Computing network features...")
    net_feat = compute_network_features(ci, ri, uuids)

    logger.info("Computing tabular features...")
    tab_feat = compute_tabular_features(companies_df, cf, ct, edu, jobs)

    logger.info("Merging features...")
    df = tab_feat.merge(net_feat, on="company_uuid", how="left")

    # One-hot encode last_funding_type (top categories)
    top_types = df["last_funding_type"].value_counts().head(8).index.tolist()
    df["last_funding_type_clean"] = df["last_funding_type"].where(
        df["last_funding_type"].isin(top_types), other="other"
    )
    dummies = pd.get_dummies(df["last_funding_type_clean"], prefix="fund_type")
    df = pd.concat([df, dummies], axis=1)
    df.drop(columns=["last_funding_type", "last_funding_type_clean"], inplace=True)

    # Save
    out_path = MODEL_DIR / "feature_matrix.csv"
    df.to_csv(out_path, index=False)
    logger.info("Feature matrix saved: %s (%d rows, %d columns)", out_path, len(df), len(df.columns))

    # Summary
    labeled = df[df["is_success"].notna()]
    logger.info("Labeled samples: %d (success=%.1f%%)",
                len(labeled), 100 * labeled["is_success"].mean())

    # Missing data summary
    logger.info("--- Missing Values ---")
    missing = df.isnull().sum()
    for col in missing[missing > 0].index:
        logger.info("  %s: %d (%.1f%%)", col, missing[col], 100 * missing[col] / len(df))


if __name__ == "__main__":
    main()

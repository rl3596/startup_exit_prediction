"""
build_edu_job_features.py — Education and employment network features.

Builds co-alumni and co-worker networks from education/jobs data,
computes per-company features (university prestige, alumni overlap with
investors, co-worker networks, etc.), and saves to
data/model/edu_job_features.csv.

Usage:
    python build_edu_job_features.py
"""

import sqlite3
import logging
import sys
from pathlib import Path
from itertools import combinations

import networkx as nx
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("build_edu_job_features")

MODEL_DIR = config.DATA_DIR / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

DB = str(config.DB_PATH)
MIN_FUNDING = 1_000_000


def load_data(conn):
    """Load all needed tables."""
    # Filtered company UUIDs
    companies = pd.read_sql_query(
        "SELECT uuid FROM companies WHERE funding_total_usd >= ?",
        conn, params=(MIN_FUNDING,),
    )
    company_uuids = set(companies["uuid"])

    # Company-founder links
    cf = pd.read_sql_query("SELECT * FROM company_founders", conn)
    cf = cf[cf["company_uuid"].isin(company_uuids)]

    # Company-investor links
    ci = pd.read_sql_query(
        "SELECT DISTINCT company_uuid, investor_uuid FROM company_investors", conn
    )
    ci = ci[ci["company_uuid"].isin(company_uuids)]

    # Company team (all roles)
    ct = pd.read_sql_query("SELECT * FROM company_team", conn)
    ct = ct[ct["company_uuid"].isin(company_uuids)]

    # Investor team
    it = pd.read_sql_query("SELECT * FROM investor_team", conn)

    # Education and jobs (all people)
    edu = pd.read_sql_query("SELECT * FROM education", conn)
    jobs = pd.read_sql_query("SELECT * FROM jobs", conn)

    # Founders table (to check education_fetched)
    founders = pd.read_sql_query("SELECT uuid, education_fetched FROM founders", conn)

    return company_uuids, cf, ci, ct, it, edu, jobs, founders


def build_university_graph(edu):
    """Build person-university bipartite graph and compute university PageRank."""
    G = nx.Graph()
    for _, row in edu.iterrows():
        p = row["founder_uuid"]
        u = row["institution_uuid"]
        if pd.notna(u) and u:
            G.add_node(p, bipartite="person")
            G.add_node(u, bipartite="university")
            G.add_edge(p, u)

    logger.info("University bipartite graph: %d nodes, %d edges",
                G.number_of_nodes(), G.number_of_edges())
    return G


def build_org_graph(jobs):
    """Build person-organization bipartite graph from job history."""
    G = nx.Graph()
    for _, row in jobs.iterrows():
        p = row["founder_uuid"]
        o = row["organization_uuid"]
        if pd.notna(o) and o:
            G.add_node(p, bipartite="person")
            G.add_node(o, bipartite="org")
            G.add_edge(p, o)

    logger.info("Organization bipartite graph: %d nodes, %d edges",
                G.number_of_nodes(), G.number_of_edges())
    return G


def compute_university_metrics(G_univ, edu):
    """Compute university-level metrics: degree and PageRank."""
    if G_univ.number_of_nodes() == 0:
        return {}, {}

    pagerank = nx.pagerank(G_univ, alpha=0.85)
    degree = dict(G_univ.degree())

    # Filter to university nodes only
    univ_nodes = {n for n, d in G_univ.nodes(data=True) if d.get("bipartite") == "university"}
    univ_pagerank = {n: pagerank[n] for n in univ_nodes}
    univ_degree = {n: degree[n] for n in univ_nodes}

    return univ_pagerank, univ_degree


def compute_org_metrics(G_org, jobs):
    """Compute organization-level metrics: degree and PageRank."""
    if G_org.number_of_nodes() == 0:
        return {}, {}

    pagerank = nx.pagerank(G_org, alpha=0.85)
    degree = dict(G_org.degree())

    org_nodes = {n for n, d in G_org.nodes(data=True) if d.get("bipartite") == "org"}
    org_pagerank = {n: pagerank[n] for n in org_nodes}
    org_degree = {n: degree[n] for n in org_nodes}

    return org_pagerank, org_degree


def get_person_universities(edu):
    """Map person_uuid -> set of institution_uuids."""
    return (
        edu[edu["institution_uuid"].notna()]
        .groupby("founder_uuid")["institution_uuid"]
        .apply(set)
        .to_dict()
    )


def get_person_orgs(jobs):
    """Map person_uuid -> set of organization_uuids."""
    return (
        jobs[jobs["organization_uuid"].notna()]
        .groupby("founder_uuid")["organization_uuid"]
        .apply(set)
        .to_dict()
    )


# Well-known large tech companies for "ex-FAANG" feature
MAJOR_TECH_NAMES = {
    "google", "alphabet", "meta", "facebook", "amazon", "apple", "microsoft",
    "netflix", "nvidia", "tesla", "ibm", "intel", "oracle", "salesforce",
    "uber", "airbnb", "twitter", "x corp", "linkedin", "snap", "spotify",
    "stripe", "palantir", "databricks", "snowflake", "openai", "deepmind",
    "bytedance", "tiktok",
}


def get_major_tech_orgs(jobs):
    """Find organization_uuids that match major tech company names."""
    org_names = (
        jobs[["organization_uuid", "organization_name"]]
        .drop_duplicates("organization_uuid")
        .dropna(subset=["organization_name"])
    )
    matches = org_names[
        org_names["organization_name"].str.lower().str.strip().isin(MAJOR_TECH_NAMES)
    ]
    return set(matches["organization_uuid"])


def compute_features(company_uuids, cf, ci, ct, it, edu, jobs, founders,
                     G_univ, G_org, univ_pr, univ_deg, org_pr, org_deg):
    """Compute per-company education and job network features."""

    # Precompute mappings
    person_univs = get_person_universities(edu)
    person_orgs = get_person_orgs(jobs)
    major_tech_uuids = get_major_tech_orgs(jobs)

    # Map company -> founders
    company_founders = cf.groupby("company_uuid")["founder_uuid"].apply(list).to_dict()

    # Map company -> all team members (founders + team)
    company_all_people = {}
    for c_uuid in company_uuids:
        people = set(cf[cf["company_uuid"] == c_uuid]["founder_uuid"])
        people |= set(ct[ct["company_uuid"] == c_uuid]["person_uuid"])
        company_all_people[c_uuid] = people

    # Map company -> investors
    company_investors = ci.groupby("company_uuid")["investor_uuid"].apply(set).to_dict()

    # Map investor -> team members (people working at the investor org)
    investor_people = it.groupby("investor_uuid")["person_uuid"].apply(set).to_dict()

    # Education data availability per person
    edu_fetched = set(founders[founders["education_fetched"] == 1]["uuid"])

    # Person's education degree types (for top-university identification)
    person_edu_records = edu.groupby("founder_uuid").apply(
        lambda g: list(zip(g["institution_uuid"], g["institution_name"], g["degree_type"]))
    ).to_dict()

    # Top universities by degree (number of connected people) — top 20
    top_20_univs = set(
        sorted(univ_deg.keys(), key=lambda u: univ_deg.get(u, 0), reverse=True)[:20]
    )

    # Companies in our dataset (for "founder worked at another startup" feature)
    all_company_org_uuids = set()
    for c_uuid in company_uuids:
        all_company_org_uuids.add(c_uuid)

    logger.info("Computing per-company edu/job features for %d companies...", len(company_uuids))

    records = []
    for c_uuid in company_uuids:
        row = {"company_uuid": c_uuid}
        founders_list = company_founders.get(c_uuid, [])
        all_people = company_all_people.get(c_uuid, set())
        investors = company_investors.get(c_uuid, set())

        # --- Data availability flag ---
        founders_with_edu = [f for f in founders_list if f in edu_fetched]
        row["edu_data_available"] = int(len(founders_with_edu) > 0)

        # ============================================================
        # EDUCATION NETWORK FEATURES
        # ============================================================

        # Collect all universities attended by founders
        founder_univ_set = set()
        for f in founders_list:
            founder_univ_set |= person_univs.get(f, set())

        # 1. founder_top_univ_count: founders who attended a top-20 university
        top_univ_count = 0
        for f in founders_list:
            f_univs = person_univs.get(f, set())
            if f_univs & top_20_univs:
                top_univ_count += 1
        row["founder_top_univ_count"] = top_univ_count

        # 2. founder_univ_degree_avg: average degree of founders' universities
        if founder_univ_set:
            row["founder_univ_degree_avg"] = np.mean(
                [univ_deg.get(u, 0) for u in founder_univ_set]
            )
        else:
            row["founder_univ_degree_avg"] = np.nan

        # 3. founder_univ_pagerank_max: max PageRank of any founder's university
        if founder_univ_set:
            row["founder_univ_pagerank_max"] = max(
                univ_pr.get(u, 0) for u in founder_univ_set
            )
        else:
            row["founder_univ_pagerank_max"] = np.nan

        # 4. co_alumni_investor_overlap: investors whose team attended same univ as a founder
        if founder_univ_set and investors:
            overlap_count = 0
            for inv_uuid in investors:
                inv_team = investor_people.get(inv_uuid, set())
                for person in inv_team:
                    p_univs = person_univs.get(person, set())
                    if p_univs & founder_univ_set:
                        overlap_count += 1
                        break  # count each investor once
            row["co_alumni_investor_overlap"] = overlap_count
        else:
            row["co_alumni_investor_overlap"] = np.nan if not founders_list else 0

        # 5. founder_alumni_network_size: 2-hop reach through co-alumni graph
        # (founders -> universities -> other people at those universities)
        if founder_univ_set:
            alumni_reach = set()
            for u in founder_univ_set:
                if u in G_univ:
                    alumni_reach |= set(G_univ.neighbors(u))
            # Exclude the founders themselves
            alumni_reach -= set(founders_list)
            row["founder_alumni_network_size"] = len(alumni_reach)
        else:
            row["founder_alumni_network_size"] = np.nan

        # ============================================================
        # JOB / EMPLOYMENT NETWORK FEATURES
        # ============================================================

        # Collect all prior organizations for founders
        founder_org_set = set()
        for f in founders_list:
            founder_org_set |= person_orgs.get(f, set())
        # Exclude the company itself
        founder_org_set.discard(c_uuid)

        # 6. founder_ex_faang_count: founders with prior major tech jobs
        ex_faang = 0
        for f in founders_list:
            f_orgs = person_orgs.get(f, set())
            if f_orgs & major_tech_uuids:
                ex_faang += 1
        row["founder_ex_faang_count"] = ex_faang

        # 7. founder_ex_startup_count: founders with prior jobs at other companies in dataset
        ex_startup = 0
        for f in founders_list:
            f_orgs = person_orgs.get(f, set())
            # Other companies in our dataset (exclude current company)
            if (f_orgs - {c_uuid}) & all_company_org_uuids:
                ex_startup += 1
        row["founder_ex_startup_count"] = ex_startup

        # 8. founder_prior_org_pagerank_max: max PageRank of any org in founders' job history
        if founder_org_set:
            row["founder_prior_org_pagerank_max"] = max(
                org_pr.get(o, 0) for o in founder_org_set
            )
        else:
            row["founder_prior_org_pagerank_max"] = np.nan

        # 9. coworker_investor_overlap: investors whose team worked at same org as a founder
        if founder_org_set and investors:
            coworker_overlap = 0
            for inv_uuid in investors:
                inv_team = investor_people.get(inv_uuid, set())
                for person in inv_team:
                    p_orgs = person_orgs.get(person, set())
                    if p_orgs & founder_org_set:
                        coworker_overlap += 1
                        break  # count each investor once
            row["coworker_investor_overlap"] = coworker_overlap
        else:
            row["coworker_investor_overlap"] = np.nan if not founders_list else 0

        # 10. founder_coworker_network_size: 2-hop reach through co-worker graph
        if founder_org_set:
            coworker_reach = set()
            for o in founder_org_set:
                if o in G_org:
                    coworker_reach |= set(G_org.neighbors(o))
            coworker_reach -= set(founders_list)
            row["founder_coworker_network_size"] = len(coworker_reach)
        else:
            row["founder_coworker_network_size"] = np.nan

        # 11. founder_industry_diversity: distinct orgs across all founders' job histories
        row["founder_industry_diversity"] = len(founder_org_set) if founder_org_set else 0

        # ============================================================
        # CROSS-GRAPH FEATURES
        # ============================================================

        # 12. founder_investor_social_proximity:
        # Min shared-entity count between any founder and any investor team member
        # (through shared universities OR shared employers)
        if founders_list and investors:
            max_shared = 0
            for f in founders_list:
                f_univs = person_univs.get(f, set())
                f_orgs = person_orgs.get(f, set())
                f_entities = f_univs | f_orgs
                if not f_entities:
                    continue
                for inv_uuid in investors:
                    inv_team = investor_people.get(inv_uuid, set())
                    for person in inv_team:
                        p_univs = person_univs.get(person, set())
                        p_orgs = person_orgs.get(person, set())
                        p_entities = p_univs | p_orgs
                        shared = len(f_entities & p_entities)
                        if shared > max_shared:
                            max_shared = shared
            row["founder_investor_social_proximity"] = max_shared
        else:
            row["founder_investor_social_proximity"] = np.nan if not founders_list else 0

        # 13. team_network_reach: union of alumni + coworker 2-hop reach
        alumni_size = row.get("founder_alumni_network_size")
        coworker_size = row.get("founder_coworker_network_size")
        if pd.notna(alumni_size) or pd.notna(coworker_size):
            # Recompute as union (can't just add because of overlap)
            combined_reach = set()
            if founder_univ_set:
                for u in founder_univ_set:
                    if u in G_univ:
                        combined_reach |= set(G_univ.neighbors(u))
            if founder_org_set:
                for o in founder_org_set:
                    if o in G_org:
                        combined_reach |= set(G_org.neighbors(o))
            combined_reach -= set(founders_list)
            row["team_network_reach"] = len(combined_reach)
        else:
            row["team_network_reach"] = np.nan

        records.append(row)

    return pd.DataFrame(records)


def main():
    conn = sqlite3.connect(DB)

    logger.info("Loading data...")
    company_uuids, cf, ci, ct, it, edu, jobs, founders = load_data(conn)
    conn.close()
    logger.info("Companies: %d, Education records: %d, Job records: %d",
                len(company_uuids), len(edu), len(jobs))

    logger.info("Building university graph...")
    G_univ = build_university_graph(edu)
    univ_pr, univ_deg = compute_university_metrics(G_univ, edu)
    logger.info("Universities in graph: %d", len(univ_pr))

    logger.info("Building organization graph...")
    G_org = build_org_graph(jobs)
    org_pr, org_deg = compute_org_metrics(G_org, jobs)
    logger.info("Organizations in graph: %d", len(org_pr))

    logger.info("Computing edu/job features...")
    df = compute_features(
        company_uuids, cf, ci, ct, it, edu, jobs, founders,
        G_univ, G_org, univ_pr, univ_deg, org_pr, org_deg,
    )

    out_path = MODEL_DIR / "edu_job_features.csv"
    df.to_csv(out_path, index=False)
    logger.info("Saved: %s (%d rows, %d columns)", out_path, len(df), len(df.columns))

    # Missing data summary
    logger.info("--- Missing Values ---")
    missing = df.isnull().sum()
    for col in missing[missing > 0].index:
        logger.info("  %s: %d (%.1f%%)", col, missing[col], 100 * missing[col] / len(df))

    # Quick stats
    logger.info("--- Feature Stats ---")
    for col in df.columns:
        if col == "company_uuid":
            continue
        logger.info("  %s: mean=%.3f, median=%.3f, std=%.3f",
                    col, df[col].mean(), df[col].median(), df[col].std())


if __name__ == "__main__":
    main()

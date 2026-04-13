"""
build_graph_data.py — Build PyG HeteroData from Crunchbase graph + features.

Creates a heterogeneous graph with:
  Node types: company, investor, person, university
  Edge types: invested_in, co_invested_in, founded, educated_at,
              executive_of, team_member_of, advisor_to, board_member_of

Company node features come from feature_matrix.csv (V1) and
edu_job_features.csv (V2 extra). Other node types get simple degree-based
features (investor portfolio stats, person role counts, etc.).

Uses the SAME chronological train/val/test split as XGBoost and EvolveGCN
(company's first funding year: <=2020 train, 2021-2022 val, >=2023 test).
Excludes the SAME leaked features.

Outputs:
  models/graphsage/data/hetero_graph.pt       — HeteroData
  models/graphsage/data/company_splits.pt     — train/val/test masks + labels
  models/graphsage/data/company_x_v2_extra.pt — extra V2 edu/job features

Usage:
  python3 models/graphsage/build_graph_data.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "models" / "graphsage" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

EXPORT = ROOT / "data" / "export"
MODEL  = ROOT / "data" / "model"

# Leaked features to exclude (same as XGBoost)
LEAKED = {"funding_total_usd", "log_funding", "num_funding_rounds",
          "company_age_months"}
NON_FEAT = {"company_uuid", "is_success"} | LEAKED


def main():
    print("=" * 60)
    print("BUILD GRAPHSAGE HETERO DATA")
    print("=" * 60)

    # ── Load node data ────────────────────────────────────────────────
    nodes_df = pd.read_csv(EXPORT / "graph_nodes.csv")
    edges_df = pd.read_csv(EXPORT / "graph_edges.csv")

    # Company features from feature_matrix
    fm = pd.read_csv(MODEL / "feature_matrix.csv")
    ej = pd.read_csv(MODEL / "edu_job_features.csv")

    # Labeled companies (in feature_matrix)
    labeled_companies = set(fm["company_uuid"])

    # ── Build node-type id maps ───────────────────────────────────────
    # Merge founder + person into 'person'; investor_org + investor_person
    # into 'investor'
    type_remap = {
        "company": "company",
        "investor_org": "investor",
        "investor_person": "investor",
        "founder": "person",
        "person": "person",
        "university": "university",
    }
    nodes_df["node_type"] = nodes_df["type"].map(type_remap)
    nodes_df = nodes_df.dropna(subset=["node_type"])

    id_maps = {}  # {node_type: {uuid: local_idx}}
    for ntype in ["company", "investor", "person", "university"]:
        uuids = sorted(nodes_df[nodes_df["node_type"] == ntype]["id"].unique())
        id_maps[ntype] = {u: i for i, u in enumerate(uuids)}

    for ntype, m in id_maps.items():
        print(f"  {ntype}: {len(m):,} nodes")

    # ── Build company features ────────────────────────────────────────
    feat_cols = [c for c in fm.columns if c not in NON_FEAT]
    # Convert booleans
    for c in feat_cols:
        if fm[c].dtype == bool:
            fm[c] = fm[c].astype(int)

    company_uuids = sorted(id_maps["company"].keys())
    n_comp = len(company_uuids)

    # Create ordered feature matrix: idx in id_map -> feature row
    fm_idx = fm.set_index("company_uuid")
    company_x = np.zeros((n_comp, len(feat_cols)), dtype=np.float32)
    for uuid, idx in id_maps["company"].items():
        if uuid in fm_idx.index:
            row = fm_idx.loc[uuid, feat_cols]
            company_x[idx] = row.to_numpy(dtype=np.float32, na_value=0.0)
    # Z-score normalize
    mu = company_x.mean(axis=0, keepdims=True)
    std = company_x.std(axis=0, keepdims=True)
    std[std < 1e-6] = 1.0
    company_x = (company_x - mu) / std
    print(f"  company features: {company_x.shape} ({len(feat_cols)} feats)")

    # V2 extra features
    ej_idx = ej.set_index("company_uuid")
    ej_cols = [c for c in ej.columns if c != "company_uuid"]
    company_x_v2_extra = np.zeros((n_comp, len(ej_cols)), dtype=np.float32)
    for uuid, idx in id_maps["company"].items():
        if uuid in ej_idx.index:
            row = ej_idx.loc[uuid, ej_cols]
            company_x_v2_extra[idx] = row.to_numpy(dtype=np.float32, na_value=0.0)
    mu2 = company_x_v2_extra.mean(axis=0, keepdims=True)
    std2 = company_x_v2_extra.std(axis=0, keepdims=True)
    std2[std2 < 1e-6] = 1.0
    company_x_v2_extra = (company_x_v2_extra - mu2) / std2
    print(f"  company V2 extra: {company_x_v2_extra.shape}")

    # ── Build investor features (from portfolio_edges) ────────────────
    pe = pd.read_csv(EXPORT / "portfolio_edges.csv")
    n_inv = len(id_maps["investor"])
    inv_x = np.zeros((n_inv, 4), dtype=np.float32)
    for vc_uuid, g in pe.groupby("vc_uuid"):
        if vc_uuid not in id_maps["investor"]:
            continue
        idx = id_maps["investor"][vc_uuid]
        inv_x[idx, 0] = len(g)                             # total deals
        inv_x[idx, 1] = g["portfolio_company_uuid"].nunique()  # unique companies
        amounts = g["money_raised_usd"].dropna()
        if len(amounts) > 0:
            inv_x[idx, 2] = float(np.log1p(amounts.sum()))
            inv_x[idx, 3] = float(np.log1p(amounts.mean()))
    mu_i = inv_x.mean(0, keepdims=True)
    std_i = inv_x.std(0, keepdims=True); std_i[std_i < 1e-6] = 1.0
    inv_x = (inv_x - mu_i) / std_i
    print(f"  investor features: {inv_x.shape}")

    # ── Person features (degree-based) ────────────────────────────────
    n_per = len(id_maps["person"])
    per_x = np.zeros((n_per, 4), dtype=np.float32)
    # Count edge types per person
    person_edges = edges_df[edges_df["source"].isin(id_maps["person"]) |
                            edges_df["target"].isin(id_maps["person"])]
    for _, row in person_edges.iterrows():
        for col in ["source", "target"]:
            if row[col] in id_maps["person"]:
                idx = id_maps["person"][row[col]]
                if row["type"] == "founded":
                    per_x[idx, 0] += 1
                elif row["type"] == "educated_at":
                    per_x[idx, 1] += 1
                elif row["type"] in ("executive_of", "board_member_of"):
                    per_x[idx, 2] += 1
                else:
                    per_x[idx, 3] += 1
    mu_p = per_x.mean(0, keepdims=True)
    std_p = per_x.std(0, keepdims=True); std_p[std_p < 1e-6] = 1.0
    per_x = (per_x - mu_p) / std_p
    print(f"  person features: {per_x.shape}")

    # ── University features (degree count) ────────────────────────────
    n_uni = len(id_maps["university"])
    uni_x = np.zeros((n_uni, 2), dtype=np.float32)
    edu_edges = edges_df[edges_df["type"] == "educated_at"]
    for _, row in edu_edges.iterrows():
        if row["target"] in id_maps["university"]:
            idx = id_maps["university"][row["target"]]
            uni_x[idx, 0] += 1  # number of alumni
    uni_x[:, 1] = np.log1p(uni_x[:, 0])
    mu_u = uni_x.mean(0, keepdims=True)
    std_u = uni_x.std(0, keepdims=True); std_u[std_u < 1e-6] = 1.0
    uni_x = (uni_x - mu_u) / std_u
    print(f"  university features: {uni_x.shape}")

    # ── Build edge indices ────────────────────────────────────────────
    # Map original edge types to (src_type, edge_name, dst_type)
    edge_type_map = {
        "invested_in":     ("investor", "invested_in",    "company"),
        "co_invested_in":  ("investor", "co_invested_in", "investor"),
        "founded":         ("person",   "founded",        "company"),
        "educated_at":     ("person",   "educated_at",    "university"),
        "executive_of":    ("person",   "executive_of",   "company"),
        "team_member_of":  ("person",   "team_member_of", "company"),
        "advisor_to":      ("person",   "advisor_to",     "company"),
        "board_member_of": ("person",   "board_member_of","company"),
    }

    edge_indices = {}
    for etype_str, (src_type, ename, dst_type) in edge_type_map.items():
        subset = edges_df[edges_df["type"] == etype_str]
        src_map = id_maps[src_type]
        dst_map = id_maps[dst_type]
        srcs, dsts = [], []
        for _, row in subset.iterrows():
            s = src_map.get(row["source"])
            d = dst_map.get(row["target"])
            if s is not None and d is not None:
                srcs.append(s)
                dsts.append(d)
        if srcs:
            key = (src_type, ename, dst_type)
            ei = torch.tensor([srcs, dsts], dtype=torch.long)
            edge_indices[key] = ei
            print(f"  edge ({src_type})-[{ename}]->({dst_type}): {ei.shape[1]:,}")

    # ── Assemble HeteroData ───────────────────────────────────────────
    from torch_geometric.data import HeteroData
    data = HeteroData()
    data["company"].x  = torch.tensor(company_x)
    data["investor"].x = torch.tensor(inv_x)
    data["person"].x   = torch.tensor(per_x)
    data["university"].x = torch.tensor(uni_x)

    for key, ei in edge_indices.items():
        data[key].edge_index = ei
        # Add reverse edges for message passing
        src_t, ename, dst_t = key
        rev_key = (dst_t, f"rev_{ename}", src_t)
        data[rev_key].edge_index = ei.flip(0)

    print(f"\n  HeteroData: {data}")
    torch.save(data, OUT_DIR / "hetero_graph.pt")
    print(f"  Saved hetero_graph.pt")

    # ── Labels + split ────────────────────────────────────────────────
    labels_series = fm.set_index("company_uuid")["is_success"].reindex(company_uuids)
    labels = labels_series.fillna(-1).to_numpy(dtype=np.int64)

    # Same chronological split: first funding year
    fr = pd.read_csv(EXPORT / "funding_rounds.csv",
                     usecols=["company_uuid", "announced_on"])
    fr["announced_on"] = pd.to_datetime(fr["announced_on"], errors="coerce")
    fr = fr.dropna(subset=["announced_on"])
    first_year = fr.groupby("company_uuid")["announced_on"].min().dt.year

    split = np.full(n_comp, -1, dtype=np.int64)
    for uuid, idx in id_maps["company"].items():
        if uuid in first_year.index and labels[idx] != -1:
            yr = int(first_year[uuid])
            if yr <= 2020:
                split[idx] = 0   # train
            elif yr <= 2022:
                split[idx] = 1   # val
            else:
                split[idx] = 2   # test

    tr = (split == 0).sum()
    va = (split == 1).sum()
    te = (split == 2).sum()
    print(f"  Split: train={tr}, val={va}, test={te}")

    torch.save({
        "labels": torch.tensor(labels),
        "split":  torch.tensor(split),
        "company_id_map": id_maps["company"],
        "feat_cols": feat_cols,
    }, OUT_DIR / "company_splits.pt")
    torch.save(torch.tensor(company_x_v2_extra), OUT_DIR / "company_x_v2_extra.pt")
    print(f"  Saved company_splits.pt + company_x_v2_extra.pt")
    print("=" * 60)
    print("DONE")


if __name__ == "__main__":
    main()

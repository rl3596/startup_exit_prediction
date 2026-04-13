"""
train_graphsage.py — GraphSAGE on heterogeneous Crunchbase graph.

Architecture:
  - HeteroConv wrapping SAGEConv for each edge type (incl. reverse edges)
  - 2 message-passing layers → company node embeddings
  - MLP classification head for is_success prediction

Uses the SAME chronological train/val/test split and SAME leaked-feature
exclusions as XGBoost V1/V2, for apples-to-apples comparison.

Research question: "Do learned graph representations add signal beyond
hand-engineered centrality features?"

Usage:
  python3 models/graphsage/train_graphsage.py --version v1  # no edu/job
  python3 models/graphsage/train_graphsage.py --version v2  # with edu/job
  python3 models/graphsage/train_graphsage.py --version all # both V1 and V2
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv, HeteroConv, Linear
from sklearn.metrics import roc_auc_score, average_precision_score

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "models" / "graphsage" / "data"
RESULTS_DIR = ROOT / "models" / "graphsage" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = torch.device("cpu")
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)


# ─────────────────────────── Model ────────────────────────────────────

class HeteroGraphSAGE(nn.Module):
    """
    2-layer heterogeneous GraphSAGE.
    Each layer: HeteroConv of SAGEConv per edge type → ReLU → Dropout.
    Projects all node types to shared hidden_dim first.
    """

    def __init__(self, node_feat_dims, edge_types, hidden_dim=128,
                 out_dim=64, dropout=0.3):
        super().__init__()
        # Per-node-type projection to shared hidden_dim
        self.projections = nn.ModuleDict()
        for ntype, fdim in node_feat_dims.items():
            self.projections[ntype] = Linear(fdim, hidden_dim)

        # Layer 1
        convs1 = {}
        for et in edge_types:
            convs1[et] = SAGEConv((-1, -1), hidden_dim, normalize=True)
        self.conv1 = HeteroConv(convs1, aggr="mean")

        # Layer 2
        convs2 = {}
        for et in edge_types:
            convs2[et] = SAGEConv((-1, -1), out_dim, normalize=True)
        self.conv2 = HeteroConv(convs2, aggr="mean")

        self.dropout = dropout

        # Classification head (applied to company nodes)
        self.cls_head = nn.Sequential(
            nn.Linear(out_dim, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
        )

    def forward(self, x_dict, edge_index_dict):
        # Project each node type to shared dim
        h_dict = {}
        for ntype, x in x_dict.items():
            h_dict[ntype] = F.relu(self.projections[ntype](x))

        # Message passing layer 1
        h_dict = self.conv1(h_dict, edge_index_dict)
        h_dict = {k: F.relu(v) for k, v in h_dict.items()}
        h_dict = {k: F.dropout(v, p=self.dropout, training=self.training)
                  for k, v in h_dict.items()}

        # Message passing layer 2
        h_dict = self.conv2(h_dict, edge_index_dict)

        return h_dict

    def predict(self, h_dict):
        """Return logits for company nodes."""
        return self.cls_head(h_dict["company"]).squeeze(-1)


# ─────────────────────── Training ─────────────────────────────────────

def train_single_version(version, epochs=100, lr=5e-3):
    print(f"\n{'='*60}")
    print(f"GraphSAGE — version={version}")
    print(f"{'='*60}")

    data = torch.load(DATA_DIR / "hetero_graph.pt", weights_only=False)
    meta = torch.load(DATA_DIR / "company_splits.pt", weights_only=False)
    labels = meta["labels"]
    split  = meta["split"]

    # V2: concatenate edu/job features to company node features
    if version == "v2":
        v2_extra = torch.load(DATA_DIR / "company_x_v2_extra.pt")
        data["company"].x = torch.cat([data["company"].x, v2_extra], dim=1)
        print(f"[V2] company features expanded to {data['company'].x.shape[1]}")

    # Node feature dims
    node_feat_dims = {}
    for ntype in data.node_types:
        node_feat_dims[ntype] = data[ntype].x.shape[1]
    print(f"[data] node feature dims: {node_feat_dims}")

    edge_types = list(data.edge_types)
    print(f"[data] {len(edge_types)} edge types")

    train_mask = (split == 0)
    val_mask   = (split == 1)
    test_mask  = (split == 2)
    print(f"[data] train={train_mask.sum()} val={val_mask.sum()} test={test_mask.sum()}")

    train_y = labels[train_mask].float()
    val_y   = labels[val_mask].float()
    test_y  = labels[test_mask].float()

    pos_weight = torch.tensor(
        [max(1.0, (train_y == 0).sum().item() / max(1, (train_y == 1).sum().item()))]
    )
    print(f"[train] pos_weight = {pos_weight.item():.2f}")

    x_dict = {ntype: data[ntype].x for ntype in data.node_types}
    ei_dict = {et: data[et].edge_index for et in data.edge_types}

    model = HeteroGraphSAGE(
        node_feat_dims=node_feat_dims,
        edge_types=edge_types,
        hidden_dim=128,
        out_dim=64,
        dropout=0.3,
    ).to(DEVICE)

    # Initialize lazy parameters with one forward pass
    with torch.no_grad():
        model(x_dict, ei_dict)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[model] parameters: {n_params:,}")

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    best_val_auc = -1
    best_state = None
    patience_counter = 0
    patience = 15

    t0 = time.time()
    for epoch in range(1, epochs + 1):
        model.train()
        opt.zero_grad()
        h_dict = model(x_dict, ei_dict)
        logits = model.predict(h_dict)
        loss = bce(logits[train_mask], train_y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        opt.step()
        scheduler.step()

        if epoch % 5 == 0 or epoch == 1 or epoch == epochs:
            model.eval()
            with torch.no_grad():
                h_dict_e = model(x_dict, ei_dict)
                logits_e = model.predict(h_dict_e)

                v_prob = torch.sigmoid(logits_e[val_mask]).cpu().numpy()
                v_auc = roc_auc_score(val_y.numpy(), v_prob) \
                    if len(set(val_y.tolist())) > 1 else float("nan")

                t_prob = torch.sigmoid(logits_e[test_mask]).cpu().numpy()
                t_auc = roc_auc_score(test_y.numpy(), t_prob) \
                    if len(set(test_y.tolist())) > 1 else float("nan")

                print(f"  ep{epoch:3d} loss={loss.item():.4f} "
                      f"val_auc={v_auc:.4f} test_auc={t_auc:.4f} "
                      f"lr={opt.param_groups[0]['lr']:.5f}")

                if not np.isnan(v_auc) and v_auc > best_val_auc:
                    best_val_auc = v_auc
                    best_state = {k: v.clone() for k, v in model.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 5
                    if patience_counter >= patience * 5:
                        print(f"  Early stopping at epoch {epoch}")
                        break

    elapsed = time.time() - t0
    print(f"[train] {elapsed:.1f}s total")

    # ── Final evaluation ──────────────────────────────────────────────
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        h_dict_f = model(x_dict, ei_dict)
        logits_f = model.predict(h_dict_f)

        # Test metrics
        t_prob = torch.sigmoid(logits_f[test_mask]).cpu().numpy()
        t_y    = test_y.cpu().numpy()
        test_auc = roc_auc_score(t_y, t_prob)
        test_ap  = average_precision_score(t_y, t_prob)

        # Val metrics (for reference)
        v_prob = torch.sigmoid(logits_f[val_mask]).cpu().numpy()
        v_y    = val_y.cpu().numpy()
        val_auc = roc_auc_score(v_y, v_prob)

        # Train metrics (sanity check)
        tr_prob = torch.sigmoid(logits_f[train_mask]).cpu().numpy()
        tr_y    = train_y.cpu().numpy()
        train_auc = roc_auc_score(tr_y, tr_prob)

    print(f"\n[RESULTS — {version.upper()}]")
    print(f"  Train ROC-AUC: {train_auc:.4f}")
    print(f"  Val   ROC-AUC: {val_auc:.4f}")
    print(f"  Test  ROC-AUC: {test_auc:.4f}")
    print(f"  Test  AP:      {test_ap:.4f}")

    results = {
        "model": "GraphSAGE (Heterogeneous)",
        "version": version,
        "node_types": list(node_feat_dims.keys()),
        "node_feat_dims": {k: int(v) for k, v in node_feat_dims.items()},
        "num_edge_types": len(edge_types),
        "num_params": n_params,
        "hidden_dim": 128,
        "out_dim": 64,
        "epochs_run": epoch,
        "train_time_secs": round(elapsed, 1),
        "num_train": int(train_mask.sum()),
        "num_val":   int(val_mask.sum()),
        "num_test":  int(test_mask.sum()),
        "pos_weight": round(pos_weight.item(), 2),
        "train_roc_auc": round(train_auc, 4),
        "val_roc_auc":   round(val_auc, 4),
        "test_roc_auc":  round(test_auc, 4),
        "test_ap":       round(test_ap, 4),
        "best_val_auc":  round(best_val_auc, 4),
    }

    out_path = RESULTS_DIR / f"graphsage_{version}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved -> {out_path}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=["v1", "v2", "all"], default="all")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--lr", type=float, default=5e-3)
    args = ap.parse_args()

    versions = ["v1", "v2"] if args.version == "all" else [args.version]
    all_results = {}

    for v in versions:
        r = train_single_version(v, epochs=args.epochs, lr=args.lr)
        all_results[v] = r

    if len(all_results) == 2:
        print(f"\n{'='*60}")
        print("COMPARISON: V1 vs V2")
        print(f"{'='*60}")
        print(f"{'Metric':<20} {'V1':>10} {'V2':>10} {'Delta':>10}")
        print("-" * 52)
        for metric in ["train_roc_auc", "val_roc_auc", "test_roc_auc", "test_ap"]:
            v1_val = all_results["v1"][metric]
            v2_val = all_results["v2"][metric]
            delta  = v2_val - v1_val
            print(f"  {metric:<18} {v1_val:>10.4f} {v2_val:>10.4f} {delta:>+10.4f}")

        print(f"\nCOMPARISON TO XGBOOST (from prior results):")
        print(f"  XGBoost V1:       test_roc_auc = 0.7854")
        print(f"  XGBoost V2:       test_roc_auc = 0.7999")
        print(f"  GraphSAGE V1:     test_roc_auc = {all_results['v1']['test_roc_auc']:.4f}")
        print(f"  GraphSAGE V2:     test_roc_auc = {all_results['v2']['test_roc_auc']:.4f}")

        comp = {
            "xgboost_v1": 0.7854,
            "xgboost_v2": 0.7999,
            "graphsage_v1": all_results["v1"]["test_roc_auc"],
            "graphsage_v2": all_results["v2"]["test_roc_auc"],
            "evolvegcn_v1": 0.756,
            "evolvegcn_v2": 0.739,
            "tgn_v1": 0.687,
            "tgn_v2": 0.670,
        }
        with open(RESULTS_DIR / "all_models_comparison.json", "w") as f:
            json.dump(comp, f, indent=2)
        print(f"\n  Saved all_models_comparison.json")


if __name__ == "__main__":
    main()

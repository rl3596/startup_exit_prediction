"""
train_model_v2.py — XGBoost with network + education + job features.

Merges feature_matrix.csv (original network + tabular features) with
edu_job_features.csv (education/employment network features), trains
XGBoost, and compares results to the v1 model (network-only).

Usage:
    python train_model_v2.py
"""

import logging
import sys
import json
from pathlib import Path

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import (
    classification_report, roc_auc_score, average_precision_score,
    confusion_matrix, roc_curve, precision_recall_curve,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config

try:
    import xgboost as xgb
    HAS_XGB = True
except (ImportError, Exception):
    HAS_XGB = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("train_model_v2")

MODEL_DIR = config.DATA_DIR / "model"

# Columns that leak the target definition
LEAK_COLS = {
    "company_uuid", "is_success",
    "funding_total_usd", "log_funding",
    "num_funding_rounds", "company_age_months",
}


def load_and_merge():
    """Load original features + edu/job features, merge on company_uuid."""
    df_orig = pd.read_csv(MODEL_DIR / "feature_matrix.csv")
    df_edu = pd.read_csv(MODEL_DIR / "edu_job_features.csv")

    df = df_orig.merge(df_edu, on="company_uuid", how="left")

    # Drop unlabeled
    df = df[df["is_success"].notna()].copy()
    df["is_success"] = df["is_success"].astype(int)

    logger.info("Merged dataset: %d labeled samples (%.1f%% success), %d features",
                len(df), 100 * df["is_success"].mean(), len(df.columns))
    return df


def prepare_features(df, include_edu_job=True):
    """Prepare X, y. If include_edu_job=False, drop edu/job columns for ablation."""
    edu_job_cols = {
        "edu_data_available", "founder_top_univ_count", "founder_univ_degree_avg",
        "founder_univ_pagerank_max", "co_alumni_investor_overlap",
        "founder_alumni_network_size", "founder_ex_faang_count",
        "founder_ex_startup_count", "founder_prior_org_pagerank_max",
        "coworker_investor_overlap", "founder_coworker_network_size",
        "founder_industry_diversity", "founder_investor_social_proximity",
        "team_network_reach",
    }

    drop_cols = LEAK_COLS.copy()
    if not include_edu_job:
        drop_cols |= edu_job_cols

    feature_cols = [c for c in df.columns if c not in drop_cols]
    X = df[feature_cols].copy()
    y = df["is_success"]

    return X, y, feature_cols


def build_model(y_train):
    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    if HAS_XGB:
        logger.info("Using XGBoost (scale_pos_weight=%.2f)", scale_pos_weight)
        return xgb.XGBClassifier(
            objective="binary:logistic",
            eval_metric="auc",
            scale_pos_weight=scale_pos_weight,
            max_depth=6,
            learning_rate=0.1,
            n_estimators=300,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            use_label_encoder=False,
        )
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier
        logger.info("Using HistGradientBoostingClassifier")
        return HistGradientBoostingClassifier(
            max_depth=6, learning_rate=0.1, max_iter=300, random_state=42,
        )


def evaluate_model(X, y, label=""):
    """Train/test split, CV, train, evaluate. Returns metrics dict."""
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42,
    )

    model = build_model(y_train)

    # 5-fold CV
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="roc_auc")
    logger.info("[%s] CV ROC-AUC: %.4f (+/- %.4f)", label, cv_scores.mean(), cv_scores.std())

    # Train final model
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    roc_auc = roc_auc_score(y_test, y_proba)
    pr_auc = average_precision_score(y_test, y_proba)
    report = classification_report(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)

    logger.info("[%s] Test ROC-AUC: %.4f, PR-AUC: %.4f", label, roc_auc, pr_auc)
    logger.info("[%s] Classification Report:\n%s", label, report)

    return {
        "label": label,
        "model": model,
        "cv_mean": cv_scores.mean(),
        "cv_std": cv_scores.std(),
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "report": report,
        "cm": cm,
        "y_test": y_test,
        "y_proba": y_proba,
        "y_pred": y_pred,
        "feature_cols": list(X.columns),
        "X_train": X_train,
        "y_train": y_train,
    }


def plot_comparison_roc(results_list):
    """Plot ROC curves for all models on same chart."""
    fig, ax = plt.subplots(figsize=(8, 6))
    for r in results_list:
        fpr, tpr, _ = roc_curve(r["y_test"], r["y_proba"])
        ax.plot(fpr, tpr, lw=2, label=f'{r["label"]} (AUC = {r["roc_auc"]:.4f})')
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC Curve Comparison")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(MODEL_DIR / "roc_curve_v2_comparison.png", dpi=150)
    plt.close(fig)
    logger.info("ROC comparison saved: %s", MODEL_DIR / "roc_curve_v2_comparison.png")


def plot_comparison_pr(results_list):
    """Plot PR curves for all models on same chart."""
    fig, ax = plt.subplots(figsize=(8, 6))
    for r in results_list:
        precision, recall, _ = precision_recall_curve(r["y_test"], r["y_proba"])
        ax.plot(recall, precision, lw=2, label=f'{r["label"]} (PR-AUC = {r["pr_auc"]:.4f})')
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall Curve Comparison")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(MODEL_DIR / "pr_curve_v2_comparison.png", dpi=150)
    plt.close(fig)
    logger.info("PR comparison saved: %s", MODEL_DIR / "pr_curve_v2_comparison.png")


def plot_feature_importance(model, feature_cols, suffix="v2"):
    """Plot feature importances for a single model."""
    if HAS_XGB:
        importances = model.feature_importances_
    else:
        from sklearn.inspection import permutation_importance
        # Would need X_train, y_train — skip for non-XGB
        return

    top_n = min(30, len(feature_cols))
    idx = np.argsort(importances)[-top_n:]

    fig, ax = plt.subplots(figsize=(10, 9))
    ax.barh(range(len(idx)), importances[idx], align="center")
    ax.set_yticks(range(len(idx)))
    ax.set_yticklabels([feature_cols[i] for i in idx])
    ax.set_xlabel("Feature Importance")
    ax.set_title(f"Top {top_n} Feature Importances (XGBoost {suffix})")
    fig.tight_layout()
    fig.savefig(MODEL_DIR / f"feature_importance_{suffix}.png", dpi=150)
    plt.close(fig)
    logger.info("Feature importance plot saved: %s", MODEL_DIR / f"feature_importance_{suffix}.png")

    # Print ranked
    ranked = sorted(zip(feature_cols, importances), key=lambda x: -x[1])
    logger.info("--- Feature Importance (%s, all) ---", suffix)
    for name, imp in ranked:
        if imp > 0.001:
            logger.info("  %-40s %.4f", name, imp)

    return importances


def save_results(results_list):
    """Save comparison results to text file."""
    results_path = MODEL_DIR / "results_v2.txt"
    with open(results_path, "w") as f:
        f.write("XGBoost Model Comparison — Network vs. Network + Edu/Job Features\n")
        f.write("=" * 70 + "\n\n")

        for r in results_list:
            f.write(f"Model: {r['label']}\n")
            f.write("-" * 40 + "\n")
            f.write(f"  Features:     {len(r['feature_cols'])}\n")
            f.write(f"  CV ROC-AUC:   {r['cv_mean']:.4f} (+/- {r['cv_std']:.4f})\n")
            f.write(f"  Test ROC-AUC: {r['roc_auc']:.4f}\n")
            f.write(f"  Test PR-AUC:  {r['pr_auc']:.4f}\n")
            f.write(f"  Confusion Matrix:\n{r['cm']}\n")
            f.write(f"  Classification Report:\n{r['report']}\n\n")

        # Comparison summary
        f.write("=" * 70 + "\n")
        f.write("COMPARISON SUMMARY\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"{'Model':<35} {'CV AUC':>10} {'Test AUC':>10} {'PR-AUC':>10}\n")
        f.write("-" * 70 + "\n")
        for r in results_list:
            f.write(f"{r['label']:<35} {r['cv_mean']:>10.4f} {r['roc_auc']:>10.4f} {r['pr_auc']:>10.4f}\n")

        if len(results_list) >= 2:
            delta_auc = results_list[1]["roc_auc"] - results_list[0]["roc_auc"]
            delta_pr = results_list[1]["pr_auc"] - results_list[0]["pr_auc"]
            f.write(f"\nImprovement (edu/job features):  ROC-AUC {delta_auc:+.4f},  PR-AUC {delta_pr:+.4f}\n")

    logger.info("Results saved: %s", results_path)

    # Save the full model
    if HAS_XGB and len(results_list) >= 2:
        results_list[1]["model"].save_model(str(MODEL_DIR / "model_v2.json"))
        logger.info("Model saved: %s", MODEL_DIR / "model_v2.json")


def main():
    df = load_and_merge()

    # --- Model 1: Original features only (no edu/job) ---
    logger.info("=" * 60)
    logger.info("MODEL 1: Network + Tabular (no edu/job)")
    logger.info("=" * 60)
    X1, y1, cols1 = prepare_features(df, include_edu_job=False)
    logger.info("Features: %d columns", len(cols1))
    r1 = evaluate_model(X1, y1, label="Network + Tabular")

    # --- Model 2: All features (network + edu/job) ---
    logger.info("=" * 60)
    logger.info("MODEL 2: Network + Tabular + Edu/Job")
    logger.info("=" * 60)
    X2, y2, cols2 = prepare_features(df, include_edu_job=True)
    logger.info("Features: %d columns", len(cols2))
    r2 = evaluate_model(X2, y2, label="Network + Tabular + Edu/Job")

    # --- Plots ---
    plot_comparison_roc([r1, r2])
    plot_comparison_pr([r1, r2])

    # Feature importance for the full model
    if HAS_XGB:
        plot_feature_importance(r2["model"], cols2, suffix="v2_full")

    # --- Save ---
    save_results([r1, r2])

    # --- Summary ---
    logger.info("=" * 60)
    logger.info("COMPARISON SUMMARY")
    logger.info("=" * 60)
    logger.info("%-35s  CV AUC    Test AUC  PR-AUC", "Model")
    logger.info("-" * 60)
    for r in [r1, r2]:
        logger.info("%-35s  %.4f    %.4f    %.4f",
                    r["label"], r["cv_mean"], r["roc_auc"], r["pr_auc"])
    delta = r2["roc_auc"] - r1["roc_auc"]
    logger.info("\nEdu/Job feature improvement: ROC-AUC %+.4f", delta)


if __name__ == "__main__":
    main()

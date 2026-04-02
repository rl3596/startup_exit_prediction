"""
train_model.py — Gradient boosting model for startup success prediction.

Loads feature_matrix.csv, trains a gradient boosting classifier with
stratified split, evaluates (ROC-AUC, classification report, PR-AUC),
and reports feature importances.

Uses XGBoost if available, otherwise falls back to sklearn's
HistGradientBoostingClassifier.

Usage:
    python train_model.py
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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config

# Try to import XGBoost; fall back to sklearn if unavailable
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
logger = logging.getLogger("train_model")

MODEL_DIR = config.DATA_DIR / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Exclude columns that leak the target definition:
# is_success is defined by funding_total_usd + company_age_months thresholds,
# so funding amount, log_funding, and age are circular. num_funding_rounds is
# closely tied to total funding. Keep them out to get honest network signal.
NON_FEATURE_COLS = {
    "company_uuid", "is_success",
    "funding_total_usd", "log_funding",
    "num_funding_rounds", "company_age_months",
}


def load_data():
    df = pd.read_csv(MODEL_DIR / "feature_matrix.csv")
    df = df[df["is_success"].notna()].copy()
    df["is_success"] = df["is_success"].astype(int)
    logger.info("Loaded %d labeled samples (%.1f%% success)",
                len(df), 100 * df["is_success"].mean())
    return df


def prepare_features(df):
    feature_cols = [c for c in df.columns if c not in NON_FEATURE_COLS]
    X = df[feature_cols].copy()
    y = df["is_success"]

    # Fill remaining NaNs with median
    for col in X.columns:
        if X[col].isnull().any():
            X[col] = X[col].fillna(X[col].median())

    return X, y, feature_cols


def build_model(y_train):
    """Build XGBoost if available, else HistGradientBoosting."""
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
        # HistGradientBoosting handles class weight via sample_weight in fit
        logger.info("Using HistGradientBoostingClassifier (XGBoost unavailable)")
        return HistGradientBoostingClassifier(
            max_depth=6,
            learning_rate=0.1,
            max_iter=300,
            random_state=42,
        )


def train_and_evaluate(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42,
    )

    logger.info("Train: %d, Test: %d", len(X_train), len(X_test))

    model = build_model(y_train)

    # 5-fold cross-validation
    logger.info("Running 5-fold stratified CV...")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    if HAS_XGB:
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="roc_auc")
    else:
        # For HistGradientBoosting, apply sample weights for imbalance
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="roc_auc")

    logger.info("CV ROC-AUC: %.4f (+/- %.4f)", cv_scores.mean(), cv_scores.std())

    # Train final model
    if not HAS_XGB:
        # Apply sample weights for class imbalance
        scale = (y_train == 0).sum() / (y_train == 1).sum()
        sample_weight = np.where(y_train == 1, scale, 1.0)
        model.fit(X_train, y_train, sample_weight=sample_weight)
    else:
        model.fit(X_train, y_train)

    # Predictions
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    # Metrics
    roc_auc = roc_auc_score(y_test, y_proba)
    pr_auc = average_precision_score(y_test, y_proba)
    report = classification_report(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)

    logger.info("=" * 50)
    logger.info("TEST SET RESULTS")
    logger.info("=" * 50)
    logger.info("ROC-AUC:  %.4f", roc_auc)
    logger.info("PR-AUC:   %.4f", pr_auc)
    logger.info("Confusion Matrix:\n%s", cm)
    logger.info("Classification Report:\n%s", report)

    return model, X_train, X_test, y_train, y_test, y_proba, cv_scores


def plot_roc_curve(y_test, y_proba, roc_auc):
    fpr, tpr, _ = roc_curve(y_test, y_proba)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(fpr, tpr, lw=2, label=f"Gradient Boosting (AUC = {roc_auc:.4f})")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC Curve - Startup Success Prediction")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(MODEL_DIR / "roc_curve.png", dpi=150)
    plt.close(fig)
    logger.info("ROC curve saved: %s", MODEL_DIR / "roc_curve.png")


def plot_pr_curve(y_test, y_proba, pr_auc):
    precision, recall, _ = precision_recall_curve(y_test, y_proba)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(recall, precision, lw=2, label=f"Gradient Boosting (PR-AUC = {pr_auc:.4f})")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall Curve - Startup Success Prediction")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(MODEL_DIR / "pr_curve.png", dpi=150)
    plt.close(fig)
    logger.info("PR curve saved: %s", MODEL_DIR / "pr_curve.png")


def get_feature_importances(model, X_train, y_train, feature_names):
    """Get feature importances - native for XGBoost, permutation for sklearn."""
    if HAS_XGB:
        return model.feature_importances_
    else:
        logger.info("Computing permutation importances (this may take a moment)...")
        result = permutation_importance(
            model, X_train, y_train, n_repeats=10, random_state=42, scoring="roc_auc"
        )
        return result.importances_mean


def plot_feature_importance(importances, feature_names, top_n=25):
    idx = np.argsort(importances)[-top_n:]

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(range(len(idx)), importances[idx], align="center")
    ax.set_yticks(range(len(idx)))
    ax.set_yticklabels([feature_names[i] for i in idx])
    ax.set_xlabel("Feature Importance")
    ax.set_title(f"Top {top_n} Feature Importances - Gradient Boosting")
    fig.tight_layout()
    fig.savefig(MODEL_DIR / "feature_importance.png", dpi=150)
    plt.close(fig)
    logger.info("Feature importance plot saved: %s", MODEL_DIR / "feature_importance.png")

    # Print ranked
    logger.info("--- Feature Importance (all) ---")
    ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
    for name, imp in ranked:
        if imp > 0.001:
            logger.info("  %-35s %.4f", name, imp)


def save_results(model, cv_scores, y_test, y_proba, y_pred, feature_names, importances):
    roc_auc = roc_auc_score(y_test, y_proba)
    pr_auc = average_precision_score(y_test, y_proba)
    report = classification_report(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)
    model_type = "XGBoost" if HAS_XGB else "HistGradientBoosting"

    results_path = MODEL_DIR / "results.txt"
    with open(results_path, "w") as f:
        f.write(f"{model_type} - Startup Success Prediction Results\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"CV ROC-AUC (5-fold): {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})\n")
        f.write(f"Test ROC-AUC:        {roc_auc:.4f}\n")
        f.write(f"Test PR-AUC:         {pr_auc:.4f}\n\n")
        f.write(f"Confusion Matrix:\n{cm}\n\n")
        f.write(f"Classification Report:\n{report}\n\n")
        f.write("Feature Importances:\n")
        ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
        for name, imp in ranked:
            f.write(f"  {name:35s} {imp:.4f}\n")

    if HAS_XGB:
        model.save_model(str(MODEL_DIR / "model.json"))
    else:
        import pickle
        with open(MODEL_DIR / "model.pkl", "wb") as f:
            pickle.dump(model, f)

    logger.info("Model and results saved to %s", MODEL_DIR)


def main():
    df = load_data()
    X, y, feature_cols = prepare_features(df)

    logger.info("Features: %d columns", len(feature_cols))
    model, X_train, X_test, y_train, y_test, y_proba, cv_scores = train_and_evaluate(X, y)

    y_pred = model.predict(X_test)
    roc_auc = roc_auc_score(y_test, y_proba)
    pr_auc = average_precision_score(y_test, y_proba)

    importances = get_feature_importances(model, X_train, y_train, feature_cols)

    plot_roc_curve(y_test, y_proba, roc_auc)
    plot_pr_curve(y_test, y_proba, pr_auc)
    plot_feature_importance(importances, feature_cols)
    save_results(model, cv_scores, y_test, y_proba, y_pred, feature_cols, importances)


if __name__ == "__main__":
    main()

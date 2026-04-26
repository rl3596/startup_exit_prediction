# Crunchbase AI Startup Pipeline

A data collection and network analysis pipeline for predicting startup exit outcomes using graph-derived features from the Crunchbase API v4.

**Scope**: US-based AI companies founded 2015-2025 with at least 1 funding round.

## Project Goal

Can we predict whether an AI startup will achieve a successful exit (IPO, acquisition, or unicorn valuation) by analyzing the **network structure** of its investor, founder, and co-investment relationships?

## Quick Start

### Prerequisites

- Python 3.13+
- Crunchbase API v4 key (Enterprise tier recommended)

### Setup

```bash
# Clone the repository
git clone https://github.com/rl3596/startup_exit_prediction.git
cd startup_exit_prediction

# Install dependencies
pip install -r requirements.txt

# Set your API key (or edit config.py directly)
export CB_API_KEY="your_api_key_here"
```

### Run the Full Pipeline

```bash
python run_pipeline.py
```

This runs all phases in order: `0 → 1 → 2 → 3 → 7 → 8 → 4 → 5 → 6`.

### Run Specific Phases

```bash
# Run only phases 0 through 2
python run_pipeline.py --phases 0 1 2

# Run export and validation only
python run_pipeline.py --phases 5 6
```

### Sample Mode (for Testing)

Limit data-fetching phases to the first N companies for quick end-to-end testing:

```bash
python run_pipeline.py --phases 2 3 7 4 5 6 --sample 500
```

## Pipeline Phases

| Phase | Name | Description | API Calls | Output |
|-------|------|-------------|-----------|--------|
| **0** | Access Probe | Detects API tier (Basic/Enterprise) and sets rate limit | 7 | Tier info, RPM setting |
| **1** | Discover | Searches for all US AI startups in scope | ~13 pages | 12,348 companies |
| **2** | Company Detail | Fetches per-company cards (funding, IPOs, M&A) and assigns exit labels | ~12,348 | Funding rounds, IPOs, acquisitions, `is_success` label |
| **3** | Investor Network | Builds 1-hop investor profiles + 2-hop VC portfolio edges | ~37,000 | 18,661 investors, 481K portfolio edges |
| **7** | Team Members | Discovers board members, executives, and advisors per company | ~12,348 | 14,102 team links across 6,256 companies |
| **8** | Investor Team | Discovers team members within investor organizations | varies | 66K investor-team links |
| **4** | Founders | Fetches person profiles, education, and employment history | ~93,000 | People, degrees, job history |
| **5** | Export | Flattens SQLite to CSVs and builds the heterogeneous graph | 0 (local) | 11 CSV files + graph JSON/CSV |
| **6** | Validate | Generates a summary statistics and data quality report | 0 (local) | Validation report |

### Phase Execution Order

Phases have dependencies and **must** run in this order:

```
Phase 0 (probe)
  └→ Phase 1 (discover companies)
       └→ Phase 2 (company details + exit labels)
            ├→ Phase 3 (investor network)
            │    └→ Phase 8 (investor org teams)
            └→ Phase 7 (company team members)
                 └→ Phase 4 (all people: education + jobs)
                      └→ Phase 5 (export)
                           └→ Phase 6 (validate)
```

### Phase Details

#### Phase 0: Access Probe
Tests 7 API endpoints to determine your tier (Basic or Enterprise). Enterprise gets 200 RPM; Basic gets 60 RPM. Enterprise is required for education/job data in Phase 4.

#### Phase 1: Discover
Runs a paginated search for US AI companies founded 2015-2025 with >= 1 funding round. Uses the Crunchbase `category_groups` filter with the "Artificial Intelligence (AI)" UUID. Results are stored in the `companies` table.

#### Phase 2: Company Detail
For each company, fetches entity cards: funding rounds, IPOs, acquisitions, founders, and investors. Derives the `is_success` target variable using age-tiered funding thresholds (see below). Stores results across multiple relational tables.

#### Phase 3: Investor Network
For each investor discovered in Phase 2, fetches their profile and full portfolio (2-hop expansion). This creates the `portfolio_edges` table — which investors are co-invested in which companies — forming the core of the investment network.

#### Phase 7: Team Members
For each company, fetches board members, executives (C-suite, VP), and advisors via the `board_members_and_advisors` and `current_employees` cards. Creates `company_team` links with roles.

#### Phase 8: Investor Team
For each investor organization, fetches their internal team (partners, founders, analysts). Creates `investor_team` links. Discovers new people not found through company-side data.

#### Phase 4: Founders (People)
For every person discovered in Phases 2, 7, and 8, fetches education history (degrees, institutions) and employment history (job titles, employers). Requires Enterprise tier for full data; Basic tier skips education/job cards.

#### Phase 5: Export
Exports all SQLite tables to CSV files in `data/export/` and builds a heterogeneous NetworkX graph exported as `graph_nodes.csv` and `graph_edges.csv`.

#### Phase 6: Validate
Produces a validation report with row counts, coverage metrics, null rates, and data quality checks.

## Resume & Checkpoints

Each phase saves progress to a JSON checkpoint file in `data/checkpoints/`. If the pipeline is interrupted (network error, rate limit, crash), simply re-run the same command — already-processed entities are skipped automatically.

```bash
# Safe to re-run: resumes from where it left off
python run_pipeline.py --phases 4 5 6
```

**Important**: Never run two pipeline instances simultaneously. SQLite WAL mode does not support concurrent writes from separate processes.

## Target Variable (`is_success`)

Success is defined by age-tiered funding thresholds (as of Dec 31, 2025):

| Company Age | Funding Threshold |
|-------------|-------------------|
| <= 24 months | >= $5M |
| <= 48 months | >= $25M |
| <= 72 months | >= $60M |
| <= 96 months | >= $100M |
| <= 120 months | >= $140M |

Companies also count as successful if they achieved IPO or unicorn status ($1B+ valuation).

## Filtered Dataset

A filtered subset (companies with >= $1M total funding) is available in `data/export_filtered/`. Run the filter script to regenerate:

```bash
python filter_companies.py
```

This produces 11 CSVs with cascading cleanup (only retaining entities connected to surviving companies). See [`data/export_filtered/DATA_GUIDE.md`](data/export_filtered/DATA_GUIDE.md) for full schema documentation and relationship diagrams.

| Dataset | Companies | Target Distribution |
|---------|----------:|---------------------|
| Full (`data/export/`) | 12,348 | 11.2% success, 88.8% not, 19.5% null |
| Filtered (`data/export_filtered/`) | 6,704 | 16.6% success, 81.7% not, 1.7% null |

## Model Training

After data collection and export, we engineer network features and train models to predict startup success.

### Feature Engineering

```bash
# Build graph-derived features (centrality, PageRank, co-investment)
python models/xgboost/build_features.py

# Build education/employment network features (alumni overlap, social proximity)
python models/xgboost/build_edu_job_features.py
```

This produces two CSVs in `data/model/`:
- `feature_matrix.csv` — 31 network + tabular features (6,704 companies)
- `edu_job_features.csv` — 14 education/employment network features

### Train Models

```bash
# LightGBM (Henry)
jupyter notebook models/henry_lightgbm_model_training.ipynb

# Node2Vec + Logistic Regression / + XGBoost (Lin)
jupyter notebook models/Node2Vec.ipynb
jupyter notebook models/Node2Vec+XGBoost.ipynb

# Random Forest (Leo)
jupyter notebook models/rf_startup_exit.ipynb

# Homogeneous GraphSAGE + Heterogeneous GAT (Carrie)
jupyter notebook models/GNN_phrase2_hetero.ipynb

# Heterogeneous GraphSAGE — chronological split (Ray)
python models/Graphsage/build_graph_data.py
python models/Graphsage/train_graphsage.py --version v1
python models/Graphsage/train_graphsage.py --version v2
```

### Model Results

Two feature sets are evaluated for every model:
- **V1** — 31 network + tabular features (centrality, PageRank, co-investment density, fund types, employees, …)
- **V2** — V1 + 14 education/employment features (alumni overlap, FAANG experience, university PageRank, …) = 45 features

| Model | Author | Features | Test ROC-AUC | Test PR-AUC | Test Accuracy |
|-------|:------:|:--------:|:------------:|:-----------:|:-------------:|
| **LightGBM V1**                  | Henry  | 31 | 0.7854 | 0.5212 | 85.8% |
| **LightGBM V2**                  | Henry  | 45 | 0.7999 | 0.5018 | 84.6% |
| **Node2Vec + LR V1**             | Lin    | 31 + emb | 0.8149 | 0.5500 | 76.4% |
| **Node2Vec + LR V2**             | Lin    | 45 + emb | 0.8152 | 0.5596 | 75.1% |
| **Node2Vec + XGBoost V1**        | Lin    | 31 + emb | 0.8217 | **0.5664** | 82.2% |
| **Node2Vec + XGBoost V2**        | Lin    | 45 + emb | **0.8253** | 0.5628 | 81.4% |
| **Random Forest V1**             | Leo    | 31 | 0.7877 | 0.5047 | — |
| **Random Forest V2**             | Leo    | 45 | 0.7730 | 0.4805 | 75.8% |
| **GraphSAGE (homogeneous) V1**   | Carrie | 31 | 0.8015 | 0.5141 | 73.8% |
| **GraphSAGE (homogeneous) V2**   | Carrie | 45 | 0.7960 | 0.5137 | 73.1% |
| **GAT (heterogeneous) V1**       | Carrie | 31 | 0.7973 | 0.5171 | 76.19% |
| **GAT (heterogeneous) V2**       | Carrie | 45 | 0.7886 | 0.5124 | 76.19% |
| **GraphSAGE (heterogeneous) V1** | Ray    | 31 | 0.7223 | 0.5422 | — (chrono split) |
| **GraphSAGE (heterogeneous) V2** | Ray    | 45 | 0.7325 | 0.5319 | — (chrono split) |

> **Note on splits**: Most models use a random 80/20 stratified split (test n=1,319). Ray's heterogeneous GraphSAGE uses a **chronological** split (train ≤ 2020, val 2021-22, test ≥ 2023, n=2,666) — a strictly harder, more realistic generalization test that explains the lower headline AUC.

**Best overall**: Lin's **Node2Vec + XGBoost** — V2 leads on ROC-AUC (**0.8253**), V1 leads on PR-AUC (**0.5664**).

#### Bonus tasks (Lin's Node2Vec + XGBoost)

In addition to classification, the Node2Vec embedding pipeline supports two extra tasks:

- **Link Prediction** (predicting future investor → company edges)
  - ROC-AUC **0.658**, PR-AUC **0.749**
  - Positive class precision **0.93**, recall **0.27** — the model is highly selective: when it predicts a tie, it is almost always right, but it misses many true ties.
- **Node Ranking** (most influential connector investors)
  - Connector Score = `0.7 × PageRank + 0.3 × Degree Centrality`
  - Top investors learned from the graph structure: Y Combinator, Alumni Ventures, Techstars, Andreessen Horowitz, Sequoia Capital, …

**Key findings**

1. **Network features dominate.** Across every model, the top predictors are graph-derived: `avg_investor_degree`, `company_degree`, `avg_investor_betweenness`, `company_pagerank`, `investor_coinv_density`. Investor connectivity is the single strongest signal of startup success.
2. **Education/job features (V2) add ~+0.5–1.5% AUC for tabular models** (LightGBM, Node2Vec+XGBoost) but are neutral-to-slightly-negative for the GNNs — likely because graph message passing already captures most of the social-network signal that V2 features encode, and ~40% missingness becomes noise on otherwise sparse nodes.
3. **Embedding-based models lead.** Lin's Node2Vec + XGBoost V2 is the top model on both ROC-AUC and PR-AUC, narrowly beating LightGBM V2 and the GNNs — combining unsupervised structural embeddings with a strong tabular classifier outperforms either alone.
4. **GNNs are competitive but not dominant.** Carrie's homogeneous GraphSAGE and heterogeneous GAT both reach ~0.79–0.80 AUC, on par with the tabular ensembles. Ray's heterogeneous GraphSAGE on a chronological split (the realistic deployment scenario) drops to ~0.73 — the honest "deploy in 2024" number.

### All Models

The `models/` directory contains all team members' model implementations:

| Model | File / Folder | Author |
|-------|---------------|--------|
| LightGBM (V1 + V2)                         | `models/henry_lightgbm_model_training.ipynb` | Henry  |
| Node2Vec + Logistic Regression (V1 + V2)   | `models/Node2Vec.ipynb`                      | Lin    |
| Node2Vec + XGBoost (V1 + V2 + Link Pred + Node Ranking) | `models/Node2Vec+XGBoost.ipynb` | Lin    |
| Random Forest (V1 + V2)                    | `models/rf_startup_exit.ipynb`               | Leo    |
| Homogeneous GraphSAGE + Heterogeneous GAT  | `models/GNN_phrase2_hetero.ipynb`            | Carrie |
| Heterogeneous GraphSAGE (V1 + V2)          | `models/Graphsage/`                          | Ray    |
| Logistic Regression                        | `models/weilong_logistic.py`                 | Weilong |
| GNN prototype                              | `models/JP1_GNN_prototype.ipynb`             | JP     |

### Detailed Model Reports

- [`models/Graphsage/GraphSAGE_Results.docx`](models/Graphsage/GraphSAGE_Results.docx) — Heterogeneous GraphSAGE (Ray): architecture, ablation, head-to-head with team models

### Feature Documentation

- [`data/model/FEATURE_GUIDE.md`](data/model/FEATURE_GUIDE.md) — Network + tabular feature descriptions (English)
- [`data/model/FEATURE_GUIDE_CN.md`](data/model/FEATURE_GUIDE_CN.md) — Same in simplified Chinese
- [`data/model/EDU_JOB_FEATURE_GUIDE.md`](data/model/EDU_JOB_FEATURE_GUIDE.md) — Education/employment feature descriptions (English)
- [`data/model/EDU_JOB_FEATURE_GUIDE_CN.md`](data/model/EDU_JOB_FEATURE_GUIDE_CN.md) — Same in simplified Chinese

## Project Structure

```
crunchbase_pipeline/
├── run_pipeline.py          # Main orchestrator (CLI entry point)
├── config.py                # API keys, paths, scope filters
├── filter_companies.py      # Post-processing: filter to $1M+ funded companies
├── requirements.txt         # Python dependencies
├── api/
│   ├── client.py            # HTTP client with rate limiting & retries
│   ├── endpoints.py         # Crunchbase API endpoint wrappers
│   └── access_probe.py      # Phase 0: API tier detection
├── phases/
│   ├── phase1_discover.py   # Company search
│   ├── phase2_company_detail.py  # Company cards + exit labels
│   ├── phase3_investor_network.py  # Investor profiles + portfolios
│   ├── phase4_founders.py   # People: education + jobs
│   ├── phase4b_team.py      # Company team members (Phase 7)
│   ├── phase8_investor_team.py  # Investor org teams
│   └── phase6_validate.py   # Data quality report
├── models/
│   ├── xgboost/
│   │   ├── build_features.py        # Network feature engineering (shared by all models)
│   │   └── build_edu_job_features.py # Edu/job feature engineering (shared by all models)
│   ├── Graphsage/
│   │   ├── build_graph_data.py      # Build heterogeneous PyG graph
│   │   ├── train_graphsage.py       # Heterogeneous GraphSAGE (V1 + V2) — Ray
│   │   ├── results/                 # JSON metrics + training logs
│   │   └── GraphSAGE_Results.docx   # Detailed results report
│   ├── Node2Vec.ipynb                       # Node2Vec + Logistic Regression — Lin
│   ├── Node2Vec+XGBoost.ipynb               # Node2Vec + XGBoost (+ Link Pred + Node Ranking) — Lin
│   ├── GNN_phrase2_hetero.ipynb             # Homogeneous GraphSAGE + Heterogeneous GAT — Carrie
│   ├── henry_lightgbm_model_training.ipynb  # LightGBM — Henry
│   ├── rf_startup_exit.ipynb                # Random Forest — Leo
│   ├── weilong_logistic.py                  # Logistic regression — Weilong
│   └── JP1_GNN_prototype.ipynb              # GNN prototype — JP
├── storage/
│   ├── sqlite_store.py      # SQLite DB operations (upsert, export)
│   ├── checkpoint.py        # JSON checkpoint manager
│   └── graph_builder.py     # NetworkX heterogeneous graph construction
├── data/
│   ├── db/crunchbase.db     # SQLite database (WAL mode)
│   ├── checkpoints/         # Phase checkpoint files (JSON)
│   ├── export/              # Full dataset CSVs + graph files
│   ├── export_filtered/     # Filtered dataset ($1M+ funding) + DATA_GUIDE.md
│   └── model/               # Feature matrices, trained models, results, charts
├── logs/
│   └── pipeline.log         # Runtime log
├── docs/
│   ├── project_pipeline.md  # Detailed project description
│   └── slide_outline.md     # Presentation deck outline
└── preqin/                  # Preqin/WRDS data collection (separate pipeline)
```

## Preqin / WRDS Pipeline

A separate data source using Preqin venture deal data via WRDS. Located in `preqin/` with its own extraction scripts. Produces 7 CSVs (674 companies, deals, fund managers, LPs, fund performance). See the `preqin-data` branch for details.

## Tech Stack

- **Python 3.13** with requests, networkx, pandas, tqdm, scikit-learn, xgboost, matplotlib
- **SQLite** (WAL mode) for persistent storage
- **NetworkX** for heterogeneous graph construction
- **XGBoost / scikit-learn** for ML models
- **Crunchbase API v4** (Enterprise tier, 200 RPM)

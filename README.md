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
# V1: Network + tabular features only (31 features)
python models/xgboost/train_model.py

# V2: Network + tabular + edu/job features (45 features), with V1 comparison
python models/xgboost/train_model_v2.py
```

### Model Results

| Model | Features | Test ROC-AUC | Test PR-AUC | Accuracy |
|-------|:--------:|:------------:|:-----------:|:--------:|
| **XGBoost V1** (network + tabular) | 31 | 0.785 | 0.521 | 85.8% |
| **XGBoost V2** (+ edu/job) | 45 | 0.800 | 0.502 | 84.6% |
| Logistic Lasso | 20 | 0.849 | — | 77.9% |
| LightGBM | — | — | — | — |
| Random Forest | — | — | — | — |
| GNN | — | — | — | — |

**Key finding**: Network features dominate predictions. The top 7 features by importance are all graph-derived (investor degree, company centrality, co-investment density). Investor connectivity is the single strongest predictor of startup success.

### All Models

The `models/` directory contains all team members' model implementations:

| Model | File | Author |
|-------|------|--------|
| XGBoost (V1 + V2) | `models/xgboost/` | Ray |
| Logistic Regression | `models/weilong_logistic.py` | Weilong |
| LightGBM | `models/henry_lightgbm_model_training.ipynb` | Henry |
| Random Forest | `models/rf_startup_exit.ipynb` | — |
| GNN | `models/JP1_GNN_prototype.ipynb` | JP |

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
│   │   ├── build_features.py        # Network feature engineering
│   │   ├── build_edu_job_features.py # Edu/job feature engineering
│   │   ├── train_model.py           # V1 model training
│   │   └── train_model_v2.py        # V2 model training + comparison
│   ├── weilong_logistic.py           # Logistic regression
│   ├── henry_lightgbm_model_training.ipynb  # LightGBM
│   ├── rf_startup_exit.ipynb         # Random Forest
│   └── JP1_GNN_prototype.ipynb       # Graph Neural Network
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

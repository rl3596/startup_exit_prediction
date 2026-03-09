# Predicting Startup Exit Outcomes Using Network Features

## 1. Problem Statement

Can we predict whether an AI startup will achieve a successful exit (IPO, acquisition, or unicorn valuation) by analyzing the **network structure** of its investor, founder, and co-investment relationships?

Traditional approaches use company-level financial features (funding amount, round count). This project augments those with **graph-derived network features** from a heterogeneous startup ecosystem graph.

---

## 2. Data Source

**Crunchbase API v4 (Enterprise tier)**
- Scope: US-based AI companies founded 2015-2025 with at least 1 funding round
- Selection: `category_groups = "Artificial Intelligence (AI)"`, `location = United States`

---

## 3. Pipeline Architecture

```
Phase 0       Phase 1        Phase 2          Phase 3            Phase 4
API Probe --> AI Company --> Company Detail --> Investor Network --> Founder
              Discovery     + Exit Labels      (1-hop + 2-hop)     Profiles
                |               |                    |                |
                v               v                    v                v
           [12,348          [Funding Rounds     [18,661 Investors   [21,017
            companies]       IPOs, M&A           Portfolio Edges     Education
                             Success Labels]     Co-investment]      Employment]
                                    |                    |                |
                                    v                    v                v
                              Phase 5: Export (CSVs + Graph JSON)
                                              |
                                              v
                              Phase 6: Validation Report
```

### Phase Details

| Phase | Purpose | Data Collected | API Calls |
|-------|---------|---------------|-----------|
| **0. Access Probe** | Detect API tier & set rate limit | Tier: Enterprise, 200 RPM | 7 |
| **1. Discover** | Find all US AI startups in scope | 12,348 companies | ~13 pages |
| **2. Detail** | Fetch per-company details + derive exit labels | Funding rounds, IPOs, acquisitions, founders, investors | ~12,348 |
| **3. Investor Network** | Build 1-hop investor profiles + 2-hop VC portfolios | Investor details + portfolio company edges | ~37,000+ |
| **4. Founders** | Fetch founder profiles, education, employment | Degrees, job history | ~21,017 |
| **5. Export** | Flatten to CSVs + build graph | 9 CSV files + graph JSON/CSV | 0 (local) |
| **6. Validate** | Summary statistics & data quality report | Coverage metrics | 0 (local) |

---

## 4. Data Schema

### Relational Tables (SQLite)

```
companies ----< funding_rounds
    |                |
    |----< company_investors >---- investors
    |                |                  |
    |----< company_founders       portfolio_edges (2-hop)
    |          |
    |      founders ----< education
    |          |
    |          +--------< jobs
    |
    +----< ipos
    +----< acquisitions
```

### Key Counts (Current)

| Table | Rows |
|-------|------|
| Companies | 12,348 |
| Funding Rounds | 27,623 |
| Investors | 18,661 |
| Founders | 21,017 |
| Education Records | 17,694 |
| Job Records | 47,130 |
| Portfolio Edges (2-hop) | 481,522 |
| Company-Investor Links | 125,931 |
| Round-Investor Links | 69,739 |

---

## 5. Target Variable: `is_success`

### Definition (Age-Tiered Funding Threshold)

Success is defined relative to company age as of Dec 31, 2025:

| Company Age (months) | Funding Threshold |
|----------------------|-------------------|
| <= 24 | >= $5M |
| <= 48 | >= $25M |
| <= 72 | >= $60M |
| <= 96 | >= $100M |
| <= 120 | >= $140M |

### Label Distribution

| Label | Count | % |
|-------|-------|---|
| Success (`is_success=1`) | 1,116 | 11.2% |
| Not Success (`is_success=0`) | 8,820 | 88.8% |
| Missing Data (NULL) | 2,412 | - |
| **Label Coverage** | **9,936/12,348** | **80.5%** |

### Supplemental Exit Reference

| Exit Type | Count |
|-----------|-------|
| IPO | 47 |
| Unicorn ($1B+ valuation) | 204 |

---

## 6. Heterogeneous Network Graph

### Node Types

| Type | Description | Count |
|------|-------------|-------|
| `company` | AI startup (in-scope) + portfolio companies (2-hop) | 12,348+ |
| `investor_org` | VC firms, corporate VCs, accelerators | ~14,000 |
| `investor_person` | Angel investors, individual investors | ~4,600 |
| `founder` | Company founders | 21,017 |
| `university` | Educational institutions (from founder degrees) | 2,723 |
| **Total** | | **204,055** |

### Edge Types

| Type | Description | Source |
|------|-------------|--------|
| `invested_in` | Investor -> Company | Funding rounds |
| `founded` | Founder -> Company | Org founders card |
| `educated_at` | Founder -> University | Degrees card |
| `co_invested_in` | Investor <-> Investor | Same-round participation |
| **Total** | | **609,243 edges** |

---

## 7. Planned Network Features (Downstream ML)

### Investor Network Features (per company)
- **Investor degree centrality**: How many companies has each investor funded?
- **Investor betweenness**: Does the investor bridge disconnected communities?
- **Co-investor clustering**: How interconnected is the investor syndicate?
- **VC portfolio overlap**: How many portfolio companies do co-investors share?
- **Lead investor experience**: Number of prior exits by lead investors

### Founder Network Features (per company)
- **Founder educational prestige**: University centrality in the founder-university bipartite graph
- **Serial founder indicator**: Founder linked to multiple companies
- **Co-founder network size**: 2-hop reach through shared universities or prior companies

### Structural Features
- **Ego-network density**: Density of the 1-hop subgraph around each company
- **Community membership**: Louvain/Leiden community detection labels
- **PageRank**: Recursive importance score in the investor-company graph

---

## 8. Technical Implementation

### Resilience & Resumability
- **Checkpoint system**: JSON-based per-phase checkpoints. Pipeline resumes from last successful entity on restart.
- **Rate limiting**: Token-bucket limiter respects API tier (200 RPM Enterprise).
- **Error handling**: Transient errors retry with exponential backoff. 403s caught per-entity without aborting. Failed entities skipped and retried on re-run.
- **Data integrity**: SQLite WAL mode for safe concurrent reads. Upsert semantics prevent duplicates.

### Stack
- **Language**: Python 3.13
- **Storage**: SQLite (WAL mode) + CSV + JSON export
- **Graph**: NetworkX (construction), exportable to any GNN framework
- **API Client**: requests + urllib3 retry adapter
- **Dependencies**: requests, tqdm, networkx, pandas

---

## 9. Project Timeline

```
Week 1: Data Collection Pipeline (Phases 0-6)
  - API integration, schema design, checkpoint system
  - Collect 12,348 companies, 18,661 investors, 21,017 founders

Week 2: Feature Engineering
  - Extract network features from heterogeneous graph
  - Combine with company-level financial features

Week 3: Model Training & Evaluation
  - Baseline: Logistic Regression / XGBoost on financial features only
  - Network-enhanced: Add graph features
  - Compare: Does network structure improve prediction?
  - Evaluation: AUC-ROC, Precision-Recall (imbalanced classes)

Week 4: Analysis & Presentation
  - Feature importance analysis
  - Network visualization of high-success clusters
  - Final report and presentation
```

---

## 10. Expected Outcomes

1. **Dataset**: A curated, graph-structured dataset of 12,348 US AI startups with investor/founder network data
2. **Model**: A predictive model for startup success incorporating network features
3. **Insight**: Quantified improvement in prediction when adding network structure vs. financial features alone
4. **Visualization**: Network maps showing investor clusters and success patterns

# Feature Matrix Guide

**File**: `feature_matrix.csv`
**Rows**: 6,704 companies (US AI startups, funding >= $1M)
**Columns**: 37 (1 ID + 1 target + 35 features)

## Identifier & Target

| Column | Type | Description |
|--------|------|-------------|
| `company_uuid` | ID | Unique company identifier. Not used as a feature. |
| `is_success` | Target (0/1/null) | ML target variable. 1 = successful exit (IPO, acquisition, unicorn, or met age-tiered funding threshold). 0 = not successful. Null = insufficient data to label. |

## Network Features (Graph-Derived)

These features are computed from a **bipartite investor-company graph** (22,807 nodes, 47,512 edges) and a **co-investment graph** (15,766 investor nodes, 173,986 edges where two investors share an edge if they participated in the same funding round).

### Company-Level Centrality

| Column | Type | Description |
|--------|------|-------------|
| `company_degree` | int | Number of distinct investors that funded this company. Higher degree = more investor connections. Directly measures how "popular" a company is in the investment network. |
| `company_degree_centrality` | float | Normalized degree centrality of the company in the bipartite graph. Same information as `company_degree` but scaled to [0, 1] relative to the total number of possible connections. |
| `company_pagerank` | float | PageRank score of the company in the bipartite investor-company graph (damping factor = 0.85). Measures recursive importance: a company scores higher when funded by investors who themselves fund many important companies. Captures "prestige" beyond raw investor count. |
| `company_betweenness` | float | Approximate betweenness centrality (k=500 random pivots). Measures how often this company lies on the shortest path between pairs of other nodes. High betweenness = the company is a bridge connecting otherwise separate investor communities. |

### Investor-Level Aggregates (Per Company)

For each company, we look at all its investors and aggregate their individual network metrics.

| Column | Type | Description |
|--------|------|-------------|
| `avg_investor_degree` | float | Mean degree of the company's investors in the bipartite graph. Each investor's degree = number of companies they've funded. High value means the company's investors are, on average, highly active across many portfolio companies. **Top predictive feature in the model.** |
| `max_investor_degree` | float | Maximum degree among the company's investors. Captures whether the company has at least one "super-connector" VC with a very large portfolio. |
| `avg_investor_pagerank` | float | Mean PageRank of the company's investors. Measures the average "prestige" of the investor syndicate — are the investors themselves well-connected to important companies? |
| `max_investor_pagerank` | float | Maximum PageRank among the company's investors. Captures the single most prestigious/influential investor backing the company. |
| `avg_investor_betweenness` | float | Mean betweenness centrality of the company's investors. High value = the company's investors tend to bridge different communities in the investment network, potentially giving the company access to diverse resources. |

### Co-Investment / Syndicate Features

| Column | Type | Description |
|--------|------|-------------|
| `investor_clustering_coeff` | float | Mean local clustering coefficient of the company's investors in the co-investment graph (weighted by shared rounds). Measures how often the company's investors co-invest with each other in general. High value = the investors form a tight syndicate that frequently works together. |
| `investor_coinv_density` | float | Edge density of the subgraph induced by the company's investors in the co-investment graph. For a company with N investors, this is the fraction of all possible investor-investor pairs that have actually co-invested. 1.0 = every pair of investors has co-invested before; 0.0 = none have. Measures syndicate cohesion specific to this company's investor group. |
| `num_lead_investors` | int | Number of distinct lead investors across all of the company's funding rounds (from `round_investors.is_lead`). Lead investors typically negotiate terms and conduct deeper due diligence. |

## Tabular Features (Non-Graph)

### Company Financials

| Column | Type | Description |
|--------|------|-------------|
| `funding_total_usd` | float | Total funding raised in USD. **Excluded from model training** because `is_success` is partly defined by funding thresholds — including it would be data leakage. Retained in the CSV for reference. |
| `log_funding` | float | `log(1 + funding_total_usd)`. **Excluded from model training** for the same leakage reason. |
| `num_funding_rounds` | int | Total number of funding rounds the company has raised. **Excluded from model training** — closely correlated with total funding, which defines the target. |
| `employees_ordinal` | int (1-9) | Company size ordinal encoding: 1 = 1-10 employees, 2 = 11-50, 3 = 51-100, 4 = 101-250, 5 = 251-500, 6 = 501-1000, 7 = 1001-5000, 8 = 5001-10000, 9 = 10001+. Null if undisclosed (~0.5% missing). |
| `company_age_months` | float | Company age in months as of Dec 31, 2025, computed from `founded_on`. **Excluded from model training** — directly used in the age-tiered target definition. |

### Last Funding Type (One-Hot Encoded)

The most recent funding round type, one-hot encoded. The top 8 categories are retained; rare types are grouped into `fund_type_other`.

| Column | Type | Description |
|--------|------|-------------|
| `fund_type_pre_seed` | 0/1 | Last round was pre-seed. Very early stage, typically < $2M. |
| `fund_type_seed` | 0/1 | Last round was seed. Early stage, typically $1-5M. |
| `fund_type_series_a` | 0/1 | Last round was Series A. First institutional round, typically $5-20M. |
| `fund_type_series_b` | 0/1 | Last round was Series B. Growth stage, typically $15-50M. |
| `fund_type_series_c` | 0/1 | Last round was Series C. Late growth, typically $30-100M+. |
| `fund_type_series_unknown` | 0/1 | Last round was a series round with unknown letter. |
| `fund_type_grant` | 0/1 | Last round was a grant (non-dilutive funding). |
| `fund_type_non_equity_assistance` | 0/1 | Last round was non-equity assistance (e.g., accelerator program). |
| `fund_type_other` | 0/1 | Last round was a type not in the top 8 (e.g., convertible note, debt, secondary). |

### Founder Features

| Column | Type | Description |
|--------|------|-------------|
| `num_founders` | int | Number of founders listed for the company in Crunchbase. |
| `founder_has_phd` | 0/1 | 1 if any founder holds a PhD or doctoral degree. Proxy for deep technical expertise. Based on pattern matching on `education.degree_type` (matches "PhD", "Ph.D", "Doctor"). ~44% of founders have missing education data, so this is a lower bound. |
| `founder_has_mba` | 0/1 | 1 if any founder holds an MBA degree. Proxy for business/management training. Same caveat about missing education data. |
| `max_founder_prior_jobs` | int | Maximum number of prior jobs across all founders (from `jobs` table). Proxy for the most experienced founder — serial entrepreneurs or industry veterans tend to have longer job histories. |
| `avg_founder_prior_jobs` | float | Average number of prior jobs across all founders. Measures overall team experience level. |

### Team Composition

| Column | Type | Description |
|--------|------|-------------|
| `team_size` | int | Total number of people linked to this company via `company_team` (executives, board, advisors). Does not include all employees — only those with Crunchbase profiles. |
| `c_suite_count` | int | Number of C-suite executives (CEO, CTO, CFO, COO, etc.) linked to the company. |
| `board_count` | int | Number of board members. Can indicate governance maturity or investor involvement. |
| `advisor_count` | int | Number of formal advisors. In the baseline logistic regression, high advisor count was a negative signal (weight -0.27). |

## Data Leakage Notes

Three features are **excluded from model training** but kept in the CSV:

| Excluded Feature | Reason |
|-----------------|--------|
| `funding_total_usd` / `log_funding` | `is_success` is defined by age-tiered funding thresholds. Including funding amount is circular. |
| `num_funding_rounds` | Highly correlated with total funding. |
| `company_age_months` | Directly used in the age-tier calculation for `is_success`. |

When these leaked features were included, the model achieved ROC-AUC = 0.997 (99.7%), confirming the leakage. After removal, the honest ROC-AUC is 0.774 — driven primarily by network features.

## Missing Values

| Column | Missing | % |
|--------|--------:|---:|
| `employees_ordinal` | 32 | 0.5% |
| `is_success` | 111 | 1.7% |

All other columns have zero missing values. The 111 companies with null `is_success` are excluded during model training.

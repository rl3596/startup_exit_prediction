# Education & Employment Network Feature Guide

**File**: `edu_job_features.csv`
**Rows**: 6,704 companies (US AI startups, funding >= $1M)
**Columns**: 15 (1 ID + 14 features)

## Data Sources

These features are derived from two bipartite graphs:

1. **Person-University graph** (52,554 nodes, 68,773 edges) — built from the `education` table. Each edge connects a person to a university they attended.
2. **Person-Organization graph** (135,965 nodes, 190,461 edges) — built from the `jobs` table. Each edge connects a person to an organization they worked at.

University and organization importance are measured via **PageRank** and **degree** computed on these bipartite graphs.

## Identifier

| Column | Type | Description |
|--------|------|-------------|
| `company_uuid` | ID | Unique company identifier. Join key to `feature_matrix.csv`. |

## Data Availability Flag

| Column | Type | Description |
|--------|------|-------------|
| `edu_data_available` | 0/1 | 1 if at least one founder has education data fetched from the API. When 0, education-derived features are less reliable (may undercount). Useful as a control variable in models. |

## Education Network Features

| Column | Type | Missing | Description |
|--------|------|--------:|-------------|
| `founder_top_univ_count` | int | 0% | Number of founders who attended a **top-20 university** (ranked by node degree in the person-university graph — i.e., universities with the most founders/people in the dataset). Captures elite educational background of the founding team. |
| `founder_univ_degree_avg` | float | 35.2% | Average degree of all universities attended by founders. Degree = number of people in the dataset who attended that university. High value means founders attended large, well-connected schools with many alumni in the startup ecosystem. Null when no founder has education data. |
| `founder_univ_pagerank_max` | float | 35.2% | Maximum PageRank score among all universities attended by any founder. PageRank captures recursive importance: a university scores higher when its alumni are themselves connected to many other important nodes. Represents the most "prestigious" (network-wise) school in the founding team. Null when no founder has education data. |
| `co_alumni_investor_overlap` | int | 10.8% | Number of the company's investors whose team members attended the **same university** as at least one founder. Measures **warm connections through educational ties** — did the founder likely know their investors through school networks? Each investor is counted at most once. Null when the company has no founders listed. |
| `founder_alumni_network_size` | int | 35.2% | Total number of other people in the dataset who attended the same universities as the company's founders (2-hop reach: founder -> university -> other alumni). Measures the **social capital** of the founding team through educational networks. Excludes the founders themselves. Null when no founder has education data. |

## Employment Network Features

| Column | Type | Missing | Description |
|--------|------|--------:|-------------|
| `founder_ex_faang_count` | int | 0% | Number of founders with prior employment at a **major tech company** (Google, Meta, Amazon, Apple, Microsoft, Netflix, Nvidia, Tesla, OpenAI, Stripe, Uber, Airbnb, and ~20 others). Proxy for talent quality and brand-name experience. |
| `founder_ex_startup_count` | int | 0% | Number of founders with prior employment at **another company in the dataset** (i.e., another US AI startup). Captures serial entrepreneur or startup ecosystem experience — founders who have been through the startup lifecycle before. |
| `founder_prior_org_pagerank_max` | float | 38.3% | Maximum PageRank of any organization in the founders' combined job history (computed on the person-organization bipartite graph). Captures whether founders previously worked at a highly connected, important organization in the employment network. Null when no founder has job data. |
| `coworker_investor_overlap` | int | 10.8% | Number of the company's investors whose team members previously **worked at the same organization** as at least one founder. Measures **warm connections through professional ties** — did the founder potentially know their investors through past employers? Each investor counted at most once. Null when the company has no founders listed. |
| `founder_coworker_network_size` | int | 38.3% | Total number of other people in the dataset who worked at the same organizations as the company's founders (2-hop reach: founder -> employer -> other employees). Measures professional network breadth. Excludes founders themselves. Null when no founder has job data. |
| `founder_industry_diversity` | int | 0% | Number of distinct organizations across all founders' combined job histories (excluding the current company). Measures diversity of professional backgrounds. Higher = founders came from many different companies rather than all from the same employer. |

## Cross-Graph Features (Education + Employment Combined)

| Column | Type | Missing | Description |
|--------|------|--------:|-------------|
| `founder_investor_social_proximity` | int | 10.8% | Maximum number of **shared entities** (universities + employers) between any founder and any investor team member. If a founder and an investor partner both attended Stanford and both worked at Google, the shared count is 2. Captures the strength of the strongest social connection between the founding team and their investors. 0 = no shared background found. Null when no founders listed. |
| `team_network_reach` | int | 23.6% | Total number of unique people reachable through the **union** of alumni and co-worker networks (2-hop from founders through both universities and employers). Measures the combined social capital of the founding team across all relationship types. This is not simply the sum of alumni + coworker sizes because the same person can be reached through both paths. Null when no founder has either education or job data. |

## Missing Data Notes

Missing values occur when founder education or job data was not available from the API (~35-40% of people). The pattern is:

| Missing Pattern | Cause | Affected Columns |
|----------------|-------|------------------|
| 35.2% | No education records for any founder | `founder_univ_degree_avg`, `founder_univ_pagerank_max`, `founder_alumni_network_size` |
| 38.3% | No job records for any founder | `founder_prior_org_pagerank_max`, `founder_coworker_network_size` |
| 23.6% | No education AND no job data | `team_network_reach` |
| 10.8% | No founders listed at all | `co_alumni_investor_overlap`, `coworker_investor_overlap`, `founder_investor_social_proximity` |

For tree-based models (XGBoost, LightGBM, HistGradientBoosting), NaN values are handled natively — no imputation needed. For other models, consider median imputation plus the `edu_data_available` flag as a control.

## Model Impact

When added to the base network + tabular features (31 columns), these 14 edu/job features produced:

| Model | Features | CV ROC-AUC | Test ROC-AUC |
|-------|----------|------------|--------------|
| Network + Tabular only | 31 | 0.7939 | 0.7854 |
| Network + Tabular + Edu/Job | 45 | 0.7928 | 0.7999 |

The +0.015 ROC-AUC improvement is modest, likely due to the high missing data rate. The features capture social capital and warm connections that are not visible in the investment graph alone.

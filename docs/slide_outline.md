# Slide Deck Outline: Predicting Startup Exits with Network Features

---

## Slide 1: Title

**Predicting AI Startup Exit Outcomes Using Investor & Founder Network Features**

- Subtitle: A Graph-Based Approach to Startup Success Prediction
- Your Name | Date | Course/Department

---

## Slide 2: Motivation

**Why Network Features?**

- Traditional startup prediction uses financial data: funding amount, round count, revenue
- But startups don't exist in isolation -- they're embedded in networks:
  - Who invested? (signal of quality)
  - Who co-invested? (syndicate strength)
  - Where did founders study? (talent pipeline)
  - What else did the VC fund? (portfolio strategy)
- **Research question:** Does network structure improve exit prediction beyond financial features?

---

## Slide 3: Data Source & Scope

**Crunchbase API v4 (Enterprise Tier)**

| Parameter | Value |
|-----------|-------|
| Geography | United States |
| Industry | Artificial Intelligence (AI) |
| Founded | 2015 - 2025 |
| Min funding rounds | 1 |
| **Total companies** | **12,348** |

---

## Slide 4: Pipeline Overview (Diagram)

```
[API Probe] -> [Discover 12K Companies] -> [Fetch Details + Labels]
                                                    |
                                           [Investor Network]
                                           [18,661 investors]
                                           [459K+ portfolio edges]
                                                    |
                                           [Founder Profiles]
                                           [21,017 founders]
                                           [Education + Jobs]
                                                    |
                                           [Export Graph + CSVs]
                                                    |
                                           [Validate & Report]
```

- Fully resumable with checkpoints
- Rate-limited API access (200 req/min)
- Error-tolerant: retries on failure

---

## Slide 5: Target Variable

**is_success: Age-Tiered Funding Threshold**

| Age (months) | Threshold |
|-------------|-----------|
| <= 24 months | >= $5M |
| <= 48 months | >= $25M |
| <= 72 months | >= $60M |
| <= 96 months | >= $100M |
| <= 120 months | >= $140M |

**Distribution:** 1,116 success (11.2%) vs 8,820 not-success (88.8%)

- Supplemental: 47 IPOs, 204 unicorns
- 80.5% label coverage

---

## Slide 6: Network Graph Structure

**Heterogeneous Graph with 5 Node Types and 4 Edge Types**

| Nodes | Edges |
|-------|-------|
| Company (12K+) | invested_in (Investor -> Company) |
| Investor Org (~14K) | founded (Founder -> Company) |
| Investor Person (~4.6K) | educated_at (Founder -> University) |
| Founder (21K) | co_invested_in (Investor <-> Investor) |
| University (TBD) | |

- 2-hop investor network: VC portfolios reveal indirect competition/synergy

---

## Slide 7: Network Features (Planned)

**Investor Features:**
- Degree centrality, betweenness centrality
- Co-investor clustering coefficient
- Lead investor prior exit count
- VC portfolio overlap score

**Founder Features:**
- University prestige (centrality in founder-university graph)
- Serial founder indicator
- Co-founder network reach

**Structural Features:**
- Ego-network density
- Community detection labels
- Company PageRank

---

## Slide 8: Methodology

**Baseline vs. Network-Enhanced Comparison**

```
Financial Features Only          Financial + Network Features
(funding, rounds, age)   vs.    (+ centrality, clustering,
                                  PageRank, community)
        |                                |
   [XGBoost / LR]                 [XGBoost / LR]
        |                                |
   AUC-ROC: ???                   AUC-ROC: ???
```

- Evaluation: AUC-ROC, PR-AUC (class imbalance), F1
- Cross-validation with stratified splits
- Feature importance analysis via SHAP

---

## Slide 9: Key Data Statistics

| Metric | Value |
|--------|-------|
| Companies collected | 12,348 |
| Funding rounds | 27,623 |
| Unique investors | 18,661 |
| Founders | 21,017 |
| 2-hop portfolio edges | 459,660+ |
| Company-investor links | 125,931 |
| IPOs in dataset | 47 |
| Unicorns in dataset | 204 |

---

## Slide 10: Timeline & Current Status

| Week | Task | Status |
|------|------|--------|
| 1 | Data pipeline (collection) | In Progress |
| 2 | Feature engineering | Upcoming |
| 3 | Model training & evaluation | Upcoming |
| 4 | Analysis & final presentation | Upcoming |

**Current pipeline progress:**
- Phases 0-2: Complete (companies + details)
- Phase 3: Investor network ~61% done
- Phases 4-6: Queued

---

## Slide 11: Expected Contributions

1. **Curated Dataset**: 12,348 US AI startups with full investor/founder graph
2. **Empirical Evidence**: Quantified impact of network features on exit prediction
3. **Feature Analysis**: Which network properties matter most for startup success?
4. **Practical Insight**: Can investor syndicate structure predict outcomes?

---

## Slide 12: Questions

**Thank You**

- GitHub: [repo link]
- Data: Crunchbase API v4
- Tools: Python, SQLite, NetworkX, XGBoost

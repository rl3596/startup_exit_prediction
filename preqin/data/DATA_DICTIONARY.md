# Preqin Data Dictionary

Exported from WRDS (Preqin database) on 2026-03-09.
Source: Preqin via Wharton Research Data Services (WRDS), PostgreSQL.
Scope: US-based AI companies founded 2015-2025 with at least one funded VC deal.

Filter: `portfolio_company_country = 'US'`, `year_established BETWEEN 2015 AND 2025`,
`deal_financing_size_usd > 0`, `industry_verticals LIKE '%Artificial Intelligence%'`

---

## companies.csv (674 rows)

Unique portfolio companies extracted from VC deals. Each row is one company.

| Column | Type | Description |
|--------|------|-------------|
| `portfolio_company_id` | FLOAT | Preqin unique company identifier. Primary key. |
| `portfolio_company_name` | TEXT | Company name. |
| `portfolio_company_website` | TEXT | Company website URL. May be null. |
| `portfolio_company_state` | TEXT | US state (2-letter code, e.g. `CA`, `NY`). |
| `portfolio_company_country` | TEXT | Country code (all `US` in this dataset). |
| `portfolio_company_region` | TEXT | Geographic region (all `North America`). |
| `year_established` | FLOAT | Year the company was founded (e.g. `2018.0`). |
| `firm_about` | TEXT | Company description from Preqin. May be truncated. |
| `firm_othernames` | TEXT | Alternative company names / aliases. |
| `industry_classification` | TEXT | High-level sector (e.g. `Information Technology`, `Healthcare`). |
| `primary_industry` | TEXT | Primary industry (e.g. `Software`, `Healthcare IT`). |
| `sub_industries` | TEXT | Comma-separated sub-industries. |
| `industry_verticals` | TEXT | Comma-separated verticals (all contain `Artificial Intelligence`). |
| `industry_subverticals` | TEXT | Sub-verticals. Often null. |
| `deal_count` | INT | Number of funded VC rounds in Preqin. |
| `total_funding_usd` | FLOAT | Sum of `deal_financing_size_usd` across all rounds (in millions USD). |
| `first_deal_date` | DATE | Date of first known funded round. |
| `last_deal_date` | DATE | Date of most recent funded round. |
| `last_stage` | TEXT | Stage of the most recent round (e.g. `Series A`, `Seed`). |
| `preqin_total_known_funding_usd` | FLOAT | Preqin's own total known funding figure (in millions USD). |

**Note:** All USD amounts in Preqin are in **millions USD** (not raw USD like Crunchbase).

---

## deals.csv (1,304 rows)

All VC funding rounds for the 674 companies. One row per deal.

| Column | Type | Description |
|--------|------|-------------|
| `ventureid` | FLOAT | Preqin unique deal identifier. Primary key. |
| `portfolio_company_id` | FLOAT | Foreign key to `companies.csv`. |
| `portfolio_company_name` | TEXT | Company name (denormalized). |
| `portfolio_company_website` | TEXT | Company website. |
| `portfolio_company_state` | TEXT | US state code. |
| `portfolio_company_country` | TEXT | Country (`US`). |
| `portfolio_company_region` | TEXT | Region (`North America`). |
| `year_established` | FLOAT | Founding year. |
| `firm_about` | TEXT | Company description. |
| `firm_othernames` | TEXT | Alternative names. |
| `industry_classification` | TEXT | High-level sector. |
| `primary_industry` | TEXT | Primary industry. |
| `sub_industries` | TEXT | Comma-separated sub-industries. |
| `industry_verticals` | TEXT | Comma-separated verticals. |
| `industry_subverticals` | TEXT | Sub-verticals. |
| `stage` | TEXT | Deal stage (e.g. `Seed`, `Series A`, `Series B/Round 2`, `Venture Debt`). |
| `deal_date` | DATE | Date the deal was announced/completed. |
| `deal_status` | TEXT | Deal status (e.g. `Completed`, `Announced`). |
| `investment_status` | TEXT | Investment status (e.g. `Unrealised`, `Realised`). |
| `currency` | TEXT | Original currency of the deal (e.g. `USD`). |
| `deal_financing_size` | FLOAT | Deal size in original currency (millions). |
| `deal_financing_size_usd` | FLOAT | Deal size in millions USD. |
| `deal_financing_size_eur` | FLOAT | Deal size in millions EUR. |
| `total_known_funding_usd` | FLOAT | Total known funding for the company (millions USD). |
| `total_known_funding_eur` | FLOAT | Total known funding for the company (millions EUR). |

---

## managers.csv (21,587 rows)

Fund managers (General Partners / VC firms). Includes all VC-strategy firms and AI-focused managers globally.

| Column | Type | Description |
|--------|------|-------------|
| `firm_id` | FLOAT | Preqin unique firm identifier. Primary key. |
| `firmname` | TEXT | Firm name (e.g. `Sequoia Capital`, `Andreessen Horowitz`). |
| `firmtype` | TEXT | Firm type (e.g. `Fund Manager`, `Bank`). |
| `sourceofcapital` | TEXT | Capital source (e.g. `Private Equity Funds`). |
| `mainfirmstrategy` | TEXT | Primary strategy (e.g. `Venture Capital`, `Buyout`). |
| `firmcity` | TEXT | City of headquarters. |
| `firmstate` | TEXT | State (if US). |
| `firmcountry` | TEXT | Country. |
| `about` | TEXT | Firm description. |
| `established` | FLOAT | Year the firm was established. |
| `staffcounttotal` | FLOAT | Total staff count. |
| `staffcountmanagement` | FLOAT | Management staff count. |
| `staffcountinvestment` | FLOAT | Investment staff count. |
| `firmtrait` | TEXT | Firm trait classification. |
| `profilecurrency` | TEXT | Profile currency (e.g. `USD`). |
| `totalfundsraised10yearsmn` | FLOAT | Total funds raised in last 10 years (millions). |
| `investorcoinvestmentrights` | TEXT | Whether LP co-investment is offered (`Yes`/`No`). |
| `geofocus` | TEXT | Semicolon-separated geographic focus areas. |
| `industryfocus` | TEXT | Semicolon-separated industry focus areas. |
| `isminorityowned` | TEXT | Whether the firm is minority-owned (`TRUE`/`FALSE`). |
| `iswomenowned` | TEXT | Whether the firm is women-owned (`TRUE`/`FALSE`). |
| `listed_firm` | TEXT | Whether the firm is publicly listed (`TRUE`/`FALSE`). |

---

## funds.csv (21,939 rows)

VC funds with vintage year >= 2010.

| Column | Type | Description |
|--------|------|-------------|
| `fund_id` | FLOAT | Preqin unique fund identifier. Primary key. |
| `firm_id` | FLOAT | Foreign key to `managers.csv` (the GP managing this fund). |
| `fund_name` | TEXT | Fund name. |
| `firm_name` | TEXT | Managing firm name (denormalized). |
| `vintage` | FLOAT | Fund vintage year (e.g. `2020.0`). |
| `fund_type` | TEXT | Fund type (e.g. `Venture Capital (General)`, `Venture Capital - Early Stage`). |
| `local_currency` | TEXT | Fund's local currency. |
| `target_size_usd` | FLOAT | Target fund size (millions USD). |
| `final_size_usd` | FLOAT | Final fund size at close (millions USD). |
| `fund_status` | TEXT | Status (e.g. `Closed`, `Open`, `Liquidated`). |
| `fund_focus` | TEXT | Geographic focus (e.g. `North America`, `Global`). |
| `region` | TEXT | Semicolon-separated target regions. |
| `industry` | TEXT | Semicolon-separated target industries. |

---

## investors.csv (17,776 rows)

Limited Partners (LPs) currently investing in PE/VC.

| Column | Type | Description |
|--------|------|-------------|
| `firm_id` | FLOAT | Preqin unique LP identifier. Primary key. |
| `firm_name` | TEXT | Investor name (e.g. pension funds, endowments, family offices). |
| `currently_investing_pe` | TEXT | Whether actively investing (all `Yes`). |
| `firm_type` | TEXT | LP type (e.g. `Public Pension Fund`, `Endowment Plan`, `Family Office`). |
| `web_address` | TEXT | Website. |
| `firm_city` | TEXT | City. |
| `firm_state` | TEXT | State. |
| `firm_country` | TEXT | Country. |
| `lp_currency_lpc` | TEXT | Local currency. |
| `funds_under_management_usd` | FLOAT | Total assets under management (millions USD). |
| `current_pe_allocation_pcent` | FLOAT | Current PE allocation as % of total AUM. |
| `current_pe_allocation_usd` | FLOAT | Current PE allocation (millions USD). |
| `target_pe_allocation_pcent` | FLOAT | Target PE allocation %. |
| `target_pe_allocation_usd` | FLOAT | Target PE allocation (millions USD). |
| `typically_invest_min_usd` | FLOAT | Typical minimum fund commitment (millions USD). |
| `typically_invest_max_usd` | FLOAT | Typical maximum fund commitment (millions USD). |
| `coinvest_with_gp` | TEXT | Whether LP co-invests directly (`Yes`/`No`). |
| `first_close_investor` | TEXT | Whether LP typically invests at first close. |
| `separate_accounts` | TEXT | Whether LP uses separate accounts. |

---

## investor_portfolio.csv (123,933 rows)

Junction table: LP commitments to specific funds.

| Column | Type | Description |
|--------|------|-------------|
| `firm_id` | FLOAT | Foreign key to `investors.csv` (LP). |
| `fund_id` | FLOAT | Foreign key to `funds.csv`. |
| `commitment_currency` | TEXT | Currency of the commitment. |
| `lp_commitment_mn` | FLOAT | LP commitment amount in local currency (millions). |
| `commitment_usd` | FLOAT | LP commitment amount (millions USD). |

---

## fund_performance.csv (9,146 rows)

Performance metrics for VC funds (vintage >= 2010).

| Column | Type | Description |
|--------|------|-------------|
| `fund_id` | FLOAT | Foreign key to `funds.csv`. |
| `date_reported` | TEXT | Date of performance measurement (YYYYMMDD format). |
| `vintage` | FLOAT | Fund vintage year. |
| `called_pcent` | FLOAT | % of committed capital called. |
| `distr_dpi_pcent` | FLOAT | DPI — Distributions to Paid-In (%). |
| `value_rvpi_pcent` | FLOAT | RVPI — Remaining Value to Paid-In (%). |
| `multiple` | FLOAT | Net TVPI (Total Value to Paid-In multiple). |
| `net_irr_pcent` | FLOAT | Net Internal Rate of Return (%). |
| `benchmark_id` | FLOAT | Preqin benchmark ID for comparison. |

---

## Key Relationships

```
companies  <--  deals              (portfolio_company_id)
managers   <--  funds              (firm_id)
investors  <--  investor_portfolio (firm_id)
funds      <--  investor_portfolio (fund_id)
funds      <--  fund_performance   (fund_id)
```

---

## Crunchbase vs Preqin Comparison

| Dimension | Crunchbase | Preqin |
|-----------|-----------|--------|
| **US AI companies (2015-2025)** | 12,348 | 674 |
| **Funding rounds** | 27,623 | 1,304 |
| **Company descriptions** | Yes | Yes |
| **Founding year** | Yes | Yes |
| **Deal amounts** | Raw USD | Millions USD |
| **Investors (direct)** | 18,661 (VC firms + angels) | — (no deal-level investor names) |
| **Fund managers (GPs)** | — | 21,587 |
| **Funds** | — | 21,939 |
| **Limited Partners (LPs)** | — | 17,776 |
| **LP-Fund commitments** | — | 123,933 |
| **Fund performance (IRR)** | — | 9,146 |
| **Founders / team members** | 25,721 | — |
| **Education / jobs** | 25,082 / 73,247 | — |
| **Exit data (IPO/M&A)** | Yes (binary flags) | `investment_status` field |
| **Industry taxonomy** | AI category group | `industry_verticals` keyword |

**Key differences:**
- Crunchbase has much broader company coverage (12,348 vs 674) because Preqin focuses on larger VC-backed deals
- Preqin has unique fund-level data (fund sizes, performance, LP commitments) not available in Crunchbase
- Crunchbase has people data (founders, board, education, jobs) not available in Preqin
- Preqin USD amounts are in **millions**; Crunchbase amounts are in **raw USD**

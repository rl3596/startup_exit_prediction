# Filtered Dataset Guide

US AI startups (founded 2015–2025) with **funding >= $1M**, sourced from Crunchbase API v4.

## Dataset Summary

| File | Rows | Description |
|------|-----:|-------------|
| companies.csv | 6,704 | Core company profiles with exit labels |
| funding_rounds.csv | 19,441 | Individual funding rounds |
| investors.csv | 16,864 | Investor profiles (orgs + angels) |
| people.csv | 81,498 | All people (founders, executives, board, advisors) |
| education.csv | 68,963 | Academic degrees and institutions |
| jobs.csv | 201,788 | Work history across all people |
| company_team.csv | 11,102 | Company–person role assignments |
| investor_team.csv | 66,055 | Investor org–person role assignments |
| portfolio_edges.csv | 461,543 | VC firm portfolio investments (2-hop) |
| ipos.csv | 50 | IPO events |
| acquisitions.csv | 63 | Acquisition events |

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   UNIVERSITY                                                            │
│   (via education.csv)                                                   │
│       ▲                                                                 │
│       │ educated_at                                                     │
│       │ (education.csv: person_uuid → institution_uuid)                 │
│       │                                                                 │
│   PERSON ◄──────────── jobs.csv ──────────► ORGANIZATION (external)     │
│   (people.csv)         person_uuid           organization_uuid          │
│       │                                                                 │
│       │         ┌──── company_team.csv ────┐                            │
│       │         │     (person_uuid →       │                            │
│       │         │      company_uuid)       ▼                            │
│       │         │                     ┌─────────┐                       │
│       │         │                     │ COMPANY │                       │
│       │         │                     │         │◄── funding_rounds.csv │
│       │         │                     │         │    (company_uuid)     │
│       │         │                     │         │                       │
│       │         │                     │         │◄── ipos.csv           │
│       │         │                     │         │    (company_uuid)     │
│       │         │                     │         │                       │
│       │         │                     │         │◄── acquisitions.csv   │
│       │         │                     │         │    (acquiree_uuid)    │
│       │         │                     └────┬────┘                       │
│       │         │                          │                            │
│       │         │                          │ invested_in                │
│       │         │                          │ (portfolio_edges.csv:      │
│       │         │                          │  vc_uuid →                 │
│       │         │                          │  portfolio_company_uuid)   │
│       │         │                          ▼                            │
│       │         │                     ┌──────────┐                      │
│       ├─────────┴── investor_team.csv │ INVESTOR │                      │
│       │             (person_uuid →    │          │                      │
│       │              investor_uuid)   └──────────┘                      │
│       │                                                                 │
└───────┴─────────────────────────────────────────────────────────────────┘
```

## Table Schemas and Join Keys

### companies.csv
The central table. All other tables link back to companies.

| Column | Type | Description |
|--------|------|-------------|
| company_uuid | PK | Unique company identifier |
| permalink | text | URL slug |
| name | text | Company name |
| description | text | Short description |
| founded_on | date | Founding date (YYYY-MM-DD) |
| operating_status | text | `active`, `closed`, `ipo`, `acquired` |
| funding_total_usd | float | Total funding raised in USD (>= 1,000,000) |
| num_funding_rounds | int | Number of funding rounds |
| last_funding_type | text | e.g. `seed`, `series_a`, `series_b` |
| last_funding_at | date | Date of most recent round |
| num_employees_enum | text | Employee range (e.g. `c_00101_00250`) |
| ipo_status | text | `private`, `public`, `delisted` |
| is_ipo | bool | 1 if company went public |
| is_acquired | bool | 1 if company was acquired |
| is_unicorn | bool | 1 if post-money valuation >= $1B |
| is_success | int/null | **ML target**: 1 = success, 0 = not, NULL = insufficient data |
| hq_city | text | Headquarters city |
| hq_country | text | Always "United States" |
| website | text | Company website URL |
| linkedin | text | LinkedIn URL |
| stock_symbol | text | Ticker symbol (if public) |
| collected_at | datetime | When data was fetched |

### funding_rounds.csv
One row per funding round. Joins to companies on `company_uuid`.

| Column | Type | Description |
|--------|------|-------------|
| round_uuid | PK | Unique round identifier |
| company_uuid | FK → companies | Which company raised this round |
| announced_on | date | Round announcement date |
| investment_type | text | `seed`, `series_a`, `series_b`, `series_c`, etc. |
| money_raised_usd | float | Amount raised in USD |
| num_investors | int | Number of investors in this round |
| post_money_valuation_usd | float | Post-money valuation (if disclosed) |

### investors.csv
Investor profiles. Links to companies via `portfolio_edges.csv`.

| Column | Type | Description |
|--------|------|-------------|
| investor_uuid | PK | Unique investor identifier |
| permalink | text | URL slug |
| name | text | Investor name |
| entity_def_id | text | `organization` (VC firm) or `person` (angel) |
| investor_type | text | `venture_capital`, `angel`, `corporate_venture_capital`, etc. |
| investment_count | int | Total investments made |
| website | text | Investor website |

### people.csv
Universal person registry: founders, executives, board members, advisors, and investor org team members.

| Column | Type | Description |
|--------|------|-------------|
| person_uuid | PK | Unique person identifier |
| permalink | text | URL slug |
| first_name | text | First name |
| last_name | text | Last name |
| primary_job_title | text | Current/primary job title |
| linkedin | text | LinkedIn URL |
| gender | text | `male`, `female`, or null |
| education_fetched | bool | 1 if education data was retrieved |

### education.csv
Academic records. Joins to people on `person_uuid`.

| Column | Type | Description |
|--------|------|-------------|
| id | PK | Auto-increment ID |
| person_uuid | FK → people | Who attended |
| institution_uuid | text | University identifier (can be used as a node ID) |
| institution_name | text | University name |
| degree_type | text | `BA`, `BS`, `MS`, `MBA`, `PhD`, etc. |
| subject | text | Field of study |
| started_on | date | Start date |
| completed_on | date | Completion date |
| is_completed | bool | Whether the degree was completed |

### jobs.csv
Work history. Joins to people on `person_uuid`.

| Column | Type | Description |
|--------|------|-------------|
| id | PK | Auto-increment ID |
| person_uuid | FK → people | Who held this job |
| organization_uuid | text | Employer UUID (may match a company_uuid or be external) |
| organization_name | text | Employer name |
| title | text | Job title |
| started_on | date | Start date |
| ended_on | date | End date (null if current) |
| is_current | bool | 1 if currently employed here |

### company_team.csv
Links people to companies with a role. Joins to both companies and people.

| Column | Type | Description |
|--------|------|-------------|
| company_uuid | FK → companies | The company |
| person_uuid | FK → people | The person |
| role | text | `c_suite`, `founder`, `vp`, `board_member`, `advisor`, `other` |
| title | text | Raw job title (e.g. "Co-Founder, CEO") |

### investor_team.csv
Links people to investor organizations with a role.

| Column | Type | Description |
|--------|------|-------------|
| investor_uuid | FK → investors | The investor org |
| person_uuid | FK → people | The person |
| role | text | `c_suite`, `founder`, `vp`, `board_member`, `advisor`, `investor`, `other` |
| title | text | Raw job title |

### portfolio_edges.csv
VC portfolio investments (2-hop expansion). Links investors to companies they invested in, including companies outside the core 6,704.

| Column | Type | Description |
|--------|------|-------------|
| vc_uuid | FK → investors | The investing VC firm |
| portfolio_company_uuid | text | The portfolio company (may or may not be in companies.csv) |
| portfolio_company_name | text | Portfolio company name |
| announced_on | date | Investment date |
| investment_type | text | Round type |
| money_raised_usd | float | Round size in USD |

### ipos.csv
IPO events. Joins to companies on `company_uuid`.

| Column | Type | Description |
|--------|------|-------------|
| ipo_uuid | PK | Unique IPO identifier |
| company_uuid | FK → companies | Which company went public |
| went_public_on | date | IPO date |
| stock_exchange | text | Exchange (e.g. `nasdaq`, `nyse`) |
| money_raised_usd | float | IPO proceeds |

### acquisitions.csv
Acquisition events. Joins to companies on `acquiree_uuid`.

| Column | Type | Description |
|--------|------|-------------|
| acquisition_uuid | PK | Unique acquisition identifier |
| acquiree_uuid | FK → companies | The company that was acquired |
| acquirer_name | text | Name of the acquirer |
| acquirer_uuid | text | UUID of the acquirer (may be external) |
| announced_on | date | Announcement date |
| price_usd | float | Acquisition price (if disclosed) |
| acquisition_type | text | `acquisition`, `merger`, etc. |

## How Tables Connect

```
companies.company_uuid
    ├── funding_rounds.company_uuid        (1 company : N rounds)
    ├── company_team.company_uuid          (1 company : N people with roles)
    ├── ipos.company_uuid                  (1 company : 0-1 IPO)
    └── acquisitions.acquiree_uuid         (1 company : 0-1 acquisition)

investors.investor_uuid
    ├── portfolio_edges.vc_uuid            (1 investor : N portfolio companies)
    └── investor_team.investor_uuid        (1 investor : N people with roles)

people.person_uuid
    ├── education.person_uuid              (1 person : N degrees)
    ├── jobs.person_uuid                   (1 person : N jobs)
    ├── company_team.person_uuid           (1 person : N company roles)
    └── investor_team.person_uuid          (1 person : N investor org roles)
```

## ML Target Variable (is_success)

| Label | Count | % |
|-------|------:|--:|
| Success (1) | 1,116 | 16.6% |
| Not success (0) | 5,477 | 81.7% |
| NULL | 111 | 1.7% |

Defined by age-tiered funding thresholds:

| Company Age | Funding Threshold |
|-------------|-------------------|
| <= 24 months | $5M |
| <= 48 months | $25M |
| <= 72 months | $60M |
| <= 96 months | $100M |
| <= 120 months | $140M |

Companies also count as success if they achieved IPO or unicorn status ($1B+ valuation).

## Filter Criteria

This dataset was filtered from the full Crunchbase collection:
- **Country**: United States only
- **Category**: AI / Artificial Intelligence
- **Founded**: 2015–2025
- **Funding**: >= $1,000,000 total raised
- **Cascade**: All related tables filtered to only include entities connected to retained companies

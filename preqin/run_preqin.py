"""
Preqin Data Pipeline via WRDS
==============================
Queries WRDS PostgreSQL for Preqin VC data matching the Crunchbase scope:
  - US-based AI companies
  - Founded 2015-2025
  - At least one funded deal (deal_financing_size_usd > 0)

Exports:
  preqin/data/companies.csv     — Unique portfolio companies
  preqin/data/deals.csv         — All VC funding rounds
  preqin/data/managers.csv      — Fund managers (GPs / VC firms)
  preqin/data/funds.csv         — VC funds investing in AI
  preqin/data/investors.csv     — Limited partners (LPs)
  preqin/data/fund_performance.csv — Fund performance (IRR, multiples)

Usage:
    python -m preqin.run_preqin
"""

import logging
import wrds
import pandas as pd
from pathlib import Path
from preqin.config import WRDS_USERNAME, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("preqin.pipeline")


def connect():
    logger.info("Connecting to WRDS as '%s'...", WRDS_USERNAME)
    return wrds.Connection(wrds_username=WRDS_USERNAME)


def query(db, sql, description=""):
    """Execute SQL and return DataFrame using engine.connect()."""
    logger.info("Querying: %s", description)
    with db.engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    logger.info("  -> %d rows", len(df))
    return df


def save(df, name):
    path = DATA_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    logger.info("Saved %s (%d rows)", path, len(df))
    return path


# ------------------------------------------------------------------ #
#  Step 1: VC Deals (funding rounds)                                  #
# ------------------------------------------------------------------ #

def fetch_deals(db) -> pd.DataFrame:
    """
    Fetch all VC deals for US AI companies founded 2015-2025
    that had at least one funded round.
    """
    sql = """
        SELECT
            ventureid,
            portfolio_company_id,
            portfolio_company_name,
            portfolio_company_website,
            portfolio_company_state,
            portfolio_company_country,
            portfolio_company_region,
            year_established,
            firm_about,
            firm_othernames,
            industry_classification,
            primary_industry,
            sub_industries,
            industry_verticals,
            industry_subverticals,
            stage,
            deal_date,
            deal_status,
            investment_status,
            currency,
            deal_financing_size,
            deal_financing_size_usd,
            deal_financing_size_eur,
            total_known_funding_usd,
            total_known_funding_eur
        FROM preqin.venturedealsdetails
        WHERE portfolio_company_country = 'US'
          AND year_established >= 2015
          AND year_established <= 2025
          AND deal_financing_size_usd > 0
          AND LOWER(industry_verticals) LIKE '%%artificial intelligence%%'
        ORDER BY portfolio_company_id, deal_date
    """
    return query(db, sql, "US AI VC deals (founded 2015-2025, funded)")


# ------------------------------------------------------------------ #
#  Step 2: Extract unique companies from deals                        #
# ------------------------------------------------------------------ #

def extract_companies(deals: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate deals into a company-level table.
    Takes the first row per portfolio_company_id for static fields,
    plus aggregates: deal_count, total_known_funding_usd.
    """
    static_cols = [
        "portfolio_company_id", "portfolio_company_name",
        "portfolio_company_website", "portfolio_company_state",
        "portfolio_company_country", "portfolio_company_region",
        "year_established", "firm_about", "firm_othernames",
        "industry_classification", "primary_industry",
        "sub_industries", "industry_verticals", "industry_subverticals",
    ]
    # Take first row per company for static fields
    companies = deals.drop_duplicates(subset="portfolio_company_id",
                                       keep="first")[static_cols].copy()

    # Coerce deal_date to proper datetime (some rows may be NaT)
    deals = deals.copy()
    deals["deal_date"] = pd.to_datetime(deals["deal_date"], errors="coerce")

    # Aggregate deal-level stats
    agg = deals.groupby("portfolio_company_id").agg(
        deal_count=("ventureid", "count"),
        total_funding_usd=("deal_financing_size_usd", "sum"),
        first_deal_date=("deal_date", "min"),
        last_deal_date=("deal_date", "max"),
        last_stage=("stage", "last"),
    ).reset_index()

    # Also take the max total_known_funding_usd (preqin's own aggregate)
    funding_agg = deals.groupby("portfolio_company_id")["total_known_funding_usd"].max().reset_index()
    funding_agg.columns = ["portfolio_company_id", "preqin_total_known_funding_usd"]

    companies = companies.merge(agg, on="portfolio_company_id", how="left")
    companies = companies.merge(funding_agg, on="portfolio_company_id", how="left")

    logger.info("Extracted %d unique companies from %d deals", len(companies), len(deals))
    return companies


# ------------------------------------------------------------------ #
#  Step 3: Fund Managers (GPs / VC firms)                             #
# ------------------------------------------------------------------ #

def fetch_managers(db) -> pd.DataFrame:
    """
    Fetch all fund managers (GPs) that focus on VC and have
    some US / AI relevance.
    """
    sql = """
        SELECT
            firm_id,
            firmname,
            firmtype,
            sourceofcapital,
            mainfirmstrategy,
            firmcity,
            firmstate,
            firmcountry,
            about,
            established,
            staffcounttotal,
            staffcountmanagement,
            staffcountinvestment,
            firmtrait,
            profilecurrency,
            totalfundsraised10yearsmn,
            investorcoinvestmentrights,
            geofocus,
            industryfocus,
            isminorityowned,
            iswomenowned,
            listed_firm
        FROM preqin.preqinmanagerdetails
        WHERE (mainfirmstrategy = 'Venture Capital'
               OR LOWER(industryfocus) LIKE '%%artificial intelligence%%'
               OR LOWER(industryfocus) LIKE '%%machine learning%%')
        ORDER BY firm_id
    """
    return query(db, sql, "Fund managers (VC / AI-focused)")


# ------------------------------------------------------------------ #
#  Step 4: Funds                                                       #
# ------------------------------------------------------------------ #

def fetch_funds(db) -> pd.DataFrame:
    """Fetch VC funds."""
    sql = """
        SELECT
            fund_id,
            firm_id,
            fund_name,
            firm_name,
            vintage,
            fund_type,
            local_currency,
            target_size_usd,
            final_size_usd,
            fund_status,
            fund_focus,
            region,
            industry
        FROM preqin.preqinfunddetails
        WHERE (fund_type LIKE '%%Venture%%'
               OR LOWER(industry) LIKE '%%artificial intelligence%%')
          AND vintage >= 2010
        ORDER BY fund_id
    """
    return query(db, sql, "VC funds (vintage >= 2010)")


# ------------------------------------------------------------------ #
#  Step 5: Investors (LPs)                                             #
# ------------------------------------------------------------------ #

def fetch_investors(db) -> pd.DataFrame:
    """Fetch LP investor details."""
    sql = """
        SELECT
            firm_id,
            firm_name,
            currently_investing_pe,
            firm_type,
            web_address,
            firm_city,
            firm_state,
            firm_country,
            lp_currency_lpc,
            funds_under_management_usd,
            current_pe_allocation_pcent,
            current_pe_allocation_usd,
            target_pe_allocation_pcent,
            target_pe_allocation_usd,
            typically_invest_min_usd,
            typically_invest_max_usd,
            coinvest_with_gp,
            first_close_investor,
            separate_accounts
        FROM preqin.preqininvestordetails
        WHERE currently_investing_pe = 'Yes'
        ORDER BY firm_id
    """
    return query(db, sql, "LP investors (currently investing)")


# ------------------------------------------------------------------ #
#  Step 6: Investor-Fund portfolio (LP commitments)                    #
# ------------------------------------------------------------------ #

def fetch_investor_portfolio(db) -> pd.DataFrame:
    """Fetch LP-to-Fund commitments."""
    sql = """
        SELECT
            firm_id,
            fund_id,
            commitment_currency,
            lp_commitment_mn,
            commitment_usd
        FROM preqin.investorportfolio
        ORDER BY firm_id, fund_id
    """
    return query(db, sql, "Investor-Fund portfolio commitments")


# ------------------------------------------------------------------ #
#  Step 7: Fund performance                                            #
# ------------------------------------------------------------------ #

def fetch_fund_performance(db) -> pd.DataFrame:
    """Fetch fund performance data (IRR, multiples)."""
    sql = """
        SELECT *
        FROM preqin.preqinfundperformance
        WHERE fund_id IN (
            SELECT fund_id FROM preqin.preqinfunddetails
            WHERE (fund_type LIKE '%%Venture%%'
                   OR LOWER(industry) LIKE '%%artificial intelligence%%')
              AND vintage >= 2010
        )
        ORDER BY fund_id
    """
    return query(db, sql, "Fund performance for VC funds")


# ------------------------------------------------------------------ #
#  Main                                                                #
# ------------------------------------------------------------------ #

def main():
    db = connect()

    # Deals and companies
    deals = fetch_deals(db)
    save(deals, "deals")

    companies = extract_companies(deals)
    save(companies, "companies")

    # Managers (GPs)
    managers = fetch_managers(db)
    save(managers, "managers")

    # Funds
    funds = fetch_funds(db)
    save(funds, "funds")

    # Investors (LPs)
    investors = fetch_investors(db)
    save(investors, "investors")

    # LP-Fund portfolio
    portfolio = fetch_investor_portfolio(db)
    save(portfolio, "investor_portfolio")

    # Fund performance
    perf = fetch_fund_performance(db)
    save(perf, "fund_performance")

    db.close()

    # Print summary
    print("\n" + "=" * 60)
    print("  PREQIN DATA EXPORT SUMMARY")
    print("=" * 60)
    print(f"  Companies:          {len(companies):,}")
    print(f"  Deals (rounds):     {len(deals):,}")
    print(f"  Fund managers (GP): {len(managers):,}")
    print(f"  Funds:              {len(funds):,}")
    print(f"  Investors (LP):     {len(investors):,}")
    print(f"  LP-Fund links:      {len(portfolio):,}")
    print(f"  Fund performance:   {len(perf):,}")
    print(f"\n  Exported to: {DATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()

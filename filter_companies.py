"""
filter_companies.py — Filter dataset to companies with funding_total_usd >= $1M.

Cascades the filter to all related tables:
  1. companies           — direct filter on funding_total_usd
  2. funding_rounds      — keep rounds for retained companies
  3. company_team        — keep team links for retained companies
  4. ipos                — keep IPOs for retained companies
  5. acquisitions        — keep acquisitions for retained companies
  6. investors           — keep investors who invested in retained companies
  7. investor_team       — keep team links for retained investors
  8. portfolio_edges     — keep portfolio edges for retained investors
  9. people              — keep people referenced by retained founders/team/investor_team
  10. education          — keep education for retained people
  11. jobs               — keep jobs for retained people
  12. graph              — rebuild from filtered data

Reads from data/export/, writes filtered versions to data/export_filtered/.
"""

import csv
import os
import shutil
from pathlib import Path

SRC = Path("data/export")
DST = Path("data/export_filtered")

MIN_FUNDING = 1_000_000


def read_csv(name):
    with open(SRC / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(name, rows, fieldnames=None):
    if not rows:
        print(f"  {name}: 0 rows (empty)")
        return
    fieldnames = fieldnames or list(rows[0].keys())
    with open(DST / name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def main():
    DST.mkdir(parents=True, exist_ok=True)

    # 1. Filter companies
    print("Loading and filtering companies (funding >= $1M)...")
    companies = read_csv("companies.csv")
    filtered = [
        c for c in companies
        if c["funding_total_usd"] and float(c["funding_total_usd"]) >= MIN_FUNDING
    ]
    company_uuids = {c["company_uuid"] for c in filtered}
    print(f"  Companies: {len(companies)} -> {len(filtered)}")
    write_csv("companies.csv", filtered)

    # 2. Funding rounds
    print("Filtering funding_rounds...")
    rounds = read_csv("funding_rounds.csv")
    rounds_f = [r for r in rounds if r["company_uuid"] in company_uuids]
    round_uuids = {r["round_uuid"] for r in rounds_f}
    write_csv("funding_rounds.csv", rounds_f)

    # 3. Company team
    print("Filtering company_team...")
    team = read_csv("company_team.csv")
    team_f = [t for t in team if t["company_uuid"] in company_uuids]
    write_csv("company_team.csv", team_f)

    # 4. IPOs
    print("Filtering ipos...")
    ipos = read_csv("ipos.csv")
    ipos_f = [i for i in ipos if i["company_uuid"] in company_uuids]
    write_csv("ipos.csv", ipos_f)

    # 5. Acquisitions
    print("Filtering acquisitions...")
    acq = read_csv("acquisitions.csv")
    acq_f = [a for a in acq if a["acquiree_uuid"] in company_uuids]
    write_csv("acquisitions.csv", acq_f)

    # 6. Investors — keep only those who invested in a retained company
    #    We need round_investors or company_investors from DB. Use portfolio approach:
    #    An investor is retained if they appear in a retained funding round.
    print("Filtering investors...")
    investors_all = read_csv("investors.csv")

    # Build investor set from funding rounds: read portfolio_edges for vc_uuid,
    # but more directly, we need company_investors. Since we don't export that
    # junction table, derive from the DB or use round association.
    # Actually, let's use the portfolio_edges + check which investors funded retained companies.
    # We'll query the DB for this.
    import sqlite3
    db = sqlite3.connect("data/db/crunchbase.db")
    db.row_factory = sqlite3.Row
    investor_uuids_in_retained = set()
    for row in db.execute(
        "SELECT DISTINCT investor_uuid FROM company_investors WHERE company_uuid IN "
        f"({','.join('?' * len(company_uuids))})",
        list(company_uuids),
    ):
        investor_uuids_in_retained.add(row["investor_uuid"])
    db.close()

    investors_f = [i for i in investors_all if i["investor_uuid"] in investor_uuids_in_retained]
    investor_uuids = {i["investor_uuid"] for i in investors_f}
    write_csv("investors.csv", investors_f)

    # 7. Investor team — keep for retained investors
    print("Filtering investor_team...")
    inv_team = read_csv("investor_team.csv")
    inv_team_f = [t for t in inv_team if t["investor_uuid"] in investor_uuids]
    write_csv("investor_team.csv", inv_team_f)

    # 8. Portfolio edges — keep for retained investors
    print("Filtering portfolio_edges...")
    portfolio = read_csv("portfolio_edges.csv")
    portfolio_f = [p for p in portfolio if p["vc_uuid"] in investor_uuids]
    write_csv("portfolio_edges.csv", portfolio_f)

    # 9. People — keep those referenced as founders, team members, or investor team
    print("Filtering people...")
    # Collect all person UUIDs that are still referenced
    person_uuids = set()

    # From company_founders (DB) — founders of retained companies
    db = sqlite3.connect("data/db/crunchbase.db")
    db.row_factory = sqlite3.Row
    for row in db.execute(
        "SELECT DISTINCT founder_uuid FROM company_founders WHERE company_uuid IN "
        f"({','.join('?' * len(company_uuids))})",
        list(company_uuids),
    ):
        person_uuids.add(row["founder_uuid"])
    db.close()

    # From filtered company_team
    for t in team_f:
        person_uuids.add(t["person_uuid"])

    # From filtered investor_team
    for t in inv_team_f:
        person_uuids.add(t["person_uuid"])

    people = read_csv("people.csv")
    people_f = [p for p in people if p["person_uuid"] in person_uuids]
    write_csv("people.csv", people_f)

    # 10. Education — keep for retained people
    print("Filtering education...")
    edu = read_csv("education.csv")
    edu_f = [e for e in edu if e["person_uuid"] in person_uuids]
    write_csv("education.csv", edu_f)

    # 11. Jobs — keep for retained people
    print("Filtering jobs...")
    jobs = read_csv("jobs.csv")
    jobs_f = [j for j in jobs if j["person_uuid"] in person_uuids]
    write_csv("jobs.csv", jobs_f)

    # Summary
    print("\n=== Filter Summary ===")
    print(f"  Companies:       {len(companies):>8} -> {len(filtered):>8}")
    print(f"  Funding rounds:  {len(rounds):>8} -> {len(rounds_f):>8}")
    print(f"  Investors:       {len(investors_all):>8} -> {len(investors_f):>8}")
    print(f"  People:          {len(people):>8} -> {len(people_f):>8}")
    print(f"  Education:       {len(edu):>8} -> {len(edu_f):>8}")
    print(f"  Jobs:            {len(jobs):>8} -> {len(jobs_f):>8}")
    print(f"  Company team:    {len(team):>8} -> {len(team_f):>8}")
    print(f"  Investor team:   {len(inv_team):>8} -> {len(inv_team_f):>8}")
    print(f"  Portfolio edges:  {len(portfolio):>8} -> {len(portfolio_f):>8}")
    print(f"  IPOs:            {len(ipos):>8} -> {len(ipos_f):>8}")
    print(f"  Acquisitions:    {len(acq):>8} -> {len(acq_f):>8}")
    print(f"\nFiltered data written to {DST}/")


if __name__ == "__main__":
    main()

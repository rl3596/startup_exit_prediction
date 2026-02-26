"""
SQLite storage layer.

All pipeline phases write through this class.  The relational schema
keeps companies, funding rounds, investors, founders, and education
linked by UUID foreign keys, making graph construction straightforward.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    uuid                TEXT PRIMARY KEY,
    permalink           TEXT UNIQUE NOT NULL,
    name                TEXT,
    description         TEXT,
    founded_on          TEXT,
    operating_status    TEXT,
    funding_total_usd   REAL,
    num_funding_rounds  INTEGER,
    last_funding_type   TEXT,
    last_funding_at     TEXT,
    num_employees_enum  TEXT,
    ipo_status          TEXT,
    is_ipo              INTEGER DEFAULT 0,
    is_acquired         INTEGER DEFAULT 0,
    is_unicorn          INTEGER DEFAULT 0,
    is_success          INTEGER DEFAULT NULL,
    hq_city             TEXT,
    hq_country          TEXT,
    website             TEXT,
    linkedin            TEXT,
    stock_symbol        TEXT,
    collected_at        TEXT
);

CREATE TABLE IF NOT EXISTS funding_rounds (
    uuid                     TEXT PRIMARY KEY,
    company_uuid             TEXT REFERENCES companies(uuid),
    announced_on             TEXT,
    investment_type          TEXT,
    money_raised_usd         REAL,
    num_investors            INTEGER,
    post_money_valuation_usd REAL
);

CREATE TABLE IF NOT EXISTS investors (
    uuid             TEXT PRIMARY KEY,
    permalink        TEXT,
    name             TEXT,
    entity_def_id    TEXT,    -- "organization" or "person"
    investor_type    TEXT,    -- "venture_capital" | "angel" | "corporate_vc" | etc.
    investment_count INTEGER,
    website          TEXT
);

CREATE TABLE IF NOT EXISTS company_investors (
    company_uuid  TEXT REFERENCES companies(uuid),
    investor_uuid TEXT REFERENCES investors(uuid),
    round_uuid    TEXT,
    PRIMARY KEY (company_uuid, investor_uuid, round_uuid)
);

CREATE TABLE IF NOT EXISTS round_investors (
    round_uuid    TEXT REFERENCES funding_rounds(uuid),
    investor_uuid TEXT REFERENCES investors(uuid),
    is_lead       INTEGER DEFAULT 0,
    PRIMARY KEY (round_uuid, investor_uuid)
);

CREATE TABLE IF NOT EXISTS founders (
    uuid              TEXT PRIMARY KEY,
    permalink         TEXT,
    first_name        TEXT,
    last_name         TEXT,
    primary_job_title TEXT,
    linkedin          TEXT,
    gender            TEXT,
    education_fetched INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS company_founders (
    company_uuid TEXT REFERENCES companies(uuid),
    founder_uuid TEXT REFERENCES founders(uuid),
    PRIMARY KEY (company_uuid, founder_uuid)
);

CREATE TABLE IF NOT EXISTS education (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    founder_uuid     TEXT REFERENCES founders(uuid),
    institution_uuid TEXT,
    institution_name TEXT,
    degree_type      TEXT,
    subject          TEXT,
    started_on       TEXT,
    completed_on     TEXT,
    is_completed     INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    founder_uuid      TEXT REFERENCES founders(uuid),
    organization_uuid TEXT,
    organization_name TEXT,
    title             TEXT,
    started_on        TEXT,
    ended_on          TEXT,
    is_current        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ipos (
    uuid            TEXT PRIMARY KEY,
    company_uuid    TEXT REFERENCES companies(uuid),
    went_public_on  TEXT,
    stock_exchange  TEXT,
    money_raised_usd REAL
);

CREATE TABLE IF NOT EXISTS acquisitions (
    uuid             TEXT PRIMARY KEY,
    acquiree_uuid    TEXT,   -- UUID of the company that was acquired (no FK: may be outside our dataset)
    acquirer_name    TEXT,
    acquirer_uuid    TEXT,
    announced_on     TEXT,
    price_usd        REAL,
    acquisition_type TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_edges (
    vc_uuid                TEXT REFERENCES investors(uuid),
    portfolio_company_uuid TEXT,
    portfolio_company_name TEXT,
    announced_on           TEXT,
    investment_type        TEXT,
    money_raised_usd       REAL,
    PRIMARY KEY (vc_uuid, portfolio_company_uuid, announced_on)
);
"""


class SQLiteStore:

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("Database initialised at %s", self.db_path)

    # ------------------------------------------------------------------ #
    #  Companies                                                           #
    # ------------------------------------------------------------------ #

    def upsert_company(self, record: dict):
        sql = """
            INSERT INTO companies
                (uuid, permalink, name, description, founded_on,
                 operating_status, funding_total_usd, num_funding_rounds,
                 last_funding_type, collected_at)
            VALUES
                (:uuid, :permalink, :name, :description, :founded_on,
                 :operating_status, :funding_total_usd, :num_funding_rounds,
                 :last_funding_type, :collected_at)
            ON CONFLICT(uuid) DO UPDATE SET
                name              = excluded.name,
                description       = excluded.description,
                operating_status  = excluded.operating_status,
                funding_total_usd = excluded.funding_total_usd,
                num_funding_rounds= excluded.num_funding_rounds,
                last_funding_type = excluded.last_funding_type,
                collected_at      = excluded.collected_at
        """
        record.setdefault("collected_at", datetime.utcnow().isoformat())
        with self._connect() as conn:
            conn.execute(sql, record)

    def upsert_company_detail(self, uuid: str, props: dict, exits: dict,
                              is_success=None):
        sql = """
            UPDATE companies SET
                last_funding_at    = :last_funding_at,
                num_employees_enum = :num_employees_enum,
                ipo_status         = :ipo_status,
                is_ipo             = :is_ipo,
                is_acquired        = :is_acquired,
                is_unicorn         = :is_unicorn,
                is_success         = :is_success,
                website            = :website,
                linkedin           = :linkedin,
                stock_symbol       = :stock_symbol
            WHERE uuid = :uuid
        """
        params = {
            "uuid":             uuid,
            "last_funding_at":  props.get("last_funding_at"),
            "num_employees_enum": props.get("num_employees_enum"),
            "ipo_status":       props.get("ipo_status"),
            "is_ipo":           int(exits.get("is_ipo", False)),
            "is_acquired":      int(exits.get("is_acquired", False)),
            "is_unicorn":       int(exits.get("is_unicorn", False)),
            "is_success":       is_success,  # None → SQL NULL; 0/1 → integer
            "website":          props.get("website", {}).get("value") if isinstance(props.get("website"), dict) else props.get("website"),
            "linkedin":         props.get("linkedin", {}).get("value") if isinstance(props.get("linkedin"), dict) else props.get("linkedin"),
            "stock_symbol":     props.get("stock_symbol", {}).get("value") if isinstance(props.get("stock_symbol"), dict) else props.get("stock_symbol"),
        }
        with self._connect() as conn:
            conn.execute(sql, params)

    def upsert_hq(self, uuid: str, hq_entities: list):
        if not hq_entities:
            return
        # Take first location identifier with location_type == "city"
        city = country = None
        for ent in hq_entities:
            props = ent.get("properties", {})
            for loc in props.get("location_identifiers", []):
                if isinstance(loc, dict):
                    if loc.get("location_type") == "city":
                        city = loc.get("value")
                    elif loc.get("location_type") == "country":
                        country = loc.get("value")
        with self._connect() as conn:
            conn.execute(
                "UPDATE companies SET hq_city=?, hq_country=? WHERE uuid=?",
                (city, country, uuid)
            )

    def upsert_hq_flat(self, uuid: str, hq_list: list):
        """
        Flat list version: each item is the HQ record directly (no 'properties' wrapper).
        Fields: location_identifiers (list of {location_type, value} dicts)
        """
        if not hq_list:
            return
        city = country = None
        for rec in hq_list:
            for loc in rec.get("location_identifiers", []):
                if isinstance(loc, dict):
                    loc_type = loc.get("location_type")
                    if loc_type == "city":
                        city = loc.get("value")
                    elif loc_type == "country":
                        country = loc.get("value")
        with self._connect() as conn:
            conn.execute(
                "UPDATE companies SET hq_city=?, hq_country=? WHERE uuid=?",
                (city, country, uuid)
            )

    # ------------------------------------------------------------------ #
    #  Funding Rounds                                                      #
    # ------------------------------------------------------------------ #

    def upsert_funding_rounds(self, company_uuid: str, round_entities: list):
        sql_round = """
            INSERT OR REPLACE INTO funding_rounds
                (uuid, company_uuid, announced_on, investment_type,
                 money_raised_usd, num_investors, post_money_valuation_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        sql_inv = """
            INSERT OR IGNORE INTO round_investors (round_uuid, investor_uuid, is_lead)
            VALUES (?, ?, ?)
        """
        sql_ci = """
            INSERT OR IGNORE INTO company_investors (company_uuid, investor_uuid, round_uuid)
            VALUES (?, ?, ?)
        """
        with self._connect() as conn:
            for ent in round_entities:
                props = ent.get("properties", {})
                ident = props.get("identifier", {})
                r_uuid = ident.get("uuid")
                if not r_uuid:
                    continue

                money = props.get("money_raised", {})
                money_usd = money.get("value_usd") if isinstance(money, dict) else None
                valuation = props.get("post_money_valuation", {})
                val_usd = valuation.get("value_usd") if isinstance(valuation, dict) else None

                conn.execute(sql_round, (
                    r_uuid, company_uuid,
                    props.get("announced_on", {}).get("value") if isinstance(props.get("announced_on"), dict) else props.get("announced_on"),
                    props.get("investment_type"),
                    money_usd,
                    props.get("num_investors"),
                    val_usd,
                ))

                # Lead investors
                for lead in props.get("lead_investor_identifiers", []):
                    if isinstance(lead, dict):
                        inv_uuid = lead.get("uuid")
                        if inv_uuid:
                            self._ensure_investor(conn, lead)
                            conn.execute(sql_inv, (r_uuid, inv_uuid, 1))
                            conn.execute(sql_ci, (company_uuid, inv_uuid, r_uuid))

                # All investors
                for inv in props.get("investor_identifiers", []):
                    if isinstance(inv, dict):
                        inv_uuid = inv.get("uuid")
                        if inv_uuid:
                            self._ensure_investor(conn, inv)
                            conn.execute(sql_inv, (r_uuid, inv_uuid, 0))
                            conn.execute(sql_ci, (company_uuid, inv_uuid, r_uuid))

    def upsert_funding_rounds_flat(self, company_uuid: str, rounds: list):
        """
        Flat list version: each item is the funding round record directly.
        Key fields: identifier (dict), announced_on (dict), investment_type (str),
                    money_raised (dict with value_usd), investor_identifiers (list)
        """
        sql_round = """
            INSERT OR REPLACE INTO funding_rounds
                (uuid, company_uuid, announced_on, investment_type,
                 money_raised_usd, num_investors, post_money_valuation_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        sql_inv = "INSERT OR IGNORE INTO round_investors (round_uuid, investor_uuid, is_lead) VALUES (?,?,?)"
        sql_ci  = "INSERT OR IGNORE INTO company_investors (company_uuid, investor_uuid, round_uuid) VALUES (?,?,?)"

        with self._connect() as conn:
            for rec in rounds:
                ident = rec.get("identifier", {})
                r_uuid = ident.get("uuid") if isinstance(ident, dict) else None
                if not r_uuid:
                    continue

                announced = rec.get("announced_on", {})
                announced_val = announced.get("value") if isinstance(announced, dict) else announced
                money = rec.get("money_raised", {})
                money_usd = money.get("value_usd") if isinstance(money, dict) else None
                valuation = rec.get("post_money_valuation", {})
                val_usd = valuation.get("value_usd") if isinstance(valuation, dict) else None
                # investor_identifiers in round card is a list of {uuid, value, role, ...}
                inv_list = rec.get("investor_identifiers") or []

                conn.execute(sql_round, (
                    r_uuid, company_uuid,
                    announced_val,
                    rec.get("investment_type"),
                    money_usd,
                    len(inv_list) if inv_list else None,
                    val_usd,
                ))

                for inv in inv_list:
                    if not isinstance(inv, dict):
                        continue
                    inv_uuid = inv.get("uuid")
                    if not inv_uuid:
                        continue
                    self._ensure_investor(conn, inv)
                    is_lead = 1 if inv.get("role") == "lead_investor" else 0
                    conn.execute(sql_inv, (r_uuid, inv_uuid, is_lead))
                    conn.execute(sql_ci, (company_uuid, inv_uuid, r_uuid))

    # ------------------------------------------------------------------ #
    #  Investors                                                           #
    # ------------------------------------------------------------------ #

    def _ensure_investor(self, conn: sqlite3.Connection, ident: dict):
        """Insert investor stub from an identifier dict if not already present."""
        uuid = ident.get("uuid")
        if not uuid:
            return
        conn.execute(
            """
            INSERT OR IGNORE INTO investors
                (uuid, permalink, name, entity_def_id)
            VALUES (?, ?, ?, ?)
            """,
            (uuid, ident.get("permalink"), ident.get("value"),
             ident.get("entity_def_id"))
        )

    def upsert_org_investors(self, company_uuid: str, investor_entities: list):
        sql_ci = """
            INSERT OR IGNORE INTO company_investors (company_uuid, investor_uuid, round_uuid)
            VALUES (?, ?, 'direct')
        """
        with self._connect() as conn:
            for ent in investor_entities:
                props = ent.get("properties", {})
                ident = props.get("identifier", {})
                if not isinstance(ident, dict):
                    continue
                inv_uuid = ident.get("uuid")
                if not inv_uuid:
                    continue
                self._ensure_investor(conn, ident)
                conn.execute(sql_ci, (company_uuid, inv_uuid))

    def upsert_org_investors_flat(self, company_uuid: str, investors: list):
        """
        Flat list version: each item is the investor record directly.
        Key fields: identifier (dict with uuid, permalink, value, entity_def_id),
                    investor_type (list or str)
        """
        sql_ci = "INSERT OR IGNORE INTO company_investors (company_uuid, investor_uuid, round_uuid) VALUES (?,?,'direct')"
        with self._connect() as conn:
            for rec in investors:
                ident = rec.get("identifier", {})
                if not isinstance(ident, dict):
                    continue
                inv_uuid = ident.get("uuid")
                if not inv_uuid:
                    continue
                self._ensure_investor(conn, ident)
                # Persist investor_type from the full record
                inv_type = rec.get("investor_type")
                if isinstance(inv_type, list):
                    inv_type = ",".join(inv_type)
                if inv_type:
                    conn.execute("UPDATE investors SET investor_type=? WHERE uuid=?",
                                 (inv_type, inv_uuid))
                conn.execute(sql_ci, (company_uuid, inv_uuid))

    def upsert_investor_detail(self, uuid: str, props: dict):
        sql = """
            UPDATE investors SET
                investor_type    = ?,
                investment_count = ?,
                website          = ?
            WHERE uuid = ?
        """
        website = props.get("website", {})
        website_val = website.get("value") if isinstance(website, dict) else website
        with self._connect() as conn:
            conn.execute(sql, (
                props.get("investor_type"),
                props.get("investment_count"),
                website_val,
                uuid,
            ))

    def upsert_investor_person(self, uuid: str, props: dict):
        with self._connect() as conn:
            conn.execute(
                "UPDATE investors SET investor_type=? WHERE uuid=?",
                ("angel_investor", uuid)
            )

    def get_all_investors(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uuid, permalink, name, entity_def_id FROM investors"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Founders                                                            #
    # ------------------------------------------------------------------ #

    def upsert_org_founders(self, company_uuid: str, founder_entities: list):
        sql_f  = "INSERT OR IGNORE INTO founders (uuid, permalink, first_name, last_name) VALUES (?, ?, ?, ?)"
        sql_cf = "INSERT OR IGNORE INTO company_founders (company_uuid, founder_uuid) VALUES (?, ?)"
        with self._connect() as conn:
            for ent in founder_entities:
                props = ent.get("properties", {})
                ident = props.get("identifier", {})
                if not isinstance(ident, dict):
                    continue
                f_uuid = ident.get("uuid")
                if not f_uuid:
                    continue
                name_parts = ident.get("value", "").split(" ", 1)
                first = name_parts[0] if name_parts else None
                last  = name_parts[1] if len(name_parts) > 1 else None
                conn.execute(sql_f, (f_uuid, ident.get("permalink"), first, last))
                conn.execute(sql_cf, (company_uuid, f_uuid))

    def upsert_org_founders_flat(self, company_uuid: str, founders: list):
        """
        Flat list version: each item is the founder (person) record directly.
        Key fields: identifier (dict), first_name (str), last_name (str),
                    linkedin (str or dict), gender (str)
        """
        sql_f  = "INSERT OR IGNORE INTO founders (uuid, permalink, first_name, last_name, linkedin, gender) VALUES (?,?,?,?,?,?)"
        sql_cf = "INSERT OR IGNORE INTO company_founders (company_uuid, founder_uuid) VALUES (?,?)"
        with self._connect() as conn:
            for rec in founders:
                ident = rec.get("identifier", {})
                if not isinstance(ident, dict):
                    continue
                f_uuid = ident.get("uuid")
                if not f_uuid:
                    continue
                linkedin = rec.get("linkedin")
                if isinstance(linkedin, dict):
                    linkedin = linkedin.get("value")
                conn.execute(sql_f, (
                    f_uuid,
                    ident.get("permalink"),
                    rec.get("first_name"),
                    rec.get("last_name"),
                    linkedin,
                    rec.get("gender"),
                ))
                conn.execute(sql_cf, (company_uuid, f_uuid))

    def upsert_founder_detail(self, uuid: str, props: dict):
        sql = """
            UPDATE founders SET
                first_name        = ?,
                last_name         = ?,
                primary_job_title = ?,
                linkedin          = ?,
                gender            = ?
            WHERE uuid = ?
        """
        linkedin = props.get("linkedin", {})
        linkedin_val = linkedin.get("value") if isinstance(linkedin, dict) else linkedin
        with self._connect() as conn:
            conn.execute(sql, (
                props.get("first_name"),
                props.get("last_name"),
                props.get("primary_job_title"),
                linkedin_val,
                props.get("gender"),
                uuid,
            ))

    def get_all_founders(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uuid, permalink, first_name, last_name FROM founders"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Education                                                           #
    # ------------------------------------------------------------------ #

    def upsert_education(self, founder_uuid: str, degree_entries: list):
        """
        Accepts the flat list returned by the 'degrees' card.
        Each entry is a dict with 'school_identifier', 'subject',
        'type_name', 'started_on', 'completed_on'.
        """
        sql = """
            INSERT OR IGNORE INTO education
                (founder_uuid, institution_uuid, institution_name,
                 degree_type, subject, started_on, completed_on, is_completed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            for entry in degree_entries:
                # Flat dict — no 'properties' wrapper
                school = entry.get("school_identifier", {})
                if isinstance(school, dict):
                    inst_uuid = school.get("uuid")
                    inst_name = school.get("value")
                else:
                    inst_uuid = inst_name = None

                started   = entry.get("started_on", {})
                completed = entry.get("completed_on", {})
                conn.execute(sql, (
                    founder_uuid,
                    inst_uuid,
                    inst_name,
                    entry.get("type_name"),      # e.g. "Degree", "Bachelor"
                    entry.get("subject"),
                    started.get("value")   if isinstance(started, dict)   else started,
                    completed.get("value") if isinstance(completed, dict) else completed,
                    0,   # is_completed not directly in this card structure
                ))
            conn.execute(
                "UPDATE founders SET education_fetched=1 WHERE uuid=?",
                (founder_uuid,)
            )

    def upsert_jobs(self, founder_uuid: str, job_entities: list):
        """
        Persists employment history records from the 'jobs' card.
        Each record: organization_identifier (dict), title (str),
                     started_on (dict or str), ended_on (dict or str),
                     is_current (bool/int).
        """
        sql = """
            INSERT OR IGNORE INTO jobs
                (founder_uuid, organization_uuid, organization_name,
                 title, started_on, ended_on, is_current)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            for rec in job_entities:
                org     = rec.get("organization_identifier", {})
                started = rec.get("started_on", {})
                ended   = rec.get("ended_on", {})
                conn.execute(sql, (
                    founder_uuid,
                    org.get("uuid")  if isinstance(org, dict) else None,
                    org.get("value") if isinstance(org, dict) else None,
                    rec.get("title"),
                    started.get("value") if isinstance(started, dict) else started,
                    ended.get("value")   if isinstance(ended, dict)   else ended,
                    int(bool(rec.get("is_current"))),
                ))

    def get_all_education(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT founder_uuid, institution_uuid, institution_name, "
                "degree_type, subject FROM education"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_eligible_funding_usd(self, company_uuid: str) -> float | None:
        """
        Sum of money_raised_usd for all funding rounds of this company
        where announced_on <= 2025-12-31 and money_raised_usd is not NULL.
        Returns None if no eligible rounds found.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(money_raised_usd) FROM funding_rounds "
                "WHERE company_uuid=? AND announced_on <= '2025-12-31' "
                "AND money_raised_usd IS NOT NULL",
                (company_uuid,)
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    # ------------------------------------------------------------------ #
    #  IPOs and Acquisitions                                               #
    # ------------------------------------------------------------------ #

    def upsert_ipo(self, company_uuid: str, ipo_entities: list):
        sql = """
            INSERT OR IGNORE INTO ipos
                (uuid, company_uuid, went_public_on, stock_exchange, money_raised_usd)
            VALUES (?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            for ent in ipo_entities:
                props = ent.get("properties", {})
                ident = props.get("identifier", {})
                uuid  = ident.get("uuid") if isinstance(ident, dict) else None
                if not uuid:
                    continue
                money = props.get("money_raised", {})
                money_usd = money.get("value_usd") if isinstance(money, dict) else None
                conn.execute(sql, (
                    uuid, company_uuid,
                    props.get("went_public_on", {}).get("value") if isinstance(props.get("went_public_on"), dict) else props.get("went_public_on"),
                    props.get("stock_exchange_symbol"),
                    money_usd,
                ))

    def upsert_acquisition(self, company_uuid: str, acq_entities: list):
        sql = """
            INSERT OR IGNORE INTO acquisitions
                (uuid, acquiree_uuid, acquirer_name, acquirer_uuid,
                 announced_on, price_usd, acquisition_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            for ent in acq_entities:
                props = ent.get("properties", {})
                ident = props.get("identifier", {})
                uuid  = ident.get("uuid") if isinstance(ident, dict) else None
                if not uuid:
                    continue
                acqr  = props.get("acquirer_identifier", {})
                price = props.get("price", {})
                price_usd = price.get("value_usd") if isinstance(price, dict) else None
                conn.execute(sql, (
                    uuid, company_uuid,
                    acqr.get("value") if isinstance(acqr, dict) else None,
                    acqr.get("uuid")  if isinstance(acqr, dict) else None,
                    props.get("announced_on", {}).get("value") if isinstance(props.get("announced_on"), dict) else props.get("announced_on"),
                    price_usd,
                    props.get("acquisition_type"),
                ))

    def upsert_ipo_flat(self, company_uuid: str, ipos: list):
        """
        Flat list version of upsert_ipo.
        Each item: identifier (dict), went_public_on (dict), stock_exchange_symbol (str),
                   money_raised (dict)
        """
        sql = "INSERT OR IGNORE INTO ipos (uuid, company_uuid, went_public_on, stock_exchange, money_raised_usd) VALUES (?,?,?,?,?)"
        with self._connect() as conn:
            for rec in ipos:
                ident = rec.get("identifier", {})
                uuid  = ident.get("uuid") if isinstance(ident, dict) else None
                if not uuid:
                    continue
                went_public = rec.get("went_public_on", {})
                money = rec.get("money_raised", {})
                conn.execute(sql, (
                    uuid, company_uuid,
                    went_public.get("value") if isinstance(went_public, dict) else went_public,
                    rec.get("stock_exchange_symbol"),
                    money.get("value_usd") if isinstance(money, dict) else None,
                ))

    def upsert_acquisition_flat(self, company_uuid: str, acqs: list):
        """
        Flat list version of upsert_acquisition.

        NOTE: The 'acquiree_acquisitions' card returns acquisitions *made by*
        this company (company_uuid is the acquirer). Each record has both
        acquirer_identifier and acquiree_identifier. We store the acquiree's
        uuid in acquiree_uuid and the acquirer's uuid in acquirer_uuid so the
        table correctly represents who bought whom.

        Fields: identifier (dict), acquirer_identifier (dict),
                acquiree_identifier (dict), announced_on (dict),
                price (dict), acquisition_type (str)
        """
        sql = """
            INSERT OR IGNORE INTO acquisitions
                (uuid, acquiree_uuid, acquirer_name, acquirer_uuid,
                 announced_on, price_usd, acquisition_type)
            VALUES (?,?,?,?,?,?,?)
        """
        with self._connect() as conn:
            for rec in acqs:
                ident = rec.get("identifier", {})
                uuid  = ident.get("uuid") if isinstance(ident, dict) else None
                if not uuid:
                    continue
                acqr      = rec.get("acquirer_identifier", {})
                acqe      = rec.get("acquiree_identifier", {})
                price     = rec.get("price", {})
                announced = rec.get("announced_on", {})
                # acquiree_uuid: the company that was bought
                acquiree_uuid = acqe.get("uuid") if isinstance(acqe, dict) else None
                conn.execute(sql, (
                    uuid,
                    acquiree_uuid,  # correct: the company that was acquired
                    acqr.get("value") if isinstance(acqr, dict) else None,
                    acqr.get("uuid")  if isinstance(acqr, dict) else None,
                    announced.get("value") if isinstance(announced, dict) else announced,
                    price.get("value_usd") if isinstance(price, dict) else None,
                    rec.get("acquisition_type"),
                ))

    # ------------------------------------------------------------------ #
    #  Portfolio Edges (2-hop investor network)                            #
    # ------------------------------------------------------------------ #

    def upsert_portfolio_edges(self, vc_uuid: str, investment_entities: list):
        sql = """
            INSERT OR IGNORE INTO portfolio_edges
                (vc_uuid, portfolio_company_uuid, portfolio_company_name,
                 announced_on, investment_type, money_raised_usd)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            for ent in investment_entities:
                props  = ent.get("properties", {})
                org    = props.get("organization_identifier", {})
                money  = props.get("funding_round_money_raised", {})
                money_usd = money.get("value_usd") if isinstance(money, dict) else None
                org_uuid  = org.get("uuid")  if isinstance(org, dict) else None
                org_name  = org.get("value") if isinstance(org, dict) else None
                if not org_uuid:
                    continue
                conn.execute(sql, (
                    vc_uuid, org_uuid, org_name,
                    props.get("announced_on", {}).get("value") if isinstance(props.get("announced_on"), dict) else props.get("announced_on"),
                    props.get("investment_type"),
                    money_usd,
                ))

    def upsert_portfolio_edges_flat(self, vc_uuid: str, investments: list):
        """
        Flat list version for the 'participated_investments' card.
        Called WITHOUT card_field_ids; response nested under {"cards": {...}}.
        Each record fields: organization_identifier (dict with uuid/value/permalink),
                            announced_on (str date or dict),
                            funding_round_money_raised (dict with value_usd),
                            funding_round_investment_type (str),
                            identifier (dict with uuid — the investment UUID)
        """
        sql = """
            INSERT OR IGNORE INTO portfolio_edges
                (vc_uuid, portfolio_company_uuid, portfolio_company_name,
                 announced_on, investment_type, money_raised_usd)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            for rec in investments:
                org = rec.get("organization_identifier", {})
                if not isinstance(org, dict):
                    continue
                org_uuid = org.get("uuid")
                if not org_uuid:
                    continue
                org_name = org.get("value")

                announced = rec.get("announced_on")
                announced_val = announced.get("value") if isinstance(announced, dict) else announced

                money = rec.get("funding_round_money_raised", {})
                money_usd = money.get("value_usd") if isinstance(money, dict) else None

                inv_type = rec.get("funding_round_investment_type")

                conn.execute(sql, (
                    vc_uuid, org_uuid, org_name,
                    announced_val,
                    inv_type,
                    money_usd,
                ))

    def get_portfolio_edges(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT vc_uuid, portfolio_company_uuid, portfolio_company_name, "
                "announced_on, investment_type FROM portfolio_edges"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Graph query helpers                                                 #
    # ------------------------------------------------------------------ #

    def get_all_companies(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uuid, permalink, name, founded_on, operating_status, "
                "funding_total_usd, is_ipo, is_acquired, is_unicorn, is_success FROM companies"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_company_investor_edges(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT company_uuid, investor_uuid, round_uuid FROM company_investors"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_company_founder_edges(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT company_uuid, founder_uuid FROM company_founders"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_co_investor_pairs(self) -> list:
        """Pairs of investors who co-invested in the same round."""
        sql = """
            SELECT a.investor_uuid AS investor_a_uuid,
                   b.investor_uuid AS investor_b_uuid,
                   a.round_uuid
            FROM round_investors a
            JOIN round_investors b
              ON a.round_uuid = b.round_uuid
             AND a.investor_uuid < b.investor_uuid
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Validation stats                                                    #
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        queries = {
            "num_companies":           "SELECT COUNT(*) FROM companies",
            "companies_with_rounds":   "SELECT COUNT(DISTINCT company_uuid) FROM funding_rounds",
            "companies_with_investors":"SELECT COUNT(DISTINCT company_uuid) FROM company_investors",
            "companies_with_founders": "SELECT COUNT(DISTINCT company_uuid) FROM company_founders",
            "companies_with_education":"SELECT COUNT(DISTINCT cf.company_uuid) FROM company_founders cf JOIN education e ON cf.founder_uuid=e.founder_uuid",
            # Primary success metric
            "num_success":             "SELECT COUNT(*) FROM companies WHERE is_success=1",
            "num_not_success":         "SELECT COUNT(*) FROM companies WHERE is_success=0",
            "num_success_null":        "SELECT COUNT(*) FROM companies WHERE is_success IS NULL",
            # Supplemental exit reference data
            "num_ipo":                 "SELECT COUNT(*) FROM companies WHERE is_ipo=1",
            "num_acquired":            "SELECT COUNT(*) FROM companies WHERE is_acquired=1",
            "num_unicorn":             "SELECT COUNT(*) FROM companies WHERE is_unicorn=1",
            "num_investors":           "SELECT COUNT(*) FROM investors",
            "num_founders":            "SELECT COUNT(*) FROM founders",
            "num_universities":        "SELECT COUNT(DISTINCT institution_uuid) FROM education WHERE institution_uuid IS NOT NULL",
            "num_rounds":              "SELECT COUNT(*) FROM funding_rounds",
            "num_jobs":                "SELECT COUNT(*) FROM jobs",
        }
        stats = {}
        with self._connect() as conn:
            for key, sql in queries.items():
                stats[key] = conn.execute(sql).fetchone()[0]

        total = stats["num_companies"] or 1
        labeled = stats["num_success"] + stats["num_not_success"]
        stats["success_coverage_pct"] = 100.0 * labeled / total
        return stats

    # ------------------------------------------------------------------ #
    #  CSV export helpers                                                  #
    # ------------------------------------------------------------------ #

    def export_table_to_csv(self, table: str, csv_path: str):
        import csv
        with self._connect() as conn:
            cur  = conn.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)
        logger.info("Exported %s -> %s (%d rows)", table, csv_path, len(rows))

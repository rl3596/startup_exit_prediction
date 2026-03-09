"""
Preqin Schema Discovery Script
===============================
Connects to WRDS and discovers all Preqin tables, columns, and sample data.
Saves a full schema report to preqin/data/schema_report.txt.

Run once:
    python -m preqin.discover_schema

Requires WRDS credentials (interactive prompt or ~/.pgpass).
"""

import wrds
import sys
from preqin.config import WRDS_USERNAME, SCHEMA_REPORT_PATH


def discover():
    print(f"Connecting to WRDS as '{WRDS_USERNAME}'...")
    db = wrds.Connection(wrds_username=WRDS_USERNAME)

    # 1. Find all Preqin-related libraries
    all_libs = db.list_libraries()
    preqin_libs = sorted([lib for lib in all_libs if "preqin" in lib.lower()])
    print(f"\nPreqin libraries found: {preqin_libs}")

    lines = []
    lines.append("=" * 80)
    lines.append("PREQIN SCHEMA REPORT (WRDS)")
    lines.append("=" * 80)
    lines.append(f"\nPreqin libraries: {preqin_libs}\n")

    for lib in preqin_libs:
        lines.append(f"\n{'#' * 80}")
        lines.append(f"# LIBRARY: {lib}")
        lines.append(f"{'#' * 80}")

        try:
            tables = db.list_tables(library=lib)
        except Exception as e:
            lines.append(f"  ERROR listing tables: {e}")
            continue

        lines.append(f"Tables ({len(tables)}): {tables}\n")

        for table in sorted(tables):
            lines.append(f"\n{'─' * 70}")
            lines.append(f"TABLE: {lib}.{table}")
            lines.append(f"{'─' * 70}")

            # Row count
            try:
                count = db.get_row_count(library=lib, table=table)
                lines.append(f"  Row count: {count:,}")
            except Exception as e:
                lines.append(f"  Row count: ERROR - {e}")

            # Column descriptions
            try:
                desc = db.describe_table(library=lib, table=table)
                lines.append(f"  Columns ({len(desc)}):")
                for _, row in desc.iterrows():
                    col_name = row.get("name", "?")
                    col_type = row.get("type", "?")
                    lines.append(f"    {col_name:40s}  {col_type}")
            except Exception as e:
                lines.append(f"  Describe ERROR: {e}")

            # Sample rows
            try:
                sample = db.get_table(library=lib, table=table, rows=3)
                lines.append(f"\n  Sample ({min(3, len(sample))} rows):")
                for idx, srow in sample.iterrows():
                    lines.append(f"    ROW {idx}:")
                    for col in sample.columns:
                        val = srow[col]
                        val_str = str(val)[:120]
                        lines.append(f"      {col}: {val_str}")
            except Exception as e:
                lines.append(f"  Sample ERROR: {e}")

    db.close()

    report = "\n".join(lines)
    SCHEMA_REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\nSchema report saved to {SCHEMA_REPORT_PATH}")
    print(f"Total lines: {len(lines)}")

    # Also print a quick summary
    print("\n" + "=" * 60)
    print("QUICK SUMMARY")
    print("=" * 60)
    print(report[:5000])


if __name__ == "__main__":
    discover()

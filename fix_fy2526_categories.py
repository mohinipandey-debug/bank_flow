"""
fix_fy2526_categories.py
Updates FY2526 transactions in DB with correct categories from Excel.
Matches rows by fingerprint. Updates only final_group, group_name,
main_group, category. Does NOT re-insert or delete anything.

Usage:
    python fix_fy2526_categories.py --file "Bank Flow FY25-26.xlsx"
"""

import pandas as pd
import math
import sqlite3
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATABASE_FILE
from database import make_fingerprint   # uses the EXACT same formula as insert_transactions

FINANCIAL_YEAR = "FY2526"
FY_START       = "2025-04-01"
FY_END         = "2026-03-31"

ENTITY_MAP = {"CKSPL": "Stores", "CKVPL": "Ventures"}
ACCOUNT_MAP = {
    "8218": "AXIS-8218", "7647": "AXIS-7647",
    "5881": "HDFC-5881", "5623": "AXIS-5623",
    "7862": "HDFC-7862", "7640": "HDFC-7640",
}


def _parse_amount(raw):
    """Mirrors import_fy2526._parse_amount exactly — no abs(), round to 2dp."""
    try:
        v = float(raw)
        return 0.0 if math.isnan(v) else round(v, 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(raw):
    """'2025-04-01 00:00:00' or ISO-like string -> 'YYYY-MM-DD', else None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "nan", "NaT"):
        return None
    return s[:10]


def _clean(raw, fallback=""):
    s = str(raw).strip() if raw is not None else fallback
    return fallback if s in ("nan", "-", "") else s


def run(filepath):
    print(f"\n[FIX] File: {filepath}")
    print(f"[FIX] Reading Excel...")

    try:
        df = pd.read_excel(filepath, sheet_name="Sheet1", header=1, dtype=str)
    except Exception as e:
        print(f"[ERROR] Cannot read file: {e}")
        sys.exit(1)

    df.columns = [str(c).strip() for c in df.columns]
    print(f"[FIX] Rows in Excel: {len(df):,}")

    required = ["Company", "Account Number", "Value Date", "Description",
                "DebitAmount", "CreditAmount", "FINAL GROUP"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"[ERROR] Missing columns: {missing}")
        print(f"[ERROR] Available: {list(df.columns)}")
        sys.exit(1)
    print(f"[FIX] All critical columns found OK")

    conn = sqlite3.connect(DATABASE_FILE)

    updated   = 0
    not_found = 0
    skipped   = 0
    errors    = 0
    BATCH     = 2000
    batch_updates = []

    print(f"[FIX] Processing rows...\n")

    for idx, r in df.iterrows():
        try:
            # Entity — mirrors import_fy2526 exactly
            company = _clean(r.get("Company"))
            entity  = ENTITY_MAP.get(company)
            if not entity:
                skipped += 1
                continue

            # Bank account
            acct_raw = _clean(r.get("Account Number"))
            acct_key = acct_raw[-4:] if len(acct_raw) >= 4 else acct_raw
            bank_id  = ACCOUNT_MAP.get(acct_key)
            if not bank_id:
                skipped += 1
                continue

            # Date
            date_str = _parse_date(r.get("Value Date"))
            if not date_str or not (FY_START <= date_str <= FY_END):
                skipped += 1
                continue

            # Amounts — no abs(), matches database.make_fingerprint inputs
            debit  = _parse_amount(r.get("DebitAmount"))
            credit = _parse_amount(r.get("CreditAmount"))
            if debit == 0.0 and credit == 0.0:
                skipped += 1
                continue

            # Narration — mirrors import_fy2526 fallback chain
            narration = (_clean(r.get("Description"))
                         or _clean(r.get("Final Particulars"))
                         or "—")

            # Categories from Excel
            fg  = _clean(r.get("FINAL GROUP"),  "Uncategorized")
            grp = _clean(r.get("GROUP"),         "")
            mg  = _clean(r.get("MAIN GROUP"),    "")
            pr  = _clean(r.get("Payment/Receipt"), "")
            if not mg:
                mg = pr if pr in ("Receipt", "Payment") else (
                    "Receipt" if credit > 0 else "Payment")
            if fg in ("Uncategorized", ""):
                fg = "Uncategorized"

            # Skip rows that are already Uncategorized in the Excel
            if fg == "Uncategorized":
                skipped += 1
                continue

            fp = make_fingerprint(entity, bank_id, date_str,
                                  narration, debit, credit)
            batch_updates.append((fg, fg, grp, mg, fp))

            if len(batch_updates) >= BATCH:
                u, nf = _flush_updates(conn, batch_updates)
                updated   += u
                not_found += nf
                batch_updates = []
                print(f"  {updated:,} updated | {not_found:,} not found...")

        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"  [ROW {idx} ERROR] {e}")

    # Final flush
    if batch_updates:
        u, nf = _flush_updates(conn, batch_updates)
        updated   += u
        not_found += nf

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    print(f"[DONE]")
    print(f"   Updated:   {updated:,} rows")
    print(f"   Not found: {not_found:,} rows (fingerprint mismatch)")
    print(f"   Skipped:   {skipped:,} rows (out of FY range, no amount, or already categorized)")
    print(f"   Errors:    {errors:,}")

    if not_found > 1000:
        print(f"\n[WARN] High not-found count ({not_found:,}) suggests fingerprint mismatch.")
        print(f"   Run the fingerprint diagnostic to investigate.")

    print(f"\nNext: Restart dashboard -> select FY 2025-26 -> check Uncategorised tab")


def _flush_updates(conn, batch):
    updated = not_found = 0
    for fg, cat, grp, mg, fp in batch:
        r = conn.execute("""
            UPDATE transactions
            SET final_group         = ?,
                category            = ?,
                group_name          = ?,
                main_group          = ?,
                manually_overridden = 0
            WHERE fingerprint = ?
            AND financial_year = 'FY2526'
            AND (final_group = 'Uncategorized'
                 OR final_group IS NULL
                 OR TRIM(final_group) = '')
        """, [fg, cat, grp, mg, fp])
        if r.rowcount > 0:
            updated += 1
        else:
            not_found += 1
    conn.commit()
    return updated, not_found


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True,
                        help="Path to Bank Flow FY25-26.xlsx")
    args = parser.parse_args()
    if not os.path.exists(args.file):
        print(f"[ERROR] File not found: {args.file}")
        sys.exit(1)
    run(args.file)

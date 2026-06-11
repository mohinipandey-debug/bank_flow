"""
Import FY 2025-26 transactions from Bank Flow FY25-26.xlsx into BankFlow DB.

Run from the Output/ directory:
    python import_fy2526.py
    python import_fy2526.py "D:/path/to/Bank Flow FY25-26.xlsx"

The source file has a blank physical row 0; column headers are in row 1;
data starts from row 2.  pandas header=1 reads this correctly.
"""
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import insert_transactions, init_db, mark_file_processed

FINANCIAL_YEAR = "FY2526"

COMPANY_MAP = {
    "CKSPL": "Stores",
    "CKVPL": "Ventures",
}

# Last-4 digits of account number → full bank-account ID in BankFlow
ACCOUNT_MAP = {
    "8218": "AXIS-8218",
    "7647": "AXIS-7647",
    "5881": "HDFC-5881",
    "5623": "AXIS-5623",
    "7862": "HDFC-7862",
    "7640": "HDFC-7640",
}

DEFAULT_XLSX = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "input Files", "Bank Flow FY25-26.xlsx",
    )
)


def _parse_date(raw):
    """'2025-04-01 00:00:00' or any ISO-like string → 'YYYY-MM-DD', else None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "nan", "NaT"):
        return None
    return s[:10]


def _parse_amount(raw):
    """Numeric string or float → float; NaN / blank → 0.0."""
    try:
        v = float(raw)
        import math
        return 0.0 if math.isnan(v) else round(v, 2)
    except (TypeError, ValueError):
        return 0.0


def _clean(raw, fallback=""):
    s = str(raw).strip() if raw is not None else fallback
    return fallback if s in ("nan", "-", "") else s


def main(filepath=None):
    filepath = filepath or DEFAULT_XLSX
    if not os.path.exists(filepath):
        print(f"[ERROR] File not found: {filepath}")
        sys.exit(1)

    print(f"[INFO] Reading: {filepath}")
    # Row 0 in the physical file is blank; row 1 = headers; data from row 2
    df = pd.read_excel(filepath, sheet_name="Sheet1", header=1, dtype=str)
    print(f"[INFO] {len(df):,} raw rows loaded")

    rows   = []
    skipped = 0

    for _, r in df.iterrows():
        # ── Entity ───────────────────────────────────────────────────────────
        company = _clean(r.get("Company"))
        entity  = COMPANY_MAP.get(company)
        if not entity:
            skipped += 1
            continue

        # ── Bank account ID ──────────────────────────────────────────────────
        acct_raw = _clean(r.get("Account Number"))
        acct_key = acct_raw[-4:] if len(acct_raw) >= 4 else acct_raw
        bank_id  = ACCOUNT_MAP.get(acct_key)
        if not bank_id:
            skipped += 1
            continue

        # ── Date ─────────────────────────────────────────────────────────────
        # "Value Date" is the first (index-3) column; pandas may duplicate-rename
        # the second "Value Date" to "Value Date.1" — always use the first.
        date_str = _parse_date(r.get("Value Date"))
        if not date_str:
            skipped += 1
            continue

        # ── Amounts ──────────────────────────────────────────────────────────
        debit  = _parse_amount(r.get("DebitAmount"))
        credit = _parse_amount(r.get("CreditAmount"))

        # Skip rows with no movement (both sides zero)
        if debit == 0.0 and credit == 0.0:
            skipped += 1
            continue

        balance = _parse_amount(r.get("Running Balance")) or None

        # ── Narration ────────────────────────────────────────────────────────
        narration = _clean(r.get("Description")) or _clean(r.get("Final Particulars")) or "—"

        # ── Pre-categorised fields ────────────────────────────────────────────
        final_group = _clean(r.get("FINAL GROUP"), "Uncategorized")
        group_name  = _clean(r.get("GROUP"),       "")
        main_group  = _clean(r.get("MAIN GROUP"),  "")

        if final_group in ("Uncategorized", ""):
            final_group = "Uncategorized"

        rows.append({
            "entity":              entity,
            "bank":                bank_id,
            "date":                date_str,
            "narration":           narration,
            "debit":               debit,
            "credit":              credit,
            "balance":             balance,
            "category":            final_group,
            "final_group":         final_group,
            "group_name":          group_name,
            "main_group":          main_group,
            "source_file":         os.path.basename(filepath),
            "manually_overridden": 0,
        })

    print(f"[INFO] {len(rows):,} valid rows prepared | {skipped:,} skipped")

    init_db()
    inserted, dup = insert_transactions(rows)
    mark_file_processed(filepath, "All", "ALL", len(rows))
    print(f"[DONE] Inserted: {inserted:,} | Duplicates skipped: {dup:,}")


if __name__ == "__main__":
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    main(fp)

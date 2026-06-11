# BankFlow Configuration

ENTITIES = {
    "Stores":   ["AXIS-8218", "AXIS-7647", "HDFC-5881"],
    "Ventures": ["AXIS-5623", "HDFC-7862", "HDFC-7640"],
}

# ─── AXIS FORMAT ───────────────────────────────────────────────────────────────
# File type: .XLSX
# Header row: Row 19 or 20 (varies slightly per account — auto-detected)
# Columns: S.NO | Transaction Date (dd/mm/yyyy) | Value Date | Particulars |
#          Amount(INR) | Debit/Credit | Balance(INR) | Cheque Number | Branch Name
# Single Amount column + Debit/Credit flag; Opening/Closing Balance rows filtered out.

AXIS_FORMAT = {
    "file_ext": [".xlsx", ".xls"],
    "engine": "openpyxl",
    "header_detect_keyword": "S.NO",
    "columns": {
        "date":       "Transaction Date (dd/mm/yyyy)",
        "narration":  "Particulars",
        "amount":     "Amount(INR)",
        "dr_cr_flag": "Debit/Credit",
        "balance":    "Balance(INR)",
    },
    "date_format": "%d/%m/%Y",
    "amount_is_single_col": True,
}

# ─── HDFC FORMAT ───────────────────────────────────────────────────────────────
# File type: .xls (OLE2 binary, needs xlrd engine)
# Header row: Row 20; separator row (asterisks) on Row 21 — skipped.
# Separate Withdrawal (debit) and Deposit (credit) columns, already numeric.
# Date format: DD/MM/YY (2-digit year)

HDFC_FORMAT = {
    "file_ext": [".xls"],
    "engine": "xlrd",
    "header_detect_keyword": "Date",
    "columns": {
        "date":      "Date",
        "narration": "Narration",
        "debit":     "Withdrawal Amt.",
        "credit":    "Deposit Amt.",
        "balance":   "Closing Balance",
    },
    "date_format": "%d/%m/%y",
    "amount_is_single_col": False,
}

BANK_FORMATS = {
    "AXIS": AXIS_FORMAT,
    "HDFC": HDFC_FORMAT,
}

# Keywords master Excel file (must be in the same folder as these scripts)
KEYWORDS_FILE = "keywords_master.xlsx"
KEYWORDS_SHEET = "Sheet1"

# Database — override via DATABASE_FILE env var on Railway (Volume mount path)
import os as _os
DATABASE_FILE = _os.environ.get("DATABASE_FILE", "data/bankflow.db")

# Large debit alert threshold (₹)
LARGE_DEBIT_THRESHOLD = 1000000

# Narration strings that are not real transactions — filtered out at read time
EXCLUDE_NARRATIONS = [
    "opening balance", "closing balance", "b/f", "brought forward",
    "balance b/f", "balance c/f", "carried forward", "statement summary"
]

# These main_group values are excluded from P&L inflow/outflow calculations
TRANSFER_GROUPS = ["INTERBANK", "INTERCOMPANY"]

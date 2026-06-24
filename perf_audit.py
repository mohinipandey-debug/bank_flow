"""
perf_audit.py — identifies slow DB queries
Run: python perf_audit.py
"""
import sqlite3, time
from config import DATABASE_FILE

conn = sqlite3.connect(DATABASE_FILE)
conn.row_factory = sqlite3.Row

queries = [
    ("Total row count",
     "SELECT COUNT(*) FROM transactions"),
    ("Summary aggregate",
     "SELECT SUM(credit),SUM(debit),COUNT(*) FROM transactions WHERE final_group!='OPENING BALANCE'"),
    ("Uncategorized count",
     "SELECT COUNT(*) FROM transactions WHERE final_group='Uncategorized'"),
    ("Monthly trend",
     "SELECT strftime('%Y-%m',date) as m,SUM(credit),SUM(debit) FROM transactions WHERE final_group!='OPENING BALANCE' GROUP BY m"),
    ("Paginated transactions",
     "SELECT * FROM transactions WHERE financial_year='FY2627' ORDER BY date DESC LIMIT 500"),
    ("Cash flow receipts",
     "SELECT final_group,SUM(credit) FROM transactions WHERE credit>0 AND date BETWEEN '2026-06-01' AND '2026-06-30' GROUP BY final_group"),
    ("Investment transactions",
     "SELECT * FROM transactions WHERE UPPER(main_group)='INVESTMENT'"),
    ("Opening balances",
     "SELECT bank,balance FROM transactions WHERE final_group='OPENING BALANCE'"),
]

print(f"{'Query':<35} {'Time (ms)':>10} {'Rows':>8}")
print("-" * 56)
for label, sql in queries:
    start = time.perf_counter()
    rows  = conn.execute(sql).fetchall()
    ms    = (time.perf_counter() - start) * 1000
    print(f"{label:<35} {ms:>10.1f} {len(rows):>8}")

print()
print("=== EXISTING INDEXES ===")
for r in conn.execute(
    "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name"
).fetchall():
    print(f"  {r[0]} on {r[1]}")

conn.close()

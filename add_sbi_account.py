"""
add_sbi_account.py
One-time script to add SBI-0211 opening balance.
Run once: python add_sbi_account.py
"""
import sqlite3, hashlib, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATABASE_FILE

SBI_BALANCE = 1509789.00
SBI_BANK    = "SBI-0211"
SBI_ENTITY  = "Ventures"

conn = sqlite3.connect(DATABASE_FILE)

for fy, ob_date in [("FY2526", "2025-04-01"), ("FY2627", "2026-04-01")]:
    existing = conn.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE bank=? AND final_group='OPENING BALANCE'
        AND financial_year=?
    """, [SBI_BANK, fy]).fetchone()[0]

    if existing > 0:
        print(f"[SKIP] {fy} OB already exists for SBI-0211")
        continue

    fp = hashlib.md5(
        f"{SBI_ENTITY}|{SBI_BANK}|{ob_date}|OPENING BALANCE"
        f"|0|0|{fy}|SBI".encode()
    ).hexdigest()

    conn.execute("""
        INSERT OR IGNORE INTO transactions
        (fingerprint, entity, bank, date, narration,
         debit, credit, balance, category,
         final_group, group_name, main_group,
         source_file, manually_overridden, financial_year)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        fp, SBI_ENTITY, SBI_BANK, ob_date, "OPENING BALANCE",
        0, 0, SBI_BALANCE, "OPENING BALANCE",
        "OPENING BALANCE", "OPENING BALANCE", "OPENING BALANCE",
        "manual_entry", 1, fy
    ))
    print(f"[OK] Inserted SBI-0211 OB for {fy}: Rs.{SBI_BALANCE:,.2f}")

conn.commit()
conn.close()
print("Done.")

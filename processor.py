import os
import shutil
import argparse
from datetime import datetime
from reader import read_statement
from categorizer import load_keywords, categorize_dataframe
from database import init_db, insert_transactions, mark_file_processed


STATEMENTS_DIR = "statements"
PROCESSED_DIR  = "processed"


def process_file(filepath, keywords=None, entity=None, bank=None, delete_after=False):
    """Full pipeline: read -> categorize -> save -> archive (or delete if delete_after=True)."""
    print(f"\n{'='*55}")
    print(f"[PROCESS] {filepath}")

    df = read_statement(filepath, entity=entity, bank=bank)
    if df.empty:
        print(f"[SKIP] No data extracted from {filepath}")
        return 0, 0

    if keywords is None:
        keywords = load_keywords()

    entity = df["entity"].iloc[0]
    df = categorize_dataframe(df, entity, keywords)

    # ── Exception: flag uncategorized transactions immediately ──────────────
    uncat = df[df["final_group"] == "Uncategorized"]
    if not uncat.empty:
        print(f"\n[!] EXCEPTION — {len(uncat)} uncategorized transaction(s) in "
              f"{os.path.basename(filepath)}:")
        for _, row in uncat.iterrows():
            amt = f"DR Rs.{row['debit']:,.0f}" if row["debit"] > 0 else f"CR Rs.{row['credit']:,.0f}"
            print(f"    {row['date']}  {amt:>18}  {row['narration'][:60]}")
        print(f"[!] Add these narration keywords to keywords_master.xlsx "
              f"and click 'Reload Keywords' in the dashboard.\n")
    # ────────────────────────────────────────────────────────────────────────

    records = df.to_dict("records")
    inserted, skipped = insert_transactions(records)
    print(f"[DB] Inserted: {inserted} | Skipped duplicates: {skipped}")

    bank = df["bank"].iloc[0]
    mark_file_processed(filepath, entity, bank, len(df))

    if delete_after:
        try:
            os.unlink(filepath)
        except OSError:
            pass
        print(f"[CLEANUP] Temp file removed")
    else:
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        basename  = os.path.basename(filepath)
        dest = os.path.join(PROCESSED_DIR, f"{timestamp}_{basename}")
        shutil.move(filepath, dest)
        print(f"[ARCHIVE] Moved to {dest}")

    return inserted, skipped


def scan_all():
    """Load keywords once, then process every statement file found."""
    keywords = load_keywords()
    if not keywords:
        print("[WARN] No keywords loaded — all transactions will be Uncategorized")

    total_inserted = 0
    total_skipped  = 0
    files_found    = 0

    for root, dirs, files in os.walk(STATEMENTS_DIR):
        for filename in sorted(files):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in [".xlsx", ".xls", ".pdf"]:
                continue
            if filename.startswith("~$") or filename.startswith("."):
                continue
            filepath = os.path.join(root, filename)
            ins, skp = process_file(filepath, keywords=keywords)
            total_inserted += ins
            total_skipped  += skp
            files_found    += 1

    if files_found == 0:
        print("\n[INFO] No statement files found in statements/ folder.")
    else:
        print(f"\n{'='*55}")
        print(f"[DONE] Files: {files_found} | "
              f"Inserted: {total_inserted} | Skipped duplicates: {total_skipped}")


if __name__ == "__main__":
    init_db()
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-all", action="store_true")
    parser.add_argument("--file", help="Process a single file")
    args = parser.parse_args()

    if args.scan_all:
        scan_all()
    elif args.file:
        process_file(args.file)
    else:
        scan_all()

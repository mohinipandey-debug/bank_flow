import re
import os
import pandas as pd
from config import KEYWORDS_FILE, KEYWORDS_SHEET

MIN_KEYWORD_LENGTH = 3

# Short keywords requiring word-boundary matching to avoid false positives
BOUNDARY_KEYWORDS = {"GST", "EMI", "TDS", "EPF", "ESI", "MCA"}


# ─── Column Detection ──────────────────────────────────────────────────────────

def detect_columns(df):
    """
    Map keyword-master column headers to internal keys using exact strip-match
    against the actual column names found in the Excel file.

    Returns a dict of internal_key -> actual_col_name.
    """
    col_map = {}
    actual_cols = {c.strip(): c for c in df.columns}

    print(f"[CATEGORIZER] All columns in file: {list(actual_cols.keys())}")

    # Exact names from keywords_master.xlsx (as confirmed by diagnostic)
    STORE_COL   = "Key word for Stores"
    VENTURE_COL = "Key word for Ventures"
    FINAL_GRP   = "FINAL GROUP"
    GROUP_COL   = "GROUP"
    MAIN_GRP    = "MAIN GROUP"
    PAY_REC     = "Payment/Receipt"

    if STORE_COL   in actual_cols: col_map["kw_stores"]       = actual_cols[STORE_COL]
    if VENTURE_COL in actual_cols: col_map["kw_ventures"]     = actual_cols[VENTURE_COL]
    if FINAL_GRP   in actual_cols: col_map["final_group"]     = actual_cols[FINAL_GRP]
    if GROUP_COL   in actual_cols: col_map["group"]           = actual_cols[GROUP_COL]
    if MAIN_GRP    in actual_cols: col_map["main_group"]      = actual_cols[MAIN_GRP]
    if PAY_REC     in actual_cols: col_map["payment_receipt"] = actual_cols[PAY_REC]

    print(f"[CATEGORIZER] Mapped: {col_map}")
    missing = [k for k in ("kw_stores", "kw_ventures", "final_group", "group", "main_group")
               if k not in col_map]
    if missing:
        print(f"[CATEGORIZER] WARNING — unmapped: {missing}")

    return col_map


# ─── Keyword Loader ────────────────────────────────────────────────────────────

def load_keywords():
    """
    Read all keyword rules from KEYWORDS_FILE / KEYWORDS_SHEET.

    Returns a list of rule dicts:
        keyword, entity, final_group, group_name, main_group,
        payment_receipt, boundary_match
    """
    print(f"[KEYWORDS] File  : {os.path.abspath(KEYWORDS_FILE)}")
    print(f"[KEYWORDS] Sheet : {KEYWORDS_SHEET}")

    if not os.path.exists(KEYWORDS_FILE):
        print(f"[KEYWORDS] ERROR: File not found — {KEYWORDS_FILE}")
        return []

    try:
        df = pd.read_excel(KEYWORDS_FILE, sheet_name=KEYWORDS_SHEET, dtype=str)
    except Exception as exc:
        print(f"[KEYWORDS] ERROR reading file: {exc}")
        return []

    df = df.fillna("")
    df.columns = [c.strip() for c in df.columns]

    print(f"[KEYWORDS] Columns found ({len(df.columns)}): {list(df.columns)}")

    col_map = detect_columns(df)
    print(f"[KEYWORDS] Column mapping: {col_map}")

    missing = [k for k in ("kw_stores", "kw_ventures", "final_group") if k not in col_map]
    if missing:
        print(f"[KEYWORDS] WARNING: Could not map these keys: {missing}")
        print("[KEYWORDS] Keyword loading may produce 0 rules.")

    # ── Helper: add one rule for a single keyword string ─────────────────────
    def _add_rule(kw_raw, entity, row_idx, final_group, group_name, main_group, pay_rec, out):
        kw = kw_raw.strip().upper()
        if not kw:
            return
        if len(kw) < MIN_KEYWORD_LENGTH:
            print(f"[KEYWORDS] SKIP short keyword '{kw}' "
                  f"(row {row_idx + 2}, entity={entity}, group={final_group})")
            return
        out.append({
            "keyword":         kw,
            "entity":          entity,
            "final_group":     final_group,
            "group_name":      group_name,
            "main_group":      main_group,
            "payment_receipt": pay_rec,
            "boundary_match":  kw in BOUNDARY_KEYWORDS,
        })

    # ── Walk every data row ───────────────────────────────────────────────────
    keywords = []
    counts = {"Stores": 0, "Ventures": 0}

    fg_col  = col_map.get("final_group", "")
    grp_col = col_map.get("group", "")
    mg_col  = col_map.get("main_group", "")
    pr_col  = col_map.get("payment_receipt", "")
    ks_col  = col_map.get("kw_stores", "")
    kv_col  = col_map.get("kw_ventures", "")

    for row_idx, row in df.iterrows():
        final_group = (row.get(fg_col) or "").strip()  if fg_col  else ""
        group_name  = (row.get(grp_col) or "").strip() if grp_col else ""
        main_group  = (row.get(mg_col) or "").strip()  if mg_col  else ""
        pay_rec     = (row.get(pr_col) or "").strip()  if pr_col  else ""

        if not final_group:
            continue  # skip rows with no category

        # Each cell may contain multiple keywords separated by comma or slash
        for raw_cell, entity in ((row.get(ks_col, ""), "Stores"),
                                 (row.get(kv_col, ""), "Ventures")):
            cell_val = (raw_cell or "").strip()
            if not cell_val:
                continue
            # Split on comma or forward-slash, strip whitespace from each token
            tokens = [t.strip() for t in re.split(r"[,/]", cell_val) if t.strip()]
            for tok in tokens:
                before = len(keywords)
                _add_rule(tok, entity, row_idx, final_group, group_name, main_group, pay_rec, keywords)
                counts[entity] += len(keywords) - before

    print(f"[KEYWORDS] Rules loaded — Stores: {counts['Stores']}, "
          f"Ventures: {counts['Ventures']}, Total: {len(keywords)}")

    if len(keywords) == 0:
        print("[KEYWORDS] WARNING: 0 rules loaded. Check column mapping above.")

    # Check for duplicate keywords (same entity + keyword, different Final Group)
    seen = {}
    duplicates = []
    for rule in keywords:
        key = f"{rule['entity']}::{rule['keyword']}"
        if key in seen:
            duplicates.append({
                "keyword":          rule["keyword"],
                "entity":           rule["entity"],
                "first_maps_to":    seen[key],
                "duplicate_maps_to": rule["final_group"],
            })
        else:
            seen[key] = rule["final_group"]

    if duplicates:
        print(f"\n[CATEGORIZER] WARNING — {len(duplicates)} DUPLICATE KEYWORDS FOUND:")
        print("[CATEGORIZER] The FIRST occurrence wins. Fix these in keywords_master.xlsx:")
        for d in duplicates:
            print(f"  Keyword='{d['keyword']}' Entity={d['entity']}"
                  f" -> '{d['first_maps_to']}' wins over '{d['duplicate_maps_to']}'")
        print()

    return keywords


# ─── Matching ─────────────────────────────────────────────────────────────────

def _matches(rule, narration_upper):
    """Return True if this rule's keyword matches the narration string."""
    kw = rule["keyword"]
    if rule["boundary_match"]:
        pattern = r"(?<![A-Z0-9])" + re.escape(kw) + r"(?![A-Z0-9])"
        return bool(re.search(pattern, narration_upper))
    return kw in narration_upper


# ─── Categorization ───────────────────────────────────────────────────────────

def categorize_narration(narration, entity, keywords, debit=0, credit=0):
    """
    Return the best matching rule dict, or None if no match.

    Priority:
        1. Entity-specific keyword (rule["entity"] == entity)
        2. Rules with no entity restriction are not used — all rules are entity-tagged.

    Special case: "OPENING BALANCE" narration always gets its own category.

    Respects Payment/Receipt flag:
        - Rule 'Payment' → only matches debit > 0 rows
        - Rule 'Receipt' → only matches credit > 0 rows
        - No flag       → matches either side (unchanged behaviour)
    """
    if not narration:
        return None

    if str(narration).strip().upper() == "OPENING BALANCE":
        return {
            "keyword":         "OPENING BALANCE",
            "entity":          entity,
            "final_group":     "OPENING BALANCE",
            "group_name":      "OPENING BALANCE",
            "main_group":      "OPENING BALANCE",
            "payment_receipt": "",
            "boundary_match":  False,
        }

    narration_upper = str(narration).strip().upper()
    debit  = float(debit  or 0)
    credit = float(credit or 0)

    def _side_matches(rule):
        flag = (rule.get("payment_receipt") or "").strip().lower()
        if not flag:
            return True
        if flag == "payment":
            return debit > 0
        if flag == "receipt":
            return credit > 0
        return True

    # Priority 1: entity-specific match
    for rule in keywords:
        if rule["entity"] == entity and _matches(rule, narration_upper) and _side_matches(rule):
            return rule

    # Priority 2: entity-agnostic match (entity=None or entity="")
    for rule in keywords:
        if not rule["entity"] and _matches(rule, narration_upper) and _side_matches(rule):
            return rule

    return None


def categorize_dataframe(df, entity, keywords):
    """
    Categorize every row in df. Never mutates the original DataFrame.
    Returns a copy with final_group, group_name, main_group, category columns set.
    Passes debit/credit per row so Payment/Receipt flag is honoured.
    """
    df = df.copy()

    def _cat_row(row):
        return categorize_narration(
            row["narration"], entity, keywords,
            debit=float(row.get("debit",  0) or 0),
            credit=float(row.get("credit", 0) or 0),
        ) or {}

    results = df.apply(_cat_row, axis=1)

    df["final_group"] = results.apply(lambda r: r.get("final_group") or "Uncategorized")
    df["group_name"]  = results.apply(lambda r: r.get("group_name")  or "")
    df["main_group"]  = results.apply(lambda r: r.get("main_group")  or "")
    df["category"]    = df["final_group"]
    return df


# ─── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("CATEGORIZER SELF-TEST")
    print("=" * 60)

    kws = load_keywords()

    print()
    print(f"Total rules: {len(kws)}")

    stores_rules   = [r for r in kws if r["entity"] == "Stores"]
    ventures_rules = [r for r in kws if r["entity"] == "Ventures"]
    print(f"  Stores rules   : {len(stores_rules)}")
    print(f"  Ventures rules : {len(ventures_rules)}")

    if kws:
        print()
        print("Sample rules (first 5):")
        for r in kws[:5]:
            print(f"  [{r['entity']:>8}] {r['keyword']:<30} -> {r['final_group']}")

    print()
    print("Narration match tests:")
    test_cases = [
        ("NEFT/HDFC/SALARY PAYMENT", "Stores"),
        ("GST PAYMENT 2024", "Ventures"),
        ("OPENING BALANCE", "Stores"),
    ]
    for narr, ent in test_cases:
        result = categorize_narration(narr, ent, kws, debit=1, credit=0)
        if result:
            print(f"  [{ent}] '{narr}'"
                  f"\n         -> matched: '{result['keyword']}' "
                  f"| group: {result['final_group']}")
        else:
            print(f"  [{ent}] '{narr}' -> NO MATCH (Uncategorized)")

    print()
    print("Self-test complete.")

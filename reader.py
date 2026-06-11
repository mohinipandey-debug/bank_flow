import pandas as pd
import os
from config import BANK_FORMATS, EXCLUDE_NARRATIONS


def detect_bank_from_path(filepath):
    parts = filepath.replace("\\", "/").split("/")
    for part in parts:
        pu = part.upper()
        if pu.startswith("AXIS"):
            return "AXIS", part
        elif pu.startswith("HDFC"):
            return "HDFC", part
    return "UNKNOWN", "UNKNOWN"


def detect_entity_from_path(filepath):
    parts = filepath.replace("\\", "/").split("/")
    for part in parts:
        if part.lower() in ["stores", "ventures"]:
            return part.capitalize()
    return "Unknown"


def clean_amount(val):
    """Debit/credit amounts — always returned as positive float."""
    if pd.isna(val) or str(val).strip() in ["", "-", "--", "nan", "None"]:
        return 0.0
    val = str(val).replace(",", "").replace("INR", "").replace("Rs.", "").strip()
    try:
        return abs(float(val))
    except ValueError:
        return 0.0


def clean_balance(val):
    """Balance preserves sign — overdraft accounts can go negative."""
    if pd.isna(val) or str(val).strip() in ["", "-", "--", "nan", "None"]:
        return None
    val = (str(val).replace(",", "").replace("INR", "").replace("Rs.", "")
           .replace("Dr", "-").replace("CR", "").strip())
    try:
        return float(val)
    except ValueError:
        return None


def find_header_row_index(df_raw, keyword):
    kw = keyword.lower().strip()
    # Pass 1: exact cell match — prevents "Date" from matching "A/C Open Date :..."
    for i, row in df_raw.iterrows():
        for val in row.values:
            if isinstance(val, str) and val.strip().lower() == kw:
                return i
    # Pass 2: substring fallback for keywords like "S.NO" with trailing content
    for i, row in df_raw.iterrows():
        for val in row.values:
            if isinstance(val, str) and kw in val.lower():
                return i
    return 0


def read_axis(filepath):
    fmt = BANK_FORMATS["AXIS"]
    df_raw = pd.read_excel(filepath, engine=fmt["engine"], header=None)
    header_idx = find_header_row_index(df_raw, fmt["header_detect_keyword"])

    df = pd.read_excel(filepath, engine=fmt["engine"], header=header_idx, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    cols = fmt["columns"]
    needed = [cols["date"], cols["narration"], cols["amount"], cols["dr_cr_flag"], cols["balance"]]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"[WARN] Axis missing columns: {missing}")
        print(f"       Available: {list(df.columns)}")
        return pd.DataFrame()

    df = df[needed].copy()
    df.columns = ["date", "narration", "amount_raw", "dr_cr", "balance"]

    # Capture opening balance row before any filter (debit=0, credit=0 so it gets dropped later)
    _ob_nr_mask = df["narration"].str.upper().str.strip().str.contains("OPENING BAL", na=False)
    _ob_raw_row = df[_ob_nr_mask].copy()

    df["date"] = pd.to_datetime(df["date"], format=fmt["date_format"], errors="coerce", dayfirst=True)
    df = df[df["date"].notna()].copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    df["amount"] = df["amount_raw"].apply(clean_amount)
    df["dr_cr"]  = df["dr_cr"].str.strip().str.upper()
    df["debit"]  = df.apply(lambda r: r["amount"] if r["dr_cr"] == "DR" else 0.0, axis=1)
    df["credit"] = df.apply(lambda r: r["amount"] if r["dr_cr"] == "CR" else 0.0, axis=1)
    df["balance"] = df["balance"].apply(clean_balance)

    df = df[(df["debit"] > 0) | (df["credit"] > 0)].copy()
    df = df[~df["narration"].str.lower().str.strip().isin(EXCLUDE_NARRATIONS)].copy()

    # Prepend opening balance row (pinned at top, debit=0 credit=0)
    if not _ob_raw_row.empty:
        _ob_r   = _ob_raw_row.iloc[0]
        _ob_bal = clean_balance(_ob_r["balance"])
        _ob_dt  = pd.to_datetime(str(_ob_r["date"]).strip(),
                                  format=fmt["date_format"], errors="coerce", dayfirst=True)
        if pd.isna(_ob_dt) and not df.empty:
            _ob_dt = pd.to_datetime(df["date"].min()) - pd.Timedelta(days=1)
        if not pd.isna(_ob_dt) and _ob_bal is not None:
            ob_frame = pd.DataFrame([{
                "date":      _ob_dt.strftime("%Y-%m-%d"),
                "narration": "OPENING BALANCE",
                "debit":     0.0,
                "credit":    0.0,
                "balance":   _ob_bal,
            }])
            df = pd.concat([ob_frame, df], ignore_index=True)

    return df[["date", "narration", "debit", "credit", "balance"]].reset_index(drop=True)


def read_hdfc(filepath):
    fmt = BANK_FORMATS["HDFC"]
    df_raw = pd.read_excel(filepath, engine=fmt["engine"], header=None)

    # Scan the bottom section of df_raw for the opening balance in the HDFC summary block
    _hdfc_ob_bal = None
    for _ri in range(len(df_raw) - 1, max(len(df_raw) - 40, -1), -1):
        _rrow  = df_raw.iloc[_ri]
        _cells = [str(v).strip() for v in _rrow.values]
        if any("opening bal" in c.lower() for c in _cells):
            # First try: value in the same row
            for _cv in _rrow.values:
                _parsed = clean_balance(str(_cv))
                if _parsed is not None and abs(_parsed) > 0:
                    _hdfc_ob_bal = abs(_parsed)
                    break
            # Second try: this is a header row; find the column index and read next row
            if _hdfc_ob_bal is None and (_ri + 1) < len(df_raw):
                _ob_col = next(
                    (_ci for _ci, _cv in enumerate(_rrow.values)
                     if "opening bal" in str(_cv).lower()), None
                )
                if _ob_col is not None:
                    _parsed = clean_balance(str(df_raw.iloc[_ri + 1].iloc[_ob_col]))
                    if _parsed is not None and abs(_parsed) > 0:
                        _hdfc_ob_bal = abs(_parsed)
            break

    header_idx = find_header_row_index(df_raw, fmt["header_detect_keyword"])

    cols = fmt["columns"]
    df = pd.read_excel(filepath, engine=fmt["engine"], header=header_idx)
    df.columns = [str(c).strip() for c in df.columns]

    needed = [cols["date"], cols["narration"], cols["debit"], cols["credit"], cols["balance"]]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"[WARN] HDFC missing columns: {missing}")
        print(f"       Available: {list(df.columns)}")
        return pd.DataFrame()

    df = df[needed].copy()
    df.columns = ["date", "narration", "debit", "credit", "balance"]

    # Skip separator rows (rows of asterisks that HDFC puts after the header)
    df = df[~df["date"].astype(str).str.startswith("*")].copy()

    df["date"] = pd.to_datetime(df["date"], format=fmt["date_format"], errors="coerce", dayfirst=True)
    df = df[df["date"].notna()].copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    df["debit"]   = df["debit"].apply(clean_amount)
    df["credit"]  = df["credit"].apply(clean_amount)
    df["balance"] = df["balance"].apply(clean_balance)

    df = df[(df["debit"] > 0) | (df["credit"] > 0)].copy()
    df = df[~df["narration"].str.lower().str.strip().isin(EXCLUDE_NARRATIONS)].copy()

    # Prepend HDFC opening balance row from summary block
    if _hdfc_ob_bal is not None and not df.empty:
        _ob_dt   = pd.to_datetime(df["date"].min()) - pd.Timedelta(days=1)
        ob_frame = pd.DataFrame([{
            "date":      _ob_dt.strftime("%Y-%m-%d"),
            "narration": "OPENING BALANCE",
            "debit":     0.0,
            "credit":    0.0,
            "balance":   _hdfc_ob_bal,
        }])
        df = pd.concat([ob_frame, df], ignore_index=True)

    return df[["date", "narration", "debit", "credit", "balance"]].reset_index(drop=True)


def read_statement(filepath, entity=None, bank=None):
    _bank_type_auto, _account_id_auto = detect_bank_from_path(filepath)
    _entity_auto = detect_entity_from_path(filepath)

    entity     = entity or _entity_auto
    account_id = bank   or _account_id_auto
    if bank:
        bank_type = ("AXIS" if bank.upper().startswith("AXIS") else
                     "HDFC" if bank.upper().startswith("HDFC") else _bank_type_auto)
    else:
        bank_type = _bank_type_auto

    if entity == "Unknown" or bank_type == "UNKNOWN":
        print(
            f"[SKIP] Cannot detect entity/bank from path: {filepath} — "
            f"rename folder to Stores/Ventures and account ID before processing"
        )
        return pd.DataFrame()

    print(f"\n[READER] {os.path.basename(filepath)} -> {entity} / {account_id}")

    try:
        if bank_type == "AXIS":
            df = read_axis(filepath)
        elif bank_type == "HDFC":
            df = read_hdfc(filepath)
        else:
            print(f"[WARN] Unknown bank type, trying Axis format for: {filepath}")
            df = read_axis(filepath)
    except Exception as e:
        print(f"[ERROR] {filepath}: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame()

    if df.empty:
        print(f"[WARN] No transactions extracted from {os.path.basename(filepath)}")
        return df

    df["entity"]      = entity
    df["bank"]        = account_id   # explicit override or auto-detected
    df["source_file"] = os.path.basename(filepath)

    print(f"[READER] OK: {len(df)} transactions | "
          f"Debits: Rs.{df['debit'].sum():,.0f} | Credits: Rs.{df['credit'].sum():,.0f}")
    return df


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        df = read_statement(sys.argv[1])
        if not df.empty:
            print(df.head(10).to_string())

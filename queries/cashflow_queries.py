"""Cash Flow DB queries — extracted from dashboard.py Cash Flow tab."""

import sqlite3
import datetime as _dt


def get_bank_closing_balance(entity, d_to, db_file=None):
    """
    Get the last actual balance per bank from DB on or before d_to.
    Returns dict: {bank: balance}
    """
    if db_file is None:
        from config import DATABASE_FILE
        db_file = DATABASE_FILE

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    entity_clause = ""
    entity_params = []
    if entity and entity != "All":
        entity_clause = "AND entity = ?"
        entity_params = [entity]

    banks = conn.execute(f"""
        SELECT DISTINCT bank FROM transactions
        WHERE final_group != 'OPENING BALANCE'
        {entity_clause}
    """, entity_params).fetchall()

    closing = {}
    for b in banks:
        bank = b["bank"]
        row = conn.execute(f"""
            SELECT balance FROM transactions
            WHERE bank = ?
            AND final_group != 'OPENING BALANCE'
            AND date <= ?
            AND balance IS NOT NULL
            {entity_clause}
            ORDER BY date DESC, id DESC
            LIMIT 1
        """, [bank, d_to] + entity_params).fetchone()
        if row and row["balance"] is not None:
            closing[bank] = row["balance"]

    conn.close()
    return closing


def fetch_cf(entity, d_from, d_to, db_file, financial_year=None):
    """
    Returns all Cash Flow data for entity + date range.
    Rule: credit > 0 = receipt, debit > 0 = payout.
    All categories (including Bank Charges) flow through normally.
    """
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    entity_clause = ""
    entity_params = []
    if entity and entity != "All":
        entity_clause = "AND entity = ?"
        entity_params = [entity]

    fy_clause = " AND financial_year = ?" if financial_year else ""
    fy_param  = [financial_year]          if financial_year else []

    # ── Opening balance — last actual balance per bank on or before (d_from - 1) ─
    # Works for any start date: mid-year week, mid-month, or FY start.
    # Falls back to OPENING BALANCE row only when no transactions exist before d_from.
    d_before = str(_dt.date.fromisoformat(d_from) - _dt.timedelta(days=1))

    banks = conn.execute(f"""
        SELECT DISTINCT bank FROM transactions
        WHERE 1=1 {entity_clause}
    """, entity_params).fetchall()

    opening_balances = {}
    for b in banks:
        bank = b["bank"]
        row = conn.execute(f"""
            SELECT balance FROM transactions
            WHERE bank = ?
            AND date <= ?
            AND balance IS NOT NULL
            AND final_group != 'OPENING BALANCE'
            {entity_clause}
            ORDER BY date DESC, id DESC
            LIMIT 1
        """, [bank, d_before] + entity_params).fetchone()

        if row and row["balance"] is not None:
            opening_balances[bank] = row["balance"]
        else:
            # Fallback: FY start — use earliest OPENING BALANCE row for this bank
            ob_row = conn.execute(f"""
                SELECT balance FROM transactions
                WHERE bank = ?
                AND final_group = 'OPENING BALANCE'
                {entity_clause}
                ORDER BY date ASC LIMIT 1
            """, [bank] + entity_params).fetchone()
            opening_balances[bank] = (ob_row["balance"] if ob_row else 0) or 0

    # ── Receipts — ALL credit > 0 transactions, no exclusions ─────────────────
    receipts = conn.execute(f"""
        SELECT
            COALESCE(NULLIF(TRIM(group_name), ''), 'Other') as group_name,
            CASE
                WHEN final_group IS NULL OR TRIM(final_group) = ''
                     OR final_group = 'Uncategorized'
                THEN 'Uncategorized'
                ELSE final_group
            END as category,
            ROUND(SUM(credit), 2) as total
        FROM transactions
        WHERE credit > 0
        AND final_group != 'OPENING BALANCE'
        AND date BETWEEN ? AND ? {entity_clause} {fy_clause}
        GROUP BY group_name, category
        ORDER BY group_name, total DESC
    """, [d_from, d_to] + entity_params + fy_param).fetchall()

    # ── Payouts — ALL debit > 0 transactions, no exclusions ───────────────────
    payouts = conn.execute(f"""
        SELECT
            COALESCE(NULLIF(TRIM(group_name), ''), 'Other') as group_name,
            CASE
                WHEN final_group IS NULL OR TRIM(final_group) = ''
                     OR final_group = 'Uncategorized'
                THEN 'Uncategorized'
                ELSE final_group
            END as category,
            ROUND(SUM(debit), 2) as total
        FROM transactions
        WHERE debit > 0
        AND final_group != 'OPENING BALANCE'
        AND date BETWEEN ? AND ? {entity_clause} {fy_clause}
        GROUP BY group_name, category
        ORDER BY group_name, total DESC
    """, [d_from, d_to] + entity_params + fy_param).fetchall()

    # ── Closing balance — computed from formula per bank ──────────────────────
    # Opening + ALL credits - ALL debits (interbank + intercompany included)
    # so that the tally always holds exactly.
    closing_balances = {}
    for bank, ob in opening_balances.items():
        row = conn.execute(f"""
            SELECT
                ROUND(SUM(CASE WHEN credit > 0 THEN credit ELSE 0 END), 2) as cr,
                ROUND(SUM(CASE WHEN debit  > 0 THEN debit  ELSE 0 END), 2) as dr
            FROM transactions
            WHERE bank = ?
            AND date BETWEEN ? AND ?
            AND final_group != 'OPENING BALANCE'
            {entity_clause}
        """, [bank, d_from, d_to] + entity_params).fetchone()
        bank_cr = row["cr"] or 0
        bank_dr = row["dr"] or 0
        closing_balances[bank] = round((ob or 0) + bank_cr - bank_dr, 2)

    total_closing = sum(closing_balances.values())

    # ── Interbank / Intercompany period net (CR - DR) ─────────────────────────
    # Used as reconciling lines: net ≠ 0 signals missing statements or mis-tags.
    def _period_net(prefix):
        row = conn.execute(f"""
            SELECT
                ROUND(SUM(CASE WHEN credit > 0 THEN credit ELSE 0 END), 2) as cr,
                ROUND(SUM(CASE WHEN debit  > 0 THEN debit  ELSE 0 END), 2) as dr
            FROM transactions
            WHERE (UPPER(final_group) LIKE UPPER(?)
                OR UPPER(group_name)  LIKE UPPER(?)
                OR UPPER(main_group)  LIKE UPPER(?))
            AND date BETWEEN ? AND ?
            {entity_clause}
        """, [f"{prefix}%", f"{prefix}%", f"{prefix}%",
              d_from, d_to] + entity_params).fetchone()
        cr = row["cr"] or 0
        dr = row["dr"] or 0
        return round(cr - dr, 2)

    interbank_period_net    = _period_net("INTERBANK")
    intercompany_period_net = _period_net("INTERCOMPANY")

    conn.close()

    # ── Build nested {group_name: {final_group: amount}} structure ─────────────
    def _build_nested(rows):
        nested = {}
        for r in rows:
            grp = r["group_name"]
            cat = r["category"]
            amt = r["total"] or 0
            if grp not in nested:
                nested[grp] = {}
            nested[grp][cat] = nested[grp].get(cat, 0) + amt
        return nested

    receipts_nested = _build_nested(receipts)
    payouts_nested  = _build_nested(payouts)

    # ── Interbank / Intercompany netting ───────────────────────────────────────
    INTERBANK_KEYS    = ["INTERBANK", "Interbank", "INTERBANK TRANSFER", "Interbank Transfer"]
    INTERCOMPANY_KEYS = ["INTERCOMPANY", "Intercompany", "INTERCOMPANY TRANSFER", "Intercompany Transfer"]

    def _extract_group(nested, keys):
        """Remove matching groups from nested dict; return their combined total."""
        total      = 0
        upper_keys = [k.upper() for k in keys]
        for k in list(nested.keys()):
            if k.strip().upper() in upper_keys:
                total += sum(nested[k].values())
                del nested[k]
        return total

    # Interbank netting — always applied
    ib_receipts = _extract_group(receipts_nested, INTERBANK_KEYS)
    ib_payouts  = _extract_group(payouts_nested,  INTERBANK_KEYS)
    ib_net      = ib_receipts - ib_payouts
    if abs(ib_net) > 1000:
        if ib_net > 0:
            receipts_nested["Interbank (Net)"] = {"Interbank (Net)": ib_net}
        else:
            payouts_nested["Interbank (Net)"]  = {"Interbank (Net)": abs(ib_net)}
    interbank_net_info = {
        "receipts": ib_receipts,
        "payouts":  ib_payouts,
        "net":      ib_net,
        "material": abs(ib_net) > 1000,
    }

    # Intercompany netting — only when showing all entities (entity is None)
    ic_net_info = {"receipts": 0, "payouts": 0, "net": 0, "material": False}
    if entity is None:
        ic_receipts = _extract_group(receipts_nested, INTERCOMPANY_KEYS)
        ic_payouts  = _extract_group(payouts_nested,  INTERCOMPANY_KEYS)
        ic_net      = ic_receipts - ic_payouts
        ic_net_info = {
            "receipts": ic_receipts,
            "payouts":  ic_payouts,
            "net":      ic_net,
            "material": abs(ic_net) > 1000,
        }
        if abs(ic_net) > 1000:
            if ic_net > 0:
                receipts_nested["Intercompany (Net)"] = {"Intercompany (Net)": ic_net}
            else:
                payouts_nested["Intercompany (Net)"]  = {"Intercompany (Net)": abs(ic_net)}

    _total_rec = sum(sum(v.values()) for v in receipts_nested.values())
    _total_pay = sum(sum(v.values()) for v in payouts_nested.values())

    return {
        "opening_balances":        opening_balances,
        # flat dicts kept for Excel export / backwards-compat
        "receipts":                {r["category"]: r["total"] or 0 for r in receipts},
        "payouts":                 {r["category"]: r["total"] or 0 for r in payouts},
        # nested dicts for GROUP → FINAL GROUP hierarchy display (post-netting)
        "receipts_nested":         receipts_nested,
        "payouts_nested":          payouts_nested,
        "closing_balances":        closing_balances,
        "total_opening":           sum(opening_balances.values()),
        "total_receipts":          _total_rec,   # post-netting (matches breakdown display)
        "total_payouts":           _total_pay,   # post-netting (matches breakdown display)
        "total_closing":           total_closing,
        "net_cash_flow":           total_closing - sum(opening_balances.values()),
        # Reconciling: non-zero signals a missing statement or mis-tagged transaction
        "interbank_net":           interbank_period_net    if abs(interbank_period_net)    > 1 else None,
        "intercompany_net":        intercompany_period_net if abs(intercompany_period_net) > 1 else None,
        "interbank_period_net":    interbank_period_net,
        "intercompany_period_net": intercompany_period_net,
    }

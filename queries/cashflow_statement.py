"""
Cash Flow Statement — Operating / Investing / Financing (direct method), management view.

Every transaction of the period is classified by its category through the `cashflow_map` table
(see database._CF_MAP_SEED) and each line is NET (credits - debits), so a bounce-back or refund
reduces the same line it came from instead of showing up as a receipt.

Perimeter = bank balances + Cash at Stores + Mutual funds and FDs at cost (the "total cash position"
on the top banner). Opening and closing are therefore like-for-like. A purchase / redemption of MF or FD
only moves money inside the perimeter, so the Investing lines show just the gain / interest realised:
  ledger net of the MF / FD transactions + change in the MF / FD balance at cost.

Accuracy controls (returned in `checks`):
  1. lines_vs_ledger : sum of all lines (net of the store-cash adjustment) == sum(credit - debit) of the
                       period's transactions — nothing dropped or double counted.
  2. closing_vs_bank : opening position + net movement == actual closing (last bank balances +
                       Cash at Stores + MF + FD at cost). Non-zero means a statement day is missing or a balance
                       is broken — it is shown, never hidden.
"""

import datetime as _dt
import sqlite3

from database import _CF_MAP_SEED, get_cashflow_map

ACTIVITY_ORDER = ["Operating", "Investing", "Financing", "Pending review"]
_BUCKET_ORDER = {}
_SUB_ORDER = {}
for _i, (_cat, _act, _bk, _sb, _ft) in enumerate(_CF_MAP_SEED):
    _BUCKET_ORDER.setdefault((_act, _bk), _i)
    _SUB_ORDER.setdefault((_act, _bk, _sb), _i)
_SUB_ORDER[("Investing", "Treasury investments", "Mutual funds")] = _SUB_ORDER.get(
    ("Investing", "Treasury investments", "Mutual funds"), 900)
_SUB_ORDER[("Investing", "Treasury investments", "Fixed deposits")] = _SUB_ORDER.get(
    ("Investing", "Treasury investments", "Fixed deposits"), 901)

MF_SUB = "Mutual funds - gain / (loss) and balance adjustments"
FD_SUB = "Fixed deposits - interest and balance adjustments"
NOT_IN_BAL_SUB = "MF / FD transactions not in the investment balance"
CASH_DEP_SUB = "Cash deposited in banks"
STORE_CASH_SUB = "Increase / (decrease) in cash held at stores"
_SUB_ORDER[("Investing", "Treasury investments", MF_SUB)] = 900
_SUB_ORDER[("Investing", "Treasury investments", FD_SUB)] = 901
_SUB_ORDER[("Investing", "Treasury investments", NOT_IN_BAL_SUB)] = 902

INTERBANK = "Interbank transfer"
INTERCOMPANY = "Intercompany transfers"


def _connect():
    from config import DATABASE_FILE
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _bank_balances(conn, entity, as_of):
    """{bank: last actual balance on or before as_of}; falls back to the account's opening-balance row."""
    ec, ep = ("AND entity = ?", [entity]) if entity else ("", [])
    banks = [r["bank"] for r in conn.execute(
        f"SELECT DISTINCT bank FROM transactions WHERE 1=1 {ec}", ep).fetchall()]
    out = {}
    for b in banks:
        row = conn.execute(
            f"SELECT balance FROM transactions WHERE bank=? AND date<=? AND balance IS NOT NULL "
            f"AND final_group != 'OPENING BALANCE' {ec} ORDER BY date DESC, ord_key DESC LIMIT 1",
            [b, as_of] + ep).fetchone()
        if row and row["balance"] is not None:
            out[b] = row["balance"]
        else:
            ob = conn.execute(
                f"SELECT balance FROM transactions WHERE bank=? AND final_group='OPENING BALANCE' {ec} "
                f"ORDER BY date ASC LIMIT 1", [b] + ep).fetchone()
            out[b] = (ob["balance"] if ob else 0) or 0
    return out


def build_statement(entity, d_from, d_to):
    """
    entity: None (All) / 'Stores' / 'Ventures';  d_from / d_to: ISO dates (inclusive).
    Returns a dict — see module docstring. Amounts are signed: inflow +, outflow -.
    """
    from queries.cashflow_queries import get_mf_fd_cash_asof
    from config import DATABASE_FILE
    entity = None if entity in (None, "All") else entity
    d_before = str(_dt.date.fromisoformat(d_from) - _dt.timedelta(days=1))
    cmap = {k.lower(): v for k, v in get_cashflow_map().items()}

    conn = _connect()
    ec, ep = ("AND t.entity = ?", [entity]) if entity else ("", [])
    rows = conn.execute(f"""
        SELECT COALESCE(NULLIF(TRIM(t.final_group), ''), 'Uncategorized') AS cat,
               COALESCE(NULLIF(m.st, ''), 'FD') AS scheme_type,
               CASE WHEN UPPER(t.main_group) = 'INVESTMENT' THEN 1 ELSE 0 END AS in_bal,
               ROUND(SUM(COALESCE(t.credit, 0)), 2) AS cr, ROUND(SUM(COALESCE(t.debit, 0)), 2) AS dr
        FROM transactions t
        LEFT JOIN (SELECT transaction_id, MAX(scheme_type) AS st FROM investment_txn_mapping
                   GROUP BY transaction_id) m ON t.id = m.transaction_id
        WHERE t.date BETWEEN ? AND ? AND t.final_group != 'OPENING BALANCE' {ec}
        GROUP BY cat, scheme_type, in_bal""", [d_from, d_to] + ep).fetchall()
    open_banks = _bank_balances(conn, entity, d_before)
    close_banks = _bank_balances(conn, entity, d_to)
    conn.close()

    open_x = get_mf_fd_cash_asof(entity, d_before, DATABASE_FILE)
    close_x = get_mf_fd_cash_asof(entity, d_to, DATABASE_FILE)
    cash_adj = close_x["cash"] - open_x["cash"]

    lines = {}        # (activity, bucket, sub_bucket) -> net
    internal = {}     # label -> net
    ledger_net = 0.0
    derived_key = None

    def add(d, k, v):
        d[k] = round(d.get(k, 0.0) + v, 2)

    for r in rows:
        cat, st, net = r["cat"], r["scheme_type"], round((r["cr"] or 0) - (r["dr"] or 0), 2)
        ledger_net += net
        low = cat.lower()
        m = cmap.get(low)
        if low.startswith("interbank"):
            add(internal, INTERBANK, net)
            continue
        if low.startswith("intercompany") and entity is None:
            add(internal, INTERCOMPANY, net)
            continue
        if m is None:
            add(lines, ("Pending review", "Pending review", f"Unmapped category: {cat}"), net)
            continue
        sub = m["sub_bucket"]
        if m["bucket"] == "Treasury investments":
            is_mf = low == "mutual fund" or (low == "investment" and st == "MF")
            sub = MF_SUB if is_mf else FD_SUB
            if not r["in_bal"]:
                # not part of the MF / FD balance used by the banner, so the balance change cannot net it
                sub = NOT_IN_BAL_SUB
        elif m["flow_type"] == "derived":
            sub = CASH_DEP_SUB
        key = (m["activity"], m["bucket"], sub)
        if m["flow_type"] == "derived":
            derived_key = key
        add(lines, key, net)

    # Cash sales = cash deposited into the bank + change in cash still lying at stores
    if abs(cash_adj) >= 0.005:
        base = derived_key or ("Operating", "Customer receipts", CASH_DEP_SUB)
        key = (base[0], base[1], STORE_CASH_SUB)
        _SUB_ORDER[key] = _SUB_ORDER.get(base, 0) + 0.5
        add(lines, key, cash_adj)

    # MF / FD are inside the perimeter: their change at cost is part of the movement, and nets the
    # purchase / redemption cash flows down to the gain / interest actually realised.
    d_mf = round(close_x["mf"] - open_x["mf"], 2)
    d_fd = round(close_x["fd"] - open_x["fd"], 2)
    for sub, dv in ((MF_SUB, d_mf), (FD_SUB, d_fd)):
        if abs(dv) >= 0.005:
            add(lines, ("Investing", "Treasury investments", sub), dv)

    # ── totals / checks ───────────────────────────────────────────────────────
    act_tot = {a: round(sum(v for (a2, _, _), v in lines.items() if a2 == a), 2) for a in ACTIVITY_ORDER}
    internal_tot = round(sum(internal.values()), 2)
    net_change = round(sum(act_tot.values()) + internal_tot, 2)

    opening_total = round(sum(open_banks.values()) + open_x["cash"] + open_x["mf"] + open_x["fd"], 2)
    closing_actual = round(sum(close_banks.values()) + close_x["cash"] + close_x["mf"] + close_x["fd"], 2)
    closing_calc = round(opening_total + net_change, 2)
    checks = {
        "lines_vs_ledger": round(net_change - cash_adj - d_mf - d_fd - ledger_net, 2),
        "closing_vs_bank": round(closing_calc - closing_actual, 2),
    }
    return {
        "d_from": d_from, "d_to": d_to,
        "opening": {"banks": open_banks, "cash": open_x["cash"], "mf": open_x["mf"], "fd": open_x["fd"],
                    "total": opening_total},
        "lines": lines, "internal": internal, "act_tot": act_tot, "internal_tot": internal_tot,
        "net_change": net_change,
        "closing_calc": closing_calc,
        "closing_actual": {"banks": close_banks, "cash": close_x["cash"], "mf": close_x["mf"], "fd": close_x["fd"],
                           "total": closing_actual},
        "memo": {"mf": close_x["mf"], "fd": close_x["fd"],
                 "total_position": closing_actual},
        "checks": checks,
    }


def structure(stmts):
    """Ordered hierarchy present in any of the statements: [(activity, [(bucket, [sub,...]), ...]), ...]."""
    seen = {}
    for s in stmts:
        for (a, b, sb) in s["lines"]:
            seen.setdefault(a, {}).setdefault(b, set()).add(sb)
    out = []
    for a in ACTIVITY_ORDER:
        if a not in seen:
            continue
        bks = sorted(seen[a], key=lambda b: (_BUCKET_ORDER.get((a, b), 999), b))
        out.append((a, [(b, sorted(seen[a][b], key=lambda sb: (_SUB_ORDER.get((a, b, sb), 999), sb)))
                        for b in bks]))
    return out


def combine(stmts):
    """'Total' column for consecutive, non-overlapping periods: flows add up; opening = first, closing = last."""
    if not stmts:
        return None
    first, last = stmts[0], stmts[-1]
    lines, internal = {}, {}
    for s in stmts:
        for k, v in s["lines"].items():
            lines[k] = round(lines.get(k, 0.0) + v, 2)
        for k, v in s["internal"].items():
            internal[k] = round(internal.get(k, 0.0) + v, 2)
    act_tot = {a: round(sum(s["act_tot"][a] for s in stmts), 2) for a in ACTIVITY_ORDER}
    return {
        "d_from": first["d_from"], "d_to": last["d_to"],
        "opening": first["opening"], "lines": lines, "internal": internal, "act_tot": act_tot,
        "internal_tot": round(sum(s["internal_tot"] for s in stmts), 2),
        "net_change": round(sum(s["net_change"] for s in stmts), 2),
        "closing_calc": last["closing_calc"], "closing_actual": last["closing_actual"],
        "memo": last["memo"],
        "checks": {"lines_vs_ledger": round(sum(s["checks"]["lines_vs_ledger"] for s in stmts), 2),
                   "closing_vs_bank": last["checks"]["closing_vs_bank"]},
    }


def build_workbook(stmts, labels, title, entity_label):
    """Excel bytes: 'Cash Flow' (full hierarchy) + 'Reconciliation' (checks and memo bridge)."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    cols = list(stmts)
    heads = list(labels)
    tot = None
    if len(stmts) > 1:
        tot = combine(stmts)
        cols = cols + [tot]
        heads = heads + ["Total"]
    n = len(cols)
    NUM = '#,##0;[Red](#,##0);"-"'
    hdr_fill = PatternFill("solid", fgColor="F1F3F5")
    tot_fill = PatternFill("solid", fgColor="E8F4FD")
    navy = PatternFill("solid", fgColor="1B2B4B")

    wb = Workbook()
    ws = wb.active
    ws.title = "Cash Flow"
    ws.column_dimensions["A"].width = 52
    for i in range(n):
        ws.column_dimensions[chr(66 + i)].width = 20
    ws.append([f"Cash Flow Statement — {title} — {entity_label}"])
    ws["A1"].font = Font(bold=True, size=13, color="1B2B4B")
    ws.append(["Direct method · figures in ₹ · inflows positive, outflows in (brackets)"])
    ws["A2"].font = Font(italic=True, size=9, color="6B7A90")
    ws.append(["Particulars"] + heads)
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = navy
        c.alignment = Alignment(horizontal="right" if c.column > 1 else "left")

    def put(label, vals, indent=0, style="normal"):
        ws.append([("    " * indent) + label] + [None if v is None else v for v in vals])
        r = ws.max_row
        for c in range(2, n + 2):
            ws.cell(r, c).number_format = NUM
            ws.cell(r, c).alignment = Alignment(horizontal="right")
        for c in ws[r]:
            if style == "head":
                c.font = Font(bold=True, size=11)
                c.fill = hdr_fill
            elif style == "total":
                c.font = Font(bold=True, color="1E3A5F")
                c.fill = tot_fill
                c.border = Border(top=Side(style="medium", color="4E8DF5"),
                                  bottom=Side(style="medium", color="4E8DF5"))
            elif style == "bold":
                c.font = Font(bold=True)

    put("Opening balance (cash, bank, MF & FD at cost)", [s["opening"]["total"] for s in cols], style="head")
    for bk in sorted({b for s in stmts for b in s["opening"]["banks"]}):
        put(f"Bank ({bk})", [s["opening"]["banks"].get(bk, 0) for s in cols], 1)
    put("Cash at Stores", [s["opening"]["cash"] for s in cols], 1)
    put("Mutual funds at cost", [s["opening"]["mf"] for s in cols], 1)
    put("Fixed deposits at cost", [s["opening"]["fd"] for s in cols], 1)

    names = {"Operating": "A. Cash flows from operating activities",
             "Investing": "B. Cash flows from investing activities",
             "Financing": "C. Cash flows from financing activities",
             "Pending review": "D. Pending review (uncategorised / unmapped)"}
    for act, buckets in structure(stmts):
        put(names[act], [s["act_tot"][act] for s in cols], style="total")
        for bk, subs in buckets:
            put(bk, [sum(v for (a, b, _), v in s["lines"].items() if a == act and b == bk) for s in cols],
                1, "bold")
            for sb in subs:
                put(sb, [s["lines"].get((act, bk, sb), 0) for s in cols], 2)
    put("Net increase / (decrease) in cash & bank (A+B+C+D)",
        [round(sum(s["act_tot"].values()), 2) for s in cols], style="total")
    put("Internal movements (net, should be nil)", [s["internal_tot"] for s in cols], style="head")
    for lbl in (INTERBANK, INTERCOMPANY):
        if any(abs(s["internal"].get(lbl, 0)) > 0.5 for s in cols):
            put(lbl, [s["internal"].get(lbl, 0) for s in cols], 1)
    put("Closing balance (cash, bank, MF & FD at cost) - matches the top banner",
        [s["closing_calc"] for s in cols], style="total")
    for bk in sorted({b for s in stmts for b in s["closing_actual"]["banks"]}):
        put(f"Bank ({bk})", [s["closing_actual"]["banks"].get(bk, 0) for s in cols], 1)
    put("Cash at Stores", [s["closing_actual"]["cash"] for s in cols], 1)
    put("Mutual funds at cost", [s["closing_actual"]["mf"] for s in cols], 1)
    put("Fixed deposits at cost", [s["closing_actual"]["fd"] for s in cols], 1)
    put("Difference vs actual closing", [s["checks"]["closing_vs_bank"] for s in cols], 1, "bold")
    ws.freeze_panes = "B4"

    # ── Reconciliation sheet ──
    rs = wb.create_sheet("Reconciliation")
    rs.column_dimensions["A"].width = 56
    for i in range(n):
        rs.column_dimensions[chr(66 + i)].width = 20
    rs.append(["Reconciliation"] + heads)
    for c in rs[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = navy
        c.alignment = Alignment(horizontal="right" if c.column > 1 else "left")

    def rput(label, vals, bold=False):
        rs.append([label] + list(vals))
        r = rs.max_row
        for c in range(2, n + 2):
            rs.cell(r, c).number_format = NUM
            rs.cell(r, c).alignment = Alignment(horizontal="right")
            if bold:
                rs.cell(r, c).font = Font(bold=True)
        rs.cell(r, 1).font = Font(bold=bold)

    rput("Opening balance (banks + Cash at Stores + MF + FD at cost)", [s["opening"]["total"] for s in cols], True)
    for act in ACTIVITY_ORDER:
        rput(f"  {names[act]}", [s["act_tot"][act] for s in cols])
    rput("  Internal movements (net)", [s["internal_tot"] for s in cols])
    rput("Closing balance - computed", [s["closing_calc"] for s in cols], True)
    rput("Closing balance - actual (banks + Cash at Stores + MF + FD at cost)", [s["closing_actual"]["total"] for s in cols], True)
    rput("Difference (must be nil)", [s["checks"]["closing_vs_bank"] for s in cols], True)
    rput("Lines vs ledger difference (must be nil)", [s["checks"]["lines_vs_ledger"] for s in cols], True)
    rs.append([])
    rs.append([])
    rs.append(["Basis: each line is net of credits and debits of its categories (refunds / bounce-backs reduce the same "
               "line). Cash sales = cash deposited + change in Cash at Stores. MF / FD purchases and redemptions are internal to the balance; only gain / interest realised is shown. Mapping: table cashflow_map."])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

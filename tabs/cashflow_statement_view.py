"""Cash Flow tab — Operating / Investing / Financing statement (Weekly and MTD)."""

import datetime

import streamlit as st

from queries.cashflow_statement import (
    ACTIVITY_ORDER, INTERBANK, INTERCOMPANY, build_statement, build_workbook, combine, structure,
)
from utils.formatters import _group_indian

_CSS = """
<style>
.cfs-title { display:flex; justify-content:space-between; align-items:baseline; margin:10px 0 8px; }
.cfs-title b { font-size:20px; color:#0A1628; letter-spacing:-0.3px; }
.cfs-title span { font-size:13px; color:#6B7A90; }
.cfs-hdr { background:#1B2B4B; color:#fff; font-size:11.5px; font-weight:700; letter-spacing:0.05em;
  padding:9px 14px; text-align:right; border-radius:0; min-height:36px; display:flex; align-items:center; justify-content:flex-end; }
.cfs-hdr.l { justify-content:flex-start; border-radius:8px 0 0 8px; }
.cfs-lbl, .cfs-v { display:flex; align-items:center; min-height:34px; font-size:13.5px; color:#1F2937;
  font-variant-numeric:tabular-nums; }
.cfs-lbl { padding-left:12px; }
.cfs-v { justify-content:flex-end; padding-right:14px; }
.cfs-neg { color:#B91C1C; }
.cfs-dim { color:#9CA3AF; }
.cfs-open .cfs-lbl, .cfs-open .cfs-v { background:#EAF0FA; color:#1B2B4B; font-weight:700; }
.cfs-act { }
.cfs-act.A .cfs-lbl, .cfs-act.A .cfs-v { background:#EAF0FA; color:#1B2B4B; font-weight:700; border-left:0; }
.cfs-bk .cfs-lbl, .cfs-bk .cfs-v { background:#F8FAFC; font-weight:600; }
.cfs-sub .cfs-lbl, .cfs-sub .cfs-v { background:#FFFFFF; color:#374151; }
.cfs-sub .cfs-lbl { padding-left:56px; }
.cfs-bk .cfs-lbl { padding-left:30px; }
.cfs-tot .cfs-lbl, .cfs-tot .cfs-v { background:#14233F; color:#fff; font-weight:800; }
.cfs-tot .cfs-neg { color:#FCA5A5; }
.cfs-net .cfs-lbl, .cfs-net .cfs-v { background:#EAF0FA; color:#1B2B4B; font-weight:800; border-top:2px solid #1B2B4B; }
.cfs-memo .cfs-lbl, .cfs-memo .cfs-v { background:#FFFFFF; color:#6B7A90; font-size:12.5px; }
.cfs-ok .cfs-lbl, .cfs-ok .cfs-v { background:#F0FDF4; color:#166534; font-weight:700; }
.cfs-bad .cfs-lbl, .cfs-bad .cfs-v { background:#FEF2F2; color:#991B1B; font-weight:700; }
.cfs-pend .cfs-lbl, .cfs-pend .cfs-v { background:#FFF7ED; color:#7C2D12; font-weight:700; }
</style>
"""


@st.cache_data(ttl=300, show_spinner=False)
def _stmt(entity, d_from, d_to):
    return build_statement(entity, d_from, d_to)


def _num(v, tot=False):
    """Accounting style: 1,23,456 / (1,23,456) in red / — for nil."""
    if v is None or abs(v) < 0.5:
        return '<span class="cfs-dim">—</span>'
    n = _group_indian(int(round(abs(v))))
    return f'<span class="cfs-neg">({n})</span>' if v < 0 else n


def _toggle(key):
    st.session_state[key] = not st.session_state.get(key, False)


def _week_ranges(anchor):
    w4s = anchor - datetime.timedelta(days=anchor.weekday())
    ranges = [(w4s, anchor)]
    end = w4s - datetime.timedelta(days=1)
    for _ in range(3):
        ranges.insert(0, (end - datetime.timedelta(days=6), end))
        end = end - datetime.timedelta(days=7)
    return ranges


def render_cashflow_statement(view, entity, mtd_from, mtd_to, week_anchor):
    """view: 'Monthly' (MTD) or 'Weekly'. entity: None / 'Stores' / 'Ventures'."""
    st.markdown(_CSS, unsafe_allow_html=True)
    fmt = lambda d: datetime.date.fromisoformat(str(d)).strftime("%d %b %Y")
    ent_lbl = entity or "All entities"

    if view == "Weekly":
        vid = "w"
        rngs = _week_ranges(week_anchor)
        labels = [f"W{i + 1} {a.strftime('%d %b')}–{b.strftime('%d %b')}" for i, (a, b) in enumerate(rngs)]
        stmts = [_stmt(entity, str(a), str(b)) for a, b in rngs]
        head_range = f"Last 4 weeks ending {fmt(week_anchor)}"
        title = "Weekly"
    else:
        vid = "m"
        labels = [f"{datetime.date.fromisoformat(str(mtd_from)).strftime('%d %b')}–{fmt(mtd_to)}"]
        stmts = [_stmt(entity, str(mtd_from), str(mtd_to))]
        head_range = f"{fmt(mtd_from)} → {fmt(mtd_to)}"
        title = "MTD"

    cols_data = list(stmts)
    col_labels = list(labels)
    if len(stmts) > 1:
        cols_data.append(combine(stmts))
        col_labels.append("Total")
    P = len(cols_data)
    widths = [0.035, 0.36] + [0.605 / P] * P if P > 1 else [0.035, 0.50, 0.2]

    st.markdown(f'<div class="cfs-title"><b>Cash Flow Statement</b><span>{head_range} &nbsp;·&nbsp; {ent_lbl} '
                f'&nbsp;·&nbsp; direct method</span></div>', unsafe_allow_html=True)

    # ── export ────────────────────────────────────────────────────────────────
    _, xc = st.columns([8.5, 1.5])
    with xc:
        fname = (f"cashflow_{title.lower()}_{(entity or 'All')}_{stmts[0]['d_from']}_{stmts[-1]['d_to']}.xlsx")
        st.download_button("⬇️ Export Excel", build_workbook(stmts, labels, title, ent_lbl),
                           file_name=fname,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True, key=f"dl_cfs_{vid}")

    # ── integrity notes (never hidden) ───────────────────────────────────────
    bad = [(l, s["checks"]["closing_vs_bank"]) for l, s in zip(labels, stmts) if abs(s["checks"]["closing_vs_bank"]) > 1]
    if bad:
        st.warning("Closing does not tie to the bank balances for: " +
                   "; ".join(f"{l} (difference {_group_indian(int(abs(round(d))))})" for l, d in bad) +
                   ". A statement day is probably missing — see Exception Report, Data Integrity.")
    # ── helpers to draw rows ─────────────────────────────────────────────────
    def key_of(node):
        return f"cf_stmt_open_{vid}_{node}"

    def is_open(node):
        return st.session_state.setdefault(key_of(node), False)

    def draw(cls, label, vals, node=None, expandable=False):
        c = st.columns(widths)
        with c[0]:
            if expandable:
                st.button("−" if is_open(node) else "+", key=f"btn_cfs_{vid}_{node}",
                          on_click=_toggle, args=(key_of(node),))
        with c[1]:
            st.markdown(f'<div class="{cls}"><div class="cfs-lbl">{label}</div></div>', unsafe_allow_html=True)
        for i, v in enumerate(vals):
            with c[2 + i]:
                st.markdown(f'<div class="{cls}"><div class="cfs-v">{_num(v)}</div></div>', unsafe_allow_html=True)

    # register every expandable node up front so one click of Expand All opens all levels
    for _n in ("open", "close", "internal"):
        is_open(_n)
    for _act, _bks in structure(stmts):
        is_open(_act)
        for _bk, _ in _bks:
            is_open(f"{_act}|{_bk}")

    # header
    h = st.columns(widths)
    with h[1]:
        st.markdown('<div class="cfs-hdr l">Particulars</div>', unsafe_allow_html=True)
    for i, l in enumerate(col_labels):
        with h[2 + i]:
            st.markdown(f'<div class="cfs-hdr">{l}</div>', unsafe_allow_html=True)

    # opening
    draw("cfs-open", "Opening balance (cash, bank, MF &amp; FD at cost)",
         [s["opening"]["total"] for s in cols_data], "open", True)
    if is_open("open"):
        for bk in sorted({b for s in stmts for b in s["opening"]["banks"]}):
            draw("cfs-sub", f"Bank ({bk})", [s["opening"]["banks"].get(bk, 0) for s in cols_data])
        draw("cfs-sub", "Cash at Stores", [s["opening"]["cash"] for s in cols_data])
        draw("cfs-sub", "Mutual funds at cost", [s["opening"]["mf"] for s in cols_data])
        draw("cfs-sub", "Fixed deposits at cost", [s["opening"]["fd"] for s in cols_data])

    names = {"Operating": "A. Cash flows from operating activities",
             "Investing": "B. Cash flows from investing activities",
             "Financing": "C. Cash flows from financing activities",
             "Pending review": "D. Pending review (uncategorised)"}
    for act, buckets in structure(stmts):
        draw("cfs-act A" if act != "Pending review" else "cfs-pend", names[act],
             [s["act_tot"][act] for s in cols_data], act, True)
        if is_open(act):
            for bk, subs in buckets:
                bnode = f"{act}|{bk}"
                draw("cfs-bk", bk,
                     [sum(v for (a, b, _), v in s["lines"].items() if a == act and b == bk) for s in cols_data],
                     bnode, True)
                if is_open(bnode):
                    for sb in subs:
                        draw("cfs-sub", sb, [s["lines"].get((act, bk, sb), 0) for s in cols_data])

    draw("cfs-net", "Net increase / (decrease) (A+B+C+D)",
         [round(sum(s["act_tot"].values()), 2) for s in cols_data])

    internal_vals = [s["internal_tot"] for s in cols_data]
    draw("cfs-memo", "Internal movements — interbank / intercompany (net, nil when all accounts are in view)",
         internal_vals, "internal", any(abs(s["internal"].get(k, 0)) > 0.5 for s in cols_data
                                        for k in (INTERBANK, INTERCOMPANY)))
    if is_open("internal"):
        for lbl in (INTERBANK, INTERCOMPANY):
            if any(abs(s["internal"].get(lbl, 0)) > 0.5 for s in cols_data):
                draw("cfs-sub", lbl, [s["internal"].get(lbl, 0) for s in cols_data])

    draw("cfs-tot", "Closing balance (cash, bank, MF &amp; FD at cost)",
         [s["closing_calc"] for s in cols_data], "close", True)
    if is_open("close"):
        for bk in sorted({b for s in stmts for b in s["closing_actual"]["banks"]}):
            draw("cfs-sub", f"Bank ({bk})", [s["closing_actual"]["banks"].get(bk, 0) for s in cols_data])
        draw("cfs-sub", "Cash at Stores", [s["closing_actual"]["cash"] for s in cols_data])
        draw("cfs-sub", "Mutual funds at cost", [s["closing_actual"]["mf"] for s in cols_data])
        draw("cfs-sub", "Fixed deposits at cost", [s["closing_actual"]["fd"] for s in cols_data])

    diffs = [s["checks"]["closing_vs_bank"] for s in cols_data]
    ok = all(abs(d) <= 1 for d in diffs)
    draw("cfs-ok" if ok else "cfs-bad",
         "✔ Ties to the top banner (closing banks + Cash at Stores + MF + FD)" if ok else "✖ Difference vs closing bank balances",
         diffs)

    st.caption("Each line is net of credits and debits, so refunds and bounce-backs reduce the same line. "
               "Cash sales = cash deposited + change in Cash at Stores. Mutual fund / FD purchases and redemptions "
               "move money inside the balance, so Investing shows only the gain / interest realised.")

"""Investments tab — management view: balance, gains, ROI, and FD-vs-Mutual-Fund comparison."""

import datetime
import io
import os
import tempfile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database import (
    get_capital_gain_lots, compute_fifo, get_entity_investment_asof, get_fd_rate_card,
    save_fd_rate_card, import_cg_sheet, import_opening_lots, get_opening_lots,
    get_latest_data_date, get_investment_events, _fund_type,
    compute_fd_earnings, get_fd_terms, import_fd_terms, save_fd_terms, build_fd_terms_workbook,
)
from queries.cashflow_queries import get_investment_mf_asof
from utils.formatters import fmt_inr, fmt_cr
from utils.ui import amount_config

_H = 178   # KPI card height (px) — every card is the same height

_CSS = """
<style>
.iv-top { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap; margin-bottom:4px; }
.iv-title { font-size:30px; font-weight:800; letter-spacing:-0.6px; color:#0A1628; line-height:1.1; }
.iv-subtitle { font-size:13.5px; color:#6B7A90; margin-top:4px; }
.iv-chips { display:flex; gap:8px; flex-wrap:wrap; }
.iv-chip { background:#FFFFFF; border:1px solid #E2E7EF; border-radius:999px; padding:5px 12px; font-size:12px; color:#3B4A63; }
.iv-chip b { color:#0A1628; font-weight:700; }
.iv-kpi { position:relative; overflow:hidden; background:#FFFFFF; border:1px solid #E2E7EF; border-radius:14px;
  padding:18px 22px 14px; box-shadow:0 1px 4px rgba(10,22,40,0.06); height:__H__px; box-sizing:border-box; }
.iv-kpi::before { content:''; position:absolute; left:0; top:0; bottom:0; width:4px; background:#1B2B4B; }
.iv-kpi.g::before { background:#16A34A; } .iv-kpi.b::before { background:#2563EB; } .iv-kpi.r::before { background:#DC2626; }
.iv-kpi.n::before { background:#94A3B8; }
.iv-label { font-size:10.5px; font-weight:700; letter-spacing:0.13em; text-transform:uppercase; color:#6B7A90; margin-bottom:8px; }
.iv-val { font-size:29px; font-weight:800; letter-spacing:-0.7px; line-height:1.05; color:#0A1628; font-variant-numeric:tabular-nums; }
.iv-kpi.g .iv-val { color:#166534; } .iv-kpi.r .iv-val { color:#991B1B; }
.iv-sub { font-size:12px; color:#6B7A90; margin-top:8px; line-height:1.5; font-variant-numeric:tabular-nums; }
.iv-hero { background:#14233F; border-color:#14233F; }
.iv-hero::before { background:#4ADE80; }
.iv-hero .iv-label { color:rgba(255,255,255,0.6); } .iv-hero .iv-val { color:#FFFFFF; } .iv-hero .iv-sub { color:rgba(255,255,255,0.72); }
.iv-hint { margin-top:7px; font-size:11.5px; font-weight:600; color:#7DD3FC; }
.iv-bar { display:flex; height:10px; border-radius:5px; overflow:hidden; background:#E2E7EF; margin-top:12px; }
.iv-bar span { display:block; height:100%; }
.iv-legend { display:flex; justify-content:space-between; font-size:12px; color:#3B4A63; margin-top:8px; font-variant-numeric:tabular-nums; }
.iv-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }
.iv-h { font-size:12px; font-weight:800; letter-spacing:0.16em; text-transform:uppercase; color:#1B2B4B; margin:28px 0 4px; }
.iv-sub-h { font-size:12.5px; color:#6B7A90; margin:0 0 10px; }
.iv-box { border-radius:12px; padding:16px 22px; margin:10px 0 14px; font-size:13.5px; line-height:1.6; border:1px solid; }
.iv-box.good { background:#ECFDF3; border-color:#BBF7D0; color:#14532D; }
.iv-box.warn { background:#FFF7ED; border-color:#FDBA74; color:#7C2D12; }
.iv-box.info { background:#EAF0FA; border-color:#C8D3E0; color:#1B2B4B; }
.iv-box ul { margin:6px 0 0 18px; padding:0; }
.iv-box li { margin:3px 0; }
.iv-panel { background:#FFFFFF; border:1px solid #E2E7EF; border-radius:14px; padding:18px 22px; box-shadow:0 1px 4px rgba(10,22,40,0.05); margin:4px 0 10px; }
.iv-tbl-wrap { max-height:420px; overflow:auto; border:1px solid #E2E7EF; border-radius:12px; background:#fff; }
table.iv-tbl { width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
table.iv-tbl th { position:sticky; top:0; background:#F4F6FA; color:#3B4A63; font-weight:700; font-size:11.5px;
  text-transform:uppercase; letter-spacing:0.06em; padding:10px 12px; text-align:right; border-bottom:1px solid #E2E7EF; white-space:nowrap; }
table.iv-tbl th:first-child, table.iv-tbl td:first-child { text-align:left; }
table.iv-tbl td { padding:9px 12px; text-align:right; border-bottom:1px solid #EEF1F6; color:#0A1628; white-space:nowrap; }
table.iv-tbl tr.tot td { background:#EAF0FA; font-weight:800; border-top:2px solid #1B2B4B; border-bottom:none; }
table.iv-tbl .pos { color:#166534; font-weight:700; } table.iv-tbl .neg { color:#991B1B; font-weight:700; }
/* clickable balance card: invisible button laid over the card */
.st-key-iv_toggle { margin-top:-__HG__px; height:__H__px; position:relative; z-index:5; }
.st-key-iv_toggle button { width:100%; height:__H__px; opacity:0; cursor:pointer; }
.st-key-iv_toggle > div, .st-key-iv_toggle [data-testid="stElementContainer"] { height:__H__px; }
</style>
""".replace("__HG__", str(_H)).replace("__H__", str(_H))


def _rs(x):
    """₹ with Indian grouping, minus sign in front."""
    return fmt_inr(x)


def _bank_of(name):
    """FD names carry the bank in brackets, e.g. '925040079999702 (Axis)'."""
    if "(" in name and name.strip().endswith(")"):
        return name[name.rindex("(") + 1:-1].strip() or "Other"
    return "Other / untagged"


def _breakdown(entity, as_of):
    """Per-scheme balances (at cost) from the same event feed as the Summary tab."""
    ents = [entity] if entity else ["Stores", "Ventures"]
    ev = pd.DataFrame(get_investment_events(entity))
    if ev.empty:
        return pd.DataFrame(columns=["entity", "scheme_type", "scheme_name", "balance"])
    ev = ev[ev["date"].isna() | (ev["date"] <= as_of)]
    ev = ev[ev["entity"].isin(ents)]
    g = ev.groupby(["entity", "scheme_type", "scheme_name"], as_index=False)["delta"].sum()
    return g.rename(columns={"delta": "balance"})


def _alloc_pct(fd, mf):
    """FD / MF share, one decimal, forced to add up to 100.0."""
    tot = fd + mf
    if tot <= 0:
        return 0.0, 0.0
    f = round(fd / tot * 100, 1)
    return f, round(100.0 - f, 1)


def _card(cls, label, value, sub, extra=""):
    return (f'<div class="iv-kpi {cls}"><div class="iv-label">{label}</div>'
            f'<div class="iv-val">{value}</div><div class="iv-sub">{sub}</div>{extra}</div>')


def render_investment_header(entity_label=None, as_of=None):
    """Page title."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="iv-title">Investment Portfolio</div>', unsafe_allow_html=True)


def _flip():
    st.session_state["iv_open"] = not st.session_state.get("iv_open", False)


def _render_breakdown(bd, fd_bal, mf_bal, total, fd_stats=None, mf_stats=None, notes=None):
    """fd_stats / mf_stats: {key: dict(earned, roi, ann, days)} plus key '__total__'."""
    fd_df = bd[bd["scheme_type"] == "FD"].copy()
    mf_df = bd[bd["scheme_type"] == "MF"].copy()
    fd_df = fd_df[fd_df["balance"].abs() >= 1]
    mf_df = mf_df[mf_df["balance"].abs() >= 1]

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    _, h2 = st.columns([6, 1])
    with h2:
        st.button("▲ Collapse", key="iv_collapse", on_click=_flip, use_container_width=True)

    def _cells(x):
        if not x:
            return "<td>—</td><td>—</td><td>—</td><td>—</td>"
        gc = "pos" if x["earned"] >= 0 else "neg"
        return (f"<td class='{gc}'>{_rs(x['earned'])}</td><td>{_pct(x['roi'])}</td>"
                f"<td>{_pct(x['ann'])}</td><td>{x['days']:.0f}</td>")

    def _tbl(df, key_col, title, total_ref, stats, earned_label):
        if df.empty:
            return f"<div class='iv-sub-h'>{title}: no balances.</div>"
        stats = stats or {}
        g = df.groupby(key_col, as_index=False)["balance"].sum().sort_values("balance", ascending=False)
        rows = "".join(f"<tr><td>{r[key_col]}</td><td>{_rs(r['balance'])}</td>"
                       f"<td>{(r['balance'] / total_ref * 100 if total_ref else 0):.1f}%</td>"
                       f"{_cells(stats.get(r[key_col]))}</tr>" for _, r in g.iterrows())
        rest = total_ref - g["balance"].sum()
        if abs(rest) >= 1:
            rows += (f"<tr><td>Other / unallocated</td><td>{_rs(rest)}</td>"
                     f"<td>{(rest / total_ref * 100):.1f}%</td>{_cells(None)}</tr>")
        rows += (f"<tr class='tot'><td>Total</td><td>{_rs(total_ref)}</td><td>100.0%</td>"
                 f"{_cells(stats.get('__total__'))}</tr>")
        return (f"<div class='iv-label' style='margin-top:14px'>{title}</div>"
                f"<div class='iv-tbl-wrap'><table class='iv-tbl'><thead><tr><th>{key_col}</th><th>Balance</th>"
                f"<th>Contribution</th><th>{earned_label}</th><th>ROI</th><th>Return p.a.</th>"
                f"<th>Avg holding (days)</th></tr></thead><tbody>{rows}</tbody></table></div>")

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Fixed Deposits**")
        if not fd_df.empty:
            fd_df["Bank"] = fd_df["scheme_name"].apply(_bank_of)
        st.markdown(_tbl(fd_df, "Bank", "By bank", fd_bal, fd_stats, "Interest earned")
                    if not fd_df.empty else "", unsafe_allow_html=True)
        if fd_stats:
            st.caption("Interest = quarterly compounding on each FD's own rate and dates, for the period selected "
                       "above. ROI = interest / average capital deployed in the period. Return p.a. is on original "
                       "principal, so it can sit above the stated rate late in a term (interest on interest).")
        for n in (notes or []):
            st.warning(n)
    with d2:
        st.markdown("**Mutual Funds**")
        if not mf_df.empty:
            mf_df["Fund category"] = mf_df["scheme_name"].apply(_fund_type)
        st.markdown(_tbl(mf_df, "Fund category", "By fund category", mf_bal, mf_stats, "Gain realised")
                    if not mf_df.empty else "", unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def _lots(entity):
    return get_capital_gain_lots(entity)


@st.cache_data(ttl=300, show_spinner=False)
def _fifo(entity):
    return compute_fifo(entity)


def _pct(x):
    return f"{x * 100:.2f}%"


def _agg(df):
    """Totals for a set of lots. Annualised = capital-weighted: gain / sum(cost x days) x 365."""
    if df.empty:
        return dict(n=0, cost=0.0, gain=0.0, fd=0.0, benefit=0.0, missed=0.0, roi=0.0, ann=0.0, days=0.0,
                    fd_ann=0.0)
    cost, gain = df["cost"].sum(), df["gain"].sum()
    cd = (df["cost"] * df["days"]).sum()
    fd = df["fd_interest"].sum()
    return dict(n=len(df), cost=cost, gain=gain, fd=fd, benefit=gain - fd, missed=df["missed"].sum(),
                roi=gain / cost if cost else 0.0,
                ann=gain / cd * 365 if cd else 0.0,
                days=cd / cost if cost else 0.0,
                fd_ann=fd / cd * 365 if cd else 0.0)


def _verdict(mf_ann, fd_ann, n):
    d = mf_ann - fd_ann
    v = "✅ Mutual fund better" if d >= 0.0025 else ("⚠️ FD better" if d <= -0.0025 else "≈ Similar")
    return v + (" (few lots)" if n < 3 else "")


def render_investment_overview(entity=None, as_of=None, win_from=None, win_to=None, win_label="All time"):
    """entity: None (all) / 'Stores' / 'Ventures'.  win_*: the sidebar period (FY / month / date range)."""
    st.markdown(_CSS, unsafe_allow_html=True)
    ents = [entity] if entity else ["Stores", "Ventures"]
    as_of = as_of or get_latest_data_date() or str(datetime.date.today())
    as_of_txt = datetime.date.fromisoformat(as_of).strftime('%d %b %Y')

    # ── balances (at cost) — FD = combined − MF, exactly as the Cash Flow tab ─
    total = sum(get_entity_investment_asof(e, as_of) for e in ents)
    mf_bal = sum(get_investment_mf_asof(e, as_of) for e in ents)
    fd_bal = total - mf_bal
    fd_pct, mf_pct = _alloc_pct(fd_bal, mf_bal)
    bd = _breakdown(entity, as_of)
    n_fd = int((bd[bd["scheme_type"] == "FD"]["balance"].abs() >= 1).sum()) if not bd.empty else 0
    n_mf = int((bd[bd["scheme_type"] == "MF"]["balance"].abs() >= 1).sum()) if not bd.empty else 0

    lots = pd.DataFrame(_lots(entity))
    fifo = _fifo(entity)

    # ── Period comes from the sidebar filters (date range > month > financial year) ──
    period = win_label
    if lots.empty:
        sel = lots
    else:
        sel = lots
        if win_from:
            sel = sel[sel["sale_date"] >= win_from]
        if win_to:
            sel = sel[sel["sale_date"] <= win_to]
    a = _agg(sel)

    # FD interest for the same period
    w0 = win_from
    w1 = min(as_of, win_to) if win_to else as_of
    fd_terms = get_fd_terms()
    earn = compute_fd_earnings(entity, w0, w1) if fd_terms else []
    fd_stats = {}
    if earn:
        edf = pd.DataFrame(earn)
        d_from = datetime.date.fromisoformat(w0) if w0 else datetime.date.fromisoformat(edf["start"].min())
        wdays = (datetime.date.fromisoformat(w1) - d_from).days or 1

        def _fs(g):
            i, cd, pr = g["interest"].sum(), g["cap_days"].sum(), g["principal"].sum()
            return dict(earned=i, roi=(i / (cd / wdays)) if cd else 0.0, ann=(i / cd * 365) if cd else 0.0,
                        days=(cd / pr) if pr else 0.0)
        for bnk, g in edf.groupby("bank"):
            fd_stats[bnk] = _fs(g)
        fd_stats["__total__"] = _fs(edf)
    fd_notes = []
    if fd_terms:
        last = {}
        for t in fd_terms:
            k = (t["entity"], t["account_no"])
            if k not in last or t["start_date"] > last[k]["start_date"]:
                last[k] = t
        stale = [t for t in last.values()
                 if t.get("end_date") and t["end_date"] < as_of and "redeem" not in (t.get("status") or "").lower()
                 and (entity is None or t["entity"] == entity)]
        if stale:
            amt = sum(t["principal"] for t in stale)
            fd_notes.append(
                f"{len(stale)} FD(s) worth {fmt_inr(amt)} passed their last recorded maturity date "
                f"({', '.join(sorted(t['account_no'] for t in stale))}). Interest stops at that date. "
                f"Add the renewal terms under Setup, FD terms, to include later interest.")
    mf_stats = {}
    if not sel.empty:
        for ft, g in sel.groupby("fund_type"):
            x = _agg(g)
            mf_stats[ft] = dict(earned=x["gain"], roi=x["roi"], ann=x["ann"], days=x["days"])
        x = _agg(sel)
        mf_stats["__total__"] = dict(earned=x["gain"], roi=x["roi"], ann=x["ann"], days=x["days"])

    # ── Row 1: portfolio overview ────────────────────────────────────────────
    is_open = st.session_state.get("iv_open", False)
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(_card(
            "iv-hero", "Total Investment Portfolio", fmt_cr(total),
            f"FD {fmt_cr(fd_bal)} &nbsp;·&nbsp; Mutual Funds {fmt_cr(mf_bal)}<br>at cost, as on {as_of_txt}",
            f'<div class="iv-hint">{"▲ Hide" if is_open else "▼ Click for breakdown"}</div>'),
            unsafe_allow_html=True)
        with st.container(key="iv_toggle"):
            st.button("toggle", key="iv_toggle_btn", on_click=_flip, use_container_width=True)
    with k2:
        st.markdown(_card(
            "b", "Fixed Deposit Investment", fmt_cr(fd_bal),
            f"{n_fd} active deposit{'s' if n_fd != 1 else ''} · principal at cost<br>"
            + (f"Interest earned {period}: {fmt_cr(fd_stats['__total__']['earned'])}<br>"
               f"{_pct(fd_stats['__total__']['ann'])} p.a."
               if fd_stats else "Interest not shown: load FD terms in Setup")), unsafe_allow_html=True)
    with k3:
        st.markdown(_card(
            "b", "Mutual Fund Portfolio", fmt_cr(mf_bal),
            f"{n_mf} scheme{'s' if n_mf != 1 else ''} · invested cost<br>"
            f"Market value &amp; unrealised gain not tracked"), unsafe_allow_html=True)
    with k4:
        bar = (f'<div class="iv-bar"><span style="width:{fd_pct}%;background:#1B2B4B"></span>'
               f'<span style="width:{mf_pct}%;background:#60A5FA"></span></div>'
               f'<div class="iv-legend"><span><span class="iv-dot" style="background:#1B2B4B"></span>FD {fd_pct:.1f}%</span>'
               f'<span><span class="iv-dot" style="background:#60A5FA"></span>MF {mf_pct:.1f}%</span></div>')
        st.markdown(_card("n", "Portfolio Allocation", f"{fd_pct:.1f}% / {mf_pct:.1f}%",
                          "Fixed Deposits / Mutual Funds", bar), unsafe_allow_html=True)

    if is_open:
        _render_breakdown(bd, fd_bal, mf_bal, total, fd_stats, mf_stats, fd_notes)

    if fifo["unmatched"]:
        for u in fifo["unmatched"]:
            st.warning(f"⚠️ Redemption on {u['date']} of {u['scheme_name']} ({u['entity']}): "
                       f"{u['units_short']:,.3f} units have no matching purchase lot. "
                       f"Upload your open holdings (Setup below) or add the missing purchase.")

    if lots.empty:
        st.info("No capital-gain data yet. Open **Capital gain data & setup** below and upload your "
                "capital-gain sheet once; after that, redemptions entered with units and NAV are added "
                "automatically on a FIFO basis.")
        _setup_panel()
        return

    # ── FD vs MF comparison + recommendation ────────────────────────────────
    st.markdown('<div class="iv-h">Opportunity cost</div>', unsafe_allow_html=True)
    if sel.empty:
        st.info("No mutual fund redemptions in the selected period.")
        _setup_panel()
        return

    # by holding period
    slab_rows, slab_reco = [], []
    for (smin, slab), g in sel.groupby(["slab_min", "slab"]):
        x = _agg(g)
        v = _verdict(x["ann"], x["fd_ann"], x["n"])
        slab_rows.append({"Holding period": slab, "Lots": x["n"], "Capital": fmt_inr(x["cost"]),
                          "Mutual fund p.a.": _pct(x["ann"]), "FD p.a.": _pct(x["fd_ann"]),
                          "MF gain": fmt_inr(x["gain"]), "FD interest": fmt_inr(x["fd"]),
                          "Benefit (MF − FD)": fmt_inr(x["benefit"]),
                          "Missed opportunity": fmt_inr(x["missed"]), "Better choice": v, "_o": smin})
        if x["n"] >= 3 and "Similar" not in v:
            slab_reco.append((smin, slab, "Mutual fund" if "Mutual" in v else "FD", x))
    st.markdown("**By holding period**")
    sdf = pd.DataFrame(slab_rows).sort_values("_o").drop(columns="_o")
    st.dataframe(sdf, use_container_width=True, hide_index=True,
                 column_config=amount_config(["Capital", "Mutual fund p.a.", "FD p.a.", "MF gain", "FD interest",
                                              "Benefit (MF − FD)", "Missed opportunity"]))

    # by fund type x holding period
    pocket_rows, pockets = [], []
    for (ft, smin, slab), g in sel.groupby(["fund_type", "slab_min", "slab"]):
        x = _agg(g)
        v = _verdict(x["ann"], x["fd_ann"], x["n"])
        pocket_rows.append({"Fund type": ft, "Holding period": slab, "Lots": x["n"], "Capital": fmt_inr(x["cost"]),
                            "Mutual fund p.a.": _pct(x["ann"]), "FD p.a.": _pct(x["fd_ann"]),
                            "Benefit (MF − FD)": fmt_inr(x["benefit"]), "Missed opportunity": fmt_inr(x["missed"]),
                            "Better choice": v, "_o": (ft, smin)})
        pockets.append((ft, slab, x, v))
    with st.expander("By fund type and holding period", expanded=False):
        pdf = pd.DataFrame(pocket_rows).sort_values("_o").drop(columns="_o")
        st.dataframe(pdf, use_container_width=True, hide_index=True,
                     column_config=amount_config(["Capital", "Mutual fund p.a.", "FD p.a.", "Benefit (MF − FD)",
                                                  "Missed opportunity"]))

    # ── lot-wise detail ──────────────────────────────────────────────────────
    with st.expander("Lot-wise detail and export", expanded=False):
        d = sel.copy() if not sel.empty else lots.copy()
        d["Verdict"] = d["benefit"].apply(lambda b: "MF better" if b > 0 else "FD better")
        show = pd.DataFrame({
            "Entity": d["entity"], "Fund": d["fund_type"], "Source": d["source"],
            "Bought": d["purchase_date"], "Sold": d["sale_date"], "Days": d["days"],
            "Cost": d["cost"].apply(fmt_inr), "Proceeds": d["proceeds"].apply(fmt_inr),
            "Gain": d["gain"].apply(fmt_inr), "ROI": d["roi"].apply(_pct), "Return p.a.": d["ann"].apply(_pct),
            "FD rate": d["fd_rate"].apply(_pct), "FD interest": d["fd_interest"].apply(fmt_inr),
            "Benefit vs FD": d["benefit"].apply(fmt_inr), "Verdict": d["Verdict"]})
        st.dataframe(show.sort_values("Sold", ascending=False), use_container_width=True, hide_index=True, height=360,
                     column_config=amount_config(["Cost", "Proceeds", "Gain", "ROI", "Return p.a.", "FD rate",
                                                  "FD interest", "Benefit vs FD"]))
        buf = io.BytesIO()
        out = d.drop(columns=["scheme_name"], errors="ignore").rename(columns={
            "entity": "Entity", "fund_type": "Fund", "source": "Source", "purchase_date": "Bought",
            "sale_date": "Sold", "units": "Units", "purchase_nav": "Buy NAV", "sale_nav": "Sell NAV",
            "cost": "Cost", "proceeds": "Proceeds", "gain": "Gain", "days": "Days", "roi": "ROI",
            "ann": "Return p.a.", "slab": "Holding slab", "fd_rate": "FD rate", "fd_interest": "FD interest",
            "benefit": "Benefit vs FD", "missed": "Missed opportunity", "fy": "FY", "month": "Month"})
        out.drop(columns=["slab_min"], errors="ignore").to_excel(buf, index=False)
        st.download_button("⬇️ Export lots (Excel)", buf.getvalue(), file_name="capital_gain_lots.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="dl_cg_lots")

    # ── open lots ────────────────────────────────────────────────────────────
    if fifo["open"]:
        st.markdown('<div class="iv-h">Open holdings (FIFO book)</div>', unsafe_allow_html=True)
        ol = pd.DataFrame(fifo["open"])
        ol["cost"] = ol["units"] * ol["nav"]
        asof_d = datetime.date.fromisoformat(as_of)
        ol["days"] = ol["date"].apply(lambda x: (asof_d - datetime.date.fromisoformat(x)).days)
        card = get_fd_rate_card()

        def _fd_rate(dd):
            pick = card[0]
            for c in card:
                if dd >= c["min_days"]:
                    pick = c
            return pick["rate"]
        ol["fd_rate"] = ol["days"].apply(_fd_rate)
        ol["fd_accr"] = ol.apply(lambda r: r["cost"] * r["fd_rate"] * (r["days"] if r["days"] >= 7 else 0) / 365, axis=1)
        g = ol.groupby(["entity", "scheme"]).agg(units=("units", "sum"), cost=("cost", "sum"),
                                                 oldest=("date", "min"), days=("days", "max"),
                                                 fd_accr=("fd_accr", "sum")).reset_index()
        gshow = pd.DataFrame({"Entity": g["entity"], "Scheme": g["scheme"], "Units": g["units"].apply(lambda v: f"{v:,.3f}"),
                              "Cost": g["cost"].apply(fmt_inr), "Oldest lot": g["oldest"], "Days held": g["days"],
                              "FD would have accrued": g["fd_accr"].apply(fmt_inr)})
        st.dataframe(gshow, use_container_width=True, hide_index=True,
                     column_config=amount_config(["Units", "Cost", "Days held", "FD would have accrued"]))

    _setup_panel()


def _setup_panel():
    with st.expander("⚙️ Capital gain data & setup (sheet upload, open holdings, FD rates)", expanded=False):
        t1, t2, t3, t4 = st.tabs(["Capital gain sheet", "Open holdings", "FD rate card", "FD terms"])

        with t1:
            st.caption("One-time load of the historical capital-gain workbook (CKVPL = Ventures, CKSPL = Stores). "
                       "Re-uploading replaces the historical lots. Redemptions entered from now on are added "
                       "automatically by FIFO — they are not read from this sheet.")
            hist = [l for l in get_capital_gain_lots(None) if l["source"] == "Sheet"]
            if hist:
                hd = pd.DataFrame(hist)
                st.success(f"Loaded: {len(hd)} historical lots "
                           f"({', '.join(f'{k} {v}' for k, v in hd.groupby('entity').size().items())}), "
                           f"sales {hd['sale_date'].min()} to {hd['sale_date'].max()}.")
            up = st.file_uploader("Capital gain workbook (.xlsx)", type=["xlsx"], key="cg_sheet_up")
            if up is not None and st.button("📥 Load capital gain sheet", key="cg_sheet_btn"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(up.getvalue())
                    path = tmp.name
                res = import_cg_sheet(path)
                try:
                    os.unlink(path)
                except OSError:
                    pass
                if res["errors"] and not res["loaded"]:
                    st.error("; ".join(res["errors"]))
                else:
                    st.success(f"Loaded {sum(res['loaded'].values())} lots: {res['loaded']}. "
                               f"Skipped {res['skipped']} incomplete rows.")
                    if abs(res.get("sheet_gain_diff", 0)) > 1:
                        st.warning(f"Total gain differs from the sheet's own CAP. GAIN column by "
                                   f"{fmt_inr(res['sheet_gain_diff'])} — please check the sheet.")
                    st.cache_data.clear()
                    st.rerun()

        with t2:
            st.caption("The units you still hold today, one row per purchase lot, so FIFO can match future "
                       "redemptions. Upload once; re-uploading replaces them. After this, new purchases are "
                       "entered with units and NAV in the entry form.")
            ol = get_opening_lots()
            if ol:
                od = pd.DataFrame(ol)
                st.success(f"Loaded: {len(od)} open lots, {od['units'].sum():,.3f} units, "
                           f"cost {fmt_inr((od['units'] * od['nav']).sum())}.")
            tmpl = pd.DataFrame(columns=["Entity", "Scheme Name", "Fund Type", "Purchase Date", "Units", "NAV"])
            note = pd.DataFrame({"Notes": [
                "Entity: Stores or Ventures.",
                "Scheme Name must match the name you use in the Add Manual FD/MF entry form.",
                "Fund Type (optional): Liquid / Money Market / Arbitrage.",
                "One row per purchase lot: Purchase Date, Units, NAV on that date.",
                "Delete nothing from the first sheet's header row."]})
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as xw:
                tmpl.to_excel(xw, sheet_name="Open lots", index=False)
                note.to_excel(xw, sheet_name="Instructions", index=False)
            st.download_button("⬇️ Download template", buf.getvalue(), file_name="open_lots_template.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="dl_open_tmpl")
            up2 = st.file_uploader("Open holdings (.xlsx)", type=["xlsx"], key="open_lots_up")
            if up2 is not None and st.button("📥 Load open holdings", key="open_lots_btn"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(up2.getvalue())
                    path = tmp.name
                res = import_opening_lots(path)
                try:
                    os.unlink(path)
                except OSError:
                    pass
                if res["errors"]:
                    st.error("Nothing loaded. " + " | ".join(res["errors"][:8]))
                else:
                    st.success(f"Loaded {res['loaded']} open lots.")
                    st.cache_data.clear()
                    st.rerun()

        with t3:
            st.caption("FD interest rate by holding period, used for the FD comparison (the sheet's own rate is "
                       "kept for lots that have one). Rates are annual, in %. Under 7 days earns no FD interest.")
            card = pd.DataFrame(get_fd_rate_card())
            card["rate"] = card["rate"] * 100
            edited = st.data_editor(
                card.rename(columns={"min_days": "From day", "label": "Holding period", "rate": "FD rate % p.a."}),
                hide_index=True, use_container_width=True, num_rows="fixed", key="fd_card_editor",
                disabled=["From day", "Holding period"])
            if st.button("💾 Save FD rates", key="fd_card_save"):
                rows = [{"min_days": int(r["From day"]), "label": r["Holding period"],
                         "rate": float(r["FD rate % p.a."]) / 100} for _, r in edited.iterrows()]
                save_fd_rate_card(rows)
                st.cache_data.clear()
                st.success("FD rates saved.")
                st.rerun()

        with t4:
            st.caption("Rate, start and maturity of each fixed deposit, used to compute the interest actually earned "
                       "(quarterly compounding). One row per term: when an FD is renewed, add a new row with the new "
                       "rate and dates. End = maturity (or redemption, if earlier).")
            terms = get_fd_terms()
            if terms:
                st.success(f"{len(terms)} FD terms loaded.")
            st.download_button("⬇️ Download FD terms workbook (current terms, upload-ready)",
                               build_fd_terms_workbook(), file_name="FD_Terms_Upload.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="dl_fd_terms")
            up3 = st.file_uploader("FD terms workbook (.xlsx) \u2014 the downloaded format, or the old FD tracker", type=["xlsx"],
                                   key="fd_terms_up")
            if up3 is not None and st.button("📥 Load FD terms from workbook", key="fd_terms_btn"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(up3.getvalue())
                    path = tmp.name
                res = import_fd_terms(path)
                try:
                    os.unlink(path)
                except OSError:
                    pass
                if res["errors"] and not res["loaded"]:
                    st.error("; ".join(res["errors"]))
                else:
                    st.success(f"Loaded {res['loaded']}; skipped {res['skipped']} incomplete rows.")
                    st.cache_data.clear()
                    st.rerun()
            if terms:
                tdf = pd.DataFrame(terms)[["entity", "bank", "account_no", "principal", "rate", "start_date",
                                           "end_date", "status", "source"]]
                tdf["start_date"] = pd.to_datetime(tdf["start_date"]).dt.date
                tdf["end_date"] = pd.to_datetime(tdf["end_date"]).dt.date
                ed = st.data_editor(
                    tdf, num_rows="dynamic", hide_index=True, use_container_width=True, key="fd_terms_editor",
                    column_config={"entity": st.column_config.SelectboxColumn("Entity", options=["Stores", "Ventures"]),
                                   "rate": st.column_config.NumberColumn("Rate % p.a.", format="%.2f"),
                                   "principal": st.column_config.NumberColumn("Principal", format="%.2f"),
                                   "start_date": st.column_config.DateColumn("Start"),
                                   "end_date": st.column_config.DateColumn("End")})
                if st.button("💾 Save FD terms", key="fd_terms_save"):
                    rows = []
                    for _, r in ed.iterrows():
                        if pd.isna(r["principal"]) or pd.isna(r["start_date"]):
                            continue
                        rows.append(dict(entity=r["entity"], bank=r["bank"], account_no=r["account_no"],
                                         principal=r["principal"], rate=r["rate"], start_date=str(r["start_date"]),
                                         end_date=(None if pd.isna(r["end_date"]) else str(r["end_date"])),
                                         status=r["status"] if isinstance(r["status"], str) else "",
                                         source=r["source"] if isinstance(r["source"], str) else "Manual"))
                    save_fd_terms(rows)
                    st.cache_data.clear()
                    st.success("FD terms saved.")
                    st.rerun()

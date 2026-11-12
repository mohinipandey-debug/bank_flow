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
    get_latest_data_date,
)
from queries.cashflow_queries import get_investment_mf_asof
from utils.formatters import fmt_inr, fmt_cr
from utils.ui import amount_config

_CSS = """
<style>
.iv-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 6px 0 20px; }
.iv-kpi { position: relative; overflow: hidden; background: #FFFFFF; border: 1px solid #E2E7EF;
  border-radius: 16px; padding: 20px 24px 18px; box-shadow: 0 2px 8px rgba(10,22,40,0.06); }
.iv-kpi::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 5px; background: #1B2B4B; }
.iv-kpi.g::before { background: #22C55E; } .iv-kpi.b::before { background: #2563EB; } .iv-kpi.r::before { background: #EF4444; }
.iv-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B7A90; margin-bottom: 10px; }
.iv-val { font-size: 30px; font-weight: 800; letter-spacing: -0.8px; line-height: 1.05; color: #0A1628; font-variant-numeric: tabular-nums; }
.iv-kpi.g .iv-val { color: #166534; } .iv-kpi.r .iv-val { color: #991B1B; }
.iv-sub { font-size: 12px; color: #6B7A90; margin-top: 9px; line-height: 1.45; font-variant-numeric: tabular-nums; }
.iv-hero { background: linear-gradient(135deg, #081528 0%, #1B2B4B 60%, #2E4A72 100%); border-color: #1B2B4B; }
.iv-hero::before { background: #4ADE80; }
.iv-hero .iv-label { color: rgba(255,255,255,0.55); } .iv-hero .iv-val { color: #FFFFFF; } .iv-hero .iv-sub { color: rgba(255,255,255,0.6); }
.iv-h { font-size: 12px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #1B2B4B; margin: 26px 0 4px; }
.iv-sub-h { font-size: 12.5px; color: #6B7A90; margin: 0 0 10px; }
.iv-box { border-radius: 14px; padding: 16px 22px; margin: 10px 0 14px; font-size: 13.5px; line-height: 1.6; border: 1px solid; }
.iv-box.good { background: #ECFDF3; border-color: #BBF7D0; color: #14532D; }
.iv-box.warn { background: #FFF7ED; border-color: #FDBA74; color: #7C2D12; }
.iv-box.info { background: #EAF0FA; border-color: #C8D3E0; color: #1B2B4B; }
.iv-box ul { margin: 6px 0 0 18px; padding: 0; }
.iv-box li { margin: 3px 0; }
</style>
"""


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


def render_investment_overview(entity=None, as_of=None):
    """entity: None (all) / 'Stores' / 'Ventures'."""
    st.markdown(_CSS, unsafe_allow_html=True)
    ents = [entity] if entity else ["Stores", "Ventures"]
    as_of = as_of or get_latest_data_date() or str(datetime.date.today())

    # ── balances (at cost) ───────────────────────────────────────────────────
    total = sum(get_entity_investment_asof(e, as_of) for e in ents)
    mf_bal = sum(get_investment_mf_asof(e, as_of) for e in ents)
    fd_bal = total - mf_bal

    lots = pd.DataFrame(_lots(entity))
    fifo = _fifo(entity)

    # ── period selector ──────────────────────────────────────────────────────
    cur_fy = None
    try:
        y, m = int(as_of[:4]), int(as_of[5:7])
        s0 = y if m >= 4 else y - 1
        cur_fy = f"FY {s0}-{str(s0 + 1)[2:]}"
    except Exception:
        pass
    fy_opts = sorted(lots["fy"].unique(), reverse=True) if not lots.empty else []
    options = fy_opts + ["All time"]
    default_idx = options.index(cur_fy) if cur_fy in options else len(options) - 1
    period = st.radio("Period for gains & returns", options, index=default_idx,
                      horizontal=True, key="inv_ov_period")
    sel = lots if (lots.empty or period == "All time") else lots[lots["fy"] == period]
    a = _agg(sel)

    # ── KPI cards ────────────────────────────────────────────────────────────
    gain_cls = "g" if a["gain"] >= 0 else "r"
    ben_cls = "g" if a["benefit"] >= 0 else "r"
    ben_txt = "ahead of" if a["benefit"] >= 0 else "behind"
    st.markdown(f"""
<div class="iv-kpis">
  <div class="iv-kpi iv-hero">
    <div class="iv-label">Current Investment Balance</div>
    <div class="iv-val">{fmt_cr(total)}</div>
    <div class="iv-sub">FD {fmt_cr(fd_bal)} &nbsp;·&nbsp; Mutual Funds {fmt_cr(mf_bal)}<br>at cost, as on {datetime.date.fromisoformat(as_of).strftime('%d %b %Y')}</div>
  </div>
  <div class="iv-kpi {gain_cls}">
    <div class="iv-label">Gains Earned · {period}</div>
    <div class="iv-val">{fmt_cr(a['gain'])}</div>
    <div class="iv-sub">{fmt_inr(a['gain'])}<br>on {fmt_cr(a['cost'])} redeemed · {a['n']} lots</div>
  </div>
  <div class="iv-kpi b">
    <div class="iv-label">Return on Investment</div>
    <div class="iv-val">{_pct(a['ann'])} <span style="font-size:14px;font-weight:600;color:#6B7A90;">p.a.</span></div>
    <div class="iv-sub">Simple ROI {_pct(a['roi'])} · avg holding {a['days']:.0f} days</div>
  </div>
  <div class="iv-kpi {ben_cls}">
    <div class="iv-label">Versus Fixed Deposit</div>
    <div class="iv-val">{fmt_cr(a['benefit'])}</div>
    <div class="iv-sub">Mutual funds {ben_txt} FD by {fmt_inr(abs(a['benefit']))}<br>FD would have paid {fmt_inr(a['fd'])} ({_pct(a['fd_ann'])} p.a.)</div>
  </div>
</div>""", unsafe_allow_html=True)

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

    # ── returns by fund type ─────────────────────────────────────────────────
    st.markdown('<div class="iv-h">Returns by fund type</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="iv-sub-h">Realised lots, {period}. FD equivalent = the same money in an FD for the same holding period.</div>',
                unsafe_allow_html=True)
    if sel.empty:
        st.info("No redemptions in this period.")
    else:
        rows = []
        for ft, g in sel.groupby("fund_type"):
            x = _agg(g)
            rows.append({"Fund type": ft, "Lots": x["n"], "Capital sold": fmt_inr(x["cost"]),
                         "Gain": fmt_inr(x["gain"]), "ROI": _pct(x["roi"]), "Return p.a.": _pct(x["ann"]),
                         "Avg days": f"{x['days']:.0f}", "FD equivalent": fmt_inr(x["fd"]),
                         "FD rate p.a.": _pct(x["fd_ann"]), "Benefit vs FD": fmt_inr(x["benefit"])})
        rows.append({"Fund type": "TOTAL", "Lots": a["n"], "Capital sold": fmt_inr(a["cost"]),
                     "Gain": fmt_inr(a["gain"]), "ROI": _pct(a["roi"]), "Return p.a.": _pct(a["ann"]),
                     "Avg days": f"{a['days']:.0f}", "FD equivalent": fmt_inr(a["fd"]),
                     "FD rate p.a.": _pct(a["fd_ann"]), "Benefit vs FD": fmt_inr(a["benefit"])})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     column_config=amount_config(["Capital sold", "Gain", "ROI", "Return p.a.", "Avg days",
                                                  "FD equivalent", "FD rate p.a.", "Benefit vs FD"]))

        # monthly chart
        mon = sel.groupby("month").agg(gain=("gain", "sum"), fd=("fd_interest", "sum")).reset_index().sort_values("month")
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Mutual fund gain", x=mon["month"], y=mon["gain"] / 1e5,
                             marker_color="#1B2B4B", hovertemplate="%{x}<br>MF gain ₹%{y:,.1f} L<extra></extra>"))
        fig.add_trace(go.Bar(name="FD equivalent", x=mon["month"], y=mon["fd"] / 1e5,
                             marker_color="#93C5FD", hovertemplate="%{x}<br>FD ₹%{y:,.1f} L<extra></extra>"))
        fig.update_layout(barmode="group", height=300, plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                          font=dict(family="Inter", size=11), legend=dict(orientation="h", y=1.12),
                          title=dict(text="Gain by month of redemption vs FD equivalent (₹ lakh)", x=0, font=dict(size=13)),
                          xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#F0F0F0"),
                          margin=dict(l=0, r=0, t=50, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # ── FD vs MF comparison + recommendation ────────────────────────────────
    st.markdown('<div class="iv-h">Fixed Deposit vs Mutual Fund — which was better?</div>', unsafe_allow_html=True)
    st.markdown('<div class="iv-sub-h">Based on your realised redemptions, all periods. Pre-tax, like the capital-gain sheet. '
                'Opportunity cost = what an FD would have paid minus what the mutual fund earned, where the FD was ahead.</div>',
                unsafe_allow_html=True)
    allx = _agg(lots)
    mf_better = lots[lots["benefit"] > 0]
    fd_better = lots[lots["benefit"] < 0]
    cls = "good" if allx["benefit"] >= 0 else "warn"
    st.markdown(f"""
<div class="iv-box {cls}">
  <b>Overall:</b> mutual funds earned {fmt_inr(allx['gain'])} against {fmt_inr(allx['fd'])} from an FD over the same holding periods —
  <b>{'ahead' if allx['benefit'] >= 0 else 'behind'} by {fmt_inr(abs(allx['benefit']))}</b>
  ({_pct(allx['ann'])} vs {_pct(allx['fd_ann'])} p.a.).<br>
  Mutual fund beat FD on <b>{len(mf_better)}</b> lots (+{fmt_inr(mf_better['benefit'].sum())}); FD would have paid more on
  <b>{len(fd_better)}</b> lots — a <b>missed opportunity of {fmt_inr(lots['missed'].sum())}</b>.
</div>""", unsafe_allow_html=True)

    # by holding period
    slab_rows, slab_reco = [], []
    for (smin, slab), g in lots.groupby(["slab_min", "slab"]):
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
    for (ft, smin, slab), g in lots.groupby(["fund_type", "slab_min", "slab"]):
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

    # plain-English guidance
    bullets = []
    for smin, slab, pick, x in sorted(slab_reco, key=lambda t: t[0]):
        bullets.append(f"<b>{slab}:</b> prefer <b>{pick}</b> — mutual funds returned {_pct(x['ann'])} p.a. vs FD "
                       f"{_pct(x['fd_ann'])} ({'+' if x['benefit'] >= 0 else '−'}{fmt_inr(abs(x['benefit']))} over {x['n']} lots).")
    worst = sorted([p for p in pockets if p[2]["n"] >= 3 and p[2]["benefit"] < 0], key=lambda p: p[2]["benefit"])[:3]
    flags = [f"<b>{ft} held {slab}:</b> FD would have been better — mutual fund {_pct(x['ann'])} vs FD {_pct(x['fd_ann'])}, "
             f"{fmt_inr(abs(x['benefit']))} left on the table ({x['n']} lots)." for ft, slab, x, v in worst]
    if bullets or flags:
        html = '<div class="iv-box info"><b>What your own history suggests</b><ul>' + \
               "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
        if flags:
            html += '<b style="display:block;margin-top:10px;">Biggest missed opportunities</b><ul>' + \
                    "".join(f"<li>{f}</li>" for f in flags) + "</ul>"
        html += ('<div style="margin-top:8px;font-size:12px;opacity:.8;">Pre-tax and based on past redemptions — '
                 'not a forecast. Slabs with fewer than 3 lots are not used for guidance.</div></div>')
        st.markdown(html, unsafe_allow_html=True)

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
        t1, t2, t3 = st.tabs(["Capital gain sheet", "Open holdings", "FD rate card"])

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

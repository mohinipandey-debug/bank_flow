import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import datetime
import io
from database import (
    get_all_transactions, get_summary, get_uncategorized,
    get_large_debits, get_missing_statements, reload_categories, init_db,
    get_cashflow, manual_categorize, get_all_categories,
    revert_manual_category, get_category_audit,
    get_investment_register, update_investment_opening,
    add_investment_scheme, delete_investment_scheme,
    get_investment_summary, get_available_months,
    get_transaction_count, get_closing_balance, get_paginated_transactions,
    get_transfer_reconciliation, get_monthly_trend,
    get_yoy_comparison, get_top_expenses_comparison, get_weekly_cash_position,
    get_upload_trail, delete_upload,
    reserve_upload_trail, finalize_upload_trail, check_upload_delete_impact,
    get_account_balances,
    set_cash_entry, get_cash_asof, get_cash_history,
    delete_cash_entry, import_cash_excel,
    get_investment_transactions, tag_investment_transaction,
    get_investment_movements, get_investment_events, get_daywise_totals,
    get_data_integrity_report, get_opening_lots, compute_fifo, repair_order_keys,
    find_duplicate_rows, remove_duplicate_rows,
    add_manual_investment, get_manual_investments,
    delete_manual_investment, get_manual_investment_totals,
    get_entity_closing_balance, get_summary_with_bank,
    import_investment_excel, get_investment_kpis,
    get_entity_bank_balance_asof,
    get_entity_investment_asof,
    get_latest_data_date,
    get_account_balances_asof,
)
from config import ENTITIES, LARGE_DEBIT_THRESHOLD, DATABASE_FILE

# ── Financial-year constants ───────────────────────────────────────────────────
FY_OPTIONS = ["FY2425", "FY2526", "FY2627"]
FY_LABELS  = {
    "FY2425": "FY 2024-25",
    "FY2526": "FY 2025-26",
    "FY2627": "FY 2026-27",
}
FY_BOUNDS  = {
    "FY2425": (datetime.date(2024, 4, 1), datetime.date(2025, 3, 31)),
    "FY2526": (datetime.date(2025, 4, 1), datetime.date(2026, 3, 31)),
    "FY2627": (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31)),
}
from utils.formatters import fmt_inr, _inr, _td, _td_dash, fmt_cr, fmt_cf
from utils.ui import rcol, amount_config

# ── Cached DB wrappers ────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _cached_summary(entity, month, financial_year):
    return get_summary(
        entity=entity if entity != "All" else None,
        month=month   if month  != "All" else None,
        financial_year=financial_year,
    )

@st.cache_data(ttl=600)
def _cached_months(financial_year):
    return get_available_months(financial_year=financial_year)

@st.cache_data(ttl=300)
def _cached_uncategorized(entity, bank, month, financial_year):
    return get_uncategorized(
        entity=entity             if entity         != "All" else None,
        bank=bank                 if bank           != "All" else None,
        month=month               if month          != "All" else None,
        financial_year=financial_year if financial_year and financial_year != "All" else None,
    )

@st.cache_data(ttl=300)
def _cached_summary_full(entity, bank, month, date_from, date_to):
    return get_summary_with_bank(
        entity=entity   if entity != "All" else None,
        bank=bank       if bank   != "All" else None,
        month=month     if month  != "All" else None,
        date_from=date_from if date_from else None,
        date_to=date_to     if date_to   else None,
    )

@st.cache_data(ttl=60)
def _cached_entity_balance(entity):
    return get_entity_closing_balance(entity)

@st.cache_data(ttl=300)
def _cached_count(entity, bank, month, financial_year, date_from=None, date_to=None):
    return get_transaction_count(
        entity=entity if entity != "All" else None,
        bank=bank     if bank   != "All" else None,
        month=month   if month  != "All" else None,
        financial_year=financial_year,
        date_from=date_from, date_to=date_to,
    )

@st.cache_data(ttl=300)
def _cached_closing(entity, bank, month, financial_year):
    return get_closing_balance(
        entity=entity if entity != "All" else None,
        bank=bank     if bank   != "All" else None,
        month=month   if month  != "All" else None,
        financial_year=financial_year,
    )

@st.cache_data(ttl=300)
def _cached_inv_header_totals():
    """Lightweight FD+MF totals for header band — avoids full investment query on every tab."""
    _d = get_investment_summary()
    return {
        "fd": sum(r["current_value"] for r in _d if r["scheme_type"] == "FD"),
        "mf": sum(r["current_value"] for r in _d if r["scheme_type"] == "MF"),
    }

from queries.cashflow_queries import fetch_cf, get_mf_fd_cash_asof

_integrity_raw = get_data_integrity_report     # uncached, for use right after an upload

# ── Cache every read-only data query (5 min; any write calls st.cache_data.clear()) ──
for _fn_name in (
    "get_monthly_trend", "get_yoy_comparison", "get_top_expenses_comparison",
    "get_weekly_cash_position", "get_account_balances_asof",
    "get_entity_investment_asof", "get_entity_bank_balance_asof", "get_cash_asof",
    "get_cash_history", "get_latest_data_date", "get_closing_balance",
    "get_all_categories", "get_paginated_transactions", "get_all_transactions",
    "get_investment_events", "get_investment_movements", "get_investment_register",
    "get_manual_investments", "get_manual_investment_totals",
    "get_investment_transactions", "get_investment_summary",
    "get_uncategorized", "get_missing_statements", "get_large_debits",
    "get_transfer_reconciliation", "get_upload_trail", "get_category_audit",
    "fetch_cf", "get_mf_fd_cash_asof", "get_daywise_totals", "get_data_integrity_report", "find_duplicate_rows",
):
    globals()[_fn_name] = st.cache_data(ttl=300, show_spinner=False)(globals()[_fn_name])
from tabs.overview import render_overview
from tabs.review_queue import render_review_queue
from tabs.investment_overview import render_investment_overview, render_investment_header
from tabs.cashflow_statement_view import render_cashflow_statement

# ── Live-view badge — shown in tabs that are NOT filtered by FY ───────────────

CF_STYLE = """
<span class="cf-scope"></span>
<style>
/* ═══ Cash Flow tab — roomy card layout ═══════════════════════════════════ */
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .cf-scope) { gap: 0.5rem !important; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .cf-scope)
  > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]:not(:has(.nav-active-indicator)) {
  gap: 0 !important; align-items: stretch !important;
}
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .cf-scope)
  > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]:not(:has(.nav-active-indicator))
  > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] { height: 100%; justify-content: center; }
/* Streamlit gives markdown a -16px bottom margin, which makes tall custom bars overlap the next row */
[data-testid="stMarkdownContainer"]:has(> div[class^="cf-"]) { margin-bottom: 0 !important; }
/* detail lines sit closer together than section bars */
[data-testid="stLayoutWrapper"]:has(.cf-sub-row), [data-testid="stLayoutWrapper"]:has(.cf-detail),
[data-testid="stLayoutWrapper"]:has(.cf-wk-sub-lbl) { margin-top: -0.5rem; }
[data-testid="stLayoutWrapper"]:has(.cf-recon-lbl) { margin-top: -0.3rem; }

/* ── statement heading ── */
.cf-stmt-head {
  display: flex; align-items: center; justify-content: space-between;
  margin: 14px 0 4px; padding: 0 4px;
}
.cf-stmt-title { font-size: 12px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #1B2B4B; }
.cf-stmt-range {
  font-size: 12px; font-weight: 600; color: #3D4F66; background: #FFFFFF;
  border: 1px solid #E2E7EF; border-radius: 20px; padding: 5px 14px;
}

/* ── +/- toggle buttons ── */
[class*="st-key-btn_"] button, [class*="st-key-wbtn_"] button {
  width: 34px !important; min-height: 34px !important; height: 34px !important;
  padding: 0 !important; margin-left: 8px; border-radius: 10px !important;
  border: 1px solid #C8D3E0 !important; color: #1B2B4B !important;
  font-weight: 700 !important; font-size: 16px !important; background: #FFFFFF !important;
  box-shadow: 0 1px 2px rgba(10,22,40,0.06) !important;
}
[class*="st-key-btn_"] button:hover, [class*="st-key-wbtn_"] button:hover {
  background: #1B2B4B !important; color: #FFFFFF !important; border-color: #1B2B4B !important;
}
[class*="st-key-btn_"] > div, [class*="st-key-wbtn_"] > div { display: flex; align-items: center; }

/* Expand / Collapse — compact */
.st-key-cf_expand_all button, .st-key-cf_collapse_all button {
  min-height: 34px !important; height: 34px !important; padding: 0 14px !important;
  font-size: 12.5px !important; border-radius: 10px !important; white-space: nowrap;
}
.st-key-cf_expand_all, .st-key-cf_collapse_all { margin-right: 6px; }

/* ── section bars ── */
.cf-section-label {
  display: flex !important; align-items: center; min-height: 58px;
  padding: 0 24px !important; font-size: 15px !important; font-weight: 700;
  letter-spacing: 0.02em; border-radius: 14px 0 0 14px !important;
  box-shadow: 0 1px 3px rgba(10,22,40,0.05);
}
.cf-section-total {
  display: flex !important; align-items: center; justify-content: flex-end;
  min-height: 58px; padding: 0 26px !important; font-size: 18px !important;
  font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.3px !important;
  border-radius: 0 14px 14px 0 !important; box-shadow: 0 1px 3px rgba(10,22,40,0.05);
}
.cf-ob, .cf-cb   { background: #EAF0FA !important; color: #1B2B4B !important; border-left: 5px solid #1B2B4B !important; }
.cf-rec          { background: #ECFDF3 !important; color: #166534 !important; border-left: 5px solid #22C55E !important; }
.cf-pay          { background: #FEF0F0 !important; color: #991B1B !important; border-left: 5px solid #EF4444 !important; }
.cf-section-total.sky { background: #EAF0FA !important; color: #1B2B4B !important; }
.cf-section-total.pos { background: #ECFDF3 !important; color: #166534 !important; }
.cf-section-total.neg { background: #FEF0F0 !important; color: #991B1B !important; }

/* ── group rows ── */
.cf-grp-row, .cf-grp-val, .cf-wk-grp-lbl, .cf-wk-grp-val {
  display: flex !important; align-items: center; min-height: 46px;
  background: #F6F8FB !important; font-weight: 600 !important; font-size: 13.5px !important;
  color: #1B2B4B !important; font-variant-numeric: tabular-nums;
}
.cf-grp-row, .cf-wk-grp-lbl { padding: 0 20px !important; border-left: 4px solid #93A4BF; border-radius: 10px 0 0 10px; }
.cf-grp-val, .cf-wk-grp-val { justify-content: flex-end; padding: 0 24px !important; border-radius: 0 10px 10px 0; }
.cf-wk-grp-val { border-radius: 0; padding: 0 16px !important; }

/* ── detail rows ── */
.cf-sub-row, .cf-sub-val, .cf-detail, .cf-dval, .cf-wk-sub-lbl, .cf-wk-sub-val {
  display: flex !important; align-items: center; min-height: 40px;
  font-size: 13px !important; color: #3D4F66 !important;
  background: #FFFFFF; border-bottom: 1px solid #EDF0F5;
  font-variant-numeric: tabular-nums;
}
.cf-sub-row, .cf-detail, .cf-wk-sub-lbl { padding: 0 16px 0 44px !important; }
.cf-sub-val, .cf-dval, .cf-wk-sub-val { justify-content: flex-end; padding: 0 26px !important; }
.cf-sub-row.unc, .cf-sub-val.unc, .cf-detail.unc, .cf-dval.unc { color: #6B7A90 !important; font-style: italic; }

/* ── reconciling lines ── */
.cf-recon-lbl {
  display: flex; align-items: center; min-height: 46px; padding: 0 20px;
  font-size: 13.5px; font-weight: 600; color: #1B2B4B; background: #F6F8FB;
  border-left: 4px solid #93A4BF; border-radius: 10px 0 0 10px;
}
.cf-recon-val {
  display: flex; align-items: center; justify-content: flex-end; min-height: 46px;
  padding: 0 24px; font-size: 14px; font-weight: 700; background: #F6F8FB;
  border-radius: 0 10px 10px 0; font-variant-numeric: tabular-nums;
}

/* ── weekly table ── */
.cf-wk-hdr {
  display: flex; align-items: center; justify-content: flex-end; min-height: 42px;
  padding: 0 14px !important; background: #1B2B4B !important; color: #FFFFFF !important;
  white-space: nowrap; font-size: 11.5px !important; font-weight: 700; letter-spacing: 0.03em; border-radius: 0 !important;
}
.cf-wk-hdr.ttl { background: #2E4A72 !important; }
.cf-wk-val {
  display: flex !important; align-items: center; justify-content: flex-end; min-height: 50px;
  padding: 0 16px !important; font-variant-numeric: tabular-nums;
}

[data-testid="stLayoutWrapper"]:has(.cf-detail) .cf-wk-val {
  min-height: 40px; font-size: 13px; font-weight: 500; color: #3D4F66; background: #FFFFFF;
  border-bottom: 1px solid #EDF0F5;
}

/* ── net movement + tally ── */
.cf-net {
  border-radius: 16px !important; border-width: 2px 0 !important; padding: 20px 28px !important;
  margin-top: 14px !important; font-size: 15px !important; box-shadow: 0 2px 8px rgba(10,22,40,0.06) !important;
}
.cf-net span:last-child { font-size: 26px !important; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.6px; }
.cf-tally { border-radius: 12px !important; padding: 10px 18px !important; margin-top: 10px !important; }
</style>
"""

LIVE_BANNER = """
<div style="display:inline-flex; align-items:center; gap:8px;
     background:#F0FDF4; border:1px solid #86EFAC;
     border-radius:20px; padding:4px 14px; margin-bottom:16px;
     font-size:12px; color:#166534; font-weight:500;">
    <span style="width:8px; height:8px; background:#22C55E;
          border-radius:50%; display:inline-block;
          animation:pulse 2s infinite;"></span>
    Live &middot; All periods &middot; All entities
</div>
<style>
@keyframes pulse {
    0%, 100% { opacity:1; }
    50%       { opacity:0.4; }
}
</style>
"""


st.set_page_config(
    page_title="BankFlow | Ventures & Stores",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# TO ADD YOUR COMPANY LOGO:
# 1. Save your logo file as 'logo.png' in the BankFlow folder
#    (same folder as dashboard.py)
# 2. Replace the logo placeholder block in the sidebar with:
#
#    from PIL import Image
#    logo = Image.open("logo.png")
#    st.sidebar.image(logo, use_container_width=True)
#
# 3. pip install Pillow  (run once in terminal)
# 4. Restart Streamlit

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ═══════════════════════════════════════════════════════════
   DESIGN TOKENS
═══════════════════════════════════════════════════════════ */
:root {
  /* Surfaces */
  --bg-app:        #E8ECF3;
  --bg-surface:    #FFFFFF;
  --bg-raised:     #F4F6FA;
  --bg-inset:      #F0F3F8;

  /* Borders */
  --border-xs:     #EDF0F5;
  --border-sm:     #E2E7EF;
  --border-md:     #C8D3E0;

  /* Text */
  --tx-1:          #0A1628;
  --tx-2:          #3D4F66;
  --tx-3:          #6B7A90;
  --tx-4:          #96A3B4;

  /* Brand */
  --navy-900:      #081528;
  --navy-800:      #0F2044;
  --navy-700:      #1B2B4B;
  --navy-600:      #243654;
  --navy-500:      #2E4A72;
  --blue-600:      #1E40AF;
  --blue-500:      #2563EB;
  --blue-400:      #3B82F6;
  --blue-100:      #DBEAFE;
  --blue-50:       #EFF6FF;

  /* Semantic */
  --green-700:     #15803D;
  --green-500:     #22C55E;
  --green-400:     #4ADE80;
  --green-50:      #F0FDF4;
  --green-border:  #BBF7D0;

  --red-700:       #B91C1C;
  --red-500:       #EF4444;
  --red-400:       #F87171;
  --red-50:        #FFF1F2;
  --red-border:    #FECDD3;

  --amber-700:     #B45309;
  --amber-50:      #FFFBEB;
  --amber-border:  #FDE68A;

  /* Shadows — three tiers */
  --shadow-xs:     0 1px 2px rgba(10,22,40,0.04);
  --shadow-sm:     0 1px 3px rgba(10,22,40,0.06), 0 2px 8px rgba(10,22,40,0.04);
  --shadow-md:     0 2px 6px rgba(10,22,40,0.07), 0 4px 16px rgba(10,22,40,0.05);
  --shadow-lg:     0 4px 12px rgba(10,22,40,0.09), 0 8px 28px rgba(10,22,40,0.06);
  --shadow-inset:  inset 0 1px 2px rgba(10,22,40,0.05);

  /* Radius */
  --r-sm:  6px;
  --r-md:  8px;
  --r-lg:  12px;
  --r-xl:  16px;

  /* Transitions */
  --t-fast:  all 0.12s ease;
  --t-base:  all 0.18s ease;
}

/* ═══════════════════════════════════════════════════════════
   BASE RESET
═══════════════════════════════════════════════════════════ */
html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  -webkit-font-smoothing: antialiased !important;
  text-rendering: optimizeLegibility !important;
}

.block-container {
  padding-top: 3.5rem !important;
  padding-bottom: 1.5rem !important;
  max-width: 100% !important;
}

.stApp {
  background: var(--bg-app) !important;
}

/* Custom scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-md); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--tx-4); }

/* ═══════════════════════════════════════════════════════════
   SIDEBAR
═══════════════════════════════════════════════════════════ */
section[data-testid="stSidebar"] {
  background: var(--bg-surface) !important;
  border-right: 1px solid var(--border-sm) !important;
  box-shadow: 2px 0 12px rgba(10,22,40,0.05) !important;
}

/* Sidebar filter labels */
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stDateInput label {
  color: var(--tx-3) !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
}

/* Sidebar selectbox */
section[data-testid="stSidebar"] .stSelectbox > div > div {
  background: var(--bg-inset) !important;
  border: 1px solid var(--border-sm) !important;
  border-radius: var(--r-md) !important;
  color: var(--tx-1) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  box-shadow: var(--shadow-inset) !important;
  transition: var(--t-fast) !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div:hover {
  border-color: var(--border-md) !important;
  background: var(--bg-surface) !important;
}

/* Sidebar date inputs */
[data-testid="stSidebar"] [data-baseweb="input"] {
  background: var(--bg-inset) !important;
  border-color: var(--border-sm) !important;
  border-radius: var(--r-md) !important;
  box-shadow: var(--shadow-inset) !important;
  font-size: 12px !important;
}

/* Sidebar section headers */
.sidebar-section {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--tx-4);
  margin: 18px 0 8px 2px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-xs);
}

/* ═══════════════════════════════════════════════════════════
   HEADER BAND
═══════════════════════════════════════════════════════════ */
.header-band {
  background: linear-gradient(135deg, var(--navy-900) 0%, var(--navy-700) 55%, var(--navy-600) 100%);
  padding: 16px 28px 16px 28px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  box-shadow: 0 4px 20px rgba(8,21,40,0.4);
}

.header-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
  min-height: 44px;
}

.header-logo-area { display: flex; align-items: center; gap: 12px; }

.header-logo-box {
  width: 38px;
  height: 38px;
  background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: var(--r-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 800;
  color: #FFFFFF;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.header-title {
  font-size: 14px;
  font-weight: 700;
  color: #FFFFFF;
  margin-bottom: 2px;
  letter-spacing: 0.1px;
}

.header-subtitle {
  font-size: 11px;
  color: rgba(255,255,255,0.4);
  font-weight: 400;
  letter-spacing: 0.02em;
}

.header-pills {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 20px;
  padding: 3px 10px;
  font-size: 10px;
  font-weight: 500;
  color: rgba(255,255,255,0.6);
  letter-spacing: 0.02em;
}

.pill-dot { width:5px; height:5px; border-radius:50%; background:#4ADE80; display:inline-block; }
.pill-live { background: rgba(74,222,128,0.12); border-color: rgba(74,222,128,0.28); color: #4ADE80; }
.pill-txn  { background: rgba(147,197,253,0.10); border-color: rgba(147,197,253,0.22); color: rgba(147,197,253,0.9); }
.pill-period { background: rgba(255,255,255,0.07); border-color: rgba(255,255,255,0.12); }

/* KPI strip */
.kpi-strip {
  display: flex;
  gap: 0;
  align-items: flex-start;
  flex-wrap: wrap;
}

.kpi-strip-item {
  padding: 0 32px 0 0;
  margin-right: 0;
  border-right: 1px solid rgba(255,255,255,0.10);
}
.kpi-strip-item:last-child { border-right: none; padding-right: 0; }

.kpi-strip-hero {
  padding-right: 32px;
  margin-right: 0;
  border-right: 1px solid rgba(255,255,255,0.18) !important;
  padding-bottom: 2px;
}

.kpi-strip-label {
  font-size: 8.5px;
  font-weight: 700;
  color: rgba(255,255,255,0.35);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.kpi-strip-value {
  font-size: 21px;
  font-weight: 800;
  color: #FFFFFF;
  letter-spacing: -0.6px;
  line-height: 1.1;
}

.kpi-strip-value.pos { color: #4ADE80; }
.kpi-strip-value.neg { color: #F87171; }
.kpi-strip-value.sky { color: #93C5FD; }

.kpi-strip-sub { font-size: 10px; margin-top: 3px; font-weight: 400; line-height: 1.3; }
.kpi-positive  { color: rgba(74,222,128,0.65); }
.kpi-negative  { color: rgba(248,113,113,0.65); }
.kpi-neutral   { color: rgba(255,255,255,0.28); }

/* ═══════════════════════════════════════════════════════════
   NAV BAR (button-injected)
═══════════════════════════════════════════════════════════ */
/* Preserved .nav-bar / .nav-tab for any static uses */
.nav-bar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-xs);
  padding: 0 8px;
  margin: 0 0 16px 0;
  display: flex; gap: 0;
}
.nav-tab {
  padding: 11px 18px; font-size: 13px; font-weight: 500;
  color: var(--tx-3); border-bottom: 3px solid transparent; white-space: nowrap;
}
.nav-tab.active { color: var(--navy-700); font-weight: 700; border-bottom-color: var(--navy-700); }

/* Active nav button override */
.stButton > button[kind="primary"] {
  background: var(--blue-50) !important;
  color: var(--navy-700) !important;
  border-color: var(--navy-700) !important;
  font-weight: 700 !important;
}

/* ═══════════════════════════════════════════════════════════
   CARDS & SURFACES  (Phase 3)
═══════════════════════════════════════════════════════════ */
.card {
  background: var(--bg-surface);
  border-radius: var(--r-lg);
  padding: 18px 22px;
  border: 1px solid var(--border-sm);
  box-shadow: var(--shadow-sm);
  margin-bottom: 12px;
  transition: var(--t-base);
  overflow: hidden;
  position: relative;
}
.card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-md);
}

.card-title {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--tx-4);
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-title::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 11px;
  background: var(--blue-400);
  border-radius: 2px;
  flex-shrink: 0;
}

/* Chart card wrapper — use around plotly charts */
.chart-card {
  background: var(--bg-surface);
  border-radius: var(--r-lg);
  padding: 16px 18px 12px;
  border: 1px solid var(--border-sm);
  box-shadow: var(--shadow-sm);
  margin-bottom: 12px;
  overflow: hidden;
}

/* ═══════════════════════════════════════════════════════════
   PLOTLY CHART CONTAINERS  (Phase 3)
═══════════════════════════════════════════════════════════ */
[data-testid="stPlotlyChart"] {
  background: var(--bg-surface) !important;
  border-radius: var(--r-lg) !important;
  border: 1px solid var(--border-sm) !important;
  box-shadow: var(--shadow-sm) !important;
  padding: 6px 4px 2px !important;
  overflow: hidden !important;
}

/* ═══════════════════════════════════════════════════════════
   ENTITY CARDS  (Phase 3)
═══════════════════════════════════════════════════════════ */
.entity-card {
  background: var(--bg-surface);
  border-radius: var(--r-lg);
  padding: 0 0 16px 0;
  border: 1px solid var(--border-sm);
  box-shadow: var(--shadow-sm);
  margin-bottom: 10px;
  transition: var(--t-base);
  overflow: hidden;
}
.entity-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-md);
  transform: translateY(-1px);
}

/* Colored top accent bar — first entity blue, second teal */
.entity-card:nth-child(1) { border-top: 3px solid var(--blue-400); }
.entity-card:nth-child(2) { border-top: 3px solid #14B8A6; }

.entity-name {
  font-size: 9.5px;
  font-weight: 700;
  color: var(--tx-2);
  letter-spacing: 0.13em;
  text-transform: uppercase;
  padding: 12px 18px 10px;
  border-bottom: 1px solid var(--border-xs);
  background: var(--bg-raised);
}

.stat-row { display: flex; gap: 10px; flex-wrap: wrap; padding: 12px 16px 0; }

.stat-badge {
  display: inline-flex;
  flex-direction: column;
  background: var(--bg-raised);
  border-radius: var(--r-md);
  padding: 8px 14px;
  min-width: 88px;
  border: 1px solid var(--border-xs);
  transition: var(--t-fast);
}
.stat-badge:hover {
  border-color: var(--border-md);
  background: var(--bg-surface);
  box-shadow: var(--shadow-xs);
}

.stat-badge-label {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--tx-4);
  margin-bottom: 4px;
}

.stat-badge-value { font-size: 14px; font-weight: 700; color: var(--tx-1); letter-spacing: -0.3px; }
.badge-green .stat-badge-value { color: var(--green-700); }
.badge-red   .stat-badge-value { color: var(--red-700); }
.badge-blue  .stat-badge-value { color: var(--blue-600); }
.badge-grey  .stat-badge-value { color: var(--tx-3); }

/* ═══════════════════════════════════════════════════════════
   SECTION HEADERS
═══════════════════════════════════════════════════════════ */
.section-title, .section-header {
  font-size: 10px;
  font-weight: 700;
  color: var(--tx-4);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin: 20px 0 10px 0;
}

/* ═══════════════════════════════════════════════════════════
   KPI CARDS  (Phase 3 — refined)
═══════════════════════════════════════════════════════════ */
.kpi-card {
  background: var(--bg-surface);
  border-radius: var(--r-lg);
  padding: 16px 20px 16px 22px;
  border: 1px solid var(--border-sm);
  box-shadow: var(--shadow-sm);
  position: relative;
  overflow: hidden;
  margin-bottom: 10px;
  transition: var(--t-base);
}
.kpi-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-md);
}
.kpi-card::before {
  content: ''; position: absolute; top: 0; left: 0;
  width: 4px; height: 100%; border-radius: var(--r-lg) 0 0 var(--r-lg);
}
.kpi-card.green::before { background: linear-gradient(180deg, var(--green-400), var(--green-700)); }
.kpi-card.red::before   { background: linear-gradient(180deg, var(--red-400),   var(--red-700)); }
.kpi-card.blue::before  { background: linear-gradient(180deg, #60A5FA,          var(--blue-600)); }
.kpi-card.navy::before  { background: linear-gradient(180deg, var(--navy-500),  var(--navy-900)); }

.kpi-label {
  font-size: 9px; font-weight: 700; color: var(--tx-4);
  letter-spacing: 0.13em; text-transform: uppercase; margin-bottom: 8px;
}
.kpi-value {
  font-size: 24px; font-weight: 800; color: var(--tx-1);
  margin-bottom: 3px; letter-spacing: -0.6px; line-height: 1.1;
}
.kpi-value.positive { color: var(--green-700); }
.kpi-value.negative { color: var(--red-700); }
.kpi-sub { font-size: 11px; color: var(--tx-4); margin-top: 4px; line-height: 1.4; }

/* ═══════════════════════════════════════════════════════════
   TABLES & DATA FRAMES  (Phase 3)
═══════════════════════════════════════════════════════════ */
.stDataFrame,
[data-testid="stDataFrameResizable"] {
  border: 1px solid var(--border-sm) !important;
  border-radius: var(--r-lg) !important;
  overflow: hidden !important;
  box-shadow: var(--shadow-sm) !important;
  background: var(--bg-surface) !important;
}

/* Header row */
.stDataFrame thead tr th {
  background: linear-gradient(180deg, var(--bg-raised) 0%, #ECEEF3 100%) !important;
  color: var(--tx-3) !important;
  font-size: 9.5px !important;
  font-weight: 700 !important;
  letter-spacing: 0.09em !important;
  text-transform: uppercase !important;
  border-bottom: 2px solid var(--border-sm) !important;
  padding: 7px 12px !important;
  white-space: nowrap !important;
}

/* Body rows */
.stDataFrame tbody tr td {
  font-size: 12.5px !important;
  color: var(--tx-1) !important;
  padding: 6px 12px !important;
  border-bottom: 1px solid var(--border-xs) !important;
  transition: background 0.1s ease !important;
}
.stDataFrame tbody tr:nth-child(even) td {
  background: var(--bg-raised) !important;
}
.stDataFrame tbody tr:hover td {
  background: var(--blue-50) !important;
  color: var(--navy-700) !important;
}

/* ═══════════════════════════════════════════════════════════
   HR DIVIDERS
═══════════════════════════════════════════════════════════ */
hr { border-color: var(--border-xs) !important; margin: 10px 0 !important; }

/* ═══════════════════════════════════════════════════════════
   BUTTONS
═══════════════════════════════════════════════════════════ */
.stButton > button {
  background: var(--bg-surface) !important;
  color: var(--tx-2) !important;
  border: 1px solid var(--border-sm) !important;
  border-radius: var(--r-md) !important;
  font-size: 12.5px !important;
  font-weight: 500 !important;
  padding: 5px 14px !important;
  transition: var(--t-fast) !important;
  box-shadow: var(--shadow-xs) !important;
  letter-spacing: 0.01em !important;
}
.stButton > button:hover {
  background: var(--bg-inset) !important;
  border-color: var(--border-md) !important;
  color: var(--navy-700) !important;
  box-shadow: var(--shadow-sm) !important;
}
.stButton > button:active {
  transform: translateY(1px) !important;
  box-shadow: none !important;
}

[data-testid="stDownloadButton"] > button {
  background: var(--navy-700) !important;
  color: #FFFFFF !important;
  border-color: var(--navy-700) !important;
  border-radius: var(--r-md) !important;
  font-weight: 600 !important;
  box-shadow: 0 1px 4px rgba(27,43,75,0.3) !important;
}
[data-testid="stDownloadButton"] > button:hover {
  background: var(--navy-800) !important;
  box-shadow: 0 2px 8px rgba(27,43,75,0.4) !important;
}

/* ═══════════════════════════════════════════════════════════
   FORM INPUTS
═══════════════════════════════════════════════════════════ */
[data-testid="stTextInput"] > div > div {
  border-radius: var(--r-md) !important;
  border-color: var(--border-sm) !important;
  background: var(--bg-surface) !important;
  font-size: 13px !important;
  box-shadow: var(--shadow-inset) !important;
}
[data-testid="stTextInput"] > div > div:focus-within {
  border-color: var(--blue-400) !important;
  box-shadow: 0 0 0 3px rgba(59,130,246,0.12) !important;
}

[data-testid="stSelectbox"] > div > div {
  border-radius: var(--r-md) !important;
  border-color: var(--border-sm) !important;
  font-size: 13px !important;
}

[data-baseweb="select"] {
  border-radius: var(--r-md) !important;
}

/* ═══════════════════════════════════════════════════════════
   EXPANDERS
═══════════════════════════════════════════════════════════ */
[data-testid="stExpander"] {
  background: var(--bg-surface) !important;
  border-radius: var(--r-md) !important;
  border: 1px solid var(--border-sm) !important;
  box-shadow: var(--shadow-xs) !important;
  margin-bottom: 8px !important;
}
[data-testid="stExpander"] summary {
  font-size: 12.5px !important;
  font-weight: 600 !important;
  color: var(--tx-2) !important;
  padding: 10px 14px !important;
}
[data-testid="stExpander"] summary:hover {
  background: var(--bg-raised) !important;
  border-radius: var(--r-md) var(--r-md) 0 0 !important;
}

/* ═══════════════════════════════════════════════════════════
   METRICS
═══════════════════════════════════════════════════════════ */
[data-testid="stMetric"] {
  background: var(--bg-surface) !important;
  border-radius: var(--r-md) !important;
  padding: 12px 16px !important;
  border: 1px solid var(--border-sm) !important;
  box-shadow: var(--shadow-xs) !important;
}
[data-testid="stMetricValue"] { color: var(--tx-1) !important; }
[data-testid="stMetricLabel"] { color: var(--tx-4) !important; font-size: 10px !important; }

/* ═══════════════════════════════════════════════════════════
   CAPTIONS & ALERTS
═══════════════════════════════════════════════════════════ */
[data-testid="stCaptionContainer"] p {
  color: var(--tx-3) !important;
  font-size: 11.5px !important;
}

[data-testid="stAlert"] { border-radius: var(--r-md) !important; }

.alert-box {
  border-radius: var(--r-md);
  padding: 12px 16px;
  margin: 8px 0;
  border-left: 3px solid;
  font-size: 13px;
}
.alert-red    { background: var(--red-50);   border-color: var(--red-500);   color: #7F1D1D; }
.alert-yellow { background: var(--amber-50); border-color: var(--amber-700); color: #78350F; }
.alert-green  { background: var(--green-50); border-color: var(--green-500); color: #14532D; }
.alert-blue   { background: var(--blue-50);  border-color: var(--blue-400);  color: var(--navy-700); }

/* ═══════════════════════════════════════════════════════════
   SIDEBAR STAT CARDS
═══════════════════════════════════════════════════════════ */
.sb-stats-grid {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-bottom: 12px;
}

.sb-stat-card {
  background: var(--bg-raised);
  border-radius: var(--r-md);
  padding: 9px 14px;
  border: 1px solid var(--border-xs);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.sb-stat-card.green { background: var(--green-50);  border-color: var(--green-border); }
.sb-stat-card.red   { background: var(--red-50);    border-color: var(--red-border); }
.sb-stat-card.amber { background: var(--amber-50);  border-color: var(--amber-border); }

.sb-stat-left { display: flex; flex-direction: column; gap: 2px; }

.sb-stat-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--tx-4);
}
.sb-stat-label.green { color: var(--green-700); }
.sb-stat-label.red   { color: var(--red-700); }
.sb-stat-label.amber { color: var(--amber-700); }

.sb-stat-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--tx-1);
  letter-spacing: -0.3px;
}
.sb-stat-value.green { color: var(--green-700); }
.sb-stat-value.red   { color: var(--red-700); }
.sb-stat-value.amber { color: var(--amber-700); }

.sb-stat-icon {
  font-size: 18px;
  opacity: 0.45;
  flex-shrink: 0;
}

/* ═══════════════════════════════════════════════════════════
   WoW TREND BADGES
═══════════════════════════════════════════════════════════ */
.kpi-wow {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 9.5px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 20px;
  margin-top: 5px;
  letter-spacing: 0.02em;
}
.kpi-wow.up   { background: rgba(74,222,128,0.18); color: #4ADE80; }
.kpi-wow.down { background: rgba(248,113,113,0.18); color: #F87171; }
.kpi-wow.flat { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.4); }
.kpi-wow.warn { background: rgba(251,191,36,0.18);  color: #FBBF24; }

/* ═══════════════════════════════════════════════════════════
   EXECUTIVE INSIGHTS PANEL
═══════════════════════════════════════════════════════════ */
.insight-panel {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
  margin: 0 0 20px;
}
.insight-card {
  background: var(--bg-surface);
  border-radius: var(--r-lg);
  border: 1px solid var(--border-sm);
  padding: 13px 15px;
  display: flex;
  gap: 11px;
  align-items: flex-start;
  box-shadow: var(--shadow-xs);
}
.insight-card.green { border-color: var(--green-border); background: var(--green-50); }
.insight-card.red   { border-color: var(--red-border);   background: var(--red-50); }
.insight-card.amber { border-color: var(--amber-border); background: var(--amber-50); }
.insight-card.blue  { border-color: #BFDBFE; background: #EFF6FF; }
.insight-icon { font-size: 17px; line-height: 1.1; flex-shrink: 0; }
.insight-body { display: flex; flex-direction: column; gap: 3px; }
.insight-title { font-size: 11.5px; font-weight: 600; color: var(--tx-1); line-height: 1.35; }
.insight-desc  { font-size: 10.5px; color: var(--tx-3); line-height: 1.45; }

/* ═══════════════════════════════════════════════════════════
   ENTITY BREAKDOWN CARDS
═══════════════════════════════════════════════════════════ */
.ent-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
  margin: 0 0 18px;
}
.ent-card {
  background: var(--bg-surface);
  border-radius: var(--r-lg);
  border: 1px solid var(--border-sm);
  padding: 16px 20px;
  box-shadow: var(--shadow-xs);
  transition: var(--t-base);
}
.ent-card:hover { box-shadow: var(--shadow-md); border-color: var(--border-md); }
.ent-card-name { font-size: 9px; font-weight: 700; letter-spacing: 0.13em; text-transform: uppercase; color: var(--tx-4); margin-bottom: 7px; }
.ent-card-net  { font-size: 27px; font-weight: 800; letter-spacing: -0.6px; line-height: 1; margin-bottom: 10px; }
.ent-card-net.pos { color: var(--green-700); }
.ent-card-net.neg { color: var(--red-700); }
.ent-card-row  { display: flex; justify-content: space-between; align-items: baseline; font-size: 11px; color: var(--tx-3); padding: 3px 0; border-top: 1px solid var(--border-xs); }
.ent-card-in   { color: var(--green-700); font-weight: 600; font-size: 12px; }
.ent-card-out  { color: var(--red-700);   font-weight: 600; font-size: 12px; }

/* ═══════════════════════════════════════════════════════════
   KPI STRIP ENHANCEMENTS
═══════════════════════════════════════════════════════════ */
.kpi-strip-divider {
  height: 1px;
  background: rgba(255,255,255,0.08);
  margin: 12px 0 14px;
}

.kpi-arrow-up   { font-size: 10px; color: rgba(74,222,128,0.8); margin-right: 2px; }
.kpi-arrow-down { font-size: 10px; color: rgba(248,113,113,0.8); margin-right: 2px; }

/* ═══════════════════════════════════════════════════════════
   CASH FLOW STATEMENT  (Phase 4)
═══════════════════════════════════════════════════════════ */

/* Control bar (filter strip) */
.cf-control-bar {
  background: linear-gradient(135deg, var(--navy-900) 0%, var(--navy-700) 60%, var(--navy-600) 100%);
  border-radius: var(--r-lg);
  padding: 16px 22px 10px;
  margin-bottom: 10px;
  border: 1px solid rgba(255,255,255,0.06);
  box-shadow: var(--shadow-md);
}

.cf-bar-label {
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(255,255,255,0.7);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 14px;
}
.cf-bar-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(255,255,255,0.1);
}

/* Section dividers */
.cf-divider-sm { border: none !important; border-top: 1px solid var(--border-xs) !important; margin: 2px 0 !important; }
.cf-divider-lg { border: none !important; border-top: 2px solid var(--blue-400)  !important; margin: 2px 0 !important; }

/* Section header labels */
.cf-section-label {
  font-weight: 700;
  font-size: 14px;
  padding: 6px 10px;
  border-radius: var(--r-sm);
  display: block;
  line-height: 1.3;
}
.cf-ob  { background: #DBEAFE; color: #1E40AF; border-left: 3px solid #3B82F6; }
.cf-rec { background: #EDE9FE; color: #5B21B6; border-left: 3px solid #7C3AED; }
.cf-pay { background: #FCE7F3; color: #9D174D; border-left: 3px solid #EC4899; }
.cf-cb  { background: #DBEAFE; color: #1E40AF; border-left: 3px solid #3B82F6; }

/* Detail rows */
.cf-detail     { padding: 4px 8px 4px 28px; font-size: 13px; color: var(--tx-2); }
.cf-detail.unc { font-style: italic; color: var(--tx-3); }
.cf-dval       { text-align: right; font-size: 13px; color: var(--tx-2); padding: 4px 0; }
.cf-dval.unc   { color: var(--tx-3); }

/* NET CASH FLOW hero banner */
.cf-net {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 800;
  font-size: 16px;
  letter-spacing: 0.01em;
  padding: 13px 16px;
  margin-top: 10px;
  border-radius: var(--r-md);
  border-top: 3px solid;
  border-bottom: 3px solid;
  box-shadow: var(--shadow-xs);
}
.cf-net.pos { border-color: var(--green-500); color: var(--green-700); background: var(--green-50); }
.cf-net.neg { border-color: var(--red-500);   color: var(--red-700);   background: var(--red-50); }
.cf-net span:last-child { font-size: 18px; letter-spacing: -0.5px; }

/* Tally check pill */
.cf-tally {
  border-radius: var(--r-md);
  padding: 7px 14px;
  font-size: 11.5px;
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  line-height: 1.5;
  flex-wrap: wrap;
}
.cf-tally.ok  { background: var(--green-50); color: var(--green-700); border: 1px solid var(--green-border); }
.cf-tally.err { background: var(--red-50);   color: var(--red-700);   border: 1px solid var(--red-border); }

/* ── Statement context band ─────────────────────────────────────────────────── */
.cf-stmt-band {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-raised);
  border: 1px solid var(--border-sm);
  border-radius: var(--r-md);
  padding: 8px 14px;
  margin-bottom: 10px;
  font-size: 11px;
  color: var(--tx-3);
  gap: 16px;
}
.cf-stmt-band-kpi {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.cf-stmt-band-label { font-size: 9px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--tx-4); }
.cf-stmt-band-val   { font-size: 13px; font-weight: 700; color: var(--tx-1); letter-spacing: -0.3px; }
.cf-stmt-band-val.pos { color: var(--green-700); }
.cf-stmt-band-val.neg { color: var(--red-700); }

/* ── Section total value cells ─────────────────────────────────────────────── */
.cf-section-total {
  font-weight: 700;
  text-align: right;
  padding: 6px 0;
  font-size: 15px;
  letter-spacing: -0.4px;
  color: var(--tx-1);
  line-height: 1.2;
}
.cf-section-total.pos { color: var(--green-700); }
.cf-section-total.neg { color: var(--red-700); }
.cf-section-total.sky { color: var(--navy-700); }

/* ── GROUP level rows (L2) ──────────────────────────────────────────────────── */
.cf-grp-row {
  font-weight: 600;
  font-size: 12.5px;
  padding: 5px 10px 5px 10px;
  border-radius: 5px;
  margin: 1px 0;
  letter-spacing: 0.005em;
  display: block;
}
.cf-grp-row.rec { background: #EEF2FF; color: #1E40AF; }
.cf-grp-row.pay { background: #FFF1F2; color: #9D174D; }

/* GROUP total value cells */
.cf-grp-val {
  font-weight: 600;
  font-size: 12.5px;
  text-align: right;
  padding: 5px 2px;
}
.cf-grp-val.rec { color: #1E40AF; }
.cf-grp-val.pay { color: #9D174D; }

/* ── FINAL GROUP sub-row label (L3) ─────────────────────────────────────────── */
.cf-sub-row {
  font-size: 12px;
  color: var(--tx-2);
  padding: 3px 8px 3px 32px;
  border-radius: 3px;
  display: block;
}
.cf-sub-row.unc { font-style: italic; color: var(--tx-3); }

/* FINAL GROUP sub-row value */
.cf-sub-val {
  font-size: 12px;
  color: var(--tx-2);
  text-align: right;
  padding: 3px 2px;
}
.cf-sub-val.unc { color: var(--tx-3); }

/* ── Weekly GROUP label cells ─────────────────────────────────────────────── */
.cf-wk-grp-lbl {
  font-weight: 600;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  display: block;
}
.cf-wk-grp-lbl.rec { background: #EEF2FF; color: #1E40AF; }
.cf-wk-grp-lbl.pay { background: #FFF1F2; color: #9D174D; }

/* Weekly GROUP value cells */
.cf-wk-grp-val {
  text-align: right;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 3px;
}
.cf-wk-grp-val.rec       { color: #1E40AF; }
.cf-wk-grp-val.rec.total { background: #EFF6FF; color: #1E40AF; }
.cf-wk-grp-val.pay       { color: #9D174D; }
.cf-wk-grp-val.pay.total { background: #FFF1F2; color: #9D174D; }

/* ── Weekly sub-row cells ─────────────────────────────────────────────────── */
.cf-wk-sub-lbl {
  font-size: 12px;
  color: var(--tx-2);
  padding: 3px 8px 3px 24px;
  display: block;
}
.cf-wk-sub-lbl.unc { font-style: italic; color: var(--tx-3); }

.cf-wk-sub-val {
  text-align: right;
  font-size: 12px;
  color: var(--tx-2);
  padding: 3px 3px;
}
.cf-wk-sub-val.unc   { color: var(--tx-3); }
.cf-wk-sub-val.total { font-weight: 600; color: #1E40AF; background: #EFF6FF; }
.cf-wk-sub-val.ptotal { font-weight: 600; color: #9D174D; background: #FFF1F2; }

/* Weekly column header cells */
.cf-wk-hdr {
  font-size: 13px;
  font-weight: 700;
  text-align: right;
  padding: 6px 4px;
  border-radius: var(--r-sm);
  letter-spacing: 0.02em;
}
.cf-wk-hdr.alt { background: #DBEAFE; color: var(--blue-600); }  /* kept for possible future use */
.cf-wk-hdr.std { background: var(--bg-raised); color: var(--tx-2); }
.cf-wk-hdr.ttl { background: var(--blue-50); color: var(--navy-700); }

/* Weekly cell values */
.cf-wk-val {
  text-align: right;
  font-size: 13px;
  font-weight: 500;
  color: var(--tx-1);
  padding: 4px 4px;
}
.cf-wk-val.bold   { font-weight: 700; }
.cf-wk-val.red    { color: var(--red-700, #B91C1C); }
.cf-wk-val.total  { background: var(--blue-50); font-weight: 600; }
.cf-wk-val.dim    { color: var(--tx-3); }  /* for — dashes */

/* Weekly NET label cell */
.cf-wk-net-label {
  font-weight: 800;
  font-size: 13.5px;
  padding: 7px 10px;
  border-radius: var(--r-sm);
  background: var(--green-50);
  border-left: 3px solid var(--green-500);
  color: var(--green-700);
  display: block;
}

/* Weekly tally label */
.cf-wk-tally-label {
  color: var(--tx-3);
  font-size: 12px;
  padding: 4px 8px;
}

/* ═══════════════════════════════════════════════════════════
   TRANSACTIONS TAB
═══════════════════════════════════════════════════════════ */

/* Filter bar — same dark-navy pattern as CF control bar */
.txn-filter-bar {
  background: linear-gradient(135deg, var(--navy-900) 0%, var(--navy-700) 60%, var(--navy-600) 100%);
  border-radius: var(--r-lg);
  padding: 14px 20px 10px;
  margin-bottom: 12px;
  border: 1px solid rgba(255,255,255,0.06);
  box-shadow: var(--shadow-md);
}
.txn-filter-title {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.45);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.txn-filter-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(255,255,255,0.08);
}

/* Transaction count badge */
.txn-count-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: var(--navy-700);
  color: #FFFFFF;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 14px;
  border-radius: 20px;
  margin: 6px 0 10px;
  letter-spacing: 0.02em;
}
.txn-count-badge .txn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4ADE80;
  flex-shrink: 0;
}

/* Transaction intelligence strip */
.txn-intel-strip {
  display: flex;
  background: var(--bg-surface);
  border: 1px solid var(--border-sm);
  border-radius: var(--r-md);
  overflow: hidden;
  margin-bottom: 14px;
  box-shadow: var(--shadow-xs);
}
.txn-intel-item {
  flex: 1;
  padding: 10px 14px;
  border-right: 1px solid var(--border-xs);
}
.txn-intel-item:last-child { border-right: none; }
.txn-intel-label {
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--tx-4);
  margin-bottom: 3px;
}
.txn-intel-val {
  font-size: 15px;
  font-weight: 700;
  color: var(--tx-1);
  letter-spacing: -0.4px;
  line-height: 1.1;
}
.txn-intel-val.pos   { color: var(--green-700); }
.txn-intel-val.neg   { color: var(--red-700); }
.txn-intel-val.amber { color: var(--amber-700); }
.txn-intel-sub {
  font-size: 10px;
  color: var(--tx-4);
  margin-top: 2px;
  line-height: 1.3;
}

/* Bulk categorization panel */
.txn-cat-panel {
  background: var(--bg-raised);
  border: 1px solid var(--border-sm);
  border-radius: var(--r-md);
  padding: 12px 16px 8px;
  margin: 4px 0 10px;
}
.txn-cat-title {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--tx-4);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.txn-cat-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-xs);
}

/* Opening Balance row banner — enhanced */
.ob-banner {
  background: var(--blue-50);
  border: 1px solid #BFDBFE;
  border-radius: var(--r-md);
  padding: 8px 16px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ═══════════════════════════════════════════════════════════
   POLISH COMPONENTS  (Phase 5)
═══════════════════════════════════════════════════════════ */

/* Streamlit h3 / h4 override — keep consistent with design */
.main h1, .main h2, .main h3, .main h4, .main h5 {
  font-family: 'Inter', sans-serif !important;
  font-weight: 700 !important;
  letter-spacing: -0.2px !important;
}
.main h3 { font-size: 15px !important; color: var(--tx-1) !important; margin: 18px 0 10px !important; }
.main h4 {
  font-size: 11px !important;
  color: var(--tx-3) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.11em !important;
  margin: 16px 0 8px !important;
  padding-bottom: 7px !important;
  border-bottom: 1px solid var(--border-xs) !important;
}

/* Opening Balance row banner (Transactions tab) */
.ob-banner {
  background: var(--blue-50);
  border-radius: var(--r-md);
  padding: 8px 14px;
  border-left: 4px solid var(--blue-400);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ob-banner-label {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--blue-500);
}

/* Legend badges */
.legend-strip {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 8px 0;
}
.legend-badge {
  padding: 4px 11px;
  border-radius: var(--r-sm);
  border: 1px solid;
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.legend-badge.green { background: var(--green-50);  border-color: var(--green-border);  color: var(--green-700); }
.legend-badge.amber { background: var(--amber-50);  border-color: var(--amber-border);  color: var(--amber-700); }

/* Reconciliation strip */
.recon-strip {
  background: var(--bg-raised);
  border-radius: var(--r-md);
  padding: 11px 18px;
  border: 1px solid var(--border-sm);
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 18px;
  align-items: center;
}
.recon-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--tx-4);
  width: 100%;
  margin-bottom: 3px;
}
.recon-item       { font-size: 13px; color: var(--tx-2); }
.recon-item b     { font-weight: 700; color: var(--tx-1); }
.recon-item b.pos { color: var(--green-700); }
.recon-item b.neg { color: var(--red-700); }
.recon-sep        { color: var(--border-md); font-size: 14px; }

/* ═══════════════════════════════════════════════════════════
   STREAMLIT CHROME CLEANUP  (Phase 5 refined)
═══════════════════════════════════════════════════════════ */
/* Tighten main area top padding */
.main .block-container { padding-top: 3.5rem !important; }

/* Remove extra whitespace above first element */
.main > div:first-child { padding-top: 0 !important; margin-top: 0 !important; }

/* Tighten column gaps */
[data-testid="stHorizontalBlock"] { gap: 12px !important; }

/* Caption below inputs */
.stCaption { margin-top: 2px !important; }

/* Streamlit info / success / warning / error boxes */
[data-testid="stInfoBox"], [data-testid="stSuccessBox"],
[data-testid="stWarningBox"], [data-testid="stErrorBox"] {
  border-radius: var(--r-md) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
}

/* File uploader */
[data-testid="stFileUploader"] {
  border-radius: var(--r-lg) !important;
  border: 1.5px dashed var(--border-md) !important;
  background: var(--bg-raised) !important;
  padding: 6px !important;
  transition: var(--t-fast) !important;
}
[data-testid="stFileUploader"]:hover {
  border-color: var(--blue-400) !important;
  background: var(--blue-50) !important;
}

/* Radio buttons */
[data-testid="stRadio"] label {
  font-size: 13px !important;
  font-weight: 500 !important;
}

/* Date inputs */
[data-testid="stDateInput"] input {
  font-size: 13px !important;
}

/* Checkbox */
[data-testid="stCheckbox"] label {
  font-size: 13px !important;
}

/* Tooltip / popover */
[data-testid="stTooltipIcon"] { color: var(--tx-4) !important; }

/* ═══════════════════════════════════════════════════════════
   RESPONSIVE  (Phase 5)
═══════════════════════════════════════════════════════════ */
@media (max-width: 1200px) {
  .header-band { padding: 14px 20px 14px; }
  .kpi-strip-item { padding-right: 22px; }
  .kpi-strip-value { font-size: 18px; }
  .header-pills .pill-period { display: none; }
}

@media (max-width: 960px) {
  .kpi-strip { flex-wrap: wrap; row-gap: 14px; }
  .kpi-strip-item {
    padding-right: 16px;
    border-right: none !important;
    min-width: calc(50% - 16px);
  }
  .kpi-strip-value { font-size: 17px; }
  .header-pills { display: none; }
  .header-subtitle { font-size: 10px; }
}

@media (max-width: 700px) {
  .header-top { flex-direction: column; gap: 10px; }
  .kpi-strip-item { min-width: 100%; padding-right: 0; }
  .kpi-strip-value { font-size: 19px; }
  .header-logo-box { width: 32px; height: 32px; font-size: 11px; }
  .header-title { font-size: 13px; }
  .recon-strip { flex-direction: column; gap: 6px; }
  .legend-strip { flex-direction: column; }
  .sb-stats-grid { flex-direction: row; flex-wrap: wrap; }
  .sb-stat-card { min-width: calc(50% - 4px); }
}

/* ═══════════════════════════════════════════════════════════
   SIDEBAR LOGO GAP REDUCTION
═══════════════════════════════════════════════════════════ */
section[data-testid="stSidebar"] > div {
  padding-top: 0.25rem !important;
}
section[data-testid="stSidebar"] [data-testid="stImage"] {
  margin-top: 0 !important;
  margin-bottom: 0 !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  line-height: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stImage"] img {
  display: block !important;
  margin: 0 auto !important;
}
</style>
""", unsafe_allow_html=True)

init_db()

# ── Navigation session state ──────────────────────────────────────────────────
_NAV_TABS = ["Summary", "Cash Flow", "Investments", "Transactions", "Uncategorised", "Exception Report", "Upload"]

_today          = datetime.date.today()
_first_of_month = _today.replace(day=1)

# ─── Sidebar ───────────────────────────────────────────────────────────────────
import os as _os
LOGO_PATH = _os.path.join(_os.path.dirname(__file__), "logo.png")
if not _os.path.exists(LOGO_PATH):
    for _fb_name in ("citykart_logo.png", "citykart_logo.PNG"):
        _fallback = _os.path.join(_os.path.dirname(__file__), _fb_name)
        if _os.path.exists(_fallback):
            LOGO_PATH = _fallback
            break

if _os.path.exists(LOGO_PATH):
    st.sidebar.image(LOGO_PATH, use_container_width=True)
else:
    st.sidebar.markdown("""<div style="width:100%; height:64px;
        background:#F0F4FF; border:2px dashed #CBD5E0; border-radius:8px;
        display:flex; align-items:center; justify-content:center;
        color:#8892A4; font-size:12px;">LOGO PLACEHOLDER</div>""",
        unsafe_allow_html=True)

# ── Derive default FY from latest transaction date in DB ──────────────────────
@st.cache_data(ttl=300)
def _get_latest_date():
    """Return the most recent transaction date (YYYY-MM-DD) in the DB, or None."""
    from database import get_connection
    conn = get_connection()
    row  = conn.execute("""
        SELECT MAX(date) as latest
        FROM transactions
        WHERE final_group != 'OPENING BALANCE'
    """).fetchone()
    conn.close()
    return row["latest"] if row and row["latest"] else None

_latest_date = _get_latest_date()
if _latest_date:
    _ld = datetime.date.fromisoformat(_latest_date)
    if _ld >= datetime.date(2026, 4, 1):
        _default_fy = "FY2627"
    elif _ld >= datetime.date(2025, 4, 1):
        _default_fy = "FY2526"
    else:
        _default_fy = "FY2425"
else:
    _default_fy = "FY2627"
_default_fy_idx = FY_OPTIONS.index(_default_fy)

st.sidebar.markdown('<div class="sidebar-section">Filters</div>', unsafe_allow_html=True)

sel_fy       = st.sidebar.selectbox(
    "Financial Year", FY_OPTIONS,
    index=_default_fy_idx,
    format_func=lambda x: FY_LABELS[x],
)
sel_fy_label = FY_LABELS[sel_fy]

# Reset Cash Flow date inputs whenever the FY selector changes
_fy_s, _fy_e = FY_BOUNDS[sel_fy]
if st.session_state.get("_prev_fy") != sel_fy:
    st.session_state["_prev_fy"] = sel_fy
    st.cache_data.clear()

    # Default CF window to the latest month that has data for this FY
    from database import get_connection as _gc
    _conn = _gc()
    _row  = _conn.execute("""
        SELECT MAX(date) as latest, MIN(date) as earliest
        FROM transactions
        WHERE financial_year = ?
          AND final_group != 'OPENING BALANCE'
    """, [sel_fy]).fetchone()
    _conn.close()

    if _row and _row["latest"]:
        _cf_latest   = datetime.date.fromisoformat(_row["latest"])
        _cf_from_def = _cf_latest.replace(day=1)   # first of that month
        _cf_to_def   = _cf_latest                  # last available date
    else:
        _cf_from_def = _fy_s
        _cf_to_def   = min(_fy_e, _today)

    st.session_state["cf_from"] = _cf_from_def
    st.session_state["cf_to"]   = _cf_to_def

all_entities = ["All"] + list(ENTITIES.keys())
sel_entity   = st.sidebar.selectbox("Entity", all_entities)

all_banks = ["All"]
if sel_entity != "All":
    all_banks += ENTITIES.get(sel_entity, [])
else:
    for _bs in ENTITIES.values():
        all_banks += _bs
sel_bank = st.sidebar.selectbox("Bank Account", all_banks)

_avail_months = _cached_months(sel_fy)
month_options = ["All"] + _avail_months
sel_month     = st.sidebar.selectbox("Month", month_options)

st.sidebar.markdown("**Date Range** *(overrides Month when both set)*")
d_col1, d_col2 = st.sidebar.columns(2)
with d_col1:
    sel_date_from = st.date_input("From", value=None,
                                  format="DD/MM/YYYY", key="date_from")
with d_col2:
    sel_date_to = st.date_input("To", value=None,
                                format="DD/MM/YYYY", key="date_to")

use_date_range = sel_date_from is not None and sel_date_to is not None
date_from  = str(sel_date_from) if use_date_range else None
date_to    = str(sel_date_to)   if use_date_range else None
eff_month  = None if use_date_range else (sel_month if sel_month != "All" else None)
eff_entity = sel_entity if sel_entity != "All" else None
eff_bank   = sel_bank   if sel_bank   != "All" else None

st.sidebar.markdown("---")
st.sidebar.caption("Large debit threshold: ₹10,00,000")

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# ── Sidebar quick stats ───────────────────────────────────────────────────────

# ─── Fetch shared data — FY filter intentionally NOT applied here ──────────────
# FY filter applies only to the Transactions tab (and the Month dropdown).
# Header KPIs, Summary, Cash Flow, Investments always show the full picture.
summary = _cached_summary(sel_entity, sel_month, None)

# B3 — bank-aware + date-range-aware totals for header KPIs
_sum_full = _cached_summary_full(
    sel_entity, sel_bank,
    sel_month if not use_date_range else None,
    str(sel_date_from) if use_date_range else None,
    str(sel_date_to)   if use_date_range else None,
)
inflow  = _sum_full["total_receipts"]
outflow = _sum_full["total_payouts"]
net     = inflow - outflow

# B4 — uncats respects all sidebar filters
uncats  = _cached_uncategorized(sel_entity, sel_bank, sel_month, sel_fy)

# ─── Closing balance for KPI card (single SQL query, no full row load) ─────────
if use_date_range:
    _cb_data = get_closing_balance(
        entity=eff_entity, bank=eff_bank,
        date_from=date_from, date_to=date_to,
    )
else:
    _cb_data = _cached_closing(sel_entity, sel_bank, sel_month, None)

by_bank_bal     = _cb_data["by_bank"]
by_bank_dt      = _cb_data["dates"]
closing_balance = _cb_data["total"]

if by_bank_bal:
    if sel_bank != "All":
        closing_date = by_bank_dt.get(sel_bank, "")
        _cb_sub      = f"As of {closing_date}" if closing_date else "No transactions"
    else:
        _dt_vals     = [v for v in by_bank_dt.values() if v]
        closing_date = max(_dt_vals) if _dt_vals else ""
        _cb_sub      = " | ".join(
            f"{bk}: {fmt_inr(v)}" for bk, v in sorted(by_bank_bal.items())
        )
else:
    closing_balance = 0.0
    closing_date    = ""
    _cb_sub         = "No transactions"

# ── Date-aware header band computation ────────────────────────────────────────
_latest_data_date = get_latest_data_date() or str(datetime.date.today())
if use_date_range and sel_date_to:
    as_of_date = str(sel_date_to)
else:
    as_of_date = _latest_data_date

@st.cache_data(ttl=60)
def _cached_bank_asof(entity, as_of):
    return get_entity_bank_balance_asof(entity, as_of)

@st.cache_data(ttl=60)
def _cached_inv_asof(entity, as_of):
    return get_entity_investment_asof(entity, as_of)

stores_bank_asof   = _cached_bank_asof("Stores",   as_of_date)
ventures_bank_asof = _cached_bank_asof("Ventures", as_of_date)
stores_inv_asof    = _cached_inv_asof("Stores",    as_of_date)
ventures_inv_asof  = _cached_inv_asof("Ventures",  as_of_date)

stores_cash_asof   = get_cash_asof("Stores",   as_of_date)
ventures_cash_asof = get_cash_asof("Ventures", as_of_date)

# Investments displayed in banner now includes cash
stores_investments_display   = stores_inv_asof
ventures_investments_display = ventures_inv_asof

total_cash_position = (stores_bank_asof + ventures_bank_asof +
                       stores_investments_display + ventures_investments_display +
                       stores_cash_asof + ventures_cash_asof)

as_of_display = datetime.date.fromisoformat(as_of_date).strftime("%d %b %Y")

# ─── Transaction count (lightweight SQL COUNT — no row loading) ───────────────
txn_count = _cached_count(sel_entity, sel_bank, sel_month, None, date_from, date_to)

# Period label pill
if use_date_range:
    period_label = f"{sel_date_from} → {sel_date_to}"
elif sel_month != "All":
    period_label = sel_month
else:
    period_label = "All periods"

# Entity label pill
entity_label = sel_entity if sel_entity != "All" else "All entities"

# ── Sidebar quick stats ────────────────────────────────────────────────────────
_s_receipts = inflow
_s_payments = outflow
_s_uncat    = sum(u.get("count", 0) for u in uncats)
st.sidebar.markdown('<div class="sidebar-section">Quick Stats</div>', unsafe_allow_html=True)
st.sidebar.markdown(f"""
<div class="sb-stats-grid">
  <div class="sb-stat-card">
    <div class="sb-stat-left">
      <span class="sb-stat-label">Transactions</span>
      <span class="sb-stat-value">{txn_count:,}</span>
    </div>
    <span class="sb-stat-icon">🔢</span>
  </div>
  <div class="sb-stat-card green">
    <div class="sb-stat-left">
      <span class="sb-stat-label green">Receipts</span>
      <span class="sb-stat-value green">{fmt_cr(_s_receipts)}</span>
    </div>
    <span class="sb-stat-icon">↑</span>
  </div>
  <div class="sb-stat-card red">
    <div class="sb-stat-left">
      <span class="sb-stat-label red">Payments</span>
      <span class="sb-stat-value red">{fmt_cr(_s_payments)}</span>
    </div>
    <span class="sb-stat-icon">↓</span>
  </div>
  <div class="sb-stat-card amber">
    <div class="sb-stat-left">
      <span class="sb-stat-label amber">Uncategorized</span>
      <span class="sb-stat-value amber">{_s_uncat:,}</span>
    </div>
    <span class="sb-stat-icon">⚠</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ─── Month-over-month comparison for KPI strip (from cached summary) ──────────
_this_wk_in = _this_wk_out = _wow_in = _wow_out = 0.0
_by_month = summary.get("by_month", [])
if len(_by_month) >= 2:
    _last_m      = _by_month[-1]
    _prev_m      = _by_month[-2]
    _this_wk_in  = float(_last_m.get("inflow",  0) or 0)
    _this_wk_out = float(_last_m.get("outflow", 0) or 0)
    _prev_in     = float(_prev_m.get("inflow",  0) or 0)
    _prev_out    = float(_prev_m.get("outflow", 0) or 0)
    _wow_in  = ((_this_wk_in  - _prev_in)  / _prev_in  * 100) if _prev_in  else 0.0
    _wow_out = ((_this_wk_out - _prev_out) / _prev_out * 100) if _prev_out else 0.0
elif len(_by_month) == 1:
    _this_wk_in  = float(_by_month[0].get("inflow",  0) or 0)
    _this_wk_out = float(_by_month[0].get("outflow", 0) or 0)

# ─── Header band — dark navy KPI strip ────────────────────────────────────────
net_class    = "pos" if net >= 0 else "neg"
_bank_label  = sel_bank if sel_bank != "All" else "AXIS & HDFC"
_net_arrow   = "▲" if net >= 0 else "▼"
_net_sub_cls = "kpi-positive" if net >= 0 else "kpi-negative"

# WoW badge classes and labels (pre-computed to avoid nested f-string issues)
_wow_in_cls  = "up"   if _wow_in  > 0 else ("down" if _wow_in  < 0 else "flat")
_wow_in_txt  = (f"▲ {abs(_wow_in):.1f}% WoW"  if _wow_in  > 0
               else f"▼ {abs(_wow_in):.1f}% WoW"  if _wow_in  < 0 else "— flat WoW")
_wow_out_txt = (f"▲ {abs(_wow_out):.1f}% WoW" if _wow_out > 0
               else f"▼ {abs(_wow_out):.1f}% WoW" if _wow_out < 0 else "— flat WoW")
_exc_cls     = "warn" if _s_uncat > 0 else "flat"
_exc_txt     = f"⚠ {_s_uncat:,} uncat" if _s_uncat > 0 else "✓ all categorized"
st.markdown(f"""
<div class="header-band">
    <div class="header-top">
        <div class="header-logo-area">
            <div class="header-logo-box">CK</div>
            <div>
                <div class="header-title">BankFlow Dashboard</div>
                <div class="header-subtitle">
                    {sel_entity} &nbsp;·&nbsp; {_bank_label} &nbsp;·&nbsp; {sel_fy_label} &nbsp;·&nbsp; {period_label}
                </div>
            </div>
        </div>
        <div class="header-pills">
            <span class="pill pill-live">● Live</span>
            <span class="pill pill-txn">⊞ {txn_count:,} Txns</span>
            <span class="pill pill-period">📅 {period_label}</span>
        </div>
    </div>
    <div style="background:#1B2B4B; border-radius:12px;
         padding:18px 28px; margin-top:16px;
         display:flex; align-items:center; justify-content:space-between;
         gap:32px;">
        <div style="flex-shrink:0;">
            <div style="font-size:10px; font-weight:700; color:#8896A5;
                 letter-spacing:0.1em; text-transform:uppercase;
                 margin-bottom:4px;">TOTAL CASH POSITION</div>
            <div style="font-size:32px; font-weight:800; color:#FFFFFF;
                 letter-spacing:-1px; line-height:1;">
                {fmt_cr(total_cash_position)}
            </div>
            <div style="font-size:11px; color:#8896A5; margin-top:4px;">
                As on {as_of_display}
            </div>
        </div>
        <div style="flex-grow:1; max-width:560px;">
            <table style="width:100%; border-collapse:collapse;">
                <tr style="border-bottom:1px solid rgba(255,255,255,0.15);">
                    <td style="padding:4px 12px 6px 0; color:#8896A5;
                        font-size:11px; font-weight:700;
                        text-transform:uppercase;">Entity</td>
                    <td style="padding:4px 12px 6px 0; color:#8896A5;
                        font-size:11px; font-weight:700;
                        text-transform:uppercase; text-align:right;">
                        Bank Balance</td>
                    <td style="padding:4px 12px 6px 0; color:#8896A5;
                        font-size:11px; font-weight:700;
                        text-transform:uppercase; text-align:right;">
                        Investments</td>
                    <td style="padding:4px 0 6px 0; color:#8896A5;
                        font-size:11px; font-weight:700;
                        text-transform:uppercase; text-align:right;">
                        Cash at Stores</td>
                </tr>
                <tr>
                    <td style="padding:6px 12px 6px 0; color:#FFFFFF;
                        font-size:14px; font-weight:600;">Stores</td>
                    <td style="padding:6px 12px 6px 0; color:#FFFFFF;
                        font-size:14px; font-weight:700; text-align:right;">
                        {fmt_cr(stores_bank_asof)}</td>
                    <td style="padding:6px 12px 6px 0; color:#93C5FD;
                        font-size:14px; font-weight:700; text-align:right;">
                        {fmt_cr(stores_investments_display)}</td>
                    <td style="padding:6px 0; color:#67E8F9;
                        font-size:14px; font-weight:700; text-align:right;">
                        {fmt_cr(stores_cash_asof)}</td>
                </tr>
                <tr>
                    <td style="padding:6px 12px 0 0; color:#FFFFFF;
                        font-size:14px; font-weight:600;">Ventures</td>
                    <td style="padding:6px 12px 0 0; color:#FFFFFF;
                        font-size:14px; font-weight:700; text-align:right;">
                        {fmt_cr(ventures_bank_asof)}</td>
                    <td style="padding:6px 12px 0 0; color:#93C5FD;
                        font-size:14px; font-weight:700; text-align:right;">
                        {fmt_cr(ventures_investments_display)}</td>
                    <td style="padding:6px 0 0 0; color:#67E8F9;
                        font-size:14px; font-weight:700; text-align:right;">
                        {fmt_cr(ventures_cash_asof)}</td>
                </tr>
            </table>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Navigation ──────────────────────────────────────────────────────────────
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "Summary"
if st.session_state.get("switch_tab"):
    st.session_state["active_tab"] = st.session_state.pop("switch_tab")

# Inject CSS to style nav buttons as tabs.
# Relies on .nav-active-indicator injected below the active button —
# that class is the reliable hook; no `key` attribute needed.
st.markdown("""
<style>
/* ── Nav bar wrapper — detected by active indicator presence ── */
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) {
    background: #FFFFFF;
    border-bottom: 1px solid #EDF0F5;
    box-shadow: 0 1px 4px rgba(10,22,40,0.04);
    padding: 0;
    gap: 0 !important;
    margin-bottom: 16px !important;
    position: sticky;
    top: 0;
    z-index: 100;
    align-items: stretch !important;
}

/* ── All nav buttons — uniform base style ── */
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #6B7A90 !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    padding: 14px 8px 12px !important;
    width: 100% !important;
    box-shadow: none !important;
    letter-spacing: 0.01em !important;
    transition: color 0.15s ease, background 0.15s ease !important;
}
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button:hover {
    background: #F4F6FA !important;
    color: #1B2B4B !important;
}

/* ── Active indicator line ── */
.nav-active-indicator {
    height: 4px;
    background: #1B2B4B;
    border-radius: 2px 2px 0 0;
    margin: -4px 8px 0;
}

/* ── Nav label size + bold active label ── */
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button p {
    font-size: 15px !important;
}
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button[kind="primary"],
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button[data-testid="stBaseButton-primary"] {
    background: transparent !important;
    border: none !important;
    color: #1B2B4B !important;
}
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button[kind="primary"] p,
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stButton > button[data-testid="stBaseButton-primary"] p {
    font-weight: 800 !important;
    color: #1B2B4B !important;
}

/* ── Active button label ── */
div[data-testid="stHorizontalBlock"]:has(.nav-active-indicator) .stVerticalBlock:has(.nav-active-indicator) .stButton > button {
    color: #1B2B4B !important;
    font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)

nav_options = ["Summary", "Cash Flow", "Investments", "Transactions", "Uncategorised", "Exception Report", "Upload"]
nav_keys    = ["Summary", "Cash Flow", "Investments", "Transactions", "Uncategorised", "Exception Report", "Upload"]
nav_cols = st.columns(len(nav_options))
for i, (label, key) in enumerate(zip(nav_options, nav_keys)):
    with nav_cols[i]:
        is_active = st.session_state["active_tab"] == key
        if st.button(label, key=f"nav_{key}", use_container_width=True,
                     type="primary" if is_active else "secondary"):
            st.session_state["switch_tab"] = key
            st.rerun()
        if is_active:
            st.markdown('<div class="nav-active-indicator"></div>', unsafe_allow_html=True)

selected_tab = st.session_state["active_tab"]

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
if selected_tab == "Summary":
    st.markdown(LIVE_BANNER, unsafe_allow_html=True)
    # ── Account Balance Summary — respects Entity / Bank / Date Range filters ──
    abs_entity_filter = sel_entity if sel_entity != "All" else None
    abs_bank_filter   = sel_bank   if sel_bank   != "All" else None

    _acct_balances = get_account_balances_asof(
        as_of_date, abs_entity_filter, abs_bank_filter)

    _ABS_COLS = [2, 1.5, 2.6, 1.1, 2]
    _fmt_d = lambda x: datetime.date.fromisoformat(str(x)[:10]).strftime("%d %b %Y")

    def _abs_inv_rows(entity_name, as_of):
        """Per-scheme FD / MF balances (at cost) as on `as_of`, with the date(s) money went in."""
        ev = pd.DataFrame(get_investment_events(entity_name))
        out = {"FD": [], "MF": []}
        if ev.empty:
            return out
        ev = ev[ev["date"].isna() | (ev["date"] <= as_of)]
        if "opening_date" not in ev.columns:
            ev["opening_date"] = None
        for (stype, name), g in ev.groupby(["scheme_type", "scheme_name"]):
            if stype not in out:
                continue
            bal = g["delta"].sum()
            op = g[g["source"] == "Opening"]
            dates = []
            if not op.empty and op["delta"].sum() > 0:
                od = op["opening_date"].dropna()
                dates.append((od.iloc[0] if len(od) else None, "opening"))
            for _, r in g[(g["source"] != "Opening") & (g["delta"] > 0)].iterrows():
                dates.append((r["date"], "invested"))
            dts = sorted({d for d, _ in dates if d})
            if not dts:
                label = "—"
            else:
                label = _fmt_d(dts[0]) + (f" +{len(dts) - 1} more" if len(dts) > 1 else "")
                if len(dts) == 1 and dates and dates[0][1] == "opening":
                    label += " (opening)"
            if abs(bal) >= 1:
                out[stype].append({"name": name, "balance": bal, "date": label})
        for k in out:
            out[k].sort(key=lambda r: -r["balance"])
        return out

    def _render_entity_subtotal(entity_name, entity_bank_total, rows,
                                 show_investments, as_of_date):
        _pill_cls = "abs-stores" if entity_name == "Stores" else "abs-ventures"
        for acc in rows:
            rcols = st.columns(_ABS_COLS)
            _vals = [
                f'<span class="abs-pill {_pill_cls}">{entity_name}</span>',
                acc["bank"],
                acc["purpose"],
                acc["bank_id"],
                f'<div style="text-align:right;font-variant-numeric:tabular-nums;">{_inr(acc["balance"])}</div>',
            ]
            for _c, _v in zip(rcols, _vals):
                with _c:
                    st.markdown(_v, unsafe_allow_html=True)

        entity_total = entity_bank_total
        if show_investments:
            _inv_rows = _abs_inv_rows(entity_name, as_of_date)
            for _stype, _tlabel, _tcolor in (("FD", "Fixed Deposit", "#1E40AF"),
                                             ("MF", "Mutual Fund", "#5B21B6")):
                _rws = _inv_rows[_stype]
                if not _rws:
                    continue
                _sub = sum(r["balance"] for r in _rws)
                ircols = st.columns(_ABS_COLS)
                for _c, _v in zip(ircols, [
                    f'<span class="abs-pill" style="background:#EDE9FE;color:#5B21B6;">INV</span> {entity_name}',
                    _tlabel, f"{_tlabel}s", "—",
                    f'<div style="text-align:right;color:{_tcolor};font-weight:700;">{_inr(_sub)}</div>',
                ]):
                    with _c:
                        st.markdown(_v, unsafe_allow_html=True)
                entity_total += _sub

            # Cash Balance row — only when no specific bank account filter is active
            cash_bal = get_cash_asof(entity_name, as_of_date)
            if cash_bal:
                cash_cols_row = st.columns(_ABS_COLS)
                for _c, _v in zip(cash_cols_row, [
                    f'<span class="abs-pill" style="background:#CFFAFE;color:#0891B2;">CASH</span> {entity_name}',
                    "Cash", "Cash at Stores", "—",
                    f'<div style="text-align:right;color:#0891B2;font-weight:700;">{_inr(cash_bal)}</div>',
                ]):
                    with _c:
                        st.markdown(_v, unsafe_allow_html=True)
                entity_total += cash_bal

        st.markdown(
            f'<div style="background:#F0F4FF;padding:6px 12px;border-radius:6px;'
            f'font-weight:700;color:#1B2B4B;display:flex;justify-content:space-between;'
            f'margin-bottom:8px;">'
            f'<span>{entity_name} Subtotal{" (Bank + Investments)" if show_investments else " (Bank)"}</span>'
            f'<span>{_inr(entity_total)}</span></div>',
            unsafe_allow_html=True)
        return entity_total

    st.markdown(
        f'<div style="margin:6px 0 12px;">'
        f'<div style="font-size:18px;font-weight:800;color:#1B2B4B;letter-spacing:-0.2px;">Account Balance Summary</div>'
        f'<div style="font-size:11.5px;color:#6B7A90;margin-top:2px;">As on {_fmt_d(as_of_date)}</div>'
        f'</div>',
        unsafe_allow_html=True)

    _abs_css = """
<style>
.abs-pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.04em;}
.abs-stores{background:#DBEAFE;color:#1E40AF;}
.abs-ventures{background:#FCE7F3;color:#9D174D;}
</style>"""
    st.markdown(_abs_css, unsafe_allow_html=True)

    _hcols = st.columns(_ABS_COLS)
    for _c, _hdr in zip(_hcols, ["Entity", "Bank / Type", "Purpose", "Account", "Balance"]):
        with _c:
            st.markdown(
                f'<div style="font-size:11px;font-weight:700;color:#1B2B4B;'
                f'letter-spacing:.06em;text-transform:uppercase;padding:4px 0;'
                f'border-bottom:2px solid #1B2B4B;">{_hdr}</div>',
                unsafe_allow_html=True)

    # MF/FD rows aren't tied to a single bank account — only show them when
    # no specific Bank Account is selected.
    show_investments = not abs_bank_filter
    entities_to_show = [abs_entity_filter] if abs_entity_filter else ["Stores", "Ventures"]

    _entity_totals = {}
    for _entity_name in entities_to_show:
        _entity_rows = [r for r in _acct_balances if r["entity"] == _entity_name]
        if abs_bank_filter and not _entity_rows:
            continue  # this entity has no matching account when Bank filter applied
        _entity_bank_total = sum(r["balance"] for r in _entity_rows)
        _entity_totals[_entity_name] = _render_entity_subtotal(
            _entity_name, _entity_bank_total, _entity_rows,
            show_investments, as_of_date
        )

    _grand_total = sum(_entity_totals.values())

    st.markdown(
        f'<div style="background:#1B2B4B;color:#fff;padding:8px 12px;'
        f'border-radius:6px;font-weight:800;font-size:14px;'
        f'display:flex;justify-content:space-between;">'
        f'<span>TOTAL CASH POSITION</span>'
        f'<span>{fmt_inr(_grand_total)}</span></div>',
        unsafe_allow_html=True)
    # ── Investment ledger: what went where, and when ─────────────────────────
    if show_investments:
        with st.expander("📒 Investment ledger — amounts invested and redeemed, with dates"):
            _lev = pd.DataFrame(get_investment_events(abs_entity_filter))
            if _lev.empty:
                st.info("No investments recorded.")
            else:
                _lev = _lev[_lev["scheme_type"].isin(["FD", "MF"])]
                _lev = _lev[_lev["date"].isna() | (_lev["date"] <= as_of_date)].copy()
                if "opening_date" not in _lev.columns:
                    _lev["opening_date"] = None
                _lev["when"] = _lev["date"].fillna(_lev["opening_date"]).fillna("")
                _lev["Event"] = _lev.apply(
                    lambda r: "Opening balance" if r["source"] == "Opening"
                    else ("Invested" if r["delta"] > 0 else "Redeemed"), axis=1)
                _lev["_ord"] = _lev["source"].apply(lambda x: 0 if x == "Opening" else 1)
                _lev = _lev.sort_values(["entity", "scheme_type", "scheme_name", "_ord", "when"])
                _lev["Balance"] = _lev.groupby(["entity", "scheme_type", "scheme_name"])["delta"].cumsum()
                _ldf = pd.DataFrame({
                    "Entity": _lev["entity"],
                    "Type": _lev["scheme_type"].map({"FD": "Fixed Deposit", "MF": "Mutual Fund"}),
                    "Scheme": _lev["scheme_name"],
                    "Date": _lev["when"].apply(lambda x: _fmt_d(x) if x else "—"),
                    "Event": _lev["Event"],
                    "Amount": _lev["delta"].apply(fmt_inr),
                    "Balance after": _lev["Balance"].apply(fmt_inr),
                })
                _ldf = _ldf[_lev["delta"].abs().values >= 1]
                st.dataframe(_ldf, use_container_width=True, hide_index=True, height=360,
                             column_config=amount_config(["Amount", "Balance after"]))
                st.caption("Amounts are at cost. Opening balances carry the date the FD / fund was placed "
                           "(set it under Investments → Manage Schemes & Opening Values).")
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Day-wise total balance — ignores ALL sidebar filters (whole company) ──
    st.markdown('<div class="section-header" style="margin:10px 0 6px;">Day-wise Total Balance</div>',
                unsafe_allow_html=True)
    _dw = get_daywise_totals()
    if _dw:
        _dw_df = pd.DataFrame(_dw)
        _dw_show = pd.DataFrame({
            "Date":             pd.to_datetime(_dw_df["date"]).dt.strftime("%d %b %Y"),
            "Account balance":  _dw_df["bank"].apply(fmt_inr),
            "FD balance":       _dw_df["fd"].apply(fmt_inr),
            "Investment (MF)":  _dw_df["mf"].apply(fmt_inr),
            "Cash at Stores":   _dw_df["cash"].apply(fmt_inr),
            "Total balance":    _dw_df["total"].apply(fmt_inr),
        })
        st.dataframe(
            _dw_show, use_container_width=True, hide_index=True, height=420,
            column_config=amount_config(["Account balance", "FD balance", "Investment (MF)",
                                         "Cash at Stores", "Total balance"]))

        def _build_daywise_excel():
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
            wb = Workbook()
            ws = wb.active
            ws.title = "Day-wise Balance"
            ws.append(["Date", "Account balance", "FD balance", "Investment (MF)",
                       "Cash at Stores", "Total balance"])
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="1B2B4B")
                c.alignment = Alignment(horizontal="center")
            for r in _dw:
                ws.append([datetime.date.fromisoformat(r["date"]),
                           round(r["bank"], 2), round(r["fd"], 2), round(r["mf"], 2),
                           round(r["cash"], 2), round(r["total"], 2)])
            for row in ws.iter_rows(min_row=2):
                row[0].number_format = "dd-mmm-yyyy"
                for c in row[1:]:
                    c.number_format = "#,##0;[Red]-#,##0"
                row[5].font = Font(bold=True)
            ws.column_dimensions["A"].width = 14
            for col in "BCDEF":
                ws.column_dimensions[col].width = 20
            ws.freeze_panes = "A2"
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        _, _dw_dl = st.columns([8.5, 1.5])
        with _dw_dl:
            st.download_button(
                "⬇️ Export Excel", _build_daywise_excel(),
                file_name=f"daywise_total_balance_{_dw[0]['date']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_daywise_balance", use_container_width=True)
    else:
        st.info("No data yet.")

# ══════════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════════
elif selected_tab == "Transactions":
    # ── Category/Group options from DB — never loads all rows ─────────────────
    all_cats_for_txn = get_all_categories()
    fg_options = (
        ["All", "🔒 Manually Categorized", "Uncategorized"]
        + sorted([r["final_group"] for r in all_cats_for_txn])
    )
    mg_options = ["All"] + sorted({
        r["main_group"] for r in all_cats_for_txn if r.get("main_group")
    })

    # ── Clear filter flag — checked before widgets ─────────────────────────────
    if st.session_state.get("clear_txn_filters"):
        st.session_state["clear_txn_filters"] = False
        st.session_state["txn_fg"]     = "All"
        st.session_state["txn_mg"]     = "All"
        st.session_state["txn_search"] = ""

    # ── Read filter values from session state (widgets rendered below OB table) ─
    sel_fg = st.session_state.get("txn_fg", "All")
    sel_mg = st.session_state.get("txn_mg", "All")
    search = st.session_state.get("txn_search", "")

    # ── Map UI selections to SQL-level params ─────────────────────────────────
    _pag_cat     = None
    _pag_manonly = False
    if sel_fg == "🔒 Manually Categorized":
        _pag_manonly = True
    elif sel_fg == "Uncategorized":
        _pag_cat = "Uncategorized"
    elif sel_fg != "All":
        _pag_cat = sel_fg
    _pag_mg = sel_mg if sel_mg != "All" else None

    # ── Pagination state — reset when any filter changes ──────────────────────
    if "txn_page" not in st.session_state:
        st.session_state["txn_page"] = 1
    _fk = f"{sel_entity}_{sel_bank}_{sel_month}_{sel_fy}_{sel_fg}_{_pag_mg}_{search}"
    if st.session_state.get("_last_filter_key") != _fk:
        st.session_state["txn_page"] = 1
        st.session_state["_last_filter_key"] = _fk

    PAGE_SIZE = 500

    # ── Opening Balance rows (≤1 per bank — tiny separate query) ──────────────
    _ob_raw = get_all_transactions(
        entity=eff_entity, bank=eff_bank,
        month=eff_month, date_from=date_from, date_to=date_to,
        financial_year=sel_fy, category="OPENING BALANCE",
    )
    ob_rows = pd.DataFrame(_ob_raw) if _ob_raw else pd.DataFrame()

    # ── Paginated main rows ────────────────────────────────────────────────────
    pag = get_paginated_transactions(
        entity=eff_entity, bank=eff_bank,
        month=eff_month, date_from=date_from, date_to=date_to,
        category=_pag_cat,
        main_group=_pag_mg,
        manually_overridden_only=_pag_manonly,
        financial_year=sel_fy,
        search=search if search else None,
        page=st.session_state["txn_page"],
        page_size=PAGE_SIZE,
    )
    txn_rows     = pd.DataFrame(pag["rows"]) if pag["rows"] else pd.DataFrame()
    _total_count = pag["total_count"]
    _total_pages = pag["total_pages"]
    _cur_page    = pag["page"]

    if _total_count > 0 or not ob_rows.empty:
        _ob_suffix = f" + {len(ob_rows)} OB row(s)" if not ob_rows.empty else ""
        st.markdown(f"""
<span class="txn-count-badge">
  <span class="txn-dot"></span>
  {_total_count:,} transactions{_ob_suffix}
</span>
""", unsafe_allow_html=True)

        display_cols = ["date", "entity", "bank", "narration", "debit", "credit",
                        "balance", "final_group", "group_name", "main_group"]

        if not ob_rows.empty:
            st.markdown(
                '<div class="ob-banner">'
                '<span class="ob-banner-label">Opening Balance</span>'
                '</div>',
                unsafe_allow_html=True
            )
            ob_show = ob_rows[[c for c in display_cols if c in ob_rows.columns]].copy()
            for _c in ["debit", "credit", "balance"]:
                if _c in ob_show.columns:
                    ob_show[_c] = ob_show[_c].apply(fmt_inr)
            ob_show.columns = [c.replace("_", " ").title() for c in ob_show.columns]
            st.dataframe(ob_show, use_container_width=True, hide_index=True,
                         column_config=amount_config(["Debit", "Credit", "Balance"]))

        st.markdown("---")
        st.markdown("""
<div class="txn-filter-bar">
  <div class="txn-filter-title">Transaction Filters</div>
""", unsafe_allow_html=True)
        _fc1, _fc2, _fc3, _fc4 = st.columns([2, 2, 2, 1])
        with _fc1:
            sel_fg = st.selectbox(
                "Category", fg_options,
                index=fg_options.index(st.session_state.get("txn_fg", "All"))
                      if st.session_state.get("txn_fg", "All") in fg_options else 0,
                key="txn_fg")
        with _fc2:
            sel_mg = st.selectbox(
                "Main Group", mg_options,
                index=mg_options.index(st.session_state.get("txn_mg", "All"))
                      if st.session_state.get("txn_mg", "All") in mg_options else 0,
                key="txn_mg")
        with _fc3:
            search = st.text_input("Search narration", key="txn_search",
                                   placeholder="Type to search…")
        with _fc4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✕ Clear", use_container_width=True):
                st.session_state["clear_txn_filters"] = True
                try:
                    st.rerun()
                except AttributeError:
                    st.experimental_rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        if not txn_rows.empty:
            # ── Category lookup ───────────────────────────────────────────────
            all_cats   = all_cats_for_txn
            cat_names  = [r["final_group"] for r in all_cats]
            cat_lookup = {r["final_group"]: r for r in all_cats}
            cat_options = ["-- Select Category --"] + cat_names

            # ── Categorization panel ──────────────────────────────────────────
            st.markdown("""
<div class="txn-cat-panel">
  <div class="txn-cat-title">Bulk Categorization</div>
""", unsafe_allow_html=True)
            p1, p2, p3, p4 = st.columns([3, 2, 2, 2])
            with p1:
                sel_cat = st.selectbox(
                    "Final Group", cat_options, key="bulk_cat_select", index=0)

            # Auto-fill group name — only reset when category selection changes
            if st.session_state.get("_prev_cat") != sel_cat:
                st.session_state["_auto_group"] = (
                    cat_lookup.get(sel_cat, {}).get("group_name", "")
                    if sel_cat != "-- Select Category --" else ""
                )
                st.session_state["_prev_cat"] = sel_cat

            with p2:
                group_name_val = st.text_input(
                    "Group Name",
                    value=st.session_state.get("_auto_group", ""),
                    key="manual_group_input")
                st.session_state["_auto_group"] = group_name_val

            with p3:
                st.markdown("<br>", unsafe_allow_html=True)
                apply_btn = st.button(
                    "✅ Apply to Selected",
                    key="apply_bulk_cat",
                    use_container_width=True)

            with p4:
                st.markdown("<br>", unsafe_allow_html=True)
                revert_btn = st.button(
                    "↩️ Revert Selected",
                    key="revert_bulk_btn",
                    use_container_width=True)

            # ── Select All / Deselect All ─────────────────────────────────────
            if "select_all_rows" not in st.session_state:
                st.session_state["select_all_rows"] = None

            _sa1, _sa2, _ = st.columns([1, 1, 5])
            with _sa1:
                if st.button("☑ Select All", key="select_all_btn",
                             use_container_width=True):
                    st.session_state["select_all_rows"] = True
                    st.rerun()
            with _sa2:
                if st.button("☐ Deselect All", key="deselect_all_btn",
                             use_container_width=True):
                    st.session_state["select_all_rows"] = False
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

            # ── Data editor ───────────────────────────────────────────────────
            df_editor = txn_rows[["id", "date", "entity", "bank", "narration",
                                   "debit", "credit", "balance",
                                   "final_group", "group_name", "main_group",
                                   "manually_overridden"]].copy()
            df_editor.insert(0, "Select", False)

            if st.session_state["select_all_rows"] is True:
                df_editor["Select"] = True
            elif st.session_state["select_all_rows"] is False:
                df_editor["Select"] = False

            df_editor["debit"]   = df_editor["debit"].apply(
                lambda x: fmt_inr(float(x)) if float(x or 0) > 0 else "—")
            df_editor["credit"]  = df_editor["credit"].apply(
                lambda x: fmt_inr(float(x)) if float(x or 0) > 0 else "—")
            df_editor["balance"] = df_editor["balance"].apply(
                lambda x: fmt_inr(float(x)) if x and str(x) not in ("None", "nan") else "—")
            df_editor["manually_overridden"] = df_editor["manually_overridden"].apply(
                lambda x: "🔒" if int(x or 0) == 1 else "")

            edited = st.data_editor(
                df_editor,
                column_config={
                    "Select":              st.column_config.CheckboxColumn("✓", width="small"),
                    "id":                  st.column_config.NumberColumn("ID", width="small"),
                    "date":                st.column_config.Column("Date", width="small"),
                    "entity":              st.column_config.Column("Entity", width="small"),
                    "bank":                st.column_config.Column("Bank", width="small"),
                    "narration":           st.column_config.Column("Narration", width="large"),
                    "debit":               rcol("Debit ↓", width="medium"),
                    "credit":              rcol("Credit ↑", width="medium"),
                    "balance":             rcol("Balance", width="medium"),
                    "final_group":         st.column_config.Column("Category", width="medium"),
                    "group_name":          st.column_config.Column("Group", width="medium"),
                    "main_group":          st.column_config.Column("Main Group", width="small"),
                    "manually_overridden": st.column_config.Column("🔒", width="small"),
                },
                disabled=["id", "date", "entity", "bank", "narration",
                          "debit", "credit", "balance",
                          "final_group", "group_name", "main_group",
                          "manually_overridden"],
                hide_index=True,
                use_container_width=True,
                height=560,
                key="txn_data_editor"
            )

            # ── Apply / Revert handlers ───────────────────────────────────────
            def _get_selected_ids(edited_df):
                sel = edited_df[edited_df["Select"] == True]
                if sel.empty:
                    return []
                return [int(i) for i in sel["id"].tolist() if i]

            if apply_btn:
                if sel_cat == "-- Select Category --":
                    st.warning("⚠️ Select a Final Group first.")
                else:
                    selected_ids = _get_selected_ids(edited)
                    if not selected_ids:
                        st.warning("⚠️ No rows selected.")
                    else:
                        receipt_ids, payment_ids = [], []
                        for txn_id in selected_ids:
                            orig = txn_rows[txn_rows["id"] == txn_id]
                            if not orig.empty:
                                cr = float(orig.iloc[0].get("credit", 0) or 0)
                                receipt_ids.append(txn_id) if cr > 0 \
                                    else payment_ids.append(txn_id)
                        total = 0
                        if receipt_ids:
                            total += manual_categorize(receipt_ids, sel_cat,
                                                       group_name_val, "Receipt")
                        if payment_ids:
                            total += manual_categorize(payment_ids, sel_cat,
                                                       group_name_val, "Payment")
                        st.cache_data.clear()
                        st.success(f"✅ {total} transaction(s) categorized as '{sel_cat}'")
                        st.session_state["select_all_rows"] = None
                        st.rerun()

            if revert_btn:
                selected_ids = _get_selected_ids(edited)
                if not selected_ids:
                    st.warning("⚠️ No rows selected.")
                else:
                    reverted   = sum(1 for i in selected_ids if revert_manual_category(i))
                    st.cache_data.clear()
                    no_history = len(selected_ids) - reverted
                    if reverted:
                        st.success(f"↩️ Reverted {reverted} transaction(s) to previous category.")
                    if no_history:
                        st.warning(f"{no_history} row(s) had no previous category to revert to.")
                    st.session_state["select_all_rows"] = None
                    st.rerun()

        # ── Legend ────────────────────────────────────────────────────────────
        st.markdown("""
<div class="legend-strip">
  <span class="legend-badge green">🔒 Manually set — protected from Reload</span>
  <span class="legend-badge amber">Uncategorized rows need attention</span>
</div>
""", unsafe_allow_html=True)

        # ── Audit History ─────────────────────────────────────────────────────
        st.markdown("---")
        with st.expander("🕐 Category Change History", expanded=False):
            audit_log = get_category_audit(limit=50)
            if audit_log:
                df_audit = pd.DataFrame(audit_log)[[
                    "changed_at", "transaction_id", "bank", "entity",
                    "narration", "old_category", "new_category", "change_type"
                ]]
                df_audit.columns = [
                    "Changed At", "Txn ID", "Bank", "Entity",
                    "Narration", "From", "To", "Type"
                ]
                def _color_type(val):
                    return "color:#D97706" if val == "revert" else "color:#059669"
                st.dataframe(
                    df_audit.style.map(_color_type, subset=["Type"]),
                    use_container_width=True, hide_index=True, height=300)
                st.download_button(
                    "⬇️ Export Audit Log",
                    df_audit.to_csv(index=False).encode("utf-8"),
                    "category_audit.csv", "text/csv")
            else:
                st.info("No category changes recorded yet.")

        # ── Pagination controls ───────────────────────────────────────────────
        if _total_pages > 1:
            pg1, pg2, pg3, pg4, pg5 = st.columns([1, 1, 2, 1, 1])
            with pg1:
                if st.button("⟨⟨ First", key="txn_first_pg",
                             disabled=_cur_page == 1):
                    st.session_state["txn_page"] = 1; st.rerun()
            with pg2:
                if st.button("⟨ Prev", key="txn_prev_pg",
                             disabled=_cur_page == 1):
                    st.session_state["txn_page"] -= 1; st.rerun()
            with pg3:
                st.markdown(
                    f'<div style="text-align:center;padding:6px;font-size:13px;">'
                    f'Page {_cur_page} of {_total_pages} '
                    f'({_total_count:,} transactions)</div>',
                    unsafe_allow_html=True)
            with pg4:
                if st.button("Next ⟩", key="txn_next_pg",
                             disabled=_cur_page == _total_pages):
                    st.session_state["txn_page"] += 1; st.rerun()
            with pg5:
                if st.button("Last ⟩⟩", key="txn_last_pg",
                             disabled=_cur_page == _total_pages):
                    st.session_state["txn_page"] = _total_pages; st.rerun()

        # ── Reconciliation summary strip (uses cached summary totals) ─────────
        _ob_bal   = float(ob_rows["balance"].iloc[0]) if not ob_rows.empty else None
        _total_cr = inflow
        _total_dr = outflow
        _movement = _total_cr - _total_dr
        _mv_cls   = "pos" if _movement >= 0 else "neg"
        st.markdown(f"""
<div class="cf-stmt-band" style="margin-top:14px;">
  <div class="cf-stmt-band-kpi">
    <span class="cf-stmt-band-label">Opening Balance</span>
    <span class="cf-stmt-band-val">{fmt_inr(_ob_bal)}</span>
  </div>
  <div class="cf-stmt-band-kpi">
    <span class="cf-stmt-band-label">Total Credits</span>
    <span class="cf-stmt-band-val pos">{fmt_inr(_total_cr)}</span>
  </div>
  <div class="cf-stmt-band-kpi">
    <span class="cf-stmt-band-label">Total Debits</span>
    <span class="cf-stmt-band-val neg">{fmt_inr(_total_dr)}</span>
  </div>
  <div class="cf-stmt-band-kpi">
    <span class="cf-stmt-band-label">Net Movement</span>
    <span class="cf-stmt-band-val {_mv_cls}">{fmt_inr(_movement)}</span>
  </div>
  <div class="cf-stmt-band-kpi">
    <span class="cf-stmt-band-label">Closing Balance</span>
    <span class="cf-stmt-band-val">{fmt_inr(closing_balance)}</span>
  </div>
</div>""", unsafe_allow_html=True)

        if not txn_rows.empty:
            _csv_fname = f"transactions_{sel_fg}_{_pag_mg or 'All'}.csv".replace(" ", "_")
            st.download_button(
                label=f"⬇️ Download page ({len(txn_rows):,} rows) as CSV",
                data=txn_rows.to_csv(index=False).encode("utf-8"),
                file_name=_csv_fname,
                mime="text/csv"
            )
    else:
        st.info("No transactions found. Adjust filters or drop bank statement files.")

# ══════════════════════════════════════════════════════════════════════════════
# REVIEW QUEUE
# ══════════════════════════════════════════════════════════════════════════════
elif selected_tab == "Uncategorised":
    render_review_queue(uncats)

# ══════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ══════════════════════════════════════════════════════════════════════════════
elif selected_tab == "Exception Report":
    st.markdown("### Exceptions & Alerts")
    st.markdown("""
<div style="background:#EBF4FF; border-left:4px solid #3B82F6;
     border-radius:6px; padding:10px 16px; margin-bottom:16px;
     font-size:13px; color:#1E40AF;">
    📡 <b>Live view</b> — This tab always shows the full picture
    across all entities and periods, independent of sidebar filters.
</div>
""", unsafe_allow_html=True)

    # ── Summary warning (details below) ───────────────────────────────────────
    _integ = get_data_integrity_report()
    if _integ["missing"] or _integ["breaks"]:
        _miss_days = sum(m["days"] for m in _integ["missing"])
        _parts = []
        if _integ["missing"]:
            _parts.append(f"<b>{len(_integ['missing'])}</b> period(s) with no statement loaded "
                          f"({_miss_days} day(s))")
        if _integ["breaks"]:
            _parts.append(f"<b>{len(_integ['breaks'])}</b> day(s) where the bank balance does not tie "
                          f"to the loaded transactions (net {fmt_inr(_integ['net_diff'])})")
        st.markdown(f"""
<div style="background:#FFF7ED; border:1px solid #FDBA74; border-left:5px solid #EA580C;
     border-radius:10px; padding:11px 18px; margin:0 0 14px; font-size:13px; color:#7C2D12;">
    ⚠️ <b>Data check:</b> {" &nbsp;·&nbsp; ".join(_parts)}.
    Balances and cash flow may be incomplete.
</div>""", unsafe_allow_html=True)

    # ── Data integrity: missing statements + balance mismatches ───────────────
    st.markdown("#### 🛡️ Data Integrity")
    st.caption("Checks that every statement day is loaded and that each day's closing balance "
               "equals the previous closing + credits − debits, using the balance printed by the bank.")
    _ig = get_data_integrity_report()
    if _ig["breaks"]:
        _dups = find_duplicate_rows()
        if _dups["ids"]:
            st.warning(
                f"🧹 **{len(_dups['ids'])} duplicate transaction rows** found on {_dups['days']} day(s): the same "
                f"transaction (same account, date, amount and balance) is stored twice, usually because the bank "
                f"worded the narration differently in two downloads (e.g. “CSH/CB” vs “CSH-CB”). "
                f"They inflate that day's credits/debits and cause balance mismatches. "
                f"New uploads no longer create them; this removes the ones already stored.")
            with st.expander("Show the duplicate rows"):
                _dd = pd.DataFrame(_dups["rows"])
                _dd["debit"] = _dd["debit"].apply(fmt_inr)
                _dd["credit"] = _dd["credit"].apply(fmt_inr)
                st.dataframe(_dd.rename(columns={"id": "Row ID", "bank": "Account", "date": "Date",
                                                 "narration": "Narration", "debit": "Debit", "credit": "Credit",
                                                 "upload_id": "Upload #"}),
                             use_container_width=True, hide_index=True,
                             column_config=amount_config(["Debit", "Credit"]))
            if st.button(f"🧹 Remove {len(_dups['ids'])} duplicate rows", key="remove_dups_btn"):
                _n_del = remove_duplicate_rows(_dups["ids"])
                st.cache_data.clear()
                st.session_state["repair_msg"] = f"Removed {_n_del} duplicate rows."
                st.rerun()
        _rc1, _rc2 = st.columns([1.3, 4])
        with _rc1:
            if st.button("🔧 Re-check balance order", key="repair_order_btn",
                         help="Re-derives each day's transaction order from the bank's running balance. "
                              "Safe to run; fixes wrong day-end balances."):
                with st.spinner("Re-checking..."):
                    _rs = repair_order_keys()
                st.cache_data.clear()
                st.session_state["repair_msg"] = (
                    f"Checked {_rs['days']:,} account-days: {_rs['reordered']:,} re-ordered, "
                    f"{_rs['unresolved']:,} could not be resolved (rows missing).")
                st.rerun()
        with _rc2:
            if st.session_state.get("repair_msg"):
                st.caption(st.session_state.pop("repair_msg"))
    if not _ig["missing"] and not _ig["breaks"]:
        st.success("All clear — no missing statement dates and every balance ties.")
    if _ig["missing"]:
        st.markdown("**Missing statement dates** — upload the statement covering these dates")
        _mdf = pd.DataFrame([{
            "Account": m["bank"],
            "From": datetime.date.fromisoformat(m["from"]).strftime("%d %b %Y"),
            "To": datetime.date.fromisoformat(m["to"]).strftime("%d %b %Y"),
            "Days": m["days"],
            "Status": "Not yet loaded" if m["kind"] == "not loaded" else "Gap inside loaded data",
        } for m in _ig["missing"]])
        st.dataframe(_mdf, use_container_width=True, hide_index=True)
    if _ig["breaks"]:
        st.markdown(f"**Balance mismatches** — {len(_ig['breaks'])} day(s), net "
                    f"{fmt_inr(_ig['net_diff'])}")
        _bdf = pd.DataFrame([{
            "Account": b["bank"],
            "Date": datetime.date.fromisoformat(b["date"]).strftime("%d %b %Y"),
            "Expected balance": fmt_inr(b["expected"], dash_zero=False),
            "Bank balance": fmt_inr(b["actual"], dash_zero=False),
            "Difference": fmt_inr(b["diff"]),
            "Likely reason": (
                f"{b['gap_days']} day(s) before this date not loaded" if b["after_gap"] else
                "Transactions missing (credits)" if b["diff"] > 0 else
                "Transactions missing (debits)"),
        } for b in _ig["breaks"]])
        st.dataframe(_bdf, use_container_width=True, hide_index=True,
                     column_config=amount_config(["Expected balance", "Bank balance", "Difference"]))
        st.caption("Difference = bank balance − (previous balance + credits − debits). "
                   "Positive: credits are missing or extra debits were loaded. "
                   "Negative: debits are missing or extra credits were loaded.")
    st.markdown("")

    # All calls in this tab are unfiltered — full DB picture regardless of sidebar
    _exc_uncats      = get_uncategorized()
    _exc_stmt_status = get_missing_statements()
    _exc_large_debits = get_large_debits(LARGE_DEBIT_THRESHOLD)

    uncat_count = sum(u["count"] for u in _exc_uncats)
    if uncat_count > 0:
        by_entity_unc = {}
        for u in _exc_uncats:
            e = u.get("entity", "Unknown")
            by_entity_unc[e] = by_entity_unc.get(e, 0) + u["count"]
        breakdown      = " | ".join([f"{e}: {c}" for e, c in by_entity_unc.items()])
        top_narrations = ", ".join([u["narration"][:40] for u in _exc_uncats[:3]])
        st.markdown(f"""
        <div class="alert-box alert-red">
            <b>🔴 UNCATEGORIZED TRANSACTIONS</b><br>
            <b>{uncat_count}</b> transactions need categorization<br>
            <small>{breakdown}</small><br>
            <small>Top unmatched: {top_narrations}</small>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="alert-box alert-green">
            <b>✅ UNCATEGORIZED</b> — All transactions are categorized.
        </div>""", unsafe_allow_html=True)

    st.markdown("")

    st.markdown("#### 🏦 Bank Statement Status")
    for s in _exc_stmt_status:
        if s["status"] == "ok":
            bg, border, icon = "#F0FFF4", "#38A169", "✅"
            msg = f"Current — last entry <b>{s['last_date']}</b>"
        elif s["status"] == "warning":
            bg, border, icon = "#FFFFF0", "#D69E2E", "⚠️"
            msg = (f"Last loaded: <b>{s['last_date']}</b> "
                   f"({s['days_ago']} days ago) — "
                   f"current month not loaded")
        else:
            bg, border, icon = "#FFF5F5", "#E53E3E", "🔴"
            msg = f"No data loaded — {s['last_date']}"

        _cb = s.get("closing_bal")
        _cb_str = (f" · Closing: {fmt_inr(_cb)}" if _cb is not None else "")
        st.markdown(f"""
    <div style="background:{bg}; border-left:4px solid {border};
         border-radius:6px; padding:10px 16px; margin:5px 0;
         display:flex; justify-content:space-between;">
        <span style="font-size:13px; color:#1A202C;">
            {icon}&nbsp; <b>{s['entity']} — {s['bank']}</b>
            &nbsp;|&nbsp; {msg}
        </span>
        <span style="font-size:11px; color:#8896A5;">
            {s['total_rows']:,} rows{_cb_str}
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")

    # ── Upload Trail ──────────────────────────────────────────────────────────
    st.markdown("#### Upload Trail")
    st.caption("History of all loaded statements. Click Delete to remove a wrongly uploaded file.")
    _trail = get_upload_trail()
    if not _trail:
        st.info("No statements uploaded yet.")
    else:
        _th = st.columns([2, 1, 1, 1, 1, 1, 0.8])
        for _tc, _tl in zip(_th, ["Filename", "Entity", "Bank", "FY",
                                    "Rows", "Uploaded At", "Action"]):
            with _tc:
                st.markdown(
                    f'<div style="font-size:11px;font-weight:700;color:#8896A5;'
                    f'text-transform:uppercase;">{_tl}</div>',
                    unsafe_allow_html=True)
        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #E8ECF0;">',
                    unsafe_allow_html=True)
        for _t in _trail:
            _tc = st.columns([2, 1, 1, 1, 1, 1, 0.8])
            with _tc[0]:
                st.markdown(f'<div style="font-size:12px;color:#1A202C;padding:4px 0;'
                            f'word-break:break-all;">{_t["filename"]}</div>',
                            unsafe_allow_html=True)
            with _tc[1]:
                st.markdown(f'<div style="font-size:12px;color:#4A5568;padding:4px 0;">'
                            f'{_t["entity"] or "—"}</div>', unsafe_allow_html=True)
            with _tc[2]:
                st.markdown(f'<div style="font-size:12px;color:#4A5568;padding:4px 0;">'
                            f'{_t["bank"] or "—"}</div>', unsafe_allow_html=True)
            with _tc[3]:
                st.markdown(f'<div style="font-size:12px;color:#4A5568;padding:4px 0;">'
                            f'{_t["financial_year"] or "—"}</div>', unsafe_allow_html=True)
            with _tc[4]:
                st.markdown(f'<div style="font-size:12px;color:#4A5568;padding:4px 0;">'
                            f'{_t["rows_inserted"]:,}</div>', unsafe_allow_html=True)
            with _tc[5]:
                st.markdown(f'<div style="font-size:12px;color:#8896A5;padding:4px 0;">'
                            f'{_t["uploaded_at"][:16]}</div>', unsafe_allow_html=True)
            with _tc[6]:
                if st.button("Delete", key=f"del_upload_{_t['id']}"):
                    st.session_state[f"confirm_del_{_t['id']}"] = True
                    st.rerun()
            if st.session_state.get(f"confirm_del_{_t['id']}"):
                _impact = check_upload_delete_impact(_t["id"])
                _mo_count = _impact["manually_overridden_count"]
                _match_mode = _impact["match_mode"]

                st.warning(
                    f"Delete **{_t['filename']}**? This will remove "
                    f"{_impact['total_matched']:,} transaction row(s) "
                    f"it created. This cannot be undone."
                )
                if _match_mode == "legacy_heuristic":
                    st.info(
                        "This upload predates exact tracking — matching rows "
                        "were identified by filename + entity + bank + date "
                        "range rather than an exact link. Double-check the "
                        "count above looks right before confirming."
                    )

                _force_override = False
                if _mo_count > 0:
                    st.error(
                        f"⚠️ {_mo_count:,} of these rows were manually "
                        f"corrected (manually_overridden=1) and will be "
                        f"SKIPPED by default. Check the box below to also "
                        f"delete those manually-corrected rows."
                    )
                    _force_override = st.checkbox(
                        f"Also delete the {_mo_count:,} manually-corrected row(s)",
                        key=f"force_mo_{_t['id']}"
                    )

                _dc1, _dc2 = st.columns([1, 4])
                with _dc1:
                    if st.button("Confirm Delete", key=f"confirm_yes_{_t['id']}"):
                        _result = delete_upload(
                            _t["id"], include_manually_overridden=_force_override)
                        _msg = f"Deleted {_result['deleted']:,} rows from {_t['filename']}"
                        if _result["manually_overridden_skipped"]:
                            _msg += (f" ({_result['manually_overridden_skipped']:,} "
                                     f"manually-corrected rows kept)")
                        st.success(_msg)
                        del st.session_state[f"confirm_del_{_t['id']}"]
                        st.cache_data.clear()
                        st.rerun()
                with _dc2:
                    if st.button("Cancel", key=f"confirm_no_{_t['id']}"):
                        del st.session_state[f"confirm_del_{_t['id']}"]
                        st.rerun()
            st.markdown('<hr style="margin:2px 0;border:none;border-top:1px solid #F0F0F0;">',
                        unsafe_allow_html=True)

    st.markdown("")

    # ── Transfer Reconciliation ───────────────────────────────────────────────
    recon  = get_transfer_reconciliation()
    ib_net = recon["interbank_net"]
    ic_net = recon["intercompany_net"]

    st.markdown("#### 🔄 Transfer Reconciliation")
    for _lbl, _net, _warn_bg, _warn_txt, _hint in [
        ("Interbank",    ib_net, "#FFFFF0", "#744210",
         "Check for missing entries across bank accounts."),
        ("Intercompany", ic_net, "#FFF5F5", "#742A2A",
         "Stores vs Ventures transfers do not balance."),
    ]:
        if _net is not None:
            _direction = "Receipt side higher" if _net > 0 else "Payout side higher"
            st.markdown(f"""
        <div style="background:{_warn_bg}; border-left:4px solid #D69E2E;
             border-radius:6px; padding:10px 16px; margin:6px 0;
             font-size:13px; color:{_warn_txt};">
            ⚠️ <b>{_lbl} difference: {fmt_inr(abs(_net))}</b>
            — {_direction}. {_hint}
        </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
        <div style="background:#F0FFF4; border-left:4px solid #38A169;
             border-radius:6px; padding:10px 16px; margin:6px 0;
             font-size:13px; color:#276749;">
            ✅ <b>{_lbl} transfers fully netted</b> — no difference.
        </div>""", unsafe_allow_html=True)

    st.markdown("")

    large_debits = _exc_large_debits
    if large_debits:
        rows_html = "".join([
            f"<tr>"
            f"<td style='padding:5px 8px'>{r['date']}</td>"
            f"<td style='padding:5px 8px'>{r['entity']}</td>"
            f"<td style='padding:5px 8px'>{r['bank']}</td>"
            f"<td style='padding:5px 8px;color:var(--red-700,#B91C1C);font-weight:600'>"
            f"{fmt_inr(r['debit'])}</td>"
            f"<td style='padding:5px 8px'>{r['narration'][:50]}</td>"
            f"<td style='padding:5px 8px;color:var(--tx-3,#6B7A90)'>{r['final_group'] or '—'}</td>"
            f"</tr>"
            for r in large_debits[:10]
        ])
        st.markdown(f"""
        <div class="alert-box alert-yellow">
            <b>🟡 LARGE DEBITS</b> (above {fmt_inr(LARGE_DEBIT_THRESHOLD)})<br><br>
            <table style="width:100%;color:var(--tx-2,#3D4F66);font-size:13px;
                          border-collapse:collapse;font-family:'Inter',sans-serif;">
                <tr style="color:var(--tx-4,#96A3B4);border-bottom:1px solid var(--border-sm,#E2E7EF);
                           font-size:9.5px;font-weight:700;letter-spacing:0.09em;text-transform:uppercase;">
                    <th style="padding:6px 8px;text-align:left">Date</th>
                    <th style="padding:6px 8px;text-align:left">Entity</th>
                    <th style="padding:6px 8px;text-align:left">Bank</th>
                    <th style="padding:6px 8px;text-align:left">Amount</th>
                    <th style="padding:6px 8px;text-align:left">Narration</th>
                    <th style="padding:6px 8px;text-align:left">Category</th>
                </tr>
                {rows_html}
            </table>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="alert-box alert-green">
            <b>✅ LARGE DEBITS</b> — No debits above {fmt_inr(LARGE_DEBIT_THRESHOLD)}
        </div>""", unsafe_allow_html=True)

    st.markdown("")

    import sqlite3 as _sq3_exc
    _exc_conn = _sq3_exc.connect(DATABASE_FILE)
    _exc_conn.row_factory = _sq3_exc.Row
    _inter_row = _exc_conn.execute("""
        SELECT COUNT(*) as cnt, ROUND(SUM(debit),2) as total
        FROM transactions
        WHERE main_group IN ('INTERBANK','INTERCOMPANY')
    """).fetchone()
    _exc_conn.close()
    if _inter_row and _inter_row["cnt"] > 0:
        st.markdown(f"""
        <div class="alert-box alert-green">
            <b>ℹ️ INTERBANK / INTERCOMPANY TRANSFERS</b> — Excluded from P&amp;L<br>
            {_inter_row["cnt"]:,} transfers totalling {fmt_inr(_inter_row["total"] or 0)} are excluded
            from inflow/outflow calculations.
        </div>""", unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("🖼️ Update Logo", expanded=False):
        logo_file = st.file_uploader(
            "Upload logo (PNG/JPG)", type=["png", "jpg", "jpeg"],
            accept_multiple_files=False, key="logo_uploader_exc")
        if st.button("💾 Save Logo", key="save_logo_btn_exc"):
            if logo_file is not None:
                with open(LOGO_PATH, "wb") as _lf_w:
                    _lf_w.write(logo_file.getbuffer())
                st.success("✅ Logo saved. Refreshing...")
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("Please select a file first.")

# ══════════════════════════════════════════════════════════════════════════════
# CASH FLOW
# ══════════════════════════════════════════════════════════════════════════════
elif selected_tab == "Cash Flow":
    st.markdown(LIVE_BANNER, unsafe_allow_html=True)
    st.markdown(CF_STYLE, unsafe_allow_html=True)
    # ── Toggle session state ──────────────────────────────────────────────────
    for _k in ["cf_ob_open", "cf_rec_open", "cf_pay_open", "cf_cb_open"]:
        if _k not in st.session_state:
            st.session_state[_k] = False
    for _k in ["wcf_ob_open", "wcf_rec_open", "wcf_pay_open", "wcf_cb_open"]:
        if _k not in st.session_state:
            st.session_state[_k] = False

    # ── Drive from sidebar ────────────────────────────────────────────────────
    cf_entity = None if sel_entity == "All" else sel_entity

    if use_date_range and sel_date_from and sel_date_to:
        cf_month_from = str(sel_date_from)
        cf_month_to   = str(sel_date_to)
    else:
        _cf_latest    = get_latest_data_date() or str(datetime.date.today())
        _cf_latest_dt = datetime.date.fromisoformat(_cf_latest)
        cf_month_from = str(_cf_latest_dt.replace(day=1))
        cf_month_to   = str(_cf_latest_dt)

    if use_date_range and sel_date_to:
        week_anchor = sel_date_to
    else:
        week_anchor = datetime.date.fromisoformat(
            get_latest_data_date() or str(datetime.date.today()))

    # ── View toggle + Expand / Collapse All (one row) ─────────────────────────
    # Match section toggles (_open suffix) and group toggles (_grp_ in key)
    # but NOT widget keys like cf_ent_radio / cf_from / cf_to.
    def _cf_toggle_keys():
        return [
            k for k in st.session_state
            if (k.startswith("cf_") or k.startswith("wcf_"))
            and ("_open" in k or "_grp_" in k)
        ]

    _vc1, _vc2, _ea_col, _ca_col, _ = st.columns([2, 4.2, 1.7, 1.7, 1.4])
    with _vc1:
        cf_view = st.radio(
            "View", ["Monthly", "Weekly"],
            horizontal=True, key="cf_view_toggle", label_visibility="collapsed"
        )
    with _vc2:
        cf_fmt = st.radio(
            "Format", ["Companies Act format", "Previous format"],
            horizontal=True, key="cf_fmt_toggle", label_visibility="collapsed"
        )
    with _ea_col:
        if st.button("⊞ Expand All", key="cf_expand_all"):
            for _k in _cf_toggle_keys():
                st.session_state[_k] = True
            st.rerun()
    with _ca_col:
        if st.button("⊟ Collapse All", key="cf_collapse_all"):
            for _k in _cf_toggle_keys():
                st.session_state[_k] = False
            st.rerun()

    # ── Data fetch ────────────────────────────────────────────────────────────
    def _get_cf(d_from, d_to, financial_year=None):
        """Fetch cash flow; entity=None for All (triggers IC netting in fetch_cf)."""
        ds, de = str(d_from), str(d_to)
        return fetch_cf(cf_entity, ds, de, DATABASE_FILE, financial_year=None)

    # ── Collapsible section helper ────────────────────────────────────────────
    def _cf_section(label, total, line_items, toggle_key, btn_key,
                    label_color="#1A1A2E", total_color="#1A1A2E", is_payout=False,
                    section_cls="", section_bg=""):
        """Renders one collapsible Cash Flow section."""
        h1, h2, h3 = st.columns([0.04, 0.71, 0.25])
        with h1:
            sign = "−" if st.session_state[toggle_key] else "+"
            if st.button(sign, key=btn_key):
                st.session_state[toggle_key] = not st.session_state[toggle_key]
                st.rerun()
        with h2:
            if section_cls:
                st.markdown(
                    f'<div class="cf-section-label {section_cls}">{label}</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="font-weight:600; color:{label_color}; '
                    f'background:var(--bg-raised,#F4F6FA); padding:6px 8px; '
                    f'border-radius:6px;">{label}</div>', unsafe_allow_html=True)
        with h3:
            _tcls = "neg" if is_payout else "sky"
            _bg_style = f"background:{section_bg};" if section_bg else ""
            st.markdown(
                f'<div class="cf-section-total {_tcls}" style="{_bg_style}">{_inr(total)}</div>',
                unsafe_allow_html=True)
        if st.session_state[toggle_key]:
            for label_item, amount in line_items.items():
                _, r2, r3 = st.columns([0.04, 0.71, 0.25])
                _unc = label_item == "Uncategorized"
                _unc_cls = " unc" if _unc else ""
                with r2:
                    st.markdown(
                        f'<div class="cf-detail{_unc_cls}" style="background:#FFFFFF;color:#374151;">'
                        f'{label_item}</div>',
                        unsafe_allow_html=True)
                with r3:
                    st.markdown(
                        f'<div class="cf-dval{_unc_cls}" style="background:#FFFFFF;color:#374151;">'
                        f'{_inr(amount)}</div>',
                        unsafe_allow_html=True)
        st.markdown('<hr class="cf-divider-sm">', unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────────────
    # MONTHLY VIEW
    # ─────────────────────────────────────────────────────────────────────────
    if cf_fmt == "Companies Act format":
        render_cashflow_statement(cf_view, cf_entity, cf_month_from, cf_month_to, week_anchor)

    elif cf_view == "Monthly":
        _fmt_d = lambda d: datetime.date.fromisoformat(str(d)).strftime("%d %b %Y")
        st.markdown(f"""
<div class="cf-stmt-head">
  <span class="cf-stmt-title">Cash Flow Statement</span>
  <span class="cf-stmt-range">{_fmt_d(cf_month_from)} &nbsp;→&nbsp; {_fmt_d(cf_month_to)}</span>
</div>
""", unsafe_allow_html=True)
        cf = _get_cf(cf_month_from, cf_month_to, financial_year=None)

        # Uncategorized always last
        receipts_ordered = {k: v for k, v in cf["receipts"].items() if k != "Uncategorized"}
        if "Uncategorized" in cf["receipts"]:
            receipts_ordered["Uncategorized"] = cf["receipts"]["Uncategorized"]
        payouts_ordered = {k: v for k, v in cf["payouts"].items() if k != "Uncategorized"}
        if "Uncategorized" in cf["payouts"]:
            payouts_ordered["Uncategorized"] = cf["payouts"]["Uncategorized"]

        _ob_extra = get_mf_fd_cash_asof(cf_entity, cf["opening_asof_date"], DATABASE_FILE)
        _opening_combined = (cf["total_opening"] + _ob_extra["mf"]
                             + _ob_extra["fd"] + _ob_extra["cash"])
        _cf_section(
            "Opening Balance", _opening_combined,
            {
                **{f"Bank ({k})": v for k, v in cf["opening_balances"].items()},
                "Mutual Fund Balance":   _ob_extra["mf"],
                "Fixed Deposit Balance": _ob_extra["fd"],
                "Cash at Stores":        _ob_extra["cash"],
            },
            "cf_ob_open", "btn_cf_ob", section_cls="cf-ob", section_bg="#DBEAFE"
        )
        # ── Add Receipts — GROUP → FINAL GROUP hierarchy ─────────────────
        _rh1, _rh2, _rh3 = st.columns([0.04, 0.71, 0.25])
        with _rh1:
            _rsign = "−" if st.session_state["cf_rec_open"] else "+"
            if st.button(_rsign, key="btn_cf_rec"):
                st.session_state["cf_rec_open"] = not st.session_state["cf_rec_open"]
                st.rerun()
        with _rh2:
            st.markdown('<div class="cf-section-label cf-rec">Add Receipts</div>',
                        unsafe_allow_html=True)
        with _rh3:
            st.markdown(
                f'<div class="cf-section-total pos" style="background:#EDE9FE;">'
                f'{_inr(cf["total_receipts"])}</div>',
                unsafe_allow_html=True)
        if st.session_state["cf_rec_open"]:
            for _grp_name, _fg_dict in sorted(
                cf.get("receipts_nested", {}).items(),
                key=lambda x: sum(x[1].values()), reverse=True
            ):
                _grp_total = sum(_fg_dict.values())
                _grp_key   = f"cf_grp_rec_{_grp_name}"
                if _grp_key not in st.session_state:
                    st.session_state[_grp_key] = False
                _g1, _g2, _g3 = st.columns([0.08, 0.67, 0.25])
                with _g1:
                    _gsign = "−" if st.session_state[_grp_key] else "+"
                    if st.button(_gsign, key=f"btn_{_grp_key}"):
                        st.session_state[_grp_key] = not st.session_state[_grp_key]
                        st.rerun()
                with _g2:
                    st.markdown(f'<div class="cf-grp-row rec">{_grp_name}</div>',
                                unsafe_allow_html=True)
                with _g3:
                    st.markdown(f'<div class="cf-grp-val rec">{_inr(_grp_total)}</div>',
                                unsafe_allow_html=True)
                if st.session_state[_grp_key]:
                    for _cat, _amt in sorted(_fg_dict.items(), key=lambda x: x[1], reverse=True):
                        _is_unc = _cat == "Uncategorized"
                        _sub_cls = " unc" if _is_unc else ""
                        _, _cr2, _cr3 = st.columns([0.08, 0.67, 0.25])
                        with _cr2:
                            st.markdown(f'<div class="cf-sub-row{_sub_cls}">{_cat}</div>',
                                        unsafe_allow_html=True)
                        with _cr3:
                            st.markdown(f'<div class="cf-sub-val{_sub_cls}">{_inr(_amt)}</div>',
                                        unsafe_allow_html=True)
        st.markdown('<hr class="cf-divider-sm">', unsafe_allow_html=True)

        # ── Less Payouts — GROUP → FINAL GROUP hierarchy ──────────────────
        _ph1, _ph2, _ph3 = st.columns([0.04, 0.71, 0.25])
        with _ph1:
            _psign = "−" if st.session_state["cf_pay_open"] else "+"
            if st.button(_psign, key="btn_cf_pay"):
                st.session_state["cf_pay_open"] = not st.session_state["cf_pay_open"]
                st.rerun()
        with _ph2:
            st.markdown('<div class="cf-section-label cf-pay">Less Payouts</div>',
                        unsafe_allow_html=True)
        with _ph3:
            st.markdown(
                f'<div class="cf-section-total neg" style="background:#FCE7F3;">'
                f'{_inr(cf["total_payouts"])}</div>',
                unsafe_allow_html=True)
        if st.session_state["cf_pay_open"]:
            for _grp_name, _fg_dict in sorted(
                cf.get("payouts_nested", {}).items(),
                key=lambda x: sum(x[1].values()), reverse=True
            ):
                _grp_total = sum(_fg_dict.values())
                _grp_key   = f"cf_grp_pay_{_grp_name}"
                if _grp_key not in st.session_state:
                    st.session_state[_grp_key] = False
                _g1, _g2, _g3 = st.columns([0.08, 0.67, 0.25])
                with _g1:
                    _gsign = "−" if st.session_state[_grp_key] else "+"
                    if st.button(_gsign, key=f"btn_{_grp_key}"):
                        st.session_state[_grp_key] = not st.session_state[_grp_key]
                        st.rerun()
                with _g2:
                    st.markdown(f'<div class="cf-grp-row pay">{_grp_name}</div>',
                                unsafe_allow_html=True)
                with _g3:
                    st.markdown(f'<div class="cf-grp-val pay">{_inr(_grp_total)}</div>',
                                unsafe_allow_html=True)
                if st.session_state[_grp_key]:
                    for _cat, _amt in sorted(_fg_dict.items(), key=lambda x: x[1], reverse=True):
                        _is_unc = _cat == "Uncategorized"
                        _sub_cls = " unc" if _is_unc else ""
                        _, _pr2, _pr3 = st.columns([0.08, 0.67, 0.25])
                        with _pr2:
                            st.markdown(f'<div class="cf-sub-row{_sub_cls}">{_cat}</div>',
                                        unsafe_allow_html=True)
                        with _pr3:
                            st.markdown(f'<div class="cf-sub-val{_sub_cls}">{_inr(_amt)}</div>',
                                        unsafe_allow_html=True)
        st.markdown('<hr class="cf-divider-sm">', unsafe_allow_html=True)

        # ── Reconciling lines: Interbank / Intercompany / Investment net ──────
        for _recon_lbl, _recon_key, _recon_color in [
            ("Interbank (Net)",    "interbank_period_net", None),
            ("Intercompany (Net)", "intercompany_period_net", None),
        ]:
            _rval = cf.get(_recon_key) or 0
            if abs(_rval) > 1:
                _rcol = "#166534" if _rval >= 0 else "#B91C1C"
                _rh1, _rh2, _rh3 = st.columns([0.04, 0.71, 0.25])
                with _rh2:
                    st.markdown(f'<div class="cf-recon-lbl">{_recon_lbl}</div>',
                                unsafe_allow_html=True)
                with _rh3:
                    st.markdown(
                        f'<div class="cf-recon-val" style="color:{_rcol};">'
                        f'{fmt_cf(_rval)}</div>',
                        unsafe_allow_html=True)

        # Cash at Stores is a manually entered balance (not a bank movement) — shown as
        # its own line so Opening + Receipts - Payouts + Cash change = Closing.
        _cb_extra = get_mf_fd_cash_asof(cf_entity, cf_month_to, DATABASE_FILE)
        _cash_chg = _cb_extra["cash"] - _ob_extra["cash"]
        if abs(_cash_chg) > 1:
            _ch1, _ch2, _ch3 = st.columns([0.04, 0.71, 0.25])
            with _ch2:
                st.markdown('<div class="cf-recon-lbl">Cash at Stores (Net change)</div>',
                            unsafe_allow_html=True)
            with _ch3:
                st.markdown(
                    f'<div class="cf-recon-val" style="color:{"#166534" if _cash_chg >= 0 else "#B91C1C"};">'
                    f'{fmt_cf(_cash_chg)}</div>',
                    unsafe_allow_html=True)

        _closing_combined = (cf["total_closing"] + _cb_extra["mf"]
                             + _cb_extra["fd"] + _cb_extra["cash"])
        _cf_section(
            "Closing Balance", _closing_combined,
            {
                **{f"Bank ({k})": v for k, v in cf["closing_balances"].items()},
                "Mutual Fund Balance":   _cb_extra["mf"],
                "Fixed Deposit Balance": _cb_extra["fd"],
                "Cash at Stores":        _cb_extra["cash"],
            },
            "cf_cb_open", "btn_cf_cb", section_cls="cf-cb", section_bg="#DBEAFE"
        )

        # NET MOVEMENT — new Closing Balance TOTAL minus new Opening Balance TOTAL
        # (each TOTAL = Bank + Mutual Fund + Fixed Deposit + Cash at Stores)
        _net     = _closing_combined - _opening_combined
        _net_cls = "pos" if _net >= 0 else "neg"
        st.markdown(f"""
<div class="cf-net {_net_cls}">
  <span>NET MOVEMENT</span>
  <span>{_inr(_net)}</span>
</div>""", unsafe_allow_html=True)

        # TALLY CHECK — computed Closing TOTAL (combined) vs actual DB Closing (combined)
        # MF/FD/Cash are identical carry-forward figures on both sides, so this
        # reduces to the same bank formula-vs-actual check as before, now
        # validating the combined total the tab actually displays.
        _tally         = _closing_combined
        _db_actual_bank = get_closing_balance(
            entity=cf_entity,
            date_from="1900-01-01",
            date_to=str(cf_month_to),
        )["total"] or 0
        _db_actual = _db_actual_bank + _cb_extra["mf"] + _cb_extra["fd"] + _cb_extra["cash"]
        _diff   = round(_tally - _db_actual, 2)
        _t_ok   = abs(_diff) <= 1
        _t_icon = "✅" if _t_ok else "⚠️"
        _t_msg  = "Tallied" if _t_ok else f"Diff: {_inr(abs(_diff))}"
        _t_cls  = "ok" if _t_ok else "err"
        st.markdown(f"""
<div class="cf-tally {_t_cls}">
  <strong>{_t_icon} Tally</strong>
  Computed: {_inr(_tally)} &nbsp;·&nbsp; DB: {_inr(_db_actual)}
  &nbsp;·&nbsp; <strong>{_t_msg}</strong>
</div>""", unsafe_allow_html=True)

        # Excel export
        _, _ec2 = st.columns([8.5, 1.5])
        with _ec2:
            def _build_excel_monthly():
                from openpyxl import Workbook
                from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
                wb = Workbook()
                ws = wb.active
                ws.title = "Cash Flow"
                ws.column_dimensions["A"].width = 45
                ws.column_dimensions["B"].width = 22
                h_fill = PatternFill("solid", fgColor="F1F3F5")
                t_fill = PatternFill("solid", fgColor="E8F4FD")
                ws.append(["Particulars", "Amount (₹)"])
                for cell in ws[1]:
                    cell.font      = Font(bold=True, size=10, color="9CA3AF")
                    cell.fill      = h_fill
                    cell.alignment = Alignment(
                        horizontal="right" if cell.column > 1 else "left")

                def _xlr(label, val=None, style="normal", indent=0):
                    ws.append([("  " * indent) + label, val or None])
                    r = ws.max_row
                    if style == "header":
                        for c in ws[r]:
                            c.font = Font(bold=True, size=11)
                            c.fill = h_fill
                    elif style == "total":
                        for c in ws[r]:
                            c.font   = Font(bold=True, color="1E3A5F")
                            c.fill   = t_fill
                            c.border = Border(
                                top=Side(style="medium", color="4E8DF5"),
                                bottom=Side(style="medium", color="4E8DF5"))
                    elif style == "net":
                        pos = (val or 0) >= 0
                        for c in ws[r]:
                            c.font = Font(bold=True, size=12,
                                          color="2E7D32" if pos else "C62828")
                            c.fill = PatternFill("solid",
                                                 fgColor="F0FDF4" if pos else "FEF2F2")
                    if val is not None:
                        ws.cell(row=r, column=2).alignment = Alignment(
                            horizontal="right")

                _xlr("Opening Balance", style="header")
                for k, v in cf["opening_balances"].items():
                    _xlr(f"Bank ({k})", v, indent=1)
                _xlr("Mutual Fund Balance", _ob_extra["mf"], indent=1)
                _xlr("Fixed Deposit Balance", _ob_extra["fd"], indent=1)
                _xlr("Cash at Stores", _ob_extra["cash"], indent=1)
                _xlr("Total Opening Balance", _opening_combined, style="total")
                _xlr("Add Receipts:", style="header")
                for k, v in receipts_ordered.items():
                    _xlr(k, v, indent=1)
                _xlr("Total Receipts", cf["total_receipts"], style="total")
                _xlr("Less Payouts:", style="header")
                for k, v in payouts_ordered.items():
                    _xlr(k, v, indent=1)
                _xlr("Total Payouts", cf["total_payouts"], style="total")
                if abs(_cash_chg) > 1:
                    _xlr("Cash at Stores (Net change)", _cash_chg, style="header")
                _xlr("Closing Balance", style="header")
                for k, v in cf["closing_balances"].items():
                    _xlr(f"Bank ({k})", v, indent=1)
                _xlr("Mutual Fund Balance", _cb_extra["mf"], indent=1)
                _xlr("Fixed Deposit Balance", _cb_extra["fd"], indent=1)
                _xlr("Cash at Stores", _cb_extra["cash"], indent=1)
                _xlr("Total Closing Balance", _closing_combined, style="total")
                _xlr("Net Movement", _net, style="net")
                out = io.BytesIO()
                wb.save(out)
                return out.getvalue()

            _xl_fname = (f"cashflow_{cf_entity or 'All'}_{cf_month_from}_{cf_month_to}.xlsx"
                         .replace(" ", "_").replace("/", "-"))
            st.download_button(
                "⬇️ Export Excel", _build_excel_monthly(),
                file_name=_xl_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # ─────────────────────────────────────────────────────────────────────────
    # WEEKLY VIEW
    # ─────────────────────────────────────────────────────────────────────────
    else:  # Weekly
        st.markdown(f"""
<div style="background:#1B2B4B; color:#FFFFFF; border-radius:8px;
     padding:10px 20px; margin:24px 0 8px 0; font-size:13px;
     font-weight:700; letter-spacing:0.05em;">
    WEEKLY CASH FLOW · Last 4 weeks ending {week_anchor.strftime('%d %b %Y')}
</div>
""", unsafe_allow_html=True)
        # W4 = week Mon → week_anchor (inclusive); W1-W3 = three prior complete weeks
        _days_since_mon = week_anchor.weekday()  # Mon=0 … Sun=6
        _w4_start = week_anchor - datetime.timedelta(days=_days_since_mon)
        _w4_end   = week_anchor
        _w3_end   = _w4_start - datetime.timedelta(days=1)
        _w3_start = _w3_end   - datetime.timedelta(days=6)
        _w2_end   = _w3_start - datetime.timedelta(days=1)
        _w2_start = _w2_end   - datetime.timedelta(days=6)
        _w1_end   = _w2_start - datetime.timedelta(days=1)
        _w1_start = _w1_end   - datetime.timedelta(days=6)

        def _fmt_wk(d_from, d_to):
            f = d_from if isinstance(d_from, datetime.date) else datetime.date.fromisoformat(str(d_from))
            t = d_to   if isinstance(d_to,   datetime.date) else datetime.date.fromisoformat(str(d_to))
            return f"{f.strftime('%d %b')}–{t.strftime('%d %b')}"

        _w_ranges = [
            (_w1_start, _w1_end),
            (_w2_start, _w2_end),
            (_w3_start, _w3_end),
            (_w4_start, _w4_end),
        ]
        _w_labels = [
            f"W1 {_fmt_wk(_w1_start, _w1_end)}",
            f"W2 {_fmt_wk(_w2_start, _w2_end)}",
            f"W3 {_fmt_wk(_w3_start, _w3_end)}",
            f"W4 {_fmt_wk(_w4_start, _w4_end)}",
        ]
        _w_data = [_get_cf(w[0], w[1]) for w in _w_ranges]

        # Rolling balance with DB validation
        _ro = [0.0] * 4
        _rc = [0.0] * 4
        _ro[0] = _w_data[0]["total_opening"]
        for _wi in range(4):
            _computed = _ro[_wi] + _w_data[_wi]["total_receipts"] - _w_data[_wi]["total_payouts"]
            _rc[_wi]  = _computed
            _db_close = sum(_w_data[_wi]["closing_balances"].values())
            _w_data[_wi]["computed_closing"] = _computed
            _w_data[_wi]["db_closing"]       = _db_close
            _w_data[_wi]["tally_diff"]       = round(_computed - _db_close, 2)
            if _wi < 3:
                _ro[_wi + 1] = _computed

        # Per-bank opening/closing — use actual DB balances (last balance on or before week end).
        # W(n+1) opening = W(n) actual DB closing.  No proportional approximation.
        _bank_close = {_wi: dict(_w_data[_wi]["closing_balances"]) for _wi in range(4)}
        _bank_open  = {0: dict(_w_data[0]["opening_balances"])}
        for _wi in range(3):
            _bank_open[_wi + 1] = dict(_bank_close[_wi])

        # DB-sourced totals — used for ALL header rows so they always match the detail sums.
        _ob_totals = [sum(_bank_open[_wi].values())  for _wi in range(4)]
        _cb_totals = [sum(_bank_close[_wi].values()) for _wi in range(4)]

        # MF / FD / Cash at Stores as-on each week's boundary — same as-of
        # carry-forward functions as the header banner / Summary tab.
        # Closing[n] as-on date == Opening[n+1] as-on date (day before next
        # week start == this week's end), so W1's closing figures are simply
        # reused as W2's opening, matching the per-bank chaining above.
        _mfc_close = [get_mf_fd_cash_asof(cf_entity, str(_w_ranges[_wi][1]), DATABASE_FILE)
                      for _wi in range(4)]
        _mfc_open  = {0: get_mf_fd_cash_asof(
            cf_entity, str(_w_ranges[0][0] - datetime.timedelta(days=1)), DATABASE_FILE)}
        for _wi in range(3):
            _mfc_open[_wi + 1] = _mfc_close[_wi]

        _ob_combined = [
            _ob_totals[_wi] + _mfc_open[_wi]["mf"] + _mfc_open[_wi]["fd"] + _mfc_open[_wi]["cash"]
            for _wi in range(4)
        ]
        _cb_combined = [
            _cb_totals[_wi] + _mfc_close[_wi]["mf"] + _mfc_close[_wi]["fd"] + _mfc_close[_wi]["cash"]
            for _wi in range(4)
        ]

        # Tally diffs: computed Closing TOTAL (combined) vs actual DB Closing (combined)
        # per week. MF/FD/Cash are identical carry-forward figures on both sides,
        # so this validates the same bank formula-vs-actual gap as before —
        # now against the combined total the tab actually displays.
        _db_actual_close = [
            get_closing_balance(
                entity=cf_entity,
                date_from="1900-01-01",
                date_to=str(_w_ranges[_wi][1]),
            )["total"] or 0
            for _wi in range(4)
        ]
        _db_combined_close = [
            _db_actual_close[_wi] + _mfc_close[_wi]["mf"] + _mfc_close[_wi]["fd"] + _mfc_close[_wi]["cash"]
            for _wi in range(4)
        ]
        for _wi in range(4):
            _w_data[_wi]["tally_diff"] = round(_cb_combined[_wi] - _db_combined_close[_wi], 2)

        # All unique categories across all weeks — Uncategorized always last
        _all_rec_cats = []
        for _wd in _w_data:
            for _cat in _wd["receipts"]:
                if _cat not in _all_rec_cats:
                    _all_rec_cats.append(_cat)
        _all_rec_cats = [c for c in _all_rec_cats if c != "Uncategorized"]
        if any("Uncategorized" in _wd["receipts"] for _wd in _w_data):
            _all_rec_cats.append("Uncategorized")

        _all_pay_cats = []
        for _wd in _w_data:
            for _cat in _wd["payouts"]:
                if _cat not in _all_pay_cats:
                    _all_pay_cats.append(_cat)
        _all_pay_cats = [c for c in _all_pay_cats if c != "Uncategorized"]
        if any("Uncategorized" in _wd["payouts"] for _wd in _w_data):
            _all_pay_cats.append("Uncategorized")

        # Single column layout used for every row in the weekly table
        CF_COLS = [0.04, 0.32, 0.12, 0.12, 0.12, 0.12, 0.12]
        _wk_cls = ["std", "std", "std", "std"]  # uniform week column headers

        # ── Colour palette ────────────────────────────────────────────────
        _WK_BG  = ["#F8FAFC", "#FFFFFF", "#F8FAFC", "#FFFFFF"]  # W1-W4 alternating
        _TOT_BG = "#EAF0FA"
        _SEC = {
            "opening":  {"bg": "#EAF0FA", "text": "#1B2B4B"},
            "receipts": {"bg": "#ECFDF3", "text": "#166534"},
            "payouts":  {"bg": "#FEF0F0", "text": "#991B1B"},
            "closing":  {"bg": "#EAF0FA", "text": "#1B2B4B"},
            "net_pos":  {"bg": "#ECFDF3", "text": "#166534"},
            "net_neg":  {"bg": "#FEF0F0", "text": "#991B1B"},
        }

        # ── Column header row ─────────────────────────────────────────────
        _hdr = st.columns(CF_COLS)
        with _hdr[1]:
            st.markdown(
                '<div style="font-size:13px;font-weight:700;letter-spacing:0.1em;'
                'text-transform:uppercase;color:var(--tx-4,#96A3B4);padding:6px 0;">'
                'Particulars</div>', unsafe_allow_html=True)
        for _i, _lbl in enumerate(_w_labels):
            with _hdr[_i + 2]:
                st.markdown(
                    f'<div class="cf-wk-hdr {_wk_cls[_i]}">{_lbl}</div>',
                    unsafe_allow_html=True)
        with _hdr[6]:
            st.markdown(
                '<div class="cf-wk-hdr ttl">TOTAL</div>',
                unsafe_allow_html=True)
        st.markdown(
            '<hr style="margin:2px 0;border:none;border-top:2px solid var(--blue-400,#3B82F6);">',
            unsafe_allow_html=True)

        # ── Opening Balance ───────────────────────────────────────────────
        _ob_r = st.columns(CF_COLS)
        with _ob_r[0]:
            _sign = "−" if st.session_state["wcf_ob_open"] else "+"
            if st.button(_sign, key="wbtn_ob"):
                st.session_state["wcf_ob_open"] = not st.session_state["wcf_ob_open"]
                st.rerun()
        with _ob_r[1]:
            st.markdown(
                '<div class="cf-section-label cf-ob">Opening Balance</div>',
                unsafe_allow_html=True)
        for _i in range(4):
            with _ob_r[_i + 2]:
                st.markdown(
                    f'<div class="cf-wk-val bold" style="background:{_SEC["opening"]["bg"]};'
                    f'color:{_SEC["opening"]["text"]};">{_inr(_ob_combined[_i])}</div>',
                    unsafe_allow_html=True)
        with _ob_r[6]:
            st.markdown(
                f'<div class="cf-wk-val bold" style="background:{_SEC["opening"]["bg"]};'
                f'color:{_SEC["opening"]["text"]};">{_inr(_ob_combined[0])}</div>',
                unsafe_allow_html=True)
        if st.session_state["wcf_ob_open"]:
            for _bk in sorted(_bank_open[0]):
                _br = st.columns(CF_COLS)
                with _br[1]:
                    st.markdown(f'<div class="cf-detail">Bank ({_bk})</div>',
                                unsafe_allow_html=True)
                for _i in range(4):
                    _bov = _bank_open[_i].get(_bk, 0)
                    with _br[_i + 2]:
                        _dash_cls = " dim" if not _bov else ""
                        st.markdown(
                            f'<div class="cf-wk-val{_dash_cls}">'
                            f'{_inr(_bov) if _bov else "—"}</div>',
                            unsafe_allow_html=True)
                with _br[6]:
                    st.markdown(
                        f'<div class="cf-wk-val total">'
                        f'{_inr(_bank_open[0].get(_bk, 0))}</div>',
                        unsafe_allow_html=True)
            for _label, _mfc_key in [("Mutual Fund Balance", "mf"),
                                      ("Fixed Deposit Balance", "fd"),
                                      ("Cash at Stores", "cash")]:
                _mr = st.columns(CF_COLS)
                with _mr[1]:
                    st.markdown(f'<div class="cf-detail">{_label}</div>',
                                unsafe_allow_html=True)
                for _i in range(4):
                    _mov = _mfc_open[_i][_mfc_key]
                    with _mr[_i + 2]:
                        _dash_cls = " dim" if not _mov else ""
                        st.markdown(
                            f'<div class="cf-wk-val{_dash_cls}">'
                            f'{_inr(_mov) if _mov else "—"}</div>',
                            unsafe_allow_html=True)
                with _mr[6]:
                    st.markdown(
                        f'<div class="cf-wk-val total">'
                        f'{_inr(_mfc_open[0][_mfc_key])}</div>',
                        unsafe_allow_html=True)
        st.markdown(
            '<hr class="cf-divider-sm">',
            unsafe_allow_html=True)

        # ── Add Receipts ──────────────────────────────────────────────────
        _rec_r = st.columns(CF_COLS)
        with _rec_r[0]:
            _sign = "−" if st.session_state["wcf_rec_open"] else "+"
            if st.button(_sign, key="wbtn_rec"):
                st.session_state["wcf_rec_open"] = not st.session_state["wcf_rec_open"]
                st.rerun()
        with _rec_r[1]:
            st.markdown(
                '<div class="cf-section-label cf-rec">Add Receipts</div>',
                unsafe_allow_html=True)
        for _i, _wd in enumerate(_w_data):
            with _rec_r[_i + 2]:
                st.markdown(
                    f'<div class="cf-wk-val bold" style="background:{_SEC["receipts"]["bg"]};'
                    f'color:{_SEC["receipts"]["text"]};">{_inr(_wd["total_receipts"])}</div>',
                    unsafe_allow_html=True)
        with _rec_r[6]:
            st.markdown(
                f'<div class="cf-wk-val bold" style="background:{_SEC["receipts"]["bg"]};'
                f'color:{_SEC["receipts"]["text"]};">'
                f'{_inr(sum(_wd["total_receipts"] for _wd in _w_data))}</div>',
                unsafe_allow_html=True)
        if st.session_state["wcf_rec_open"]:
            _wk_rec_nested = [_wd.get("receipts_nested", {}) for _wd in _w_data]
            _all_rec_groups = sorted(
                set(g for _wn in _wk_rec_nested for g in _wn),
                key=lambda g: sum(sum(_wn.get(g, {}).values()) for _wn in _wk_rec_nested),
                reverse=True,
            )
            for _grp in _all_rec_groups:
                _grp_key = f"wcf_grp_rec_{_grp}"
                if _grp_key not in st.session_state:
                    st.session_state[_grp_key] = False
                _wgt = [sum(_wn.get(_grp, {}).values()) for _wn in _wk_rec_nested]
                _wgt_total = sum(_wgt)
                _gr = st.columns(CF_COLS)
                with _gr[0]:
                    _gsign = "−" if st.session_state[_grp_key] else "+"
                    if st.button(_gsign, key=f"btn_{_grp_key}"):
                        st.session_state[_grp_key] = not st.session_state[_grp_key]
                        st.rerun()
                with _gr[1]:
                    st.markdown(
                        f'<div class="cf-wk-grp-lbl rec" style="padding-left:14px;">{_grp}</div>',
                        unsafe_allow_html=True)
                for _i in range(4):
                    with _gr[_i + 2]:
                        _gv = _wgt[_i]
                        st.markdown(
                            f'<div class="cf-wk-grp-val rec">{_inr(_gv) if _gv else "—"}</div>',
                            unsafe_allow_html=True)
                with _gr[6]:
                    st.markdown(f'<div class="cf-wk-grp-val rec total">{_inr(_wgt_total)}</div>',
                                unsafe_allow_html=True)
                if st.session_state[_grp_key]:
                    _cats_in_grp = sorted(
                        set(cat for _wn in _wk_rec_nested for cat in _wn.get(_grp, {})),
                        key=lambda c: sum(_wn.get(_grp, {}).get(c, 0) for _wn in _wk_rec_nested),
                        reverse=True,
                    )
                    for _cat in _cats_in_grp:
                        _is_unc = _cat == "Uncategorized"
                        _sub_cls = " unc" if _is_unc else ""
                        _cc = st.columns(CF_COLS)
                        with _cc[1]:
                            st.markdown(
                                f'<div class="cf-wk-sub-lbl{_sub_cls}" style="padding-left:32px;">'
                                f'{_cat}</div>',
                                unsafe_allow_html=True)
                        _cat_total = 0
                        for _i in range(4):
                            _amt = _wk_rec_nested[_i].get(_grp, {}).get(_cat, 0)
                            _cat_total += _amt
                            _cell_bg = _WK_BG[_i]
                            _cell_st = f"background:{_cell_bg};color:#374151;"
                            with _cc[_i + 2]:
                                st.markdown(
                                    f'<div class="cf-wk-sub-val{_sub_cls}" style="{_cell_st}">'
                                    f'{_inr(_amt) if _amt else "—"}</div>',
                                    unsafe_allow_html=True)
                        with _cc[6]:
                            st.markdown(
                                f'<div class="cf-wk-sub-val total" style="background:{_TOT_BG};">'
                                f'{_inr(_cat_total)}</div>',
                                unsafe_allow_html=True)
        st.markdown(
            '<hr class="cf-divider-sm">',
            unsafe_allow_html=True)

        # ── Less Payouts ──────────────────────────────────────────────────
        _pay_r = st.columns(CF_COLS)
        with _pay_r[0]:
            _sign = "−" if st.session_state["wcf_pay_open"] else "+"
            if st.button(_sign, key="wbtn_pay"):
                st.session_state["wcf_pay_open"] = not st.session_state["wcf_pay_open"]
                st.rerun()
        with _pay_r[1]:
            st.markdown(
                '<div class="cf-section-label cf-pay">Less Payouts</div>',
                unsafe_allow_html=True)
        for _i, _wd in enumerate(_w_data):
            with _pay_r[_i + 2]:
                st.markdown(
                    f'<div class="cf-wk-val bold" style="background:{_SEC["payouts"]["bg"]};'
                    f'color:{_SEC["payouts"]["text"]};">{_inr(_wd["total_payouts"])}</div>',
                    unsafe_allow_html=True)
        with _pay_r[6]:
            st.markdown(
                f'<div class="cf-wk-val bold" style="background:{_SEC["payouts"]["bg"]};'
                f'color:{_SEC["payouts"]["text"]};">'
                f'{_inr(sum(_wd["total_payouts"] for _wd in _w_data))}</div>',
                unsafe_allow_html=True)
        if st.session_state["wcf_pay_open"]:
            _wk_pay_nested = [_wd.get("payouts_nested", {}) for _wd in _w_data]
            _all_pay_groups = sorted(
                set(g for _wn in _wk_pay_nested for g in _wn),
                key=lambda g: sum(sum(_wn.get(g, {}).values()) for _wn in _wk_pay_nested),
                reverse=True,
            )
            for _grp in _all_pay_groups:
                _grp_key = f"wcf_grp_pay_{_grp}"
                if _grp_key not in st.session_state:
                    st.session_state[_grp_key] = False
                _wpt = [sum(_wn.get(_grp, {}).values()) for _wn in _wk_pay_nested]
                _wpt_total = sum(_wpt)
                _gr = st.columns(CF_COLS)
                with _gr[0]:
                    _gsign = "−" if st.session_state[_grp_key] else "+"
                    if st.button(_gsign, key=f"btn_{_grp_key}"):
                        st.session_state[_grp_key] = not st.session_state[_grp_key]
                        st.rerun()
                with _gr[1]:
                    st.markdown(
                        f'<div class="cf-wk-grp-lbl pay" style="padding-left:14px;">{_grp}</div>',
                        unsafe_allow_html=True)
                for _i in range(4):
                    with _gr[_i + 2]:
                        _pv = _wpt[_i]
                        st.markdown(
                            f'<div class="cf-wk-grp-val pay">{_inr(_pv) if _pv else "—"}</div>',
                            unsafe_allow_html=True)
                with _gr[6]:
                    st.markdown(f'<div class="cf-wk-grp-val pay total">{_inr(_wpt_total)}</div>',
                                unsafe_allow_html=True)
                if st.session_state[_grp_key]:
                    _cats_in_grp = sorted(
                        set(cat for _wn in _wk_pay_nested for cat in _wn.get(_grp, {})),
                        key=lambda c: sum(_wn.get(_grp, {}).get(c, 0) for _wn in _wk_pay_nested),
                        reverse=True,
                    )
                    for _cat in _cats_in_grp:
                        _is_unc = _cat == "Uncategorized"
                        _sub_cls = " unc" if _is_unc else ""
                        _cc = st.columns(CF_COLS)
                        with _cc[1]:
                            st.markdown(
                                f'<div class="cf-wk-sub-lbl{_sub_cls}" style="padding-left:32px;">'
                                f'{_cat}</div>',
                                unsafe_allow_html=True)
                        _cat_total = 0
                        for _i in range(4):
                            _amt = _wk_pay_nested[_i].get(_grp, {}).get(_cat, 0)
                            _cat_total += _amt
                            _cell_bg = _WK_BG[_i]
                            _cell_st = f"background:{_cell_bg};color:#374151;"
                            with _cc[_i + 2]:
                                st.markdown(
                                    f'<div class="cf-wk-sub-val{_sub_cls}" style="{_cell_st}">'
                                    f'{_inr(_amt) if _amt else "—"}</div>',
                                    unsafe_allow_html=True)
                        with _cc[6]:
                            st.markdown(
                                f'<div class="cf-wk-sub-val ptotal" style="background:{_TOT_BG};">'
                                f'{_inr(_cat_total)}</div>',
                                unsafe_allow_html=True)
        st.markdown(
            '<hr class="cf-divider-sm">',
            unsafe_allow_html=True)

        # ── Reconciling lines: Interbank / Intercompany / Investment net per week ─
        _WK_RECON_BG = ["#F6F8FB", "#FFFFFF", "#F6F8FB", "#FFFFFF"]
        for _recon_lbl, _recon_key, _recon_color in [
            ("Interbank (Net)",    "interbank_period_net", None),
            ("Intercompany (Net)", "intercompany_period_net", None),
        ]:
            _week_vals   = [_wd.get(_recon_key) or 0 for _wd in _w_data]
            _grand_total = sum(_week_vals)
            if any(abs(_v) > 1 for _v in _week_vals):
                _rr = st.columns(CF_COLS)
                with _rr[1]:
                    st.markdown(f'<div class="cf-recon-lbl">{_recon_lbl}</div>',
                                unsafe_allow_html=True)
                for _i, _v in enumerate(_week_vals):
                    with _rr[_i + 2]:
                        _vc = "#166534" if _v >= 0 else "#B91C1C"
                        _vd = fmt_cf(_v) if abs(_v) > 1 else "—"
                        st.markdown(
                            f'<div class="cf-recon-val" style="color:{_vc}; border-radius:0; '
                            f'background:{_WK_RECON_BG[_i]};">{_vd}</div>',
                            unsafe_allow_html=True)
                with _rr[6]:
                    _tc = "#166534" if _grand_total >= 0 else "#B91C1C"
                    st.markdown(
                        f'<div class="cf-recon-val" style="color:{_tc}; font-weight:700; '
                        f'background:#EAF0FA;">{fmt_cf(_grand_total)}</div>',
                        unsafe_allow_html=True)

        # ── Cash at Stores (Net change) per week ─────────────────────────
        _wk_cash_chg = [_mfc_close[_wi]["cash"] - _mfc_open[_wi]["cash"] for _wi in range(4)]
        if any(abs(_v) > 1 for _v in _wk_cash_chg):
            _cr_ = st.columns(CF_COLS)
            with _cr_[1]:
                st.markdown('<div class="cf-recon-lbl">Cash at Stores (Net change)</div>',
                            unsafe_allow_html=True)
            for _i, _v in enumerate(_wk_cash_chg):
                with _cr_[_i + 2]:
                    _vc = "#166534" if _v >= 0 else "#B91C1C"
                    st.markdown(
                        f'<div class="cf-recon-val" style="color:{_vc}; border-radius:0; '
                        f'background:{_WK_RECON_BG[_i]};">{fmt_cf(_v) if abs(_v) > 1 else "—"}</div>',
                        unsafe_allow_html=True)
            with _cr_[6]:
                _tcc = sum(_wk_cash_chg)
                st.markdown(
                    f'<div class="cf-recon-val" style="color:{"#166534" if _tcc >= 0 else "#B91C1C"}; '
                    f'font-weight:700; background:#EAF0FA;">{fmt_cf(_tcc)}</div>',
                    unsafe_allow_html=True)

        # ── Closing Balance ───────────────────────────────────────────────
        _cb_r = st.columns(CF_COLS)
        with _cb_r[0]:
            _sign = "−" if st.session_state["wcf_cb_open"] else "+"
            if st.button(_sign, key="wbtn_cb"):
                st.session_state["wcf_cb_open"] = not st.session_state["wcf_cb_open"]
                st.rerun()
        with _cb_r[1]:
            st.markdown(
                '<div class="cf-section-label cf-cb">Closing Balance</div>',
                unsafe_allow_html=True)
        for _i in range(4):
            with _cb_r[_i + 2]:
                st.markdown(
                    f'<div class="cf-wk-val bold" style="background:{_SEC["closing"]["bg"]};'
                    f'color:{_SEC["closing"]["text"]};">{_inr(_cb_combined[_i])}</div>',
                    unsafe_allow_html=True)
        with _cb_r[6]:
            st.markdown(
                f'<div class="cf-wk-val bold" style="background:{_SEC["closing"]["bg"]};'
                f'color:{_SEC["closing"]["text"]};">{_inr(_cb_combined[3])}</div>',
                unsafe_allow_html=True)
        if st.session_state["wcf_cb_open"]:
            for _bk in sorted(_bank_close[0]):
                _cbr = st.columns(CF_COLS)
                with _cbr[1]:
                    st.markdown(f'<div class="cf-detail">Bank ({_bk})</div>',
                                unsafe_allow_html=True)
                for _i in range(4):
                    _bcv = _bank_close[_i].get(_bk, 0)
                    with _cbr[_i + 2]:
                        _d2 = " dim" if not _bcv else ""
                        st.markdown(
                            f'<div class="cf-wk-val{_d2}">'
                            f'{_inr(_bcv) if _bcv else "—"}</div>',
                            unsafe_allow_html=True)
                with _cbr[6]:
                    st.markdown(
                        f'<div class="cf-wk-val bold total">'
                        f'{_inr(_bank_close[3].get(_bk, 0))}</div>',
                        unsafe_allow_html=True)
            for _label, _mfc_key in [("Mutual Fund Balance", "mf"),
                                      ("Fixed Deposit Balance", "fd"),
                                      ("Cash at Stores", "cash")]:
                _mcr = st.columns(CF_COLS)
                with _mcr[1]:
                    st.markdown(f'<div class="cf-detail">{_label}</div>',
                                unsafe_allow_html=True)
                for _i in range(4):
                    _mcv = _mfc_close[_i][_mfc_key]
                    with _mcr[_i + 2]:
                        _d2 = " dim" if not _mcv else ""
                        st.markdown(
                            f'<div class="cf-wk-val{_d2}">'
                            f'{_inr(_mcv) if _mcv else "—"}</div>',
                            unsafe_allow_html=True)
                with _mcr[6]:
                    st.markdown(
                        f'<div class="cf-wk-val bold total">'
                        f'{_inr(_mfc_close[3][_mfc_key])}</div>',
                        unsafe_allow_html=True)
        st.markdown(
            '<hr class="cf-divider-sm">',
            unsafe_allow_html=True)

        # ── Net Movement per week — always visible ───────────────────
        _wnet_r = st.columns(CF_COLS)
        with _wnet_r[1]:
            st.markdown(
                '<div class="cf-wk-net-label">NET MOVEMENT</div>',
                unsafe_allow_html=True)
        # NET MOVEMENT = new Closing Balance TOTAL minus new Opening Balance
        # TOTAL, per week (each TOTAL = Bank + Mutual Fund + Fixed Deposit + Cash).
        _wnet_vals  = [_cb_combined[_wi] - _ob_combined[_wi] for _wi in range(4)]
        _total_wnet = sum(_wnet_vals)
        for _i, _wn in enumerate(_wnet_vals):
            _wn_sec = "net_pos" if _wn >= 0 else "net_neg"
            with _wnet_r[_i + 2]:
                st.markdown(
                    f'<div class="cf-wk-val bold" style="background:{_SEC[_wn_sec]["bg"]};'
                    f'color:{_SEC[_wn_sec]["text"]};font-weight:700;">'
                    f'{_inr(_wn)}</div>', unsafe_allow_html=True)
        _tn_sec = "net_pos" if _total_wnet >= 0 else "net_neg"
        with _wnet_r[6]:
            st.markdown(
                f'<div class="cf-wk-val bold" style="background:{_SEC[_tn_sec]["bg"]};'
                f'color:{_SEC[_tn_sec]["text"]};font-weight:700;">'
                f'{_inr(_total_wnet)}</div>', unsafe_allow_html=True)
        st.markdown(
            '<hr style="margin:2px 0;border:none;border-top:3px solid var(--blue-400,#3B82F6);">',
            unsafe_allow_html=True)

        # ── Tally per week — computed vs DB ──────────────────────────────
        _tally_r = st.columns(CF_COLS)
        with _tally_r[1]:
            st.markdown(
                '<div class="cf-wk-tally-label">Tally (Computed vs DB)</div>',
                unsafe_allow_html=True)
        for _wi in range(4):
            _tdif = _w_data[_wi]["tally_diff"]
            _tok  = abs(_tdif) <= 1
            _tic  = "✅" if _tok else "⚠️"
            _tip  = "Tallied" if _tok else fmt_inr(abs(_tdif))
            _tbg_t = "var(--green-50,#F0FDF4)" if _tok else "var(--amber-50,#FFFBEB)"
            with _tally_r[_wi + 2]:
                st.markdown(
                    f'<div style="text-align:center;padding:3px 2px;background:{_tbg_t};'
                    f'border-radius:4px;font-size:13px;" title="{_tip}">{_tic}</div>',
                    unsafe_allow_html=True)
        _total_tdif = round(_cb_combined[3] - _db_combined_close[3], 2)
        with _tally_r[6]:
            _gt_ok  = abs(_total_tdif) <= 1
            _gt_tip = "Tallied" if _gt_ok else fmt_inr(abs(_total_tdif))
            _gt_bg  = "var(--green-50,#F0FDF4)" if _gt_ok else "var(--amber-50,#FFFBEB)"
            st.markdown(
                f'<div style="text-align:center;padding:3px 2px;background:{_gt_bg};'
                f'border-radius:4px;font-size:13px;" title="{_gt_tip}">'
                f'{"✅" if _gt_ok else "⚠️"}</div>',
                unsafe_allow_html=True)

        # ── Excel export (same rows as the table above, every group expanded) ─
        def _build_excel_weekly():
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            wb = Workbook()
            ws = wb.active
            ws.title = "Weekly Cash Flow"
            ws.column_dimensions["A"].width = 46
            for _c in "BCDEF":
                ws.column_dimensions[_c].width = 22
            h_fill = PatternFill("solid", fgColor="F1F3F5")
            t_fill = PatternFill("solid", fgColor="E8F4FD")
            ws.append(["Particulars"] + _w_labels + ["Total"])
            for cell in ws[1]:
                cell.font = Font(bold=True, size=10, color="9CA3AF")
                cell.fill = h_fill
                cell.alignment = Alignment(horizontal="right" if cell.column > 1 else "left")

            def _xw(label, vals=None, total=None, style="normal", indent=0):
                row = [("  " * indent) + label]
                row += list(vals) if vals is not None else [None] * 4
                row += [total]
                ws.append(row)
                r = ws.max_row
                for c in range(2, 7):
                    ws.cell(row=r, column=c).alignment = Alignment(horizontal="right")
                    ws.cell(row=r, column=c).number_format = "#,##0;-#,##0"
                if style == "header":
                    for c in ws[r]:
                        c.font = Font(bold=True, size=11)
                        c.fill = h_fill
                elif style == "total":
                    for c in ws[r]:
                        c.font = Font(bold=True, color="1E3A5F")
                        c.fill = t_fill
                        c.border = Border(top=Side(style="medium", color="4E8DF5"),
                                          bottom=Side(style="medium", color="4E8DF5"))
                elif style == "group":
                    for c in ws[r]:
                        c.font = Font(bold=True)
                elif style == "net":
                    pos = (total or 0) >= 0
                    for c in ws[r]:
                        c.font = Font(bold=True, size=12, color="2E7D32" if pos else "C62828")
                        c.fill = PatternFill("solid", fgColor="F0FDF4" if pos else "FEF2F2")

            def _balance_block(title, combined, banks, mfc, last):
                _xw(title, combined, combined[last], style="header")
                for _bk in sorted(banks[0]):
                    _v = [banks[i].get(_bk, 0) for i in range(4)]
                    _xw(f"Bank ({_bk})", _v, _v[last], indent=1)
                for _lbl, _k in (("Mutual Fund Balance", "mf"), ("Fixed Deposit Balance", "fd"),
                                 ("Cash at Stores", "cash")):
                    _v = [mfc[i][_k] for i in range(4)]
                    _xw(_lbl, _v, _v[last], indent=1)

            def _flow_block(title, total_key, nested_key):
                _tot = [_wd[total_key] for _wd in _w_data]
                _xw(title, _tot, sum(_tot), style="total")
                _nested = [_wd.get(nested_key, {}) for _wd in _w_data]
                _groups = sorted(set(g for _n in _nested for g in _n),
                                 key=lambda g: sum(sum(_n.get(g, {}).values()) for _n in _nested), reverse=True)
                for _g in _groups:
                    _gv = [sum(_n.get(_g, {}).values()) for _n in _nested]
                    _xw(_g, _gv, sum(_gv), style="group", indent=1)
                    _cats = sorted(set(c for _n in _nested for c in _n.get(_g, {})),
                                   key=lambda c: sum(_n.get(_g, {}).get(c, 0) for _n in _nested), reverse=True)
                    for _c in _cats:
                        _cv = [_n.get(_g, {}).get(_c, 0) for _n in _nested]
                        _xw(_c, _cv, sum(_cv), indent=2)

            # Opening: first week's opening is the period opening
            _balance_block("Opening Balance", _ob_combined, _bank_open, _mfc_open, 0)
            _flow_block("Add Receipts", "total_receipts", "receipts_nested")
            _flow_block("Less Payouts", "total_payouts", "payouts_nested")
            for _lbl, _k in (("Interbank (Net)", "interbank_period_net"),
                             ("Intercompany (Net)", "intercompany_period_net")):
                _v = [_wd.get(_k) or 0 for _wd in _w_data]
                if any(abs(x) > 1 for x in _v):
                    _xw(_lbl, _v, sum(_v), style="header")
            _cc = [_mfc_close[i]["cash"] - _mfc_open[i]["cash"] for i in range(4)]
            if any(abs(x) > 1 for x in _cc):
                _xw("Cash at Stores (Net change)", _cc, sum(_cc), style="header")
            _balance_block("Closing Balance", _cb_combined, _bank_close, _mfc_close, 3)
            _xw("Net Movement", _wnet_vals, _total_wnet, style="net")
            _xw("Tally difference (computed vs DB)", [_w_data[i]["tally_diff"] for i in range(4)], None)
            out = io.BytesIO()
            wb.save(out)
            return out.getvalue()

        _, _wxl = st.columns([8.5, 1.5])
        with _wxl:
            _wxl_name = (f"weekly_cashflow_{cf_entity or 'All'}_{_w1_start}_{_w4_end}.xlsx"
                         .replace(" ", "_").replace("/", "-"))
            st.download_button(
                "⬇️ Export Excel", _build_excel_weekly(), file_name=_wxl_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, key="dl_weekly_cf")

# ══════════════════════════════════════════════════════════════════════════════
# INVESTMENTS
# ══════════════════════════════════════════════════════════════════════════════
elif selected_tab == "Investments":

    render_investment_header()

    # Use sidebar date range if set, else default to full history
    if use_date_range and sel_date_from and sel_date_to:
        inv_date_from = str(sel_date_from)
        inv_date_to   = str(sel_date_to)
    else:
        inv_date_from = None
        inv_date_to   = None

    # ── Get data ──────────────────────────────────────────────────────────────
    entity_filter = eff_entity
    inv_data = get_investment_summary(
        entity=entity_filter,
        date_from=inv_date_from,
        date_to=inv_date_to,
    )

    fds = [r for r in inv_data if r["scheme_type"] == "FD"]
    mfs = [r for r in inv_data if r["scheme_type"] == "MF"]

    if st.session_state.get("inv_flash"):
        st.success(st.session_state.pop("inv_flash"))

    # ── Management view: balance, gains, ROI, FD vs Mutual Fund ───────────────
    # Period: date range > month > financial year (all from the sidebar)
    if use_date_range:
        _w0, _w1 = str(sel_date_from), str(sel_date_to)
        _wl = f"{sel_date_from.strftime('%d %b %Y')} to {sel_date_to.strftime('%d %b %Y')}"
    elif eff_month:
        _my, _mm = int(eff_month[:4]), int(eff_month[5:7])
        _w0 = f"{_my}-{_mm:02d}-01"
        _w1 = str(datetime.date(_my + (_mm == 12), _mm % 12 + 1, 1) - datetime.timedelta(days=1))
        _wl = datetime.date(_my, _mm, 1).strftime("%b %Y")
    else:
        _w0, _w1 = str(FY_BOUNDS[sel_fy][0]), str(FY_BOUNDS[sel_fy][1])
        _wl = sel_fy_label
    render_investment_overview(entity_filter, as_of_date, _w0, _w1, _wl)

    st.markdown("---")
    st.markdown('<div class="section-header" style="margin:6px 0 10px;">Details &amp; Data Entry</div>',
                unsafe_allow_html=True)

    # ── Import from Excel ─────────────────────────────────────────────────────
    with st.expander("📥 Import Investments from Excel", expanded=False):
        _dl_col, _up_col = st.columns([1, 2])
        with _dl_col:
            import io as _io
            import pandas as _pde
            _tmpl_df = _pde.DataFrame(columns=[
                "Date", "Scheme Name", "Scheme Number",
                "Type", "Amount", "Entry Type", "Entity",
            ])
            _tmpl_buf = _io.BytesIO()
            _tmpl_df.to_excel(_tmpl_buf, index=False)
            _tmpl_buf.seek(0)
            st.download_button(
                "⬇ Download Template",
                data=_tmpl_buf,
                file_name="investment_import_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with _up_col:
            _inv_upload = st.file_uploader(
                "Upload filled Excel",
                type=["xlsx", "xls"],
                key="inv_excel_upload",
            )
            if _inv_upload is not None:
                if st.button("📤 Import", key="inv_do_import", use_container_width=True):
                    import tempfile as _tf, os as _osi
                    with _tf.NamedTemporaryFile(delete=False, suffix=".xlsx") as _tmp:
                        _tmp.write(_inv_upload.getvalue())
                        _tmp_path = _tmp.name
                    _result = import_investment_excel(_tmp_path)
                    try:
                        _osi.unlink(_tmp_path)
                    except Exception:
                        pass
                    if _result["errors"] == 0 and _result["skipped"] == 0:
                        st.success(f"Imported {_result['inserted']} rows successfully.")
                    else:
                        st.warning(
                            f"Inserted: {_result['inserted']} · "
                            f"Skipped: {_result['skipped']} · "
                            f"Errors: {_result['errors']}"
                        )
                        for _err in _result["error_rows"][:10]:
                            st.caption(_err)
                    if _result["inserted"] > 0:
                        st.cache_data.clear()
                        try:
                            st.rerun()
                        except AttributeError:
                            st.experimental_rerun()

    # ── Scheme-wise balances (FD and MF separately) ──────────────────────────
    st.markdown('<div class="section-header" style="margin-bottom:10px;">Investment Portfolio — Scheme-wise Balance</div>',
                unsafe_allow_html=True)

    _inv_asof = str(sel_date_to) if (use_date_range and sel_date_to) else None
    _ev_all = pd.DataFrame(get_investment_events(entity_filter))
    if _ev_all.empty:
        st.info("No investment data found.")
    else:
        _ev_all["scheme_key"] = (_ev_all["scheme_type"] + "||" + _ev_all["scheme_name"]
                                 + "||" + _ev_all["entity"])
        _ev_asof = _ev_all[_ev_all["date"].isna()
                           | (_ev_all["date"] <= (_inv_asof or "9999-12-31"))]
        st.caption(f"Balance as on {_inv_asof or 'latest'} — Opening + Invested − Redeemed. "
                   "Bank-tagged and manual entries are combined per scheme. "
                   "Untagged bank investment transactions are listed under FD as 'Untagged'.")

        _rows_by_type = {"FD": [], "MF": []}
        for (_stype, _sname, _sent), _g in _ev_asof.groupby(
                ["scheme_type", "scheme_name", "entity"]):
            if _stype not in _rows_by_type:
                continue
            _op  = _g.loc[_g["source"] == "Opening", "delta"].sum()
            _mv  = _g[_g["source"] != "Opening"]
            _inv = _mv.loc[_mv["delta"] > 0, "delta"].sum()
            _red = -_mv.loc[_mv["delta"] < 0, "delta"].sum()
            _rows_by_type[_stype].append({
                "Scheme": _sname, "Entity": _sent,
                "Opening (₹)": _op, "Invested (₹)": _inv,
                "Redeemed (₹)": _red, "Balance (₹)": _op + _inv - _red,
            })

        for _stype, _title in (("FD", "Fixed Deposits"), ("MF", "Mutual Funds")):
            st.markdown(f"##### {_title}")
            _rws = _rows_by_type[_stype]
            if not _rws:
                st.info(f"No {_title} found.")
                continue
            _dfp = pd.DataFrame(_rws).sort_values("Balance (₹)", ascending=False)
            _tot = _dfp["Balance (₹)"].sum()
            _show = _dfp.copy()
            for _c in ["Opening (₹)", "Invested (₹)", "Redeemed (₹)", "Balance (₹)"]:
                _show[_c] = _show[_c].apply(fmt_inr)
            st.dataframe(_show, use_container_width=True, hide_index=True,
                         column_config=amount_config(
                             ["Opening (₹)", "Invested (₹)", "Redeemed (₹)", "Balance (₹)"]))
            st.markdown(f"""
<div style="background:#1B2B4B;color:#FFFFFF;border-radius:8px;
     padding:10px 20px;display:flex;justify-content:space-between;margin:4px 0 14px;">
    <b>TOTAL {_title.upper()}</b><b>{fmt_inr(_tot)}</b>
</div>""", unsafe_allow_html=True)

        # ── Day-wise running balance ─────────────────────────────────────────
        st.markdown('<div class="section-header" style="margin:18px 0 10px;">Day-wise Investment Value</div>',
                    unsafe_allow_html=True)
        st.caption("Running balance (Opening + cumulative Invested − Redeemed) on each date that had a "
                   "movement. Select a row to see the scheme-wise split for that date.")
        _dated = _ev_all[_ev_all["date"].notna()]
        if _dated.empty:
            st.info("No dated investment movements yet.")
        else:
            _base = _ev_all[_ev_all["date"].isna()].groupby("scheme_key")["delta"].sum()
            _piv = (_dated.groupby(["date", "scheme_key"])["delta"].sum()
                    .unstack(fill_value=0).sort_index())
            _piv = _piv.reindex(columns=sorted(set(_piv.columns) | set(_base.index)), fill_value=0)
            _cum = _piv.cumsum().add(_base.reindex(_piv.columns, fill_value=0), axis=1)
            _is_fd = [k.split("||")[0] == "FD" for k in _cum.columns]
            _is_mf = [k.split("||")[0] == "MF" for k in _cum.columns]
            _daily = pd.DataFrame({
                "Date": _cum.index,
                "FD Balance": _cum.loc[:, _is_fd].sum(axis=1).values,
                "MF Balance": _cum.loc[:, _is_mf].sum(axis=1).values,
            })
            _daily["Total"] = _daily["FD Balance"] + _daily["MF Balance"]

            if use_date_range and sel_date_from and sel_date_to:
                _daily = _daily[(_daily["Date"] >= str(sel_date_from))
                                & (_daily["Date"] <= str(sel_date_to))]
            _daily = _daily.sort_values("Date", ascending=False).reset_index(drop=True)

            if _daily.empty:
                st.info("No investment movements in the selected date range.")
            else:
                _fig_d = go.Figure()
                _dchart = _daily.sort_values("Date")
                for _col, _clr in (("FD Balance", "#1B2B4B"), ("MF Balance", "#7C3AED")):
                    _fig_d.add_trace(go.Scatter(
                        x=_dchart["Date"], y=_dchart[_col] / 1e7, name=_col,
                        mode="lines+markers", line=dict(color=_clr, width=2, shape="hv"),
                        hovertemplate="%{x}<br>₹%{y:.2f} Cr<extra>" + _col + "</extra>"))
                _fig_d.update_layout(
                    height=280, plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                    font=dict(family="Inter", size=11), legend=dict(orientation="h", y=1.12),
                    xaxis=dict(showgrid=False),
                    yaxis=dict(showgrid=True, gridcolor="#F0F0F0", ticksuffix=" Cr"),
                    margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(_fig_d, use_container_width=True)

                _dshow = _daily.copy()
                for _c in ["FD Balance", "MF Balance", "Total"]:
                    _dshow[_c] = _dshow[_c].apply(fmt_inr)
                _sel = st.dataframe(
                    _dshow, use_container_width=True, hide_index=True, height=300,
                    column_config=amount_config(["FD Balance", "MF Balance", "Total"]),
                    on_select="rerun", selection_mode="single-row", key="inv_daily_sel")

                if _sel.selection.rows:
                    _d_pick = _daily.iloc[_sel.selection.rows[0]]["Date"]
                    _day_mv = _piv.loc[_d_pick]
                    _det = []
                    for _k in _cum.columns:
                        _stype, _sname, _sent = _k.split("||")
                        _bal = _cum.loc[_d_pick, _k]
                        if _bal == 0 and _day_mv[_k] == 0:
                            continue
                        _det.append({"Type": _stype, "Scheme": _sname, "Entity": _sent,
                                     "Movement on day (₹)": fmt_inr(_day_mv[_k]),
                                     "Balance (₹)": fmt_inr(_bal)})
                    st.markdown(f"##### Scheme-wise balance on {_d_pick}")
                    if _det:
                        st.dataframe(pd.DataFrame(_det).sort_values(["Type", "Scheme"]),
                                     use_container_width=True, hide_index=True,
                                     column_config=amount_config(
                                         ["Movement on day (₹)", "Balance (₹)"]))
                    else:
                        st.info("No scheme balances on this date.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Manage Schemes & Opening Values ──────────────────────────────────────
    with st.expander("⚙️ Manage Schemes & Opening Values", expanded=False):
        st.caption(
            "Set the amount held in each scheme and the date it was invested (shown on the Summary tab). "
            "These are saved permanently in the database.")

        all_schemes = get_investment_register()

        st.markdown("##### Update Opening Values")
        for _scheme in all_schemes:
            _ec1, _ec2, _ec3, _ec3b, _ec4 = st.columns([2, 1.6, 1.4, 1.6, 1])
            with _ec1:
                st.markdown(
                    f'<div style="padding-top:8px;font-weight:600;">'
                    f'{_scheme["scheme_name"]} '
                    f'<span style="color:#8896A5;font-size:11px;">'
                    f'({_scheme["scheme_type"]} · {_scheme["entity"]})'
                    f'</span></div>', unsafe_allow_html=True)
            with _ec2:
                _new_val = st.number_input(
                    "Opening Value (₹)",
                    value=float(_scheme["opening_value"] or 0),
                    min_value=0.0,
                    step=10000.0,
                    key=f"ov_{_scheme['scheme_name']}",
                    label_visibility="collapsed")
            with _ec3:
                _new_ent = st.selectbox(
                    "Entity",
                    ["Stores", "Ventures"],
                    index=0 if _scheme["entity"] == "Stores" else 1,
                    key=f"ent_{_scheme['scheme_name']}",
                    label_visibility="collapsed")
            with _ec3b:
                try:
                    _od0 = datetime.date.fromisoformat(str(_scheme["opening_date"])[:10])
                except Exception:
                    _od0 = datetime.date(2026, 4, 1)
                _new_od = st.date_input(
                    "Invested on", value=_od0, format="DD/MM/YYYY",
                    key=f"od_{_scheme['scheme_name']}", label_visibility="collapsed")
            with _ec4:
                if st.button("💾 Save", key=f"save_{_scheme['scheme_name']}"):
                    update_investment_opening(
                        _scheme["scheme_name"], _new_val,
                        str(_new_od), _new_ent)
                    st.cache_data.clear()
                    st.success(f"Saved {_scheme['scheme_name']}")
                    st.rerun()

        st.markdown("---")
        st.markdown("##### Add New Scheme")
        _na1, _na2, _na3, _na4, _na4b, _na5 = st.columns([2, 1, 1, 1.6, 1.4, 1])
        with _na1:
            _new_name = st.text_input(
                "Scheme Name", placeholder="e.g. FD-5 or MF-Scheme-4",
                key="new_scheme_name")
        with _na2:
            _new_type = st.selectbox("Type", ["FD", "MF"], key="new_scheme_type")
        with _na3:
            _new_ent2 = st.selectbox(
                "Entity", ["Stores", "Ventures"], key="new_scheme_entity")
        with _na4:
            _new_opening = st.number_input(
                "Opening Value (₹)", min_value=0.0,
                step=10000.0, key="new_scheme_opening")
        with _na4b:
            _new_od2 = st.date_input("Invested on", value=datetime.date.today(),
                                     format="DD/MM/YYYY", key="new_scheme_date")
        with _na5:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Add", key="add_scheme_btn"):
                if _new_name.strip():
                    add_investment_scheme(
                        _new_name.strip(), _new_type,
                        _new_ent2, _new_opening, str(_new_od2))
                    st.cache_data.clear()
                    st.success(f"Added {_new_name}")
                    st.rerun()
                else:
                    st.warning("Enter a scheme name first.")

        st.markdown("---")
        st.markdown("##### Remove a Scheme")
        _del_options = [s["scheme_name"] for s in all_schemes]
        _del_c1, _del_c2 = st.columns([3, 1])
        with _del_c1:
            _del_scheme = st.selectbox(
                "Select scheme to remove",
                _del_options, key="del_scheme_select")
        with _del_c2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ Remove", key="del_scheme_btn"):
                delete_investment_scheme(_del_scheme)
                st.cache_data.clear()
                st.success(f"Removed {_del_scheme}")
                st.rerun()

    # ── Manual FD/MF Entry ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Add Manual FD / MF Entry")
    st.caption("Add investments or redemptions not captured in bank statements.")

    with st.form("manual_inv_form", clear_on_submit=True):
        _mf1, _mf2, _mf3 = st.columns(3)
        with _mf1:
            _mi_date = st.date_input(
                "Date", value=datetime.date.today(),
                key="mi_date", format="DD/MM/YYYY")
            _mi_type = st.selectbox("Type (FD/MF)", ["FD", "MF"], key="mi_type")
        with _mf2:
            _mi_scheme = st.text_input(
                "Scheme Name",
                placeholder="e.g. SBI FD, HDFC Flexi Cap",
                key="mi_scheme")
            _mi_entity = st.selectbox(
                "Entity", ["Stores", "Ventures"], key="mi_entity")
        with _mf3:
            _mi_amount = st.number_input(
                "Amount (₹)", min_value=0.0, step=10000.0, key="mi_amount")
            _mi_entry_type = st.selectbox(
                "Invested / Redeemed", ["Invested", "Redeemed"],
                key="mi_entry_type")

        _known_schemes = sorted({e["scheme_name"] for e in get_manual_investments()
                                 if e["scheme_type"] == "MF"} |
                                {o["scheme_name"] for o in get_opening_lots()})
        _mi_pick = st.selectbox(
            "Existing mutual fund scheme (optional — avoids spelling mismatches for FIFO)",
            ["— type a new name above —"] + _known_schemes, key="mi_pick")

        _mu1, _mu2 = st.columns(2)
        with _mu1:
            _mi_units = st.number_input(
                "Units (mutual funds)", min_value=0.0, step=1.0, format="%.3f", key="mi_units",
                help="Fill Units and NAV for mutual funds: the amount is calculated and a redemption is "
                     "matched to the oldest purchases (FIFO) to give cost and capital gain.")
        with _mu2:
            _mi_nav = st.number_input(
                "NAV (₹)", min_value=0.0, step=1.0, format="%.4f", key="mi_nav")
        st.caption("Mutual funds: enter Units and NAV (Amount is then ignored). "
                   "FDs, or entries without units: enter the Amount only.")

        _mi_notes = st.text_input(
            "Notes (optional)",
            placeholder="Maturity date, interest rate etc.",
            key="mi_notes")

        if st.form_submit_button("Save Entry"):
            _mi_name = (_mi_pick if _mi_pick in _known_schemes and not _mi_scheme.strip()
                        else _mi_scheme.strip())
            _use_units = _mi_type == "MF" and _mi_units > 0 and _mi_nav > 0
            if not _mi_name:
                st.error("Scheme Name is required.")
            elif _mi_type == "MF" and ((_mi_units > 0) != (_mi_nav > 0)):
                st.error("Enter both Units and NAV (or leave both empty and enter an Amount).")
            elif not _use_units and _mi_amount <= 0:
                st.error("Amount must be greater than 0.")
            else:
                _new_id = add_manual_investment(
                    entry_date  = str(_mi_date),
                    scheme_name = _mi_name,
                    scheme_type = _mi_type,
                    amount      = (_mi_units * _mi_nav) if _use_units else _mi_amount,
                    entry_type  = _mi_entry_type,
                    entity      = _mi_entity,
                    notes       = _mi_notes.strip(),
                    units       = _mi_units if _use_units else None,
                    nav         = _mi_nav if _use_units else None,
                )
                _msg = (f"{_mi_entry_type} {fmt_inr(_mi_units * _mi_nav if _use_units else _mi_amount)} in "
                        f"{_mi_name} ({_mi_type}) saved.")
                if _use_units and _mi_entry_type == "Redeemed":
                    _fres = compute_fifo(_mi_entity)
                    _mine = [l for l in _fres["closed"] if l["entry_id"] == _new_id]
                    _cost = sum(l["units_sold"] * l["purchase_nav"] for l in _mine)
                    _proc = sum(l["units_sold"] * l["sale_nav"] for l in _mine)
                    _short = [u for u in _fres["unmatched"] if u["entry_id"] == _new_id]
                    _msg += (f" FIFO: matched {len(_mine)} lot(s), cost {fmt_inr(_cost)}, "
                             f"proceeds {fmt_inr(_proc)}, capital gain {fmt_inr(_proc - _cost)}.")
                    if _short:
                        _msg += (f" ⚠️ {_short[0]['units_short']:,.3f} units had no matching purchase — "
                                 f"load your open holdings under Capital gain data & setup.")
                st.session_state["inv_flash"] = _msg
                st.cache_data.clear()
                st.rerun()

    st.markdown("#### Manual Entry History")
    _manual_entries = get_manual_investments()
    if not _manual_entries:
        st.info("No manual entries yet.")
    else:
        for _me in _manual_entries:
            _me_color = "#16A34A" if _me["entry_type"] == "Invested" else "#DC2626"
            _me_cols  = st.columns([1.5, 2.5, 1, 1, 2, 1.5, 0.6])
            for _col, _val in zip(_me_cols[:6], [
                _me["entry_date"],
                _me["scheme_name"],
                _me["scheme_type"],
                _me["entity"],
                f'<b style="color:{_me_color};">'
                f'{_me["entry_type"]}: {fmt_inr(_me["amount"])}</b>',
                ((f'{_me["units"]:,.3f} units @ ₹{_me["nav"]:,.4f}'
                  + (f' · {_me["notes"]}' if _me["notes"] else ""))
                 if _me.get("units") else (_me["notes"] or "—")),
            ]):
                with _col:
                    st.markdown(
                        f'<div style="font-size:12px;padding:4px 0;">{_val}</div>',
                        unsafe_allow_html=True)
            with _me_cols[6]:
                if st.button("🗑️", key=f"del_mi_{_me['id']}",
                             help="Delete this entry"):
                    delete_manual_investment(_me["id"])
                    st.cache_data.clear()
                    st.rerun()

        st.markdown("---")
        st.markdown("#### Manual Entry Summary by Scheme")
        _mi_totals = get_manual_investment_totals()
        for _mt in _mi_totals:
            _mt_net   = (_mt["invested"] or 0) - (_mt["redeemed"] or 0)
            _mt_color = "#16A34A" if _mt_net >= 0 else "#DC2626"
            st.markdown(f"""
<div style="background:#FFFFFF;border-radius:8px;padding:12px 16px;
     border:1px solid #E8ECF0;margin:6px 0;
     display:flex;justify-content:space-between;align-items:center;">
    <div>
        <b style="font-size:13px;">{_mt['scheme_name']}</b>
        <span style="font-size:11px;color:#8896A5;margin-left:8px;">
            {_mt['scheme_type']} · {_mt['entity']}
        </span>
    </div>
    <div style="text-align:right;">
        <span style="font-size:12px;color:#4A5568;">
            Invested: {fmt_inr(_mt['invested'])} | Redeemed: {fmt_inr(_mt['redeemed'])}
        </span><br>
        <b style="font-size:13px;color:{_mt_color};">Net: {fmt_inr(_mt_net)}</b>
    </div>
</div>""", unsafe_allow_html=True)

    # ── Cash at Stores — date-aware entry (Entity-selectable) ────────────────
    st.markdown("#### 💵 Cash at Stores")

    cash_cols = st.columns([1, 1.3, 1, 1, 1])

    with cash_cols[0]:
        cash_entity_pick = st.selectbox(
            "Entity", ["Stores", "Ventures"], key="cash_entity_pick"
        )

    with cash_cols[1]:
        entry_date_pick = st.date_input(
            "Date", value=_today,
            key="cash_entry_date", format="DD/MM/YYYY"
        )

    current_val = get_cash_asof(cash_entity_pick, str(entry_date_pick))

    with cash_cols[2]:
        st.markdown(f"""
    <div style="background:#FFFFFF; border-radius:10px;
         padding:12px 16px; border:1px solid #E8ECF0;
         border-top:3px solid #1B2B4B;">
        <div style="font-size:10px; font-weight:700; color:#8896A5;
             text-transform:uppercase; margin-bottom:4px;">
            {cash_entity_pick.upper()} · {entry_date_pick.strftime('%d %b %Y')}</div>
        <div style="font-size:18px; font-weight:700; color:#1B2B4B;">
            {fmt_inr(current_val)}</div>
    </div>
    """, unsafe_allow_html=True)

    with cash_cols[3]:
        new_cash = st.number_input(
            "New Value (₹)", min_value=0.0, step=10000.0,
            value=float(current_val or 0), key="cash_input_v2"
        )

    with cash_cols[4]:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save", key="save_cash_v2"):
            set_cash_entry(cash_entity_pick, str(entry_date_pick), new_cash)
            st.success(
                f"✅ {cash_entity_pick} cash for {entry_date_pick.strftime('%d %b %Y')} "
                f"set to {fmt_inr(new_cash)}")
            st.cache_data.clear()
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Cash at Stores — audit trail (entity-filterable) ─────────────────────
    st.markdown("##### 📋 Cash at Stores — History")

    hist_entity_filter = st.selectbox(
        "Filter by entity", ["All", "Stores", "Ventures"],
        key="cash_hist_entity_filter"
    )

    cash_hist = get_cash_history(
        hist_entity_filter if hist_entity_filter != "All" else None
    )

    if not cash_hist:
        st.info("No entries yet.")
    else:
        for h in cash_hist[:30]:
            h_cols = st.columns([1, 1.3, 1.7, 1.3, 0.8])
            with h_cols[0]:
                st.markdown(
                    f'<div style="font-size:12px; padding:4px 0;">'
                    f'<span style="background:#EBF4FF; padding:2px 8px; '
                    f'border-radius:10px; font-size:11px; font-weight:600;">'
                    f'{h["entity"]}</span></div>', unsafe_allow_html=True)
            with h_cols[1]:
                st.markdown(
                    f'<div style="font-size:12px; padding:4px 0;">'
                    f'{h["entry_date"]}</div>', unsafe_allow_html=True)
            with h_cols[2]:
                st.markdown(
                    f'<div style="font-size:13px; font-weight:600; '
                    f'padding:4px 0;">{fmt_inr(h["value"])}</div>',
                    unsafe_allow_html=True)
            with h_cols[3]:
                st.markdown(
                    f'<div style="font-size:11px; color:#8896A5; '
                    f'padding:4px 0;">Updated: {h["updated_at"][:16]}</div>',
                    unsafe_allow_html=True)
            with h_cols[4]:
                if st.button("🗑️", key=f"del_cash_{h['id']}"):
                    delete_cash_entry(h["id"])
                    st.cache_data.clear()
                    st.rerun()

        if len(cash_hist) > 30:
            st.caption(f"Showing 30 of {len(cash_hist)} entries.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── B5: Transaction tagging ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Tag Investment Transactions")
    st.caption(
        "All transactions with Main Group = INVESTMENT. "
        "Add scheme name and number for portfolio tracking.")

    _inv_txns = get_investment_transactions(
        date_from=inv_date_from,
        date_to=inv_date_to,
        entity=entity_filter,
    )

    if not _inv_txns:
        st.info("No investment transactions found.")
    else:
        _df_it = pd.DataFrame(_inv_txns)
        _df_display = _df_it.copy()
        _df_display["debit"]  = _df_display["debit"].apply(
            lambda x: fmt_inr(x) if float(x or 0) > 0 else "—")
        _df_display["credit"] = _df_display["credit"].apply(
            lambda x: fmt_inr(x) if float(x or 0) > 0 else "—")
        _df_display.insert(0, "Tag", False)

        _edited = st.data_editor(
            _df_display[[
                "Tag", "id", "date", "entity", "bank",
                "narration", "debit", "credit",
                "final_group", "scheme_name",
                "scheme_number", "scheme_type"
            ]],
            column_config={
                "Tag":           st.column_config.CheckboxColumn("✓", width="small"),
                "id":            st.column_config.NumberColumn("ID", width="small"),
                "date":          st.column_config.Column("Date", width="small"),
                "narration":     st.column_config.Column("Narration", width="large"),
                "scheme_name":   st.column_config.Column("Scheme Name", width="medium"),
                "scheme_number": st.column_config.Column("Scheme No.", width="medium"),
                "scheme_type":   st.column_config.SelectboxColumn(
                    "Type", options=["FD", "MF", ""], width="small"),
                "debit":         rcol("Debit"),
                "credit":        rcol("Credit"),
            },
            disabled=["id", "date", "entity", "bank", "narration",
                      "debit", "credit", "final_group"],
            hide_index=True,
            use_container_width=True,
            height=400,
            key="inv_txn_editor",
        )

        _t1, _t2 = st.columns([2, 6])
        with _t1:
            if st.button("Save Tags", key="save_inv_tags"):
                _saved = 0
                for _, _trow in _edited[_edited["Tag"] == True].iterrows():
                    if str(_trow.get("scheme_name", "")).strip():
                        tag_investment_transaction(
                            transaction_id=int(_trow["id"]),
                            scheme_name=str(_trow["scheme_name"]).strip(),
                            scheme_number=str(_trow.get("scheme_number", "")).strip(),
                            scheme_type=str(_trow.get("scheme_type", "")).strip(),
                        )
                        _saved += 1
                if _saved:
                    st.success(f"Tagged {_saved} transactions")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning("Select rows and add scheme names first.")

    # ── One-time historical Cash at Stores bulk upload ────────────────────────
    st.markdown("---")
    with st.expander("📤 One-Time Historical Cash Upload (Excel)", expanded=False):
        st.caption(
            "Upload historical Cash at Stores data since 1st April 2025. "
            "Columns required: Entity | Date | Value. "
            "Re-uploading the same Entity+Date will overwrite that day's value.")

        _cash_tmpl_df = pd.DataFrame({
            "Entity": ["Stores", "Stores", "Stores"],
            "Date":   ["01/04/2025", "02/04/2025", "03/04/2025"],
            "Value":  [26500000, 26750000, 27100000],
        })
        _cash_tmpl_buf = io.BytesIO()
        _cash_tmpl_df.to_excel(_cash_tmpl_buf, index=False)
        _cash_tmpl_buf.seek(0)
        st.download_button(
            "⬇️ Download Template", _cash_tmpl_buf, "cash_at_stores_template.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_cash_template"
        )

        st.markdown("---")

        _cash_uploader_key = st.session_state.get("cash_uploader_key", 0)
        _cash_file = st.file_uploader(
            "Upload Excel file", type=["xlsx", "xls"],
            accept_multiple_files=False,
            key=f"cash_upload_{_cash_uploader_key}"
        )

        if st.button("📥 Import Cash History", key="import_cash_btn"):
            if _cash_file is None:
                st.error("Please select an Excel file first.")
            else:
                import tempfile as _cash_tf, os as _cash_os
                _cash_suffix = _cash_os.path.splitext(_cash_file.name)[1]
                with _cash_tf.NamedTemporaryFile(delete=False, suffix=_cash_suffix) as _cash_tmp:
                    _cash_tmp.write(_cash_file.getbuffer())
                    _cash_tmp_path = _cash_tmp.name

                with st.spinner("Importing..."):
                    _cash_result = import_cash_excel(_cash_tmp_path)

                try:
                    _cash_os.unlink(_cash_tmp_path)
                except Exception:
                    pass

                if _cash_result["inserted"] > 0:
                    st.success(
                        f"✅ Imported {_cash_result['inserted']:,} daily entries. "
                        f"Skipped: {_cash_result.get('skipped', 0)}. "
                        f"Errors: {_cash_result['errors']}.")
                    st.session_state["cash_uploader_key"] = _cash_uploader_key + 1
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(
                        f"❌ No entries imported. "
                        f"Skipped: {_cash_result.get('skipped', 0)}. "
                        f"Errors: {_cash_result['errors']}.")

                if _cash_result.get("error_rows"):
                    with st.expander("⚠️ Row errors"):
                        for _err in _cash_result["error_rows"][:20]:
                            st.text(_err)

# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
elif selected_tab == "Upload":
    import tempfile as _tempfile
    import sys as _sys
    import os as _os_up

    st.markdown("### Upload Bank Statements")
    st.markdown("""
<div style="background:#EBF4FF; border-left:4px solid #3B82F6;
     border-radius:6px; padding:10px 16px; margin-bottom:20px;
     font-size:13px; color:#1E40AF;">
    Select entity and account, then upload one bank statement file (.xlsx / .xls).
    Duplicate transactions are automatically skipped.
</div>
""", unsafe_allow_html=True)

    from config import ENTITIES as _UP_ENTITIES

    _up_c1, _up_c2 = st.columns(2)
    with _up_c1:
        _up_entity = st.selectbox(
            "Entity",
            list(_UP_ENTITIES.keys()),
            key="up_entity",
        )
    with _up_c2:
        _up_account = st.selectbox(
            "Account",
            _UP_ENTITIES[_up_entity],
            key="up_account",
        )

    # Uploader key rotation — allows auto-clear after processing
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0
    if st.session_state.get("_clear_result_next"):
        st.session_state.pop("last_process_result", None)
        st.session_state.pop("_clear_result_next", None)

    _uploaded_file = st.file_uploader(
        "Bank Statement File",
        accept_multiple_files=False,
        type=["xlsx", "xls"],
        key=f"uploader_{st.session_state['uploader_key']}",
        help="AXIS: .xlsx   |   HDFC: .xls   |   One file at a time.",
    )
    if _uploaded_file is not None:
        st.session_state["_clear_result_next"] = True

    # Result banner (persists across reruns until dismissed)
    _up_result = st.session_state.get("last_process_result")
    if _up_result:
        if _up_result["status"] == "success":
            st.markdown(f"""
<div style="background:#F0FFF4; border-left:4px solid #38A169;
     border-radius:6px; padding:12px 16px; margin:8px 0; font-size:13px;">
    <b>{_up_result['filename']}</b> processed successfully<br>
    <span style="color:#276749;">
        {_up_result.get('entity','?')} — {_up_result.get('bank','?')} &nbsp;|&nbsp;
        {_up_result.get('inserted',0):,} rows inserted &nbsp;|&nbsp;
        {_up_result.get('skipped',0):,} duplicates skipped
    </span>
</div>""", unsafe_allow_html=True)
            for _w in _up_result.get("warnings", []):
                st.warning(f"⚠️ {_w}")
            if not _up_result.get("warnings"):
                st.success("✅ Data check passed for this account — no gaps, balances tie.")
        elif _up_result["status"] == "already_loaded":
            st.markdown(f"""
<div style="background:#FFFFF0; border-left:4px solid #D69E2E;
     border-radius:6px; padding:12px 16px; margin:8px 0; font-size:13px;">
    <b>{_up_result['filename']}</b> — already loaded<br>
    <span style="color:#744210;">
        All {_up_result.get('skipped',0):,} rows already exist in the database.
    </span>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
<div style="background:#FFF5F5; border-left:4px solid #E53E3E;
     border-radius:6px; padding:12px 16px; margin:8px 0; font-size:13px; color:#742A2A;">
    <b>{_up_result['filename']}</b> — {_up_result.get('message','')}
</div>""", unsafe_allow_html=True)
        if st.button("Dismiss", key="dismiss_result"):
            del st.session_state["last_process_result"]
            st.rerun()

    if st.button("Process Statement", key="up_process_btn",
                 disabled=not _uploaded_file, type="primary"):
        _script_dir = _os_up.path.dirname(_os_up.path.abspath(__file__))
        if _script_dir not in _sys.path:
            _sys.path.insert(0, _script_dir)
        from processor import process_file as _process_file
        from categorizer import load_keywords as _load_kw

        _suffix  = _os_up.path.splitext(_uploaded_file.name)[1].lower() or ".xlsx"
        _tmp_path = None
        # Reserve the trail row FIRST so its id can be stamped on every
        # inserted transaction row (upload_id) — this is the reliable link
        # delete_upload() uses later; filename/entity/bank/date alone can't
        # be trusted since the same statement filename gets re-uploaded
        # every period.
        _trail_id = reserve_upload_trail(_uploaded_file.name, _up_entity, _up_account)
        try:
            with _tempfile.NamedTemporaryFile(
                    delete=False, suffix=_suffix, dir=_script_dir) as _tmp:
                _tmp.write(_uploaded_file.getbuffer())
                _tmp_path = _tmp.name

            with st.spinner(f"Processing {_uploaded_file.name}..."):
                _kw = _load_kw()
                _ins, _skp = _process_file(
                    _tmp_path,
                    keywords=_kw,
                    entity=_up_entity,
                    bank=_up_account,
                    delete_after=True,
                    upload_id=_trail_id,
                )

            if _ins > 0:
                # Derive date range and FY from the rows this upload just inserted,
                # matched by upload_id — exact, unlike filename which can repeat.
                import sqlite3 as _sq3
                _conn2 = _sq3.connect(DATABASE_FILE)
                _dr = _conn2.execute("""
                    SELECT MIN(date), MAX(date), financial_year
                    FROM transactions
                    WHERE upload_id=?
                """, [_trail_id]).fetchone()
                _conn2.close()
                _d_from = _dr[0] if _dr else ""
                _d_to   = _dr[1] if _dr else ""
                _fy     = _dr[2] if _dr else ""
                finalize_upload_trail(
                    _trail_id,
                    financial_year=_fy,
                    rows_inserted=_ins,
                    date_from=_d_from,
                    date_to=_d_to,
                )
                # Immediately check this account for gaps / balance breaks around the new data
                _warn = []
                try:
                    st.cache_data.clear()
                    _rep = _integrity_raw()
                    _lo = (datetime.date.fromisoformat(_d_from) - datetime.timedelta(days=7)).isoformat() if _d_from else "0000"
                    for _m in _rep["missing"]:
                        if _m["bank"] == _up_account and _m["to"] >= _lo:
                            _warn.append(
                                f"No statement loaded for {_m['from']} to {_m['to']} "
                                f"({_m['days']} day(s)). Upload that statement too.")
                    for _b in _rep["breaks"]:
                        if _b["bank"] == _up_account and _b["date"] >= _lo:
                            _warn.append(
                                f"Balance on {_b['date']} does not tie: difference {fmt_inr(_b['diff'])} "
                                f"({'earlier days not loaded' if _b['after_gap'] else 'some transactions missing'}).")
                except Exception:
                    pass
                st.session_state["last_process_result"] = {
                    "status": "success", "filename": _uploaded_file.name,
                    "inserted": _ins, "skipped": _skp,
                    "entity": _up_entity, "bank": _up_account,
                    "warnings": _warn,
                }
            else:
                # Nothing inserted — discard the reserved placeholder trail row.
                delete_upload(_trail_id)
                if _skp > 0:
                    st.session_state["last_process_result"] = {
                        "status": "already_loaded", "filename": _uploaded_file.name,
                        "skipped": _skp,
                    }
                else:
                    st.session_state["last_process_result"] = {
                        "status": "error", "filename": _uploaded_file.name,
                        "message": "No rows processed. Check file format.",
                    }
        except Exception as _e:
            if _tmp_path and _os_up.path.exists(_tmp_path):
                try: _os_up.unlink(_tmp_path)
                except OSError: pass
            delete_upload(_trail_id)  # discard the reserved placeholder trail row
            st.session_state["last_process_result"] = {
                "status": "error", "filename": _uploaded_file.name,
                "message": str(_e),
            }

        st.session_state["uploader_key"] += 1
        st.cache_data.clear()
        st.rerun()

    # ── DB Restore ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Restore Database")
    st.markdown("""
<div style="background:#FFF8E1; border-left:4px solid #F59E0B;
     border-radius:6px; padding:10px 16px; margin-bottom:16px;
     font-size:13px; color:#92400E;">
    ⚠️ Upload a <b>bankflow.db</b> file to restore all historical data.
    This will <b>replace</b> the current database entirely.
</div>
<div style="background:#EBF4FF; border-left:4px solid #3B82F6;
     border-radius:6px; padding:10px 16px; margin-bottom:16px;
     font-size:13px; color:#1E40AF;">
    💡 <b>Large database?</b> Upload a <b>.gz</b> or <b>.zip</b> of your
    bankflow.db instead of the raw file — it's compressed to roughly
    a quarter of the size, which is far more reliable on a hosted upload
    connection. On Windows: right-click <code>bankflow.db</code> →
    <b>Send to → Compressed (zipped) folder</b>, then upload the
    resulting .zip here. Plain uncompressed .db uploads are still supported.
</div>
""", unsafe_allow_html=True)

    _db_file = st.file_uploader(
        "Select bankflow.db (.db, .gz, or .zip)",
        type=["db", "gz", "zip"],
        key="db_restore_file",
        help="Upload your bankflow.db, or a .gz/.zip of it, to restore all data."
    )

    _db_confirm = st.checkbox("I understand this will replace the current database", key="db_restore_confirm")
    _db_btn = st.button("🗄️ Restore Database", key="db_restore_btn",
                        disabled=not (_db_file and _db_confirm),
                        type="primary")

    if _db_btn and _db_file and _db_confirm:
        import shutil as _shutil
        import gzip as _gzip
        import zipfile as _zipfile
        import io as _io_restore
        from config import DATABASE_FILE as _DB_PATH
        try:
            _os_up.makedirs(_os_up.path.dirname(_DB_PATH), exist_ok=True)
            _backup_path = _DB_PATH + ".bak"
            if _os_up.path.exists(_DB_PATH):
                _shutil.copy2(_DB_PATH, _backup_path)

            _raw_bytes = _db_file.getvalue()
            _name_lower = _db_file.name.lower()

            if _name_lower.endswith(".gz"):
                _db_bytes = _gzip.decompress(_raw_bytes)
            elif _name_lower.endswith(".zip"):
                with _zipfile.ZipFile(_io_restore.BytesIO(_raw_bytes)) as _zf:
                    _db_members = [n for n in _zf.namelist() if n.lower().endswith(".db")]
                    if not _db_members:
                        raise ValueError("No .db file found inside the uploaded zip.")
                    _db_bytes = _zf.read(_db_members[0])
            else:
                _db_bytes = _raw_bytes

            with open(_DB_PATH, "wb") as _f:
                _f.write(_db_bytes)
            st.cache_data.clear()
            st.success(
                f"✅ Database restored successfully! "
                f"({len(_db_bytes):,} bytes written"
                f"{f', {len(_raw_bytes):,} bytes uploaded' if _raw_bytes != _db_bytes else ''})"
            )
            st.info("A backup of the previous database was saved as bankflow.db.bak")
        except Exception as _e:
            st.error(f"❌ Restore failed: {_e}")

    # ── DB Download (read-only snapshot) ──────────────────────────────────────
    st.markdown("---")
    st.markdown("### Download Database")
    st.markdown("""
<div style="background:#EBF4FF; border-left:4px solid #3B82F6;
     border-radius:6px; padding:10px 16px; margin-bottom:16px;
     font-size:13px; color:#1E40AF;">
    Creates a compressed copy (<b>.gz</b>) of the current database. Click
    <b>Prepare download</b>, wait for it to finish, then click <b>Download</b>.
    Unzip it to get <code>bankflow.db</code>. This only reads the database &mdash; nothing is changed.
</div>
""", unsafe_allow_html=True)

    if st.button("📦 Prepare download", key="db_prepare_btn"):
        import sqlite3 as _sq_dl
        import gzip as _gz_dl
        import shutil as _sh_dl
        import tempfile as _tf_dl
        _tmp_db = _tmp_gz = None
        try:
            with st.spinner("Creating a consistent snapshot and compressing it..."):
                _tmp_db = _tf_dl.NamedTemporaryFile(delete=False, suffix=".db")
                _tmp_db.close()
                _tmp_gz = _tf_dl.NamedTemporaryFile(delete=False, suffix=".gz")
                _tmp_gz.close()
                _src = _sq_dl.connect(f"file:{DATABASE_FILE}?mode=ro", uri=True)
                _dst = _sq_dl.connect(_tmp_db.name)
                _src.backup(_dst)          # consistent copy even while the app is in use
                _dst.close()
                _src.close()
                with open(_tmp_db.name, "rb") as _fin, _gz_dl.open(_tmp_gz.name, "wb", compresslevel=6) as _fout:
                    _sh_dl.copyfileobj(_fin, _fout, 1024 * 1024)
                with open(_tmp_gz.name, "rb") as _fz:
                    st.session_state["db_download_bytes"] = _fz.read()
                st.session_state["db_download_name"] = (
                    f"bankflow_{datetime.date.today().isoformat()}.db.gz")
        except Exception as _e:
            st.session_state.pop("db_download_bytes", None)
            st.error(f"❌ Could not prepare the download: {_e}")
        finally:
            for _t in (_tmp_db, _tmp_gz):
                if _t is not None:
                    try:
                        _os_up.unlink(_t.name)
                    except OSError:
                        pass

    if st.session_state.get("db_download_bytes"):
        _dl_bytes = st.session_state["db_download_bytes"]
        st.success(f"Ready — {len(_dl_bytes) / 1e6:,.1f} MB compressed.")
        st.download_button(
            "⬇️ Download database (.gz)", _dl_bytes,
            file_name=st.session_state.get("db_download_name", "bankflow.db.gz"),
            mime="application/gzip", key="db_download_btn")

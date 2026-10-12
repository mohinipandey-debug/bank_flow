"""Shared number and HTML-cell formatters for the BankFlow dashboard.

One convention everywhere: Indian grouping (12,34,567), ₹ symbol, no decimals,
minus sign BEFORE the ₹ (-₹12,34,567), negatives shown in red in HTML cells.
Headline tiles use Cr / L (see fmt_cr).
"""

NEG_COLOR = "#B91C1C"


def _group_indian(n):
    """int >= 0 -> '12,34,567'."""
    s = str(n)
    if len(s) <= 3:
        return s
    last3, rem, parts = s[-3:], s[:-3], []
    while rem:
        parts.insert(0, rem[-2:])
        rem = rem[:-2]
    return ",".join(p for p in parts if p) + "," + last3


def fmt_inr(x, dash_zero=True):
    """Plain-text rupee amount, e.g. ₹12,34,567 / -₹12,34,567. Zero/None -> '—'."""
    try:
        if x is None:
            return "—"
        x = float(x)
        if x != x:                      # NaN
            return "—"
        n = int(round(abs(x)))
        if n == 0:
            return "—" if dash_zero else "₹0"
        return f"{'-' if x < 0 else ''}₹{_group_indian(n)}"
    except Exception:
        return str(x) if x else "—"


def _inr(val):
    """HTML rupee amount: same as fmt_inr, but negatives are wrapped in a red span."""
    txt = fmt_inr(val)
    try:
        if val is not None and round(float(val)) < 0:
            return f'<span style="color:{NEG_COLOR};">{txt}</span>'
    except Exception:
        pass
    return txt


def fmt_cf(x):
    """Cash-flow style amount (kept for existing callers) — same convention."""
    return _inr(x)


def fmt_cr(x):
    """Headline-tile format: ₹5.27 Cr / ₹62.46 L / ₹9,500; minus before the ₹."""
    try:
        x = float(x)
        if round(x) == 0:
            return "₹0"
        sign = "-" if x < 0 else ""
        x = abs(x)
        if x >= 1e7:
            return f"{sign}₹{x/1e7:.2f} Cr"
        if x >= 1e5:
            return f"{sign}₹{x/1e5:.2f} L"
        return f"{sign}₹{_group_indian(int(round(x)))}"
    except Exception:
        return str(x)


def _td(val, red=False, net=False):
    """Return an HTML <td> cell for a Cash Flow table value."""
    if val is None or val == 0:
        return '<td class="r muted">—</td>'
    txt = fmt_inr(val)
    if net:
        cls = "r grn" if val >= 0 else "r red"
    elif red or val < 0:
        cls = "r red"
    else:
        cls = "r mono"
    return f'<td class="{cls}">{txt}</td>'


def _td_dash():
    """Return a muted dash <td> for an empty Cash Flow cell."""
    return '<td class="r muted">—</td>'

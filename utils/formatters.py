"""Shared number and HTML-cell formatters for the BankFlow dashboard."""


def fmt_inr(x):
    """Western comma formatting with 2 decimal places.  e.g. ₹1,234,567.00"""
    try:
        x = float(x)
        if x == 0:
            return "—"
        return f"₹{x:,.2f}"
    except Exception:
        return str(x) if x else "—"


def _inr(val):
    """Indian 2-2-3 grouping, no decimal places.  e.g. ₹12,34,567"""
    if val is None or val == 0:
        return "—"
    neg = val < 0
    n   = abs(int(round(val)))
    s   = str(n)
    if len(s) <= 3:
        r = s
    else:
        last3, rem, parts = s[-3:], s[:-3], []
        while rem:
            parts.insert(0, rem[-2:])
            rem = rem[:-2]
        r = ",".join(p for p in parts if p) + "," + last3
    return ("(₹" if neg else "₹") + r


def _td(val, red=False, net=False):
    """Return an HTML <td> cell for a Cash Flow table value."""
    if val is None or val == 0:
        return '<td class="r muted">—</td>'
    txt = _inr(val)
    if net:
        cls = "r grn" if val >= 0 else "r red"
    elif red:
        cls = "r red"
    else:
        cls = "r mono"
    return f'<td class="{cls}">{txt}</td>'


def _td_dash():
    """Return a muted dash <td> for an empty Cash Flow cell."""
    return '<td class="r muted">—</td>'

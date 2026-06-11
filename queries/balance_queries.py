"""Closing-balance query — extracted from dashboard.py."""

import pandas as pd
from database import get_all_transactions


def closing_bal(entity_f, bank_f, month_f, dt_from=None, dt_to=None):
    txns = get_all_transactions(entity=entity_f, bank=bank_f, month=month_f,
                                date_from=dt_from, date_to=dt_to)
    if not txns:
        return None, ""
    _df = pd.DataFrame(txns)
    _df = _df[_df["final_group"] != "OPENING BALANCE"]
    _df = _df.sort_values(["date", "id"], ascending=[False, False])
    _v  = _df[_df["balance"].notna()]
    if _v.empty:
        return None, ""
    return float(_v.iloc[0]["balance"]), str(_v.iloc[0]["date"])

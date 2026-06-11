"""Review Queue tab — extracted from dashboard.py."""

import streamlit as st
import pandas as pd
from database import reload_categories


def render_review_queue(uncats):
    st.markdown("### Uncategorized Transactions")
    st.caption("These narrations didn't match any keyword. "
               "Add keywords to keywords_master.xlsx and click Reload.")

    if st.button("🔄 Reload Keywords & Re-Categorize All"):
        with st.spinner("Re-categorizing all transactions..."):
            updated = reload_categories()
        st.cache_data.clear()
        st.success(f"✅ Updated {updated} transactions. Refresh page to see changes.")

    if uncats:
        df_unc = pd.DataFrame(uncats)
        df_unc.columns = ["Narration", "Entity", "Count", "Total Debit (₹)"]
        df_unc["Total Debit (₹)"] = df_unc["Total Debit (₹)"].apply(
            lambda x: f"₹{x:,.0f}" if x else "—"
        )
        df_unc = df_unc.sort_values("Count", ascending=False)
        st.metric("Total uncategorized narration patterns", len(uncats))
        st.dataframe(df_unc, use_container_width=True, hide_index=True, height=400)
        st.markdown("---")
        st.markdown("**How to fix:**")
        st.markdown("1. Open `keywords_master.xlsx`")
        st.markdown("2. Add the narration keyword in the **Key word for Stores** "
                    "or **Key word for Ventures** column")
        st.markdown("3. Fill in FINAL GROUP, GROUP, MAIN GROUP")
        st.markdown("4. Save the file and click **Reload Keywords** above")
    else:
        st.success("✅ All transactions are categorized!")

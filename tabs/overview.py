"""Overview tab — extracted from dashboard.py."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def render_overview(summary):
    # Entity breakdown is rendered in the Summary tab header above this call.
    st.markdown("---")
    row1_c1, row1_c2 = st.columns(2)

    with row1_c1:
        by_month = summary.get("by_month", [])
        if by_month:
            df_month = pd.DataFrame(by_month)
            df_month["net"] = df_month["inflow"] - df_month["outflow"]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="Inflow",
                x=df_month["month"],
                y=df_month["inflow"],
                marker=dict(color="#3B82F6", opacity=0.85, line=dict(width=0)),
                hovertemplate="<b>%{x}</b><br>Inflow: ₹%{y:,.0f}<extra></extra>"
            ))
            fig.add_trace(go.Bar(
                name="Outflow",
                x=df_month["month"],
                y=df_month["outflow"],
                marker=dict(color="#F87171", opacity=0.85, line=dict(width=0)),
                hovertemplate="<b>%{x}</b><br>Outflow: ₹%{y:,.0f}<extra></extra>"
            ))
            fig.add_trace(go.Scatter(
                name="Net Flow",
                x=df_month["month"],
                y=df_month["net"],
                mode="lines+markers",
                line=dict(color="#1B3A6B", width=2, dash="dot"),
                marker=dict(size=6, color="#1B3A6B"),
                hovertemplate="<b>%{x}</b><br>Net: ₹%{y:,.0f}<extra></extra>"
            ))
            fig.update_layout(
                title=dict(text="Monthly Inflow vs Outflow",
                           font=dict(size=14, color="#1A202C"), x=0),
                barmode="group",
                bargap=0.25,
                bargroupgap=0.08,
                plot_bgcolor="#FFFFFF",
                paper_bgcolor="#FFFFFF",
                font=dict(family="Inter", color="#4A5568", size=12),
                legend=dict(
                    orientation="h",
                    yanchor="bottom", y=1.02,
                    xanchor="right", x=1,
                    font=dict(size=11)
                ),
                xaxis=dict(
                    showgrid=False,
                    tickfont=dict(size=11),
                    tickangle=-30,
                    linecolor="#E2E8F0"
                ),
                yaxis=dict(
                    showgrid=True,
                    gridcolor="#F0F0F0",
                    gridwidth=1,
                    tickfont=dict(size=11),
                    tickformat=",.0f"
                ),
                height=320,
                margin=dict(l=10, r=10, t=40, b=10)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No monthly data yet. Drop some bank statements to get started.")

    with row1_c2:
        by_cat = summary.get("by_category", [])
        if by_cat:
            df_cat = pd.DataFrame(by_cat)
            df_cat = df_cat[df_cat["total"] > 0].copy()
            df_cat_top = df_cat.head(8).copy()
            if len(df_cat) > 8:
                others_total = df_cat.iloc[8:]["total"].sum()
                df_cat_top = pd.concat([
                    df_cat_top,
                    pd.DataFrame([{"final_group": "Others", "total": others_total}])
                ], ignore_index=True)
            _DONUT_COLORS = [
                "#1B3A6B", "#3B82F6", "#60A5FA", "#93C5FD",
                "#BFDBFE", "#1E40AF", "#2563EB", "#DBEAFE", "#E2E8F0"
            ]
            _total_spend = df_cat["total"].sum()
            _center_text = (
                f"₹{_total_spend/1e7:.1f}Cr" if _total_spend >= 1e7
                else f"₹{_total_spend/1e5:.1f}L"
            )
            fig2 = go.Figure(go.Pie(
                labels=df_cat_top["final_group"],
                values=df_cat_top["total"],
                hole=0.65,
                marker=dict(
                    colors=_DONUT_COLORS[:len(df_cat_top)],
                    line=dict(color="#FFFFFF", width=2)
                ),
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>"
            ))
            fig2.add_annotation(
                text=f"{_center_text}<br><span style='font-size:10px'>Total Spend</span>",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color="#1A202C", family="Inter"),
                align="center"
            )
            fig2.update_layout(
                title=dict(text="Expenditure by Category",
                           font=dict(size=14, color="#1A202C"), x=0),
                plot_bgcolor="#FFFFFF",
                paper_bgcolor="#FFFFFF",
                font=dict(family="Inter", color="#4A5568", size=11),
                legend=dict(
                    orientation="v",
                    yanchor="middle", y=0.5,
                    xanchor="left", x=1.02,
                    font=dict(size=11),
                    itemsizing="constant"
                ),
                height=320,
                margin=dict(l=10, r=120, t=40, b=10),
                showlegend=True
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No categorized data yet.")

    by_cat = summary.get("by_category", [])
    if by_cat:
        st.markdown('<div class="section-header">Category Detail</div>',
                    unsafe_allow_html=True)
        df_cat_full = pd.DataFrame(by_cat)
        df_cat_full.columns = ["Category", "Group", "Main Group", "Total (₹)"]
        df_cat_full["Total (₹)"] = df_cat_full["Total (₹)"].apply(
            lambda x: f"₹{x:,.0f}"
        )
        st.dataframe(df_cat_full, use_container_width=True, hide_index=True)

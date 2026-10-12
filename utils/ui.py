"""Small Streamlit UI helpers."""
import streamlit as st


def rcol(label=None, **kw):
    """Right-aligned text column for amount columns in st.dataframe / st.data_editor."""
    try:
        return st.column_config.TextColumn(label, alignment="right", **kw)
    except TypeError:                       # older Streamlit without `alignment`
        return st.column_config.TextColumn(label, **kw)


def amount_config(columns):
    """{column_name: right-aligned TextColumn} for every name in `columns`."""
    return {c: rcol(c) for c in columns}

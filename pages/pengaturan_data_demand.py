import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
import pmdarima as pm
from statsmodels.tsa.statespace.sarimax import SARIMAX
import html
from bs4 import BeautifulSoup
import json, re
import holidays
from datetime import date, timedelta
import time

conn = st.connection("gsheets", type=GSheetsConnection)

def reload_df(conn, sheet_name):
    df = conn.read(worksheet=sheet_name)
    df["Periode"] = pd.to_datetime(df["Periode"])
    df.set_index("Periode", inplace=True)
    return df.sort_index()


def update_df_to_gsheet(df, sheet_name="Demand"):
    conn.update(worksheet=sheet_name, data=df.reset_index())


def get_effective_working_days(year, month):
    indo_holidays = holidays.country_holidays('ID', years=[year])
    start_date = date(year, month, 1)
    end_date = pd.Period(f"{year}-{month:02}").end_time.date()
    current = start_date
    workdays = 0
    while current <= end_date:
        if current.weekday() < 5 and current not in indo_holidays:
            workdays += 1
        current += timedelta(days=1)
    return workdays


def update_dataframe(df, updates_dict):
    for col_name, series_update in updates_dict.items():
        df.loc[series_update.index, col_name] = series_update.values
    return df

st.title("⚙️ Pengaturan Data Demand")

if "df_sbb" not in st.session_state:
    st.session_state.df_sbb = reload_df(conn, "SBB")

if "df_forecasting_assumptions" not in st.session_state:
    st.session_state.df_forecasting_assumptions = reload_df(conn, "Forecasting SBB")

df = st.session_state.df_sbb
forecasting_assumptions = st.session_state.df_forecasting_assumptions
st.dataframe(df)
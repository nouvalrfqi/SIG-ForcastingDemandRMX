import sqlite3
import pandas as pd
import numpy as np
import os
from pathlib import Path

DB_NAME = "forecasting.db"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / DB_NAME


def ensure_float(value):
    """Convert any value to float, handling commas and strings."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, str):
        value = value.replace(',', '.').strip()
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def sanitize_df(df):
    """Ensure all numeric columns in a DataFrame are float."""
    df = df.copy()
    for col in df.columns:
        if col == 'Periode':
            continue
        df[col] = pd.to_numeric(df[col].apply(
            lambda x: str(x).replace(',', '.') if isinstance(x, str) else x
        ), errors='coerce')
    return df


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # ── Unified Forecast Exogenous 2026 ──────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS forecast_exog_2026 (
        Periode DATE PRIMARY KEY,
        Inflasi REAL,
        "BI Rate" REAL,
        "PDB Konstruksi" REAL,
        "Effective Working Days" REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS demand_actual (
        Periode DATE PRIMARY KEY,
        Inflasi REAL,
        "BI Rate" REAL,
        "PDB Konstruksi" REAL,
        "Effective Working Days" REAL,
        Demand REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sbb_actual (
        Periode DATE PRIMARY KEY,
        Inflasi REAL,
        "BI Rate" REAL,
        "PDB Konstruksi" REAL,
        "Effective Working Days" REAL,
        Volume REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vub_actual (
        Periode DATE PRIMARY KEY,
        Inflasi REAL,
        "BI Rate" REAL,
        "PDB Konstruksi" REAL,
        "Effective Working Days" REAL,
        Volume REAL
    )
    """)
    # ── Forecast Results Tables ──────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS demand_forecast_results (
        Periode DATE PRIMARY KEY,
        Forecasting REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sbb_forecast_results (
        Periode DATE PRIMARY KEY,
        Forecasting REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vub_forecast_results (
        Periode DATE PRIMARY KEY,
        Forecasting REAL
    )
    """)

    conn.commit()
    conn.close()


def save_data(table_name, df):
    """Save a DataFrame to a SQLite table (replace mode)."""
    conn = get_connection()
    df = df.copy()

    if 'Periode' not in df.columns:
        df.index.name = 'Periode'
        df = df.reset_index()
    elif df.index.name == 'Periode':
        df = df.reset_index()

    if 'Periode' in df.columns:
        df['Periode'] = pd.to_datetime(df['Periode']).dt.strftime('%Y-%m-%d')

    df = sanitize_df(df)
    df.to_sql(table_name, conn, if_exists='replace', index=False)
    conn.close()


def get_data(table_name):
    """Read a table from SQLite and return as DataFrame with Periode index."""
    conn = get_connection()
    try:
        df = pd.read_sql(f'SELECT * FROM "{table_name}"', conn)
        if 'Periode' in df.columns:
            df['Periode'] = pd.to_datetime(df['Periode'])
            df.set_index('Periode', inplace=True)
            df.sort_index(inplace=True)
        # Ensure numeric types
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception as e:
        print(f"Error reading {table_name}: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def update_single_row(table_name, periode, data_dict):
    """Insert or update a single row in a table."""
    conn = get_connection()
    cursor = conn.cursor()

    # Sanitize values
    clean_dict = {k: ensure_float(v) if k != 'Periode' else v for k, v in data_dict.items()}

    cursor.execute(f'SELECT 1 FROM "{table_name}" WHERE Periode = ?', (periode,))
    exists = cursor.fetchone()

    if exists:
        set_clause = ", ".join([f'"{k}" = ?' for k in clean_dict.keys()])
        values = list(clean_dict.values()) + [periode]
        cursor.execute(f'UPDATE "{table_name}" SET {set_clause} WHERE Periode = ?', values)
    else:
        cols = ["Periode"] + list(clean_dict.keys())
        quoted_cols = [f'"{c}"' for c in cols]
        placeholders = ", ".join(["?"] * len(cols))
        values = [periode] + list(clean_dict.values())
        cursor.execute(f'INSERT INTO "{table_name}" ({", ".join(quoted_cols)}) VALUES ({placeholders})', values)

    conn.commit()
    conn.close()


def delete_row(table_name, periode):
    """Delete a row from a table by Periode."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM "{table_name}" WHERE Periode = ?', (periode,))
    conn.commit()
    conn.close()

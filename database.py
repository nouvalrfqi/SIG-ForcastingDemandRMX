import pandas as pd
import numpy as np
import os
import streamlit as st
from pathlib import Path
from sqlalchemy import create_engine, text

def get_engine():
    """Get SQLAlchemy engine using Supabase URL from secrets or environment, fallback to SQLite."""
    try:
        # Try to get from st.secrets (for Streamlit Community Cloud)
        db_url = st.secrets["supabase"]["database_url"]
    except Exception:
        # Fallback to environment variable (for local testing without secrets.toml)
        db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        # Ultimate fallback: local SQLite
        DB_NAME = "forecasting.db"
        BASE_DIR = Path(__file__).resolve().parent
        db_url = f"sqlite:///{BASE_DIR / DB_NAME}"
    else:
        # Ensure SQLAlchemy uses the psycopg2 driver for PostgreSQL
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        elif db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)

    return create_engine(db_url)

# Global Engine Instance
engine = get_engine()

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

def init_db():
    """Initialize database schemas using SQLAlchemy."""
    with engine.begin() as conn:
        # ── Unified Forecast Exogenous 2026 ──────────────────────────────
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS forecast_exog_2026 (
            "Periode" DATE PRIMARY KEY,
            "Inflasi" REAL,
            "BI Rate" REAL,
            "PDB Konstruksi" REAL,
            "Effective Working Days" REAL
        )
        """))

        # ── Demand Actual ────────────────────────────────────────────────
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS demand_actual (
            "Periode" DATE PRIMARY KEY,
            "Inflasi" REAL,
            "BI Rate" REAL,
            "PDB Konstruksi" REAL,
            "Effective Working Days" REAL,
            "Demand" REAL
        )
        """))

        # ── SBB Actual ───────────────────────────────────────────────────
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sbb_actual (
            "Periode" DATE PRIMARY KEY,
            "Inflasi" REAL,
            "BI Rate" REAL,
            "PDB Konstruksi" REAL,
            "Effective Working Days" REAL,
            "Volume" REAL
        )
        """))

        # ── VUB Actual ───────────────────────────────────────────────────
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS vub_actual (
            "Periode" DATE PRIMARY KEY,
            "Inflasi" REAL,
            "BI Rate" REAL,
            "PDB Konstruksi" REAL,
            "Effective Working Days" REAL,
            "Volume" REAL
        )
        """))

        # ── Forecast Results Tables ──────────────────────────────────────
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS demand_forecast_results (
            "Periode" DATE PRIMARY KEY,
            "Forecasting" REAL
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sbb_forecast_results (
            "Periode" DATE PRIMARY KEY,
            "Forecasting" REAL
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS vub_forecast_results (
            "Periode" DATE PRIMARY KEY,
            "Forecasting" REAL
        )
        """))

def save_data(table_name, df):
    """Save a DataFrame to a SQL table (replace mode) using Pandas."""
    df = df.copy()

    if 'Periode' not in df.columns:
        df.index.name = 'Periode'
        df = df.reset_index()
    elif df.index.name == 'Periode':
        df = df.reset_index()

    if 'Periode' in df.columns:
        df['Periode'] = pd.to_datetime(df['Periode']).dt.strftime('%Y-%m-%d')

    df = sanitize_df(df)
    # Using Pandas to_sql with SQLAlchemy engine
    df.to_sql(table_name, engine, if_exists='replace', index=False)

def get_data(table_name):
    """Read a table from SQL and return as DataFrame with Periode index."""
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(f'SELECT * FROM "{table_name}"'), conn)
            
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

def update_single_row(table_name, periode, data_dict):
    """Insert or update a single row using SQLAlchemy parameterized queries."""
    clean_dict = {k: ensure_float(v) if k != 'Periode' else v for k, v in data_dict.items()}
    
    with engine.begin() as conn:
        # Check if exists
        result = conn.execute(text(f'SELECT 1 FROM "{table_name}" WHERE "Periode" = :p'), {"p": periode}).fetchone()
        
        # Prepare params (SQLAlchemy text parameters shouldn't have spaces)
        params = {"p": periode}
        for k, v in clean_dict.items():
            safe_key = k.replace(" ", "_")
            params[safe_key] = v

        if result:
            set_clause = ", ".join([f'"{k}" = :{k.replace(" ", "_")}' for k in clean_dict.keys()])
            conn.execute(text(f'UPDATE "{table_name}" SET {set_clause} WHERE "Periode" = :p'), params)
        else:
            cols = ["Periode"] + list(clean_dict.keys())
            quoted_cols = [f'"{c}"' for c in cols]
            placeholders = ", ".join([f':{c.replace(" ", "_")}' for c in cols])
            
            # Add Periode back to params with its safe key
            params["Periode"] = periode
            
            conn.execute(text(f'INSERT INTO "{table_name}" ({", ".join(quoted_cols)}) VALUES ({placeholders})'), params)

def delete_row(table_name, periode):
    """Delete a row by Periode."""
    with engine.begin() as conn:
        conn.execute(text(f'DELETE FROM "{table_name}" WHERE "Periode" = :p'), {"p": periode})

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import joblib
import os
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import database

load_dotenv()

try:
    api_key = st.secrets['openai']['api_key']
except Exception:
    api_key = os.getenv("OPENAI_API_KEY")

client = None
if api_key:
    client = OpenAI(base_url="https://models.github.ai/inference", api_key=api_key)


@st.cache_resource
def load_model(model_path: str):
    return joblib.load(model_path)


def resolve_model_path(relative_path: str) -> str:
    base_path = Path(__file__).resolve().parent.parent
    return str(base_path / relative_path)


def generate_insight_with_gpt(df_forecast):
    if not client:
        return "⚠️ OpenAI API Key tidak ditemukan."
    data_summary = df_forecast[["Forecasting"]].tail(12).to_string()
    prompt = f"""
    PT Solusi Bangun Indonesia Tbk (SBI) bergerak di bidang produksi dan distribusi beton siap pakai (ready-mix concrete).

    Berikut adalah hasil peramalan demand readymix selama 12 bulan ke depan:
    {data_summary}

    Lakukan analisis tren penjualan, temukan insight relevan, dan berikan rekomendasi bisnis strategis dalam bahasa Indonesia yang formal dan ringkas.
    """
    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Kamu adalah analis data ahli yang memberikan insight dari data forecasting."},
                {"role": "user", "content": prompt}
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Gagal mendapatkan insight dari AI: {e}"


def show():
    st.title("📊 Peramalan Volume Penjualan ReadyMix — Demand Nasional")

    # ── Load Data ────────────────────────────────────────────────────
    df = database.get_data("demand_actual")
    exog_2026 = database.get_data("forecast_exog_2026")

    if df.empty:
        st.warning("⚠️ Data aktual belum tersedia. Buka Pengaturan Data.")
        return
    if exog_2026.empty:
        st.warning("⚠️ Data variabel eksogen 2026 belum tersedia.")
        return

    # ── Generate Forecast ────────────────────────────────────────────
    forecasting_final = None
    try:
        model_path = resolve_model_path("models/demandRMX.pkl")
        model_fit = load_model(model_path)

        # ── Hybrid Exogenous Logic ───────────────────────────────────
        # Gunakan data aktual 2026 jika tersedia, sisanya gunakan asumsi forecast_exog_2026
        best_features = ['BI Rate', 'PDB Konstruksi']
        
        # Mulai dengan data asumsi
        exog_input_2026 = exog_2026.copy()
        
        # Ambil data aktual yang masuk tahun 2026
        actual_2026 = df[df.index.year == 2026]
        
        for p in exog_input_2026.index:
            if p in actual_2026.index:
                # Jika di data aktual sudah ada BI Rate (tidak NaN dan tidak 0), gunakan itu
                if pd.notna(actual_2026.loc[p, 'BI Rate']) and actual_2026.loc[p, 'BI Rate'] != 0:
                    exog_input_2026.loc[p, 'BI Rate'] = actual_2026.loc[p, 'BI Rate']
                
                # Jika di data aktual sudah ada PDB Konstruksi, gunakan itu
                if pd.notna(actual_2026.loc[p, 'PDB Konstruksi']) and actual_2026.loc[p, 'PDB Konstruksi'] != 0:
                    exog_input_2026.loc[p, 'PDB Konstruksi'] = actual_2026.loc[p, 'PDB Konstruksi']

        exog_df = exog_input_2026[best_features].astype(float)

        forecast_values = model_fit.predict(n_periods=12, X=exog_df[:12])
        forecast_index = pd.date_range(start='2026-01-01', periods=12, freq='MS')

        forecasting_final = pd.DataFrame({
            "Forecasting": forecast_values.astype(float)
        }, index=forecast_index)
        forecasting_final.index.name = "Periode"

        # Save to separate forecast table
        database.save_data("demand_forecast_results", forecasting_final)


    except Exception as e:
        st.error(f"❌ Gagal memuat model atau menghitung prediksi: {e}")
        return

    # ── Sidebar Filter ───────────────────────────────────────────────
    df_forecast_results = database.get_data("demand_forecast_results")
    
    with st.sidebar:
        st.markdown("🗓️ **Filter Rentang Periode**")
        all_dates = df.index
        if not df_forecast_results.empty:
            # Ensure index is datetime
            df_forecast_results.index = pd.to_datetime(df_forecast_results.index)
            all_dates = all_dates.union(df_forecast_results.index)

        if all_dates.empty or not isinstance(all_dates.min(), pd.Timestamp):
            bulan_awal_val = pd.Timestamp('2024-01-01').to_pydatetime()
            bulan_akhir_val = pd.Timestamp('2026-12-01').to_pydatetime()
        else:
            bulan_awal_val = pd.Timestamp('2024-01-01').to_pydatetime()
            bulan_akhir_val = all_dates.max().to_pydatetime()

        bulan_awal, bulan_akhir = st.slider(
            "Pilih rentang bulan:",
            min_value=all_dates.min().to_pydatetime() if not all_dates.empty else pd.Timestamp('2020-01-01').to_pydatetime(),
            max_value=all_dates.max().to_pydatetime() if not all_dates.empty else pd.Timestamp('2026-12-01').to_pydatetime(),
            value=(bulan_awal_val, bulan_akhir_val),
            format="MM/YYYY"
        )

    # ── Filter data ──────────────────────────────────────────────────
    mask = (df.index >= bulan_awal) & (df.index <= bulan_akhir)
    df_filtered = df[mask]

    # Separate actual vs forecast
    has_actual = df_filtered['Demand'].notna() & (df_filtered['Demand'] > 0)
    df_actual = df_filtered[has_actual]

    # Forecast data (from separate table)
    if not df_forecast_results.empty:
        df_forecast_display = df_forecast_results[
            (df_forecast_results.index >= bulan_awal) & (df_forecast_results.index <= bulan_akhir)
        ]
    else:
        df_forecast_display = pd.DataFrame()

    # ── Chart ────────────────────────────────────────────────────────
    st.subheader("📈 Hasil Peramalan vs Data Aktual")

    fig = go.Figure()

    # Forecast line
    if not df_forecast_display.empty:
        fig.add_trace(go.Scatter(
            x=df_forecast_display.index,
            y=df_forecast_display["Forecasting"],
            mode="lines+markers",
            name="Demand Prediksi",
            line=dict(color="royalblue", width=3),
            marker=dict(size=7),
            hovertemplate="Prediksi: %{y:,.0f}<extra></extra>"
        ))

    # Actual line
    if not df_actual.empty:
        fig.add_trace(go.Scatter(
            x=df_actual.index,
            y=df_actual["Demand"],
            mode="lines+markers",
            name="Demand Aktual",
            line=dict(color="firebrick", width=3),
            marker=dict(size=7),
            hovertemplate="Aktual: %{y:,.0f}<extra></extra>"
        ))

    fig.update_layout(
        xaxis_title="Periode", yaxis_title="Demand (m³)",
        template="plotly_white", hovermode="x unified",
        height=500, autosize=True,
        legend=dict(title="Keterangan", orientation="h",
                    yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── GPT Insight ──────────────────────────────────────────────────
    if forecasting_final is not None:
        st.subheader("🧠 Rekomendasi Strategis")
        with st.spinner("Menghasilkan analisis dengan AI..."):
            insight = generate_insight_with_gpt(forecasting_final)
            st.markdown(insight)


if __name__ == "__main__" or st.runtime.exists():
    show()

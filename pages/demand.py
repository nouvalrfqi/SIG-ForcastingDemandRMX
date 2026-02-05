import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import pmdarima as pm
from statsmodels.tsa.statespace.sarimax import SARIMAX
import itertools
from tqdm import tqdm
import joblib
import os
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Safe API key retrieval
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

@st.cache_data(ttl=600)
def load_gsheet(sheet_name: str):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(worksheet=sheet_name)
    return df

@st.cache_data
def preprocess_data(df: pd.DataFrame, page_type: str):
    df = df.copy()
    df["Periode"] = pd.to_datetime(df["Periode"]).dt.normalize()
    df.set_index("Periode", inplace=True)
    return df.sort_index()

def resolve_model_path(relative_path: str) -> str:
    base_path = Path(__file__).resolve().parent.parent
    candidate = base_path / relative_path
    if candidate.exists():
        return str(candidate)
    candidate2 = Path(relative_path)
    if candidate2.exists():
        return str(candidate2)
    raise FileNotFoundError(f"Model file not found at {candidate2}")

def generate_insight_with_gpt(df_full_forecast):
    if not client:
        return "⚠️ OpenAI API Key tidak ditemukan. Pastikan sudah diatur di secrets.toml atau .env"

    data_summary = df_full_forecast[["Forecasting"]].tail(12).to_string()
    prompt = f"""
    PT Solusi Bangun Indonesia Tbk (SBI) yang bergerak di bidang produksi dan distribusi beton siap pakai (ready-mix concrete). Perusahaan ini menyediakan solusi beton berkualitas tinggi untuk berbagai kebutuhan konstruksi, mulai dari proyek infrastruktur skala besar hingga pembangunan perumahan dan komersial. Dengan jaringan lebih dari 30 batching plant yang tersebar di Pulau Jawa dan armada pengangkut yang terus diperluas, PT SIG mendukung pengiriman beton secara cepat dan efisien. Selain produk konvensional, PT SIG juga menawarkan beton inovatif seperti ThruCrete (beton berpori untuk resapan air), DekoCrete (beton dekoratif untuk estetika kawasan), dan SpeedCrete (beton cepat kering). Mengusung prinsip keberlanjutan, PT SIG menggunakan semen ramah lingkungan dan mendukung pengurangan emisi karbon dalam konstruksi. Dengan inovasi digital seperti layanan DynaPay dan komitmen terhadap mutu melalui laboratorium bersertifikasi, PT SIG berperan penting dalam pembangunan infrastruktur yang modern, efisien, dan berkelanjutan di Indonesia.
    
    Berikut adalah hasil peramalan demand readymix selama 12 bulan ke depan:

    {data_summary}

    Berdasarkan data tersebut dan latar belakang perusahaan di atas, lakukan analisis terhadap tren penjualan, temukan insight yang relevan, serta berikan rekomendasi bisnis strategis. Sampaikan dalam bahasa Indonesia yang formal, ringkas, dan berbasis data.
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
    st.title("📊 Peramalan Volume Penjualan ReadyMix Demand")

    conn = st.connection("gsheets", type=GSheetsConnection)

    PAGE_KEY = "demand"

    if f"df_{PAGE_KEY}" not in st.session_state:
        st.session_state[f"df_{PAGE_KEY}"] = preprocess_data(load_gsheet("Demand"), "Demand")
    
    if f"df_forecasting_assumptions_{PAGE_KEY}" not in st.session_state:
        st.session_state[f"df_forecasting_assumptions_{PAGE_KEY}"] = preprocess_data(load_gsheet("Forecasting Demand"), "Forecasting Demand")

    df = st.session_state[f"df_{PAGE_KEY}"]
    forecasting_assumptions = st.session_state[f"df_forecasting_assumptions_{PAGE_KEY}"]

    with st.sidebar:
        st.markdown("🗓️ **Filter Hasil Prediksi**")
        combined_index = pd.date_range(
            start=df.index.min(),
            end=forecasting_assumptions.index.max(),
            freq='MS'
        )
        periode_full = combined_index
        bulan_min = periode_full.min()
        bulan_max = periode_full.max()

        bulan_awal, bulan_akhir = st.slider(
            "Pilih rentang bulan:",
            min_value=bulan_min,
            max_value=bulan_max,
            value=(forecasting_assumptions.index.min().to_pydatetime(), forecasting_assumptions.index.max().to_pydatetime()),
            format="MM/YYYY"
        )

    forecasting_final = None
    try:
        best_features = ['BI Rate', 'Inflasi', 'APBN Infra', 'Effective Working Days']
        model_path = resolve_model_path("models/model_sarimax_Demand.pkl")
        model_fit = load_model(model_path)
        exog_df = forecasting_assumptions[best_features]
        
        forecast_12_months = model_fit.forecast(steps=12, exog=exog_df[:12])
        forecasting_final = pd.DataFrame({
            "Forecasting": forecast_12_months
        }, index=pd.date_range(start=forecasting_assumptions.index.min(), periods=12, freq='MS'))
        
        # FIX: Gunakan key dinamis yang benar
        st.session_state[f"df_forecasting_assumptions_{PAGE_KEY}"]['Forecasting'] = forecasting_final
        
        # Update GSheets
        df_to_update = st.session_state[f"df_forecasting_assumptions_{PAGE_KEY}"].reset_index().copy()
        
        conn.update(worksheet="Forecasting Demand", data=df_to_update)

        df_filtered = df[(df.index >= bulan_awal) & (df.index <= bulan_akhir)]
        
        # Handle historical forecasting if available
        if 'Forecasting' in df_filtered.columns:
             forecasting_existing = df_filtered['Forecasting']
             full_forecasting = pd.concat([forecasting_existing, forecasting_final])
             # Remove duplicates if any index overlaps, keeping the latest (final)
             full_forecasting = full_forecasting[~full_forecasting.index.duplicated(keep='last')]
        else:
             full_forecasting = forecasting_final
        
        # Filter full_forecasting based on slider
        full_forecasting = full_forecasting[(full_forecasting.index >= bulan_awal) & (full_forecasting.index <= bulan_akhir)]

        st.subheader("📈 Hasil Peramalan")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=full_forecasting.index,
            y=full_forecasting["Forecasting"],
            mode="lines+markers+text",
            name="Demand Prediksi",
            textposition="top center",
            line=dict(color="royalblue", width=3),
            marker=dict(size=7, symbol="circle"),
            hovertemplate="Demand Prediksi: %{y:.2f}<extra></extra>"
        ))

        fig.add_trace(go.Scatter(
            x=df_filtered.index,
            y=df_filtered["Demand"],
            mode="lines+markers+text",
            name="Demand Aktual",
            line=dict(color="firebrick", width=3),
            marker=dict(size=7, symbol="circle"),
            hovertemplate="Demand Aktual: %{y:.2f}<extra></extra>"
        ))

        fig.update_layout(
            xaxis_title="Periode",
            yaxis_title="Demand",
            template="plotly_white",
            hovermode="x unified",
            margin=dict(t=40, b=40, l=20, r=20),
            height=500,
            autosize=True,
            legend=dict(title="Keterangan", orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Gagal memuat model SARIMAX atau menghitung prediksi: {e}")
        forecasting_final = None

    if forecasting_final is not None:
        st.subheader("🧠 Rekomendasi Strategis")
        with st.spinner("Menghasilkan analisis dengan AI..."):
            insight = generate_insight_with_gpt(forecasting_final)
            st.markdown(insight)

if __name__ == "__main__" or st.runtime.exists():
    show()

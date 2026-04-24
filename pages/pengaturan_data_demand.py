import streamlit as st
import pandas as pd
import requests
import urllib3
import html
from bs4 import BeautifulSoup
import holidays
from datetime import date, timedelta
import time
import database

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ═══════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════

def get_effective_working_days(year, month):
    indo_holidays = holidays.country_holidays('ID', years=[year])
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    current = start_date
    workdays = 0
    while current <= end_date:
        if current.weekday() < 5 and current not in indo_holidays:
            workdays += 1
        current += timedelta(days=1)
    return float(workdays)


def scrape_inflasi():
    try:
        API_KEY = st.secrets['scraping']['api_key']
        url = f"https://webapi.bps.go.id/v1/api/view/domain/0000/model/statictable/lang/ind/id/915/key/{API_KEY}"
        response = requests.get(url, verify=False)
        json_data = response.json()
        html_encoded = json_data["data"]["table"]
        html_decoded = html.unescape(html_encoded)
        soup = BeautifulSoup(html_decoded, "html.parser")
        rows = soup.find_all('tr')
        data_months, data_years, data_inflation = [], [], []
        for row in rows:
            months = row.find_all('td', class_='xl6622202')
            months = [col.get_text(strip=True) for col in months]
            if months:
                data_months.append(months[0].replace('\xa0', '').strip())
        for row in rows:
            years = row.find_all('td', class_='xl7022202')
            years = [col.get_text(strip=True) for col in years]
            if years:
                data_years = years
        for row in rows:
            values = row.find_all('td', class_=['xl7222202', 'xl7122202'])
            values = [col.get_text(strip=True) for col in values]
            if values:
                data_inflation.append(values)
        inflation_data = []
        for i in range(len(data_months)):
            for j in range(len(data_years)):
                inflation_data.append({
                    'Tahun': data_years[j],
                    'Bulan': data_months[i],
                    'Inflasi': data_inflation[i][j] if j < len(data_inflation[i]) else None
                })
        df = pd.DataFrame(inflation_data)
        df['Inflasi'] = df['Inflasi'].str.replace(',', '.', regex=False)
        df['Inflasi'] = pd.to_numeric(df['Inflasi'], errors='coerce')
        df = df.dropna(subset=['Inflasi']).reset_index(drop=True)
        df['Inflasi'] = df['Inflasi'] / 100
        df['Tahun'] = df['Tahun'].astype(int)
        month_map = {
            "Januari": 1, "Februari": 2, "Maret": 3, "April": 4, "Mei": 5, "Juni": 6,
            "Juli": 7, "Agustus": 8, "September": 9, "Oktober": 10, "November": 11, "Desember": 12
        }
        df["Bulan"] = df["Bulan"].map(month_map)
        df['Periode'] = pd.to_datetime({'year': df['Tahun'], 'month': df['Bulan'], 'day': 1})
        return df.set_index('Periode')[['Inflasi']].sort_index()
    except Exception as e:
        st.error(f"Gagal scrape inflasi: {e}")
        return pd.DataFrame()


def scrape_bi_rate():
    try:
        API_KEY = st.secrets['scraping']['api_key']
        url = f'https://webapi.bps.go.id/v1/api/list/model/data/lang/ind/domain/0000/var/379/key/{API_KEY}?th=2020-2026'
        response = requests.get(url, verify=False)
        data = response.json()
        datacontent = data.get('datacontent', {})
        data_list = []
        for kode, value in datacontent.items():
            timecode = kode[6:]
            try:
                if len(timecode) == 3:
                    bulan = int(timecode[2])
                    tahun = 2000 + int(timecode[:2])
                elif len(timecode) == 4:
                    bulan = int(timecode[2:])
                    tahun = 2000 + int(timecode[:2])
                else:
                    continue
            except ValueError:
                continue
            data_list.append({'Tahun': tahun, 'Bulan': bulan, 'BI Rate': float(value)})
        df = pd.DataFrame(data_list)
        df = df[df['Bulan'] <= 12]
        df['BI Rate'] = df['BI Rate'] / 100
        df['Periode'] = pd.to_datetime({'year': df['Tahun'], 'month': df['Bulan'], 'day': 1})
        return df.set_index('Periode')[['BI Rate']].sort_index()
    except Exception as e:
        st.error(f"Gagal scrape BI Rate: {e}")
        return pd.DataFrame()


def compute_ewd_for_periods(periods):
    """Compute EWD for a list of datetime indices."""
    data = []
    for p in periods:
        data.append({
            'Periode': p,
            'Effective Working Days': get_effective_working_days(p.year, p.month)
        })
    return pd.DataFrame(data).set_index('Periode')


def run_scraping(table_name, df_actual):
    """Run auto-scraping and update the actual table."""
    st.info("🔄 Mengambil Inflasi dari BPS...")
    df_inf = scrape_inflasi()
    st.info("🔄 Mengambil BI Rate dari BPS...")
    df_bi = scrape_bi_rate()

    # Logic: Batas pengisian adalah ketersediaan BI Rate DAN Inflasi
    if df_inf.empty or df_bi.empty:
        st.warning("⚠️ Data Inflasi atau BI Rate tidak tersedia. Proses dibatalkan.")
        return 0

    # Cari irisan periode yang tersedia di keduanya
    common_index = df_inf.index.intersection(df_bi.index)
    if common_index.empty:
        st.warning("⚠️ Tidak ada periode yang tumpang tindih antara data Inflasi dan BI Rate.")
        return 0

    max_p = common_index.max()
    st.success(f"📅 Batas pengisian data (EWD & PDB) ditetapkan hingga: {max_p.strftime('%B %Y')}")

    st.info("🔄 Menghitung Effective Working Days...")
    # Hitung EWD untuk semua periode yang tersedia dari scraping
    df_ewd = compute_ewd_for_periods(common_index)

    # PDB Konstruksi: ambil dari forecast_exog_2026
    exog_2026 = database.get_data("forecast_exog_2026")

    count = 0
    # Iterasi berdasarkan periode yang DITEMUKAN saat scraping (2021 - max_p)
    process_periods = common_index[common_index.year >= 2021]
    
    for p in process_periods:
        updates = {}
        if p in df_inf.index:
            updates['Inflasi'] = float(df_inf.loc[p, 'Inflasi'])
        if p in df_bi.index:
            updates['BI Rate'] = float(df_bi.loc[p, 'BI Rate'])
        if p in df_ewd.index:
            updates['Effective Working Days'] = float(df_ewd.loc[p, 'Effective Working Days'])
        
        # PDB Konstruksi: Ambil dari asumsi forecast jika sudah masuk tahun 2026
        if p.year >= 2026 and not exog_2026.empty and p in exog_2026.index:
            updates['PDB Konstruksi'] = float(exog_2026.loc[p, 'PDB Konstruksi'])

        if updates:
            database.update_single_row(table_name, p.strftime('%Y-%m-%d'), updates)
            count += 1

    return count


# ═══════════════════════════════════════════════════════════════════════
# Page: Pengaturan Data Demand
# ═══════════════════════════════════════════════════════════════════════

def show():
    st.title("⚙️ Pengaturan Data Demand")

    df = database.get_data("demand_actual")
    exog_2026 = database.get_data("forecast_exog_2026")

    # ── Data Aktual ──────────────────────────────────────────────────
    st.subheader("📋 Data Aktual Demand")
    st.dataframe(df, use_container_width=True)

    # ── Auto Scraping ────────────────────────────────────────────────
    with st.expander("🔄 Update Data Otomatis (Scraping)", expanded=False):
        st.caption("Inflasi & BI Rate dari API BPS, EWD dari library holidays, PDB Konstruksi dari tabel forecast.")
        if st.button("Ambil Data dari API", type="primary", key="scrape_demand"):
            with st.spinner("Mengambil dan memproses data..."):
                count = run_scraping("demand_actual", df)
                st.success(f"✅ {count} baris diperbarui!")
                time.sleep(1)
                st.rerun()

    # ── CRUD ─────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        with st.expander("➕ Input Data Baru", expanded=True):
            last_p = df.index.max() if not df.empty else pd.Timestamp.today()
            default_p = (last_p + pd.offsets.MonthBegin(1)).replace(day=1)

            periode = st.date_input("Periode", value=default_p, format="YYYY-MM-DD", key="d_new_p")
            inflasi = st.number_input("Inflasi", value=0.0, format="%.6f", key="d_new_inf")
            bi_rate = st.number_input("BI Rate", value=0.0, format="%.6f", key="d_new_bi")
            pdb = st.number_input("PDB Konstruksi", value=0.0, format="%.2f", key="d_new_pdb")
            ewd = st.number_input("Hari Kerja Efektif", min_value=0, max_value=31,
                                  value=int(get_effective_working_days(default_p.year, default_p.month)), key="d_new_ewd")
            demand = st.number_input("Demand Aktual (m³)", value=0.0, format="%.2f", key="d_new_demand")

            if st.button("Simpan", type="primary", key="d_save"):
                database.update_single_row("demand_actual", periode.strftime('%Y-%m-%d'), {
                    "Inflasi": float(inflasi), "BI Rate": float(bi_rate),
                    "PDB Konstruksi": float(pdb), "Effective Working Days": float(ewd),
                    "Demand": float(demand)
                })
                st.toast("Data disimpan!", icon="✅")
                time.sleep(1)
                st.rerun()

    with col2:
        with st.expander("✏️ Edit Data", expanded=True):
            if not df.empty:
                p_list = df.index.strftime("%Y-%m-%d").tolist()
                sel = st.selectbox("Pilih Periode", p_list, index=len(p_list)-1, key="d_edit_sel")
                p = pd.to_datetime(sel)
                row = df.loc[p]

                # Gunakan dynamic key f"{key}_{sel}" agar widget refresh saat periode ganti
                e_inf = st.number_input("Inflasi", value=float(row.get('Inflasi', 0) or 0), format="%.6f", key=f"d_e_inf_{sel}")
                e_bi = st.number_input("BI Rate", value=float(row.get('BI Rate', 0) or 0), format="%.6f", key=f"d_e_bi_{sel}")
                e_pdb = st.number_input("PDB Konstruksi", value=float(row.get('PDB Konstruksi', 0) or 0), format="%.2f", key=f"d_e_pdb_{sel}")
                raw_ewd = row.get('Effective Working Days', 0)
                val_ewd = int(raw_ewd) if pd.notna(raw_ewd) else 0
                e_ewd = st.number_input("EWD", min_value=0, max_value=31, value=val_ewd, key=f"d_e_ewd_{sel}")
                e_dem = st.number_input("Demand (m³)", value=float(row.get('Demand', 0) or 0), format="%.2f", key=f"d_e_dem_{sel}")

                if st.button("Perbarui", type="primary", key="d_update"):
                    database.update_single_row("demand_actual", sel, {
                        "Inflasi": float(e_inf), "BI Rate": float(e_bi),
                        "PDB Konstruksi": float(e_pdb), "Effective Working Days": float(e_ewd),
                        "Demand": float(e_dem)
                    })
                    st.toast("Data diperbarui!", icon="✅")
                    time.sleep(1)
                    st.rerun()

    with col3:
        with st.expander("🗑️ Hapus Data", expanded=True):
            if not df.empty:
                h_p = st.selectbox("Pilih Periode", df.index.strftime("%Y-%m-%d").tolist(), key="d_del_sel")
                confirm = st.checkbox("Konfirmasi hapus", key="d_confirm")
                if st.button("Hapus", type="primary", key="d_del"):
                    if confirm:
                        database.delete_row("demand_actual", h_p)
                        st.toast("Data dihapus!", icon="🗑️")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("Centang konfirmasi.")

    # ── Shared Forecast Exog 2026 Editor ─────────────────────────────
    st.subheader("📊 Input Variabel Eksogen Forecast 2026")
    st.caption("Tabel ini digunakan sebagai input untuk semua model (Demand, VUB, SBB).")
    edited_exog = st.data_editor(exog_2026, use_container_width=True, key="d_exog_editor")
    if st.button("Simpan Perubahan Eksogen 2026", key="d_save_exog"):
        database.save_data("forecast_exog_2026", edited_exog)
        st.success("Data eksogen 2026 diperbarui!")
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    show()
elif st.runtime.exists():
    show()

import streamlit as st

st.title("📊 Peramalan Volume Penjualan ReadyMix")

st.write(
    "Aplikasi ini digunakan untuk memprediksi volume penjualan ReadyMix SBB, VUB dan juga Demand selama 1 tahun ke depan berdasarkan data internal perusahaan dan faktor makro eksternal"
)

st.markdown("---")

# Tampilan dua pilihan
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🔹 ReadyMix SBB")
    st.write("Lihat tren dan peramalan penjualan ReadyMix SBB selama 1 tahun ke depan.")
    if st.button("📊 Buka Dashboard SBB", type="primary"):
        st.switch_page("pages/sbb.py")

with col2:
    st.subheader("🔸 ReadyMix VUB")
    st.write("Lihat tren dan peramalan penjualan ReadyMix VUB selama 1 tahun ke depan.")
    if st.button("📊 Buka Dashboard VUB", type="primary"):
        st.switch_page("pages/vub.py")

with col3:
    st.subheader("🔹 Demand")
    st.write("Lihat tren dan peramalan penjualan Demand selama 1 tahun ke depan.")
    if st.button("📊 Buka Dashboard Demand", type="primary"):
        st.switch_page("pages/demand.py")

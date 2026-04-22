import datetime
import io
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import utils

st.set_page_config(page_title="Piyasa Verileri", layout="wide")
utils.apply_theme()

utils.require_login_page()

utils.page_header(
    "📊 Resmi Piyasa Verileri",
    "TCMB EVDS (TÜFE hibrit 2003/2025) + BIS (politika faizi)",
)

# Tarih seçimi
c1, c2, c3 = st.columns([1, 1, 2])
start_date = c1.date_input("Başlangıç", datetime.date(2023, 1, 1))
end_date = c2.date_input("Bitiş", datetime.date.today())

if start_date > end_date:
    st.error("Başlangıç tarihi bitiş tarihinden büyük olamaz.")
    st.stop()

if st.button("🔄 Verileri Getir", type="primary"):
    with st.spinner("TCMB EVDS ve BIS sunucularına bağlanılıyor..."):
        df, err = utils.fetch_market_data_adapter(start_date, end_date)

    if err and (df is None or df.empty):
        st.error(f"Veri çekme hatası: {err}")
    elif df is None or df.empty:
        st.warning("Seçilen tarih aralığında veri bulunamadı.")
    else:
        st.success(f"✅ {len(df)} aylık gözlem getirildi.")

        # Grafik
        fig = go.Figure()
        if "Aylık TÜFE" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Donem"], y=df["Aylık TÜFE"],
                mode="lines+markers", name="Aylık TÜFE (%)",
                line=dict(color="#F59E0B", width=2),
            ))
        if "Yıllık TÜFE" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Donem"], y=df["Yıllık TÜFE"],
                mode="lines+markers", name="Yıllık TÜFE (%)",
                line=dict(color="#EF4444", width=2),
                yaxis="y2",
            ))
        if "PPK Faizi" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Donem"], y=df["PPK Faizi"],
                mode="lines+markers", name="PPK Faizi (%)",
                line=dict(color="#3B82F6", width=2, dash="dash"),
                yaxis="y2",
            ))

        fig.update_layout(
            title="TÜFE ve Politika Faizi",
            hovermode="x unified",
            legend=dict(orientation="h", y=1.1),
            yaxis=dict(title="Aylık TÜFE (%)", side="left"),
            yaxis2=dict(
                title="Yıllık TÜFE / PPK Faizi (%)",
                side="right", overlaying="y",
            ),
            height=450,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=60, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tablo
        st.markdown("#### Aylık Veri Tablosu")
        display_df = df.drop(columns=[c for c in ["SortDate"] if c in df.columns])
        fmt_map = {}
        for c in ["Aylık TÜFE", "Yıllık TÜFE", "PPK Faizi"]:
            if c in display_df.columns:
                fmt_map[c] = "{:.2f}%"

        st.dataframe(
            display_df.style.format(fmt_map, na_rep="—"),
            use_container_width=True,
            height=500,
        )

        # İndir
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
            display_df.to_excel(writer, index=False, sheet_name="Piyasa_Verileri")

        st.download_button(
            "📥 Excel Olarak İndir",
            out.getvalue(),
            file_name=f"piyasa_verileri_{start_date}_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Verileri görüntülemek için tarih aralığını seçip butona basınız.")

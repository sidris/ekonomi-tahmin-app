import streamlit as st
import pandas as pd
import utils
import datetime
import io

st.set_page_config(page_title="Piyasa Verileri", layout="wide")

if not utils.check_login():
    st.warning("Lütfen giriş yapınız.")
    st.stop()

st.title("📊 Resmi Piyasa Verileri")
st.markdown("Bu sayfadaki veriler **TCMB (EVDS)** ve **BIS** servislerinden canlı olarak çekilmektedir.")

# --- Tarih Seçimi ---
c1, c2, c3 = st.columns([1, 1, 2])
start_date = c1.date_input("Başlangıç Tarihi", datetime.date(2023, 1, 1))
end_date = c2.date_input("Bitiş Tarihi", datetime.date.today())

# --- Veri Çekme Butonu ---
if st.button("🔄 Verileri Getir", type="primary"):
    with st.spinner("TCMB ve BIS sunucularına bağlanılıyor..."):
        # Utils içindeki fonksiyonu kullanıyoruz
        df, err = utils.fetch_market_data_adapter(start_date, end_date)
        
        if not df.empty:
            st.success("Veriler başarıyla çekildi.")
            
            # Tabloyu Göster
            st.dataframe(
                df.style.format({
                    "Aylık TÜFE": "{:.2f}%",
                    "Yıllık TÜFE": "{:.2f}%",
                    "PPK Faizi": "{:.2f}%"
                }), 
                use_container_width=True, 
                height=600
            )
            
            # İndirme Butonu (Excel)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Piyasa_Verileri')
            
            st.download_button(
                label="📥 Tabloyu Excel Olarak İndir",
                data=output.getvalue(),
                file_name=f"piyasa_verileri_{start_date}_{end_date}.xlsx",
                mime="application/vnd.ms-excel"
            )
            
        else:
            if err:
                st.error(f"Veri çekme hatası: {err}")
            else:
                st.warning("Seçilen tarih aralığında veri bulunamadı.")
else:
    st.info("Verileri görüntülemek için tarih aralığını seçip butona basınız.")

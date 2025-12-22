import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import datetime

# --- 1. AYARLAR VE BAĞLANTI ---
st.set_page_config(page_title="Ekonomi Tahmin Platformu", layout="wide")

# Supabase bağlantısı
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Lütfen .streamlit/secrets.toml dosyanızı veya Cloud Secrets ayarlarınızı kontrol edin.")
    st.stop()

# TABLO ADI (Senin veritabanındaki tablo adın)
TABLE_NAME = "tahminler4"

# --- YARDIMCI FONKSİYON: DÖNEM LİSTESİ OLUŞTURUCU ---
def get_period_list():
    # 2025'ten 2029'a kadar
    years = range(2025, 2030)
    months = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    period_list = []
    for y in years:
        for m in months:
            period_list.append(f"{y}-{m}")
    return period_list

tum_donemler = get_period_list()

# --- 2. GİRİŞ EKRANI KONTROLÜ ---
if 'giris_yapildi' not in st.session_state:
    st.session_state['giris_yapildi'] = False

def sifre_kontrol():
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("### 🔐 Giriş")
        sifre = st.text_input("Panel Şifresi", type="password")
        if st.button("Giriş Yap", use_container_width=True):
            if sifre == SITE_SIFRESI:
                st.session_state['giris_yapildi'] = True
                st.rerun()
            else:
                st.error("Hatalı şifre!")

if not st.session_state['giris_yapildi']:
    sifre_kontrol()
    st.stop()

# --- 3. ANA UYGULAMA ---
st.title("📈 Makroekonomi Tahmin Paneli")
st.markdown("---")

# Menü Yapısı (Artık 3 seçeneğimiz var)
page = st.sidebar.radio("Menü", ["➕ Yeni Tahmin Gir", "✏️ Düzenle / Sil", "📊 Dashboard & Analiz"])

# ========================================================
# SAYFA 1: YENİ VERİ GİRİŞİ
# ========================================================
if page == "➕ Yeni Tahmin Gir":
    st.header("Yeni Veri Girişi")
    st.info("2025 - 2029 yılları için tahminlerinizi girebilirsiniz.")

    with st.form("tahmin_formu"):
        col_id1, col_id2 = st.columns(2)
        with col_id1:
            kullanici = st.text_input("Adınız Soyadınız")
        with col_id2:
            # Otomatik oluşturulan liste
            donem = st.selectbox("Tahmin Dönemi", tum_donemler)

        st.markdown("### 📝 Tahminler")
        col1, col2 = st.columns(2)
        col3, col4 = st.columns(2)

        with col1:
            val_aylik = st.number_input("1. Aylık Enflasyon Tahmini (%)", step=0.1, format="%.2f")
        with col2:
            val_yillik = st.number_input("2. Yıllık Enflasyon Tahmini (%)", step=0.1, format="%.2f")
        with col3:
            val_yilsonu = st.number_input("3. Yıl Sonu Enflasyon Beklentisi (%)", step=0.1, format="%.2f")
        with col4:
            val_faiz = st.number_input("4. PPK Faiz Kararı Tahmini (%)", step=0.25, format="%.2f")

        submit_btn = st.form_submit_button("Tahmini Kaydet", use_container_width=True)

        if submit_btn:
            if kullanici and donem:
                yeni_veri = {
                    "kullanici_adi": kullanici,
                    "donem": donem,
                    "tahmin_aylik_enf": val_aylik,
                    "tahmin_yillik_enf": val_yillik,
                    "tahmin_yilsonu_enf": val_yilsonu,
                    "tahmin_ppk_faiz": val_faiz
                }
                try:
                    supabase.table(TABLE_NAME).insert(yeni_veri).execute()
                    st.success(f"✅ {kullanici}, {donem} tahmini başarıyla kaydedildi!")
                except Exception as e:
                    st.error(f"Kayıt sırasında hata oluştu: {e}")
            else:
                st.warning("⚠️ Lütfen isminizi girmeyi unutmayın.")

# ========================================================
# SAYFA 2: DÜZENLEME VE SİLME (YENİ)
# ========================================================
elif page == "✏️ Düzenle / Sil":
    st.header("Veri Düzenleme ve Silme")
    st.warning("Burada yapılan değişiklikler veritabanına anında işlenir.")

    # 1. Adım: Kullanıcı Seçimi
    # Veritabanından benzersiz kullanıcı isimlerini çekelim
    res_users = supabase.table(TABLE_NAME).select("kullanici_adi").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        user_list = df_users["kullanici_adi"].unique()
        selected_user_edit = st.selectbox("Hangi kullanıcının verisi düzenlenecek?", user_list)

        # 2. Adım: O kullanıcının kayıtlarını getir
        res_records = supabase.table(TABLE_NAME).select("*").eq("kullanici_adi", selected_user_edit).order("donem", desc=True).execute()
        df_records = pd.DataFrame(res_records.data)

        if not df_records.empty:
            # Seçim kutusu için format: "2025-01 | Aylık: %3.5..."
            record_options = {f"{row['donem']} (ID: {row['id']})": row for index, row in df_records.iterrows()}
            selected_option_key = st.selectbox("Düzenlemek istediğiniz kaydı seçin:", list(record_options.keys()))
            
            # Seçilen kaydın verilerini al
            selected_record = record_options[selected_option_key]

            st.markdown("---")
            st.subheader(f"{selected_record['donem']} Dönemi Düzenleniyor")

            # 3. Adım: Düzenleme Formu (Mevcut değerlerle dolu gelir)
            with st.form("edit_form"):
                col_e1, col_e2 = st.columns(2)
                col_e3, col_e4 = st.columns(2)

                # Mevcut değerleri varsayılan olarak atıyoruz
                new_aylik = col_e1.number_input("Aylık Enflasyon", value=float(selected_record['tahmin_aylik_enf']), step=0.1, format="%.2f")
                new_yillik = col_e2.number_input("Yıllık Enflasyon", value=float(selected_record['tahmin_yillik_enf']), step=0.1, format="%.2f")
                new_yilsonu = col_e3.number_input("Yıl Sonu Beklentisi", value=float(selected_record['tahmin_yilsonu_enf']), step=0.1, format="%.2f")
                new_faiz = col_e4.number_input("PPK Faiz Tahmini", value=float(selected_record['tahmin_ppk_faiz']), step=0.25, format="%.2f")

                col_btn1, col_btn2 = st.columns([1,1])
                with col_btn1:
                    update_btn = st.form_submit_button("💾 Güncelle", type="primary", use_container_width=True)
                with col_btn2:
                    # Silme butonu form içinde riskli olabilir ama Streamlit'te form içi buton kullanımı kısıtlıdır.
                    # Güvenlik için checkbox kullanacağız.
                    delete_check = st.checkbox("Bu kaydı silmek istiyorum")
                    delete_btn = st.form_submit_button("🗑️ Sil", type="secondary", use_container_width=True)

                if update_btn:
                    update_data = {
                        "tahmin_aylik_enf": new_aylik,
                        "tahmin_yillik_enf": new_yillik,
                        "tahmin_yilsonu_enf": new_yilsonu,
                        "tahmin_ppk_faiz": new_faiz
                    }
                    supabase.table(TABLE_NAME).update(update_data).eq("id", selected_record['id']).execute()
                    st.success("Kayıt güncellendi! Listeyi yenilemek için sayfayı yenileyin.")
                
                if delete_btn:
                    if delete_check:
                        supabase.table(TABLE_NAME).delete().eq("id", selected_record['id']).execute()
                        st.success("Kayıt silindi! Sayfayı yenileyin.")
                    else:
                        st.error("Silmek için lütfen onay kutusunu işaretleyin.")

        else:
            st.info("Bu kullanıcıya ait kayıt bulunamadı.")
    else:
        st.info("Henüz hiç veri girişi yapılmamış.")

# ========================================================
# SAYFA 3: DASHBOARD
# ========================================================
elif page == "📊 Dashboard & Analiz":
    st.header("Tahmin Analizleri")

    # Veriyi Çek
    response = supabase.table(TABLE_NAME).select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        df = df.sort_values(by="donem")

        # FİLTRELER
        st.sidebar.markdown("---")
        st.sidebar.header("🔍 Filtreler")
        
        # Kişi Filtresi
        all_users = list(df["kullanici_adi"].unique())
        selected_users = st.sidebar.multiselect("Kişileri Seç", all_users, default=all_users)
        
        # Dönem/Yıl Filtresi
        # Yılları ayrıştırıp filtreye koyalım
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
        available_years = list(df['yil'].unique())
        selected_years = st.sidebar.multiselect("Yıl Seç", available_years, default=available_years)

        # Filtreyi Uygula
        df_filtered = df[
            df["kullanici_adi"].isin(selected_users) & 
            df["yil"].isin(selected_years)
        ]

        if df_filtered.empty:
            st.warning("Seçilen kriterlere uygun veri yok.")
            st.stop()

        # GRAFİKLER
        tab1, tab2, tab3, tab4 = st.tabs(["📅 Aylık TÜFE", "📉 Yıllık TÜFE", "🏁 Yıl Sonu TÜFE", "bank PPK Faizi"])

        def cizgi_grafik_ciz(dataframe, y_ekseni, baslik, y_label):
            fig = px.line(dataframe, x="donem", y=y_ekseni, color="kullanici_adi", 
                          markers=True, title=baslik,
                          hover_data=[y_ekseni])
            fig.update_layout(yaxis_title=y_label, xaxis_title="Dönem")
            st.plotly_chart(fig, use_container_width=True)

        with tab1:
            cizgi_grafik_ciz(df_filtered, "tahmin_aylik_enf", "Aylık Enflasyon Tahminleri", "Aylık Enflasyon (%)")   
        with tab2:
            cizgi_grafik_ciz(df_filtered, "tahmin_yillik_enf", "Yıllık (YoY) Enflasyon Tahminleri", "Yıllık Enflasyon (%)")
        with tab3:
            cizgi_grafik_ciz(df_filtered, "tahmin_yilsonu_enf", "Yıl Sonu Enflasyon Beklentisi", "Yıl Sonu TÜFE (%)")
        with tab4:
            cizgi_grafik_ciz(df_filtered, "tahmin_ppk_faiz", "PPK Faiz Kararı Beklentisi", "Politika Faizi (%)")

        st.markdown("---")
        st.subheader("📋 Detaylı Veri Tablosu")
        st.dataframe(df_filtered, use_container_width=True)

    else:
        st.info("Görüntülenecek veri yok.")

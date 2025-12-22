import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px

# --- 1. AYARLAR VE BAĞLANTI ---
st.set_page_config(page_title="Ekonomi Tahmin Platformu", layout="wide")

# Supabase bağlantısı (Streamlit Secrets'tan gelir)
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Lütfen .streamlit/secrets.toml dosyanızı veya Cloud Secrets ayarlarınızı kontrol edin.")
    st.stop()

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

# Yan Menü (Sidebar) - Navigasyon
page = st.sidebar.radio("Menü", ["➕ Yeni Tahmin Gir", "📊 Dashboard & Analiz"])

# --- SAYFA 1: VERİ GİRİŞİ ---
if page == "➕ Yeni Tahmin Gir":
    st.header("Veri Giriş Formu")
    st.info("Lütfen ilgili ay için tahminlerinizi ondalık kısmını nokta (.) ile giriniz.")

    with st.form("tahmin_formu"):
        # Kimlik ve Dönem
        col_id1, col_id2 = st.columns(2)
        with col_id1:
            kullanici = st.text_input("Adınız Soyadınız (Örn: Ahmet Yılmaz)")
        with col_id2:
            donem = st.selectbox("Tahmin Dönemi", 
                                 ["2025-01 (Ocak)", "2025-02 (Şubat)", "2025-03 (Mart)", 
                                  "2025-04 (Nisan)", "2025-05 (Mayıs)", "2025-06 (Haziran)",
                                  "2025-07 (Temmuz)", "2025-08 (Ağustos)", "2025-09 (Eylül)",
                                  "2025-10 (Ekim)", "2025-11 (Kasım)", "2025-12 (Aralık)"])

        st.markdown("### 📝 Tahminler")
        col1, col2 = st.columns(2)
        col3, col4 = st.columns(2)

        with col1:
            val_aylik = st.number_input("1. Aylık Enflasyon Tahmini (%)", step=0.1, format="%.2f")
        with col2:
            val_yillik = st.number_input("2. Yıllık Enflasyon Tahmini (%)", step=0.1, format="%.2f", help="O ay gerçekleşecek yıllık TÜFE")
        with col3:
            val_yilsonu = st.number_input("3. Yıl Sonu Enflasyon Beklentisi (%)", step=0.1, format="%.2f")
        with col4:
            val_faiz = st.number_input("4. PPK Faiz Kararı Tahmini (%)", step=0.25, format="%.2f")

        submit_btn = st.form_submit_button("Tahmini Kaydet", use_container_width=True)

        if submit_btn:
            if kullanici and donem:
                # Veritabanına Yazma İşlemi
                yeni_veri = {
                    "kullanici_adi": kullanici,
                    "donem": donem.split(" ")[0], # Sadece 2025-01 kısmını alır
                    "tahmin_aylik_enf": val_aylik,
                    "tahmin_yillik_enf": val_yillik,
                    "tahmin_yilsonu_enf": val_yilsonu,
                    "tahmin_ppk_faiz": val_faiz
                }
                
                try:
                    supabase.table("tahminler4").insert(yeni_veri).execute()
                    st.success(f"✅ {kullanici}, {donem} dönemi için tahminlerin başarıyla kaydedildi!")
                except Exception as e:
                    st.error(f"Hata oluştu: {e}")
            else:
                st.warning("⚠️ Lütfen isminizi girmeyi unutmayın.")

# --- SAYFA 2: DASHBOARD ---
elif page == "📊 Dashboard & Analiz":
    st.header("Tahmin Analizleri")

    # Veriyi Çek
    response = supabase.table("tahminler4").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        # Dönem sıralaması bozulmasın diye sort edelim
        df = df.sort_values(by="donem")

        # --- FİLTRELEME ALANI ---
        st.sidebar.markdown("---")
        st.sidebar.header("🔍 Filtreler")
        
        # Kişi Filtresi
        all_users = list(df["kullanici_adi"].unique())
        selected_users = st.sidebar.multiselect("Kişileri Seç", all_users, default=all_users)
        
        # Filtreyi Uygula
        df_filtered = df[df["kullanici_adi"].isin(selected_users)]

        if df_filtered.empty:
            st.warning("Seçilen filtreye uygun veri bulunamadı.")
            st.stop()

        # --- GRAFİK SEKMELERİ ---
        tab1, tab2, tab3, tab4 = st.tabs(["📅 Aylık TÜFE", "📉 Yıllık TÜFE", "🏁 Yıl Sonu TÜFE", "bank PPK Faizi"])

        # Ortak Grafik Fonksiyonu
        def cizgi_grafik_ciz(dataframe, y_ekseni, baslik, y_label):
            fig = px.line(dataframe, x="donem", y=y_ekseni, color="kullanici_adi", 
                          markers=True, title=baslik,
                          hover_data=[y_ekseni])
            fig.update_layout(yaxis_title=y_label, xaxis_title="Dönem")
            st.plotly_chart(fig, use_container_width=True)

        with tab1:
            st.subheader("Aylık Enflasyon Tahminleri")
            cizgi_grafik_ciz(df_filtered, "tahmin_aylik_enf", "Katılımcıların Aylık TÜFE Beklentisi", "Aylık Enflasyon (%)")
            
        with tab2:
            st.subheader("Yıllık Enflasyon Tahminleri")
            cizgi_grafik_ciz(df_filtered, "tahmin_yillik_enf", "Katılımcıların Yıllık (YoY) TÜFE Beklentisi", "Yıllık Enflasyon (%)")

        with tab3:
            st.subheader("Yıl Sonu Enflasyon Beklentisi")
            cizgi_grafik_ciz(df_filtered, "tahmin_yilsonu_enf", "Katılımcıların 2025 Yıl Sonu TÜFE Beklentisi", "Yıl Sonu TÜFE (%)")

        with tab4:
            st.subheader("PPK Faiz Kararı Tahminleri")
            cizgi_grafik_ciz(df_filtered, "tahmin_ppk_faiz", "Katılımcıların Politika Faizi Beklentisi", "Politika Faizi (%)")

        # --- DETAYLI TABLO ---
        st.markdown("---")
        st.subheader("📋 Tüm Veriler")
        st.dataframe(df_filtered, use_container_width=True)

    else:

        st.info("📭 Henüz veri girişi yapılmamış. 'Yeni Tahmin Gir' menüsünden ilk kaydı oluşturabilirsiniz.")

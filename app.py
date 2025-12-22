import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px

# --- 1. AYARLAR VE BAĞLANTI ---
st.set_page_config(page_title="Ekonomi Tahmin Platformu", layout="wide")

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Lütfen secrets ayarlarınızı kontrol edin.")
    st.stop()

TABLE_NAME = "tahminler4"

# --- YARDIMCI FONKSİYONLAR ---

def get_period_list():
    # 2024'ten 2032'ye kadar (2033 dahil değil)
    years = range(2024, 2033)
    months = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    period_list = []
    for y in years:
        for m in months:
            period_list.append(f"{y}-{m}")
    return period_list

tum_donemler = get_period_list()

def normalize_name(name):
    """İsimleri Baş Harfi Büyük hale getirir (örn: ahmet -> Ahmet)"""
    return name.strip().title() if name else ""

# --- 2. GİRİŞ KONTROLÜ ---
if 'giris_yapildi' not in st.session_state:
    st.session_state['giris_yapildi'] = False

def sifre_kontrol():
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("### 🔐 Giriş Paneli")
        sifre = st.text_input("Giriş Şifresi", type="password")
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
st.title("📈 Makroekonomi Tahmin Merkezi")
st.markdown("---")

page = st.sidebar.radio("Menü", ["➕ Yeni Tahmin Ekle", "✏️ Düzenle / İncele", "📊 Genel Dashboard"])

# ========================================================
# SAYFA 1: YENİ VERİ GİRİŞİ (Çakışma Kontrollü)
# ========================================================
if page == "➕ Yeni Tahmin Ekle":
    st.header("Yeni Veri Girişi")
    
    with st.form("tahmin_formu"):
        col_id1, col_id2 = st.columns(2)
        with col_id1:
            raw_user = st.text_input("Adınız Soyadınız")
        with col_id2:
            donem = st.selectbox("Tahmin Dönemi", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)

        st.markdown("### 📝 Tahminler")
        col1, col2 = st.columns(2)
        col3, col4 = st.columns(2)

        with col1:
            val_aylik = st.number_input("1. Aylık Enflasyon (%)", step=0.1, format="%.2f")
        with col2:
            val_yillik = st.number_input("2. Yıllık Enflasyon (%)", step=0.1, format="%.2f")
        with col3:
            val_yilsonu = st.number_input("3. Yıl Sonu Beklentisi (%)", step=0.1, format="%.2f")
        with col4:
            val_faiz = st.number_input("4. PPK Faiz Kararı (%)", step=0.25, format="%.2f")

        submit_btn = st.form_submit_button("Tahmini Kaydet", use_container_width=True)

        if submit_btn:
            if raw_user and donem:
                # İsmi normalize et (Ahmet Yilmaz)
                clean_user = normalize_name(raw_user)
                
                # ÇAKIŞMA KONTROLÜ: Bu kişi bu dönem için daha önce veri girmiş mi?
                check_res = supabase.table(TABLE_NAME)\
                    .select("id")\
                    .eq("kullanici_adi", clean_user)\
                    .eq("donem", donem)\
                    .execute()
                
                if check_res.data:
                    # Kayıt varsa uyarı ver ve dur
                    st.warning(f"⚠️ Dikkat: **{clean_user}** kullanıcısının **{donem}** dönemi için zaten bir kaydı var.")
                    st.info("Bu veriyi değiştirmek için lütfen sol menüden 'Düzenle / İncele' sekmesini kullanın.")
                else:
                    # Kayıt yoksa ekle
                    yeni_veri = {
                        "kullanici_adi": clean_user,
                        "donem": donem,
                        "tahmin_aylik_enf": val_aylik,
                        "tahmin_yillik_enf": val_yillik,
                        "tahmin_yilsonu_enf": val_yilsonu,
                        "tahmin_ppk_faiz": val_faiz
                    }
                    try:
                        supabase.table(TABLE_NAME).insert(yeni_veri).execute()
                        st.success(f"✅ {clean_user}, {donem} tahmini kaydedildi!")
                    except Exception as e:
                        st.error(f"Hata: {e}")
            else:
                st.warning("Lütfen isminizi giriniz.")

# ========================================================
# SAYFA 2: KİŞİ BAZLI İNCELEME VE DÜZENLEME
# ========================================================
elif page == "✏️ Düzenle / İncele":
    st.header("Kişisel Geçmiş ve Düzenleme")
    
    # Tüm kullanıcıları çekip listele
    res_users = supabase.table(TABLE_NAME).select("kullanici_adi").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        # Benzersiz isimler
        user_list = sorted(df_users["kullanici_adi"].unique())
        selected_user = st.selectbox("İşlem yapılacak kişiyi seçin:", user_list)

        # Seçilen kişinin tüm verilerini çek
        res_records = supabase.table(TABLE_NAME)\
            .select("*")\
            .eq("kullanici_adi", selected_user)\
            .order("donem", desc=True)\
            .execute()
        
        df_records = pd.DataFrame(res_records.data)

        if not df_records.empty:
            # --- ZAMAN SERİSİ GRAFİĞİ (KİŞİYE ÖZEL) ---
            st.subheader(f"📊 {selected_user} - Tahmin Grafiği")
            
            # Grafik için veri düzenleme (Long format)
            df_melted = df_records.melt(id_vars=["donem"], 
                                        value_vars=["tahmin_aylik_enf", "tahmin_yillik_enf", "tahmin_yilsonu_enf", "tahmin_ppk_faiz"],
                                        var_name="Veri Tipi", value_name="Değer")
            
            fig_user = px.line(df_melted.sort_values("donem"), x="donem", y="Değer", color="Veri Tipi", markers=True)
            st.plotly_chart(fig_user, use_container_width=True)

            # --- DÜZENLEME ALANI ---
            col_list, col_edit = st.columns([1, 1])
            
            with col_list:
                st.subheader("📋 Geçmiş Kayıt Listesi")
                st.dataframe(df_records[["donem", "tahmin_aylik_enf", "tahmin_yillik_enf", "tahmin_ppk_faiz"]], use_container_width=True)

            with col_edit:
                st.subheader("🛠️ Kayıt Düzenle")
                
                # Hangi dönemi düzenleyecek?
                record_options = {f"{row['donem']}": row for index, row in df_records.iterrows()}
                selected_period_key = st.selectbox("Düzenlenecek Dönemi Seç:", list(record_options.keys()))
                
                target_record = record_options[selected_period_key]

                with st.form("edit_single_form"):
                    st.info(f"{target_record['donem']} verileri düzenleniyor...")
                    
                    e_aylik = st.number_input("Aylık Enf.", value=float(target_record['tahmin_aylik_enf']), step=0.1, format="%.2f")
                    e_yillik = st.number_input("Yıllık Enf.", value=float(target_record['tahmin_yillik_enf']), step=0.1, format="%.2f")
                    e_yilsonu = st.number_input("Yıl Sonu Beklentisi", value=float(target_record['tahmin_yilsonu_enf']), step=0.1, format="%.2f")
                    e_faiz = st.number_input("PPK Faiz", value=float(target_record['tahmin_ppk_faiz']), step=0.25, format="%.2f")

                    btn_col1, btn_col2 = st.columns(2)
                    with btn_col1:
                        update_sub = st.form_submit_button("Değişiklikleri Kaydet", type="primary", use_container_width=True)
                    with btn_col2:
                        del_check = st.checkbox("Silme Onayı")
                        del_sub = st.form_submit_button("Bu Kaydı Sil", type="secondary", use_container_width=True)

                    if update_sub:
                        upd_data = {
                            "tahmin_aylik_enf": e_aylik,
                            "tahmin_yillik_enf": e_yillik,
                            "tahmin_yilsonu_enf": e_yilsonu,
                            "tahmin_ppk_faiz": e_faiz
                        }
                        supabase.table(TABLE_NAME).update(upd_data).eq("id", target_record['id']).execute()
                        st.success("Güncellendi! (Grafik sayfayı yenileyince güncellenir)")
                        
                    if del_sub:
                        if del_check:
                            supabase.table(TABLE_NAME).delete().eq("id", target_record['id']).execute()
                            st.success("Kayıt silindi.")
                        else:
                            st.error("Silmek için kutucuğu işaretleyin.")
        else:
            st.info("Bu kullanıcıya ait kayıt bulunamadı.")
    else:
        st.info("Sistemde henüz kayıtlı kullanıcı yok.")

# ========================================================
# SAYFA 3: GENEL DASHBOARD (TÜM KULLANICILAR)
# ========================================================
elif page == "📊 Genel Dashboard":
    st.header("Genel Piyasa Beklentileri")

    response = supabase.table(TABLE_NAME).select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        df = df.sort_values(by="donem")

        # FİLTRELER
        st.sidebar.markdown("---")
        st.sidebar.header("🔍 Filtreler")
        
        all_users = sorted(list(df["kullanici_adi"].unique()))
        selected_users = st.sidebar.multiselect("Kişileri Karşılaştır", all_users, default=all_users)
        
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
        available_years = sorted(list(df['yil'].unique()))
        selected_years = st.sidebar.multiselect("Yıl Seç", available_years, default=available_years)

        df_filtered = df[df["kullanici_adi"].isin(selected_users) & df["yil"].isin(selected_years)]

        if df_filtered.empty:
            st.warning("Seçilen kriterlere uygun veri yok.")
        else:
            tab1, tab2, tab3, tab4 = st.tabs(["Aylık Enflasyon", "Yıllık Enflasyon", "Yıl Sonu TÜFE", "PPK Faizi"])

            def draw_chart(y_col, title):
                fig = px.line(df_filtered, x="donem", y=y_col, color="kullanici_adi", markers=True, title=title)
                st.plotly_chart(fig, use_container_width=True)

            with tab1: draw_chart("tahmin_aylik_enf", "Aylık Enflasyon Tahminleri")
            with tab2: draw_chart("tahmin_yillik_enf", "Yıllık Enflasyon Tahminleri")
            with tab3: draw_chart("tahmin_yilsonu_enf", "Yıl Sonu Enflasyon Beklentisi")
            with tab4: draw_chart("tahmin_ppk_faiz", "Politika Faizi Beklentisi")
            
            st.markdown("---")
            st.dataframe(df_filtered, use_container_width=True)
    else:
        st.info("Henüz veri girişi yapılmamış.")

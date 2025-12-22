import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"

# --- YARDIMCI FONKSİYONLAR ---
def get_period_list():
    years = range(2024, 2033)
    months = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    period_list = []
    for y in years:
        for m in months:
            period_list.append(f"{y}-{m}")
    return period_list

tum_donemler = get_period_list()

def normalize_name(name):
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

# Menüye "Katılımcı Yönetimi" eklendi
page = st.sidebar.radio("Menü", ["👥 Katılımcı Yönetimi", "➕ Tahmin Ekle", "✏️ Düzenle / İncele", "📊 Genel Dashboard"])

# ========================================================
# SAYFA 0: KATILIMCI YÖNETİMİ (YENİ)
# ========================================================
if page == "👥 Katılımcı Yönetimi":
    st.header("Katılımcı Listesi ve Ekleme")
    
    # 1. Yeni Kişi Ekleme Formu
    with st.form("yeni_kisi_form"):
        st.subheader("Yeni Katılımcı Tanımla")
        c1, c2 = st.columns(2)
        yeni_ad = c1.text_input("Ad Soyad / Kurum Adı")
        yeni_kat = c2.radio("Kategori", ["Bireysel", "Kurumsal"], horizontal=True)
        
        if st.form_submit_button("Listeye Ekle"):
            if yeni_ad:
                clean_ad = normalize_name(yeni_ad)
                try:
                    supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": clean_ad, "kategori": yeni_kat}).execute()
                    st.success(f"{clean_ad} başarıyla eklendi!")
                except Exception as e:
                    st.warning("Bu isim zaten listede olabilir.")
            else:
                st.warning("İsim boş olamaz.")
    
    st.markdown("---")
    
    # 2. Mevcut Listeyi Göster ve Silme
    st.subheader("Mevcut Katılımcılar")
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res.data)
    
    if not df_kat.empty:
        # Düzenleme / Silme Tablosu
        for index, row in df_kat.iterrows():
            col_list1, col_list2, col_list3 = st.columns([3, 1, 1])
            col_list1.write(f"**{row['ad_soyad']}** ({row['kategori']})")
            
            if col_list3.button("Sil", key=f"del_{row['id']}"):
                supabase.table(TABLE_KATILIMCI).delete().eq("id", row['id']).execute()
                st.rerun()
    else:
        st.info("Listeniz boş.")

# ========================================================
# SAYFA 1: YENİ VERİ GİRİŞİ (DROPDOWN İLE)
# ========================================================
elif page == "➕ Tahmin Ekle":
    st.header("Veri Girişi")

    # Önce Katılımcı Listesini Çek
    res_kat = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res_kat.data)

    if df_kat.empty:
        st.error("Lütfen önce 'Katılımcı Yönetimi' menüsünden katılımcı ekleyin.")
        st.stop()

    with st.form("tahmin_formu"):
        col_select, col_donem = st.columns(2)
        
        with col_select:
            # DROPDOWN: İsimleri listele
            selected_person_name = st.selectbox("Katılımcı Seç", df_kat["ad_soyad"].unique())
            # Seçilen kişinin kategorisini otomatik bul
            person_cat = df_kat[df_kat["ad_soyad"] == selected_person_name]["kategori"].iloc[0]
            st.caption(f"Kategori: **{person_cat}** (Otomatik)")

        with col_donem:
            donem = st.selectbox("Tahmin Dönemi", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)

        st.markdown("### 🎯 Temel Tahminler (Medyan)")
        col1, col2 = st.columns(2)
        col3, col4 = st.columns(2)
        with col1: val_aylik = st.number_input("1. Aylık Enflasyon (%)", step=0.1, format="%.2f")
        with col2: val_yillik = st.number_input("2. Yıllık Enflasyon (%)", step=0.1, format="%.2f")
        with col3: val_yilsonu = st.number_input("3. Yıl Sonu Beklentisi (%)", step=0.1, format="%.2f")
        with col4: val_faiz = st.number_input("4. PPK Faiz Kararı (%)", step=0.25, format="%.2f")

        # Aralık Tahminleri
        with st.expander("📊 Anket Aralığı (En Düşük / En Yüksek) - Opsiyonel"):
            st.info("Kurum sadece tek bir rakam açıkladıysa bu alanları 0.00 bırakın.")
            c_min1, c_max1 = st.columns(2)
            min_aylik = c_min1.number_input("Min. Aylık Enf.", step=0.1, key="min_ay")
            max_aylik = c_max1.number_input("Max. Aylık Enf.", step=0.1, key="max_ay")
            c_min2, c_max2 = st.columns(2)
            min_yillik = c_min2.number_input("Min. Yıllık Enf.", step=0.1, key="min_yil")
            max_yillik = c_max2.number_input("Max. Yıllık Enf.", step=0.1, key="max_yil")
            c_min3, c_max3 = st.columns(2)
            min_yilsonu = c_min3.number_input("Min. Yıl Sonu", step=0.1, key="min_ysonu")
            max_yilsonu = c_max3.number_input("Max. Yıl Sonu", step=0.1, key="max_ysonu")
            c_min4, c_max4 = st.columns(2)
            min_faiz = c_min4.number_input("Min. PPK Faiz", step=0.25, key="min_faiz")
            max_faiz = c_max4.number_input("Max. PPK Faiz", step=0.25, key="max_faiz")

        if st.form_submit_button("Kaydet"):
            # Çakışma Kontrolü
            check_res = supabase.table(TABLE_TAHMIN).select("id").eq("kullanici_adi", selected_person_name).eq("donem", donem).execute()
            
            if check_res.data:
                st.warning(f"⚠️ {selected_person_name} için {donem} kaydı zaten var.")
            else:
                def clean_val(val): return val if val != 0 else None
                yeni_veri = {
                    "kullanici_adi": selected_person_name,
                    "donem": donem,
                    "kategori": person_cat, # Kategori veritabanından otomatik gelir
                    "tahmin_aylik_enf": val_aylik, "tahmin_yillik_enf": val_yillik,
                    "tahmin_yilsonu_enf": val_yilsonu, "tahmin_ppk_faiz": val_faiz,
                    "min_aylik_enf": clean_val(min_aylik), "max_aylik_enf": clean_val(max_aylik),
                    "min_yillik_enf": clean_val(min_yillik), "max_yillik_enf": clean_val(max_yillik),
                    "min_yilsonu_enf": clean_val(min_yilsonu), "max_yilsonu_enf": clean_val(max_yilsonu),
                    "min_ppk_faiz": clean_val(min_faiz), "max_ppk_faiz": clean_val(max_faiz),
                }
                supabase.table(TABLE_TAHMIN).insert(yeni_veri).execute()
                st.success(f"✅ {selected_person_name} verisi eklendi!")

# ========================================================
# SAYFA 2: DÜZENLEME
# ========================================================
elif page == "✏️ Düzenle / İncele":
    st.header("Kayıt Düzenleme")
    
    # Katılımcıları yeni tablodan çekiyoruz
    res_users = supabase.table(TABLE_KATILIMCI).select("ad_soyad").order("ad_soyad").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        selected_user = st.selectbox("Düzenlenecek Kişi/Kurum:", df_users["ad_soyad"])

        res_records = supabase.table(TABLE_TAHMIN).select("*").eq("kullanici_adi", selected_user).order("donem", desc=True).execute()
        df_records = pd.DataFrame(res_records.data)

        if not df_records.empty:
            st.dataframe(df_records, use_container_width=True)
            
            record_options = {f"{row['donem']}": row for index, row in df_records.iterrows()}
            selected_period_key = st.selectbox("Dönem Seç:", list(record_options.keys()))
            target_record = record_options[selected_period_key]

            with st.form("edit_single_form"):
                st.subheader("🛠️ Verileri Güncelle")
                c1, c2 = st.columns(2)
                e_aylik = c1.number_input("Aylık Enf.", value=float(target_record['tahmin_aylik_enf'] or 0), step=0.1)
                e_yillik = c2.number_input("Yıllık Enf.", value=float(target_record['tahmin_yillik_enf'] or 0), step=0.1)
                e_yilsonu = c1.number_input("Yıl Sonu", value=float(target_record['tahmin_yilsonu_enf'] or 0), step=0.1)
                e_faiz = c2.number_input("PPK Faiz", value=float(target_record['tahmin_ppk_faiz'] or 0), step=0.25)

                st.markdown("**Min/Max (0 = Boş)**")
                cm1, cm2 = st.columns(2)
                em_min = cm1.number_input("Min Faiz", value=float(target_record.get('min_ppk_faiz') or 0), step=0.25)
                em_max = cm2.number_input("Max Faiz", value=float(target_record.get('max_ppk_faiz') or 0), step=0.25)

                if st.form_submit_button("Güncelle"):
                    def clean_val(val): return val if val != 0 else None
                    upd_data = {
                        "tahmin_aylik_enf": e_aylik, "tahmin_yillik_enf": e_yillik,
                        "tahmin_yilsonu_enf": e_yilsonu, "tahmin_ppk_faiz": e_faiz,
                        "min_ppk_faiz": clean_val(em_min), "max_ppk_faiz": clean_val(em_max)
                    }
                    supabase.table(TABLE_TAHMIN).update(upd_data).eq("id", target_record['id']).execute()
                    st.success("Güncellendi!")
    else:
        st.info("Kayıtlı katılımcı yok.")

# ========================================================
# SAYFA 3: DASHBOARD (Değişiklik yok, aynı mantık)
# ========================================================
elif page == "📊 Genel Dashboard":
    st.header("Piyasa Analiz Dashboardu")

    response = supabase.table(TABLE_TAHMIN).select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        df['kategori'] = df['kategori'].fillna('Bireysel')
        df = df.sort_values(by="donem")

        st.sidebar.header("🔍 Filtreler")
        cat_filter = st.sidebar.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
        available_users = sorted(df[df['kategori'].isin(cat_filter)]['kullanici_adi'].unique())
        user_filter = st.sidebar.multiselect("Katılımcı", available_users, default=available_users)
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
        year_filter = st.sidebar.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        df_filtered = df[df['kategori'].isin(cat_filter) & df['kullanici_adi'].isin(user_filter) & df['yil'].isin(year_filter)]

        if df_filtered.empty: st.stop()

        tab_ts, tab_dev = st.tabs(["📈 Zaman Serisi", "🍭 Medyan Sapma"])

        with tab_ts:
            def plot_with_range(df_sub, y_col, min_col, max_col, title):
                fig = px.line(df_sub, x="donem", y=y_col, color="kullanici_adi", markers=True, title=title)
                df_range = df_sub.dropna(subset=[min_col, max_col])
                if not df_range.empty:
                    for user in df_range['kullanici_adi'].unique():
                        user_data = df_range[df_range['kullanici_adi'] == user]
                        fig.add_trace(go.Scatter(x=user_data['donem'], y=user_data[y_col], mode='markers', error_y=dict(type='data', symmetric=False, array=user_data[max_col] - user_data[y_col], arrayminus=user_data[y_col] - user_data[min_col], color='gray', width=3), showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
            c1, c2 = st.columns(2)
            with c1: plot_with_range(df_filtered, "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Faiz")
            with c2: plot_with_range(df_filtered, "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "Yıl Sonu Enf.")

        with tab_dev:
            target_period = st.selectbox("Dönem Seç", sorted(df_filtered['donem'].unique(), reverse=True), key="loli_period")
            df_period = df_filtered[df_filtered['donem'] == target_period].copy()
            if len(df_period) > 1:
                metric = "tahmin_ppk_faiz"
                median_val = df_period[metric].median()
                df_period['sapma'] = df_period[metric] - median_val
                df_period = df_period.sort_values(by='sapma')
                fig_loli = go.Figure()
                for i, row in df_period.iterrows():
                    color = "crimson" if row['sapma'] < 0 else "seagreen"
                    fig_loli.add_trace(go.Scatter(x=[0, row['sapma']], y=[row['kullanici_adi'], row['kullanici_adi']], mode='lines', line=dict(color=color), showlegend=False))
                    fig_loli.add_trace(go.Scatter(x=[row['sapma']], y=[row['kullanici_adi']], mode='markers', marker=dict(color=color, size=12), name=row['kullanici_adi'], text=f"Tahmin: %{row[metric]}", hoverinfo='text'))
                fig_loli.add_vline(x=0, line_dash="dash", annotation_text="Medyan")
                fig_loli.update_layout(title=f"PPK Faiz - Sapma (Medyan: %{median_val})", height=max(400, len(df_period)*30))
                st.plotly_chart(fig_loli, use_container_width=True)

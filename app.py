import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go # Lolipop grafik için gerekli

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

page = st.sidebar.radio("Menü", ["➕ Tahmin Ekle (Bireysel/Kurum)", "✏️ Düzenle / İncele", "📊 Genel Dashboard"])

# ========================================================
# SAYFA 1: YENİ VERİ GİRİŞİ
# ========================================================
if page == "➕ Tahmin Ekle (Bireysel/Kurum)":
    st.header("Veri Girişi")
    
    with st.form("tahmin_formu"):
        # KATEGORİ SEÇİMİ EKLENDİ
        col_cat, col_dummy = st.columns(2)
        with col_cat:
            kategori_secimi = st.radio("Katılımcı Türü", ["Bireysel", "Kurumsal"], horizontal=True)

        col_id1, col_id2 = st.columns(2)
        with col_id1:
            raw_user = st.text_input("İsim / Kurum Adı (Örn: Ahmet Yılmaz veya JP Morgan)")
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

        submit_btn = st.form_submit_button("Kaydet", use_container_width=True)

        if submit_btn:
            if raw_user and donem:
                clean_user = normalize_name(raw_user)
                
                # Çakışma Kontrolü
                check_res = supabase.table(TABLE_NAME)\
                    .select("id")\
                    .eq("kullanici_adi", clean_user)\
                    .eq("donem", donem)\
                    .execute()
                
                if check_res.data:
                    st.warning(f"⚠️ {clean_user} için {donem} kaydı zaten var. Düzenleme menüsünü kullanın.")
                else:
                    yeni_veri = {
                        "kullanici_adi": clean_user,
                        "donem": donem,
                        "kategori": kategori_secimi, # YENİ ALAN
                        "tahmin_aylik_enf": val_aylik,
                        "tahmin_yillik_enf": val_yillik,
                        "tahmin_yilsonu_enf": val_yilsonu,
                        "tahmin_ppk_faiz": val_faiz
                    }
                    try:
                        supabase.table(TABLE_NAME).insert(yeni_veri).execute()
                        st.success(f"✅ {kategori_secimi}: {clean_user} verisi eklendi!")
                    except Exception as e:
                        st.error(f"Hata: {e}")
            else:
                st.warning("İsim alanı boş bırakılamaz.")

# ========================================================
# SAYFA 2: DÜZENLEME
# ========================================================
elif page == "✏️ Düzenle / İncele":
    st.header("Kayıt Düzenleme")
    
    res_users = supabase.table(TABLE_NAME).select("kullanici_adi", "kategori").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        user_list = sorted(df_users["kullanici_adi"].unique())
        selected_user = st.selectbox("Düzenlenecek Kişi/Kurum:", user_list)

        res_records = supabase.table(TABLE_NAME)\
            .select("*")\
            .eq("kullanici_adi", selected_user)\
            .order("donem", desc=True)\
            .execute()
        
        df_records = pd.DataFrame(res_records.data)

        if not df_records.empty:
            # Tablo gösterimi
            st.dataframe(df_records, use_container_width=True)

            # Düzenleme Formu
            st.subheader("🛠️ Seçili Kaydı Düzenle")
            record_options = {f"{row['donem']}": row for index, row in df_records.iterrows()}
            selected_period_key = st.selectbox("Dönem Seç:", list(record_options.keys()))
            target_record = record_options[selected_period_key]

            with st.form("edit_single_form"):
                # Kategori düzeltme imkanı da verelim
                curr_cat = target_record.get('kategori', 'Bireysel')
                # Eğer null ise 'Bireysel' varsay
                if curr_cat is None: curr_cat = 'Bireysel'
                
                new_cat = st.selectbox("Kategori", ["Bireysel", "Kurumsal"], index=["Bireysel", "Kurumsal"].index(curr_cat))
                
                col_e1, col_e2 = st.columns(2)
                e_aylik = col_e1.number_input("Aylık Enf.", value=float(target_record['tahmin_aylik_enf']), step=0.1)
                e_yillik = col_e2.number_input("Yıllık Enf.", value=float(target_record['tahmin_yillik_enf']), step=0.1)
                
                col_e3, col_e4 = st.columns(2)
                e_yilsonu = col_e3.number_input("Yıl Sonu", value=float(target_record['tahmin_yilsonu_enf']), step=0.1)
                e_faiz = col_e4.number_input("PPK Faiz", value=float(target_record['tahmin_ppk_faiz']), step=0.25)

                if st.form_submit_button("Güncelle"):
                    upd_data = {
                        "kategori": new_cat,
                        "tahmin_aylik_enf": e_aylik,
                        "tahmin_yillik_enf": e_yillik,
                        "tahmin_yilsonu_enf": e_yilsonu,
                        "tahmin_ppk_faiz": e_faiz
                    }
                    supabase.table(TABLE_NAME).update(upd_data).eq("id", target_record['id']).execute()
                    st.success("Kayıt güncellendi!")

# ========================================================
# SAYFA 3: DASHBOARD & LOLIPOP GRAFİK
# ========================================================
elif page == "📊 Genel Dashboard":
    st.header("Piyasa Analiz Dashboardu")

    response = supabase.table(TABLE_NAME).select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        # Veri Temizliği: Kategori boşsa 'Bireysel' doldur
        df['kategori'] = df['kategori'].fillna('Bireysel')
        df = df.sort_values(by="donem")

        # --- FİLTRELER ---
        st.sidebar.header("🔍 Gelişmiş Filtreler")
        
        # 1. Kategori Filtresi
        cat_filter = st.sidebar.multiselect("Kategori Seç", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
        
        # 2. Kişi/Kurum Filtresi
        available_users = sorted(df[df['kategori'].isin(cat_filter)]['kullanici_adi'].unique())
        user_filter = st.sidebar.multiselect("Katılımcı Seç", available_users, default=available_users)
        
        # 3. Yıl Filtresi
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
        year_filter = st.sidebar.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        # Ana Filtreleme
        df_filtered = df[
            df['kategori'].isin(cat_filter) &
            df['kullanici_adi'].isin(user_filter) &
            df['yil'].isin(year_filter)
        ]

        if df_filtered.empty:
            st.warning("Filtrelere uygun veri yok.")
            st.stop()

        # --- SEKMELER ---
        st.markdown("### Analizler")
        tab_ts, tab_dev = st.tabs(["📈 Zaman Serisi (Trend)", "🍭 Medyandan Sapma (Lolipop)"])

        # TAB 1: ZAMAN SERİSİ
        with tab_ts:
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                fig_faiz = px.line(df_filtered, x="donem", y="tahmin_ppk_faiz", color="kullanici_adi", 
                                   title="PPK Faiz Beklentileri", markers=True, symbol="kategori")
                st.plotly_chart(fig_faiz, use_container_width=True)
            with col_t2:
                fig_yilsonu = px.line(df_filtered, x="donem", y="tahmin_yilsonu_enf", color="kullanici_adi", 
                                      title="Yıl Sonu Enflasyon Beklentileri", markers=True, symbol="kategori")
                st.plotly_chart(fig_yilsonu, use_container_width=True)

        # TAB 2: LOLIPOP GRAFİĞİ (Deviation Chart)
        with tab_dev:
            st.subheader("Medyandan Sapma Analizi (Lollipop Chart)")
            st.info("Bu grafik, seçilen dönemde katılımcıların 'Medyan' (Ortanca) tahminden ne kadar saptığını gösterir.")

            # Lolipop için Tek Bir Dönem Seçilmeli
            target_period = st.selectbox("Analiz Edilecek Dönemi Seçin (Lolipop İçin)", sorted(df_filtered['donem'].unique(), reverse=True))
            
            # Seçilen dönem verisi
            df_period = df_filtered[df_filtered['donem'] == target_period].copy()
            
            if len(df_period) > 1:
                # Metrik Seçimi
                metric_map = {
                    "PPK Faizi": "tahmin_ppk_faiz",
                    "Yıl Sonu Enflasyon": "tahmin_yilsonu_enf",
                    "Aylık Enflasyon": "tahmin_aylik_enf",
                    "Yıllık Enflasyon": "tahmin_yillik_enf"
                }
                selected_metric_name = st.radio("Analiz Metriği", list(metric_map.keys()), horizontal=True)
                selected_metric_col = metric_map[selected_metric_name]

                # Medyan Hesapla
                median_val = df_period[selected_metric_col].median()
                st.metric(f"{target_period} Dönemi {selected_metric_name} Medyanı", f"%{median_val:.2f}")

                # Sapmayı Hesapla (Değer - Medyan)
                df_period['sapma'] = df_period[selected_metric_col] - median_val
                df_period = df_period.sort_values(by='sapma') # Grafikte sıralı görünsün

                # --- PLOTLY GRAPH OBJECTS İLE LOLIPOP ÇİZİMİ ---
                fig_lolipop = go.Figure()

                # Her bir kişi için çizgi ve nokta ekle
                for i, row in df_period.iterrows():
                    color = "crimson" if row['sapma'] < 0 else "seagreen" # Negatif kırmızı, Pozitif yeşil
                    
                    # 1. Çizgi (Sapı)
                    fig_lolipop.add_trace(go.Scatter(
                        x=[0, row['sapma']],
                        y=[row['kullanici_adi'], row['kullanici_adi']],
                        mode='lines',
                        line=dict(color=color, width=2),
                        showlegend=False,
                        hoverinfo='skip'
                    ))
                    
                    # 2. Nokta (Şekeri)
                    fig_lolipop.add_trace(go.Scatter(
                        x=[row['sapma']],
                        y=[row['kullanici_adi']],
                        mode='markers',
                        marker=dict(color=color, size=12),
                        name=row['kullanici_adi'],
                        text=f"Tahmin: %{row[selected_metric_col]}<br>Sapma: {row['sapma']:.2f} puan",
                        hoverinfo='text',
                        showlegend=False
                    ))

                # Medyan Çizgisi (0 Noktası)
                fig_lolipop.add_vline(x=0, line_width=2, line_dash="dash", line_color="gray", annotation_text="Medyan")

                fig_lolipop.update_layout(
                    title=f"{target_period} - {selected_metric_name} Sapma Tablosu",
                    xaxis_title=f"Medyandan Sapma (Puan) [Medyan: %{median_val}]",
                    yaxis_title="Katılımcılar",
                    height=max(400, len(df_period) * 30), # Kişi sayısına göre boyutu uzat
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                
                st.plotly_chart(fig_lolipop, use_container_width=True)
            else:
                st.warning("Lolipop grafiği için seçilen dönemde en az 2 katılımcı olmalıdır.")
    else:
        st.info("Veri yok.")

import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import tempfile
import os
import io
import datetime

# --- 1. AYARLAR VE TASARIM ---
st.set_page_config(
    page_title="Ekonomi Tahmin Terminali", 
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# Custom CSS ile arayüzü modernleştirme
st.markdown("""
<style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 10px;
    }
    .stButton button {
        width: 100%;
        border-radius: 8px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

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

def safe_int(val):
    try:
        if pd.isna(val) or val is None: return 0
        return int(float(val))
    except: return 0

def clean_and_sort_data(df):
    if df.empty: return df
    numeric_cols = [
        "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz",
        "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz",
        "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf",
        "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf",
        "katilimci_sayisi"
    ]
    for col in numeric_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    
    if "donem" in df.columns:
        df["temp_date"] = pd.to_datetime(df["donem"], format="%Y-%m", errors='coerce')
        df = df.sort_values(by="temp_date")
        df = df.drop(columns=["temp_date"])
    return df

def upsert_tahmin(user, period, category, forecast_date, link, data_dict):
    date_str = forecast_date.strftime("%Y-%m-%d")
    
    # Aynı gün, aynı dönem, aynı kişi kontrolü
    check_res = supabase.table(TABLE_TAHMIN)\
        .select("id")\
        .eq("kullanici_adi", user)\
        .eq("donem", period)\
        .eq("tahmin_tarihi", date_str)\
        .execute()

    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    clean_data.update({
        "kullanici_adi": user,
        "donem": period,
        "kategori": category,
        "tahmin_tarihi": date_str,
        "kaynak_link": link if link else None # Linki ekle
    })

    if check_res.data:
        record_id = check_res.data[0]['id']
        supabase.table(TABLE_TAHMIN).update(clean_data).eq("id", record_id).execute()
        return "updated"
    else:
        supabase.table(TABLE_TAHMIN).insert(clean_data).execute()
        return "inserted"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Tahminler')
    return output.getvalue()

def create_pdf_report(dataframe, figures):
    class PDF(FPDF):
        def header(self):
            self.set_font('Helvetica', 'B', 15)
            self.cell(0, 10, 'Ekonomi Tahmin Raporu', align='C')
            self.ln(15)
        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.cell(0, 10, f'Sayfa {self.page_no()}', align='C')

    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Rapor Tarihi: {pd.Timestamp.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.ln(5)
    
    for title, fig in figures.items():
        pdf.add_page()
        pdf.set_font("Helvetica", 'B', 14)
        clean_title = title.replace("ı", "i").replace("ğ", "g").replace("ş", "s").replace("İ", "I").replace("ö", "o").replace("ü", "u").replace("ç", "c")
        pdf.cell(0, 10, clean_title, ln=True, align='C')
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
            try:
                fig.write_image(tmpfile.name, width=800, height=500, scale=2)
                pdf.image(tmpfile.name, x=10, y=30, w=190)
            except: pass
        try: os.remove(tmpfile.name)
        except: pass
    return bytes(pdf.output())

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

# --- 3. ANA UYGULAMA VE MODERN ARAYÜZ ---
st.title("📈 Makroekonomi Tahmin Merkezi")
st.markdown("---")

# Yan Menü Tasarımı
with st.sidebar:
    st.header("Menü")
    page = st.radio("Git:", ["📊 Dashboard", "➕ PPK Girişi", "➕ Enflasyon Girişi", "📥 Raporlama & Excel", "⚙️ Düzenle / Sil", "👥 Katılımcı Yönetimi"])
    st.info("💡 **İpucu:** Veri girerken aynı döneme farklı tarihlerde giriş yaparsanız revizyon olarak kaydedilir.")

def get_participant_selection():
    res_kat = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res_kat.data)
    if df_kat.empty:
        st.error("Lütfen önce Katılımcı ekleyin.")
        return None, None, None
    
    df_kat['display'] = df_kat.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
    name_map = dict(zip(df_kat['display'], df_kat['ad_soyad']))
    
    sel_disp = st.selectbox("👤 Katılımcı Seç", df_kat["display"].unique())
    real_name = name_map[sel_disp]
    row = df_kat[df_kat["ad_soyad"] == real_name].iloc[0]
    
    st.caption(f"🔹 Kategori: **{row['kategori']}** | 🔹 Kaynak: {row['anket_kaynagi'] or '-'}")
    return real_name, row['kategori'], sel_disp

# ========================================================
# SAYFA: PPK GİRİŞİ (MODERN UI)
# ========================================================
if page == "➕ PPK Girişi":
    st.subheader("🏦 Faiz Tahmin Girişi")
    
    with st.container(): # Kart Görünümü
        with st.form("ppk_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1: kullanici, kategori, display_name = get_participant_selection()
            with c2: donem = st.selectbox("📅 Dönem", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)
            with c3: tahmin_tarihi = st.date_input("📆 Tahmin Tarihi", datetime.date.today())
            
            # Link Alanı
            st.markdown("")
            kaynak_link = st.text_input("🔗 Kaynak Web Linki (Opsiyonel)", placeholder="https://twitter.com/analiz... veya https://bloomberg.com/...", help="Varsa anketin veya haberin linki")

            st.markdown("---")
            
            # PPK Ana Veriler
            c_ppk1, c_ppk2 = st.columns(2)
            with c_ppk1:
                st.markdown("### 1. Bu Ayki Karar")
                val_faiz = st.number_input("Medyan % (Bu Ay)", step=0.25, format="%.2f")
            with c_ppk2:
                st.markdown("### 2. Sene Sonu Beklenti")
                val_ys_faiz = st.number_input("Medyan % (Sene Sonu)", step=0.25, format="%.2f", key="ys_f")
            
            # Detaylar (Gizli Panel)
            with st.expander("📉 Min / Max Aralık & Katılımcı Sayısı (Opsiyonel)"):
                st.info("Kurum tarafından aralık belirtildiyse doldurunuz.")
                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    st.markdown("**Bu Ay**")
                    min_faiz = st.number_input("Min %", step=0.25, format="%.2f")
                    max_faiz = st.number_input("Max %", step=0.25, format="%.2f")
                with ec2:
                    st.markdown("**Sene Sonu**")
                    min_ys_faiz = st.number_input("Min % (YS)", step=0.25, format="%.2f")
                    max_ys_faiz = st.number_input("Max % (YS)", step=0.25, format="%.2f")
                with ec3:
                    st.markdown("**Detay**")
                    kat_sayisi = st.number_input("Katılımcı (N)", min_value=0, step=1)

            submit = st.form_submit_button("✅ Veriyi Kaydet")

            if submit:
                if kullanici:
                    data = {
                        "tahmin_ppk_faiz": val_faiz, "min_ppk_faiz": min_faiz, "max_ppk_faiz": max_faiz,
                        "tahmin_yilsonu_faiz": val_ys_faiz, "min_yilsonu_faiz": min_ys_faiz, "max_yilsonu_faiz": max_ys_faiz,
                        "katilimci_sayisi": int(kat_sayisi) if kat_sayisi > 0 else 0
                    }
                    status = upsert_tahmin(kullanici, donem, kategori, tahmin_tarihi, kaynak_link, data)
                    
                    if status == "inserted": 
                        st.toast(f"{display_name} İçin Yeni Kayıt Oluşturuldu!", icon="🎉")
                    else: 
                        st.toast(f"{display_name} Verisi Güncellendi!", icon="🔄")
                else:
                    st.error("Lütfen katılımcı seçiniz.")

# ========================================================
# SAYFA: ENFLASYON GİRİŞİ (MODERN UI)
# ========================================================
elif page == "➕ Enflasyon Girişi":
    st.subheader("🏷️ Enflasyon Tahmin Girişi")
    
    with st.container():
        with st.form("enf_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1: kullanici, kategori, display_name = get_participant_selection()
            with c2: donem = st.selectbox("📅 Dönem", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)
            with c3: tahmin_tarihi = st.date_input("📆 Tahmin Tarihi", datetime.date.today())

            kaynak_link = st.text_input("🔗 Kaynak Web Linki (Opsiyonel)", placeholder="https://...")

            st.markdown("---")
            # Ana Veriler (Sadece Medyanlar) - Daha temiz görünüm
            c_main1, c_main2, c_main3 = st.columns(3)
            with c_main1: v_ay = st.number_input("1. Aylık TÜFE (Medyan)", step=0.1, key="v_ay")
            with c_main2: v_yil = st.number_input("2. Yıllık TÜFE (Medyan)", step=0.1, key="v_yi")
            with c_main3: v_ys = st.number_input("3. Yıl Sonu TÜFE (Medyan)", step=0.1, key="v_ys")

            # Detaylar
            with st.expander("📉 Min / Max Aralık & Katılımcı Sayısı (Opsiyonel)"):
                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    st.markdown("**Aylık Aralık**")
                    min_ay = st.number_input("Min Aylık", step=0.1)
                    max_ay = st.number_input("Max Aylık", step=0.1)
                with ec2:
                    st.markdown("**Yıllık Aralık**")
                    min_yil = st.number_input("Min Yıllık", step=0.1)
                    max_yil = st.number_input("Max Yıllık", step=0.1)
                with ec3:
                    st.markdown("**Yıl Sonu Aralık**")
                    min_ys = st.number_input("Min YS", step=0.1)
                    max_ys = st.number_input("Max YS", step=0.1)
                
                st.markdown("---")
                kat_sayisi = st.number_input("Katılımcı Sayısı (N)", min_value=0, step=1)

            submit = st.form_submit_button("✅ Veriyi Kaydet")

            if submit:
                if kullanici:
                    data = {
                        "tahmin_aylik_enf": v_ay, "min_aylik_enf": min_ay, "max_aylik_enf": max_ay,
                        "tahmin_yillik_enf": v_yil, "min_yillik_enf": min_yil, "max_yillik_enf": max_yil,
                        "tahmin_yilsonu_enf": v_ys, "min_yilsonu_enf": min_ys, "max_yilsonu_enf": max_ys,
                        "katilimci_sayisi": int(kat_sayisi) if kat_sayisi > 0 else 0
                    }
                    status = upsert_tahmin(kullanici, donem, kategori, tahmin_tarihi, kaynak_link, data)
                    if status == "inserted": st.toast("Kayıt Başarılı!", icon="🎉")
                    else: st.toast("Güncelleme Başarılı!", icon="🔄")

# ========================================================
# SAYFA: RAPORLAMA VE EXCEL
# ========================================================
elif page == "📥 Raporlama & Excel":
    st.subheader("📥 Veri Dışa Aktar")
    
    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    
    if not df_t.empty:
        res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "kategori", "anket_kaynagi").execute()
        df_k = pd.DataFrame(res_k.data)
        
        if not df_k.empty:
            df_full = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
            df_full['kategori'] = df_full['kategori_y'].fillna('Bireysel')
            df_full['anket_kaynagi'] = df_full['anket_kaynagi'].fillna('-')
            
            # Filtreler
            c1, c2 = st.columns(2)
            with c1: filter_type = st.radio("Kategori Filtresi", ["Hepsi", "Kurumsal", "Bireysel"], horizontal=True)
            with c2: 
                df_full['tahmin_tarihi'] = pd.to_datetime(df_full['tahmin_tarihi'])
                min_d, max_d = df_full['tahmin_tarihi'].min().date(), df_full['tahmin_tarihi'].max().date()
                date_range = st.date_input("Tarih Aralığı", [min_d, max_d])

            if filter_type != "Hepsi": df_full = df_full[df_full['kategori'] == filter_type]
            if len(date_range) == 2:
                df_full = df_full[(df_full['tahmin_tarihi'].dt.date >= date_range[0]) & (df_full['tahmin_tarihi'].dt.date <= date_range[1])]

            # Tablo Gösterimi (Linkli)
            st.markdown("### 📋 Veri Önizleme")
            
            # Link Sütununu Yapılandırma
            column_cfg = {
                "kaynak_link": st.column_config.LinkColumn(
                    "Kaynak Linki", 
                    display_text="🔗 Git",
                    help="Kaynağa gitmek için tıkla"
                ),
                "tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY")
            }
            
            # Gösterilecek Sütunlar
            cols = ['tahmin_tarihi', 'donem', 'kullanici_adi', 'kategori', 'kaynak_link', 'tahmin_ppk_faiz', 'tahmin_yilsonu_faiz', 'tahmin_aylik_enf', 'tahmin_yilsonu_enf']
            final_cols = [c for c in cols if c in df_full.columns]
            
            st.dataframe(df_full[final_cols], column_config=column_cfg, use_container_width=True)
            
            if not df_full.empty:
                df_full['tahmin_tarihi'] = df_full['tahmin_tarihi'].dt.strftime('%Y-%m-%d')
                excel_data = to_excel(df_full)
                st.download_button("📥 Excel İndir", excel_data, f"tahminler_{filter_type}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Henüz veri yok.")

# ========================================================
# SAYFA: DASHBOARD
# ========================================================
elif page == "📊 Dashboard":
    st.header("Piyasa Analiz Dashboardu")
    
    res_tahmin = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_tahmin = pd.DataFrame(res_tahmin.data)
    res_kat = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_kat = pd.DataFrame(res_kat.data)

    if not df_tahmin.empty and not df_kat.empty:
        df_tahmin = clean_and_sort_data(df_tahmin)
        # En güncel veriyi al
        df_tahmin['tahmin_tarihi'] = pd.to_datetime(df_tahmin['tahmin_tarihi'])
        df_tahmin = df_tahmin.sort_values(by='tahmin_tarihi')
        df_latest = df_tahmin.drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
        
        df = pd.merge(df_latest, df_kat, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        df['gorunen_isim'] = df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)
        df['hover_text'] = df.apply(lambda x: f"Tarih: {x['tahmin_tarihi'].strftime('%d-%m-%Y')}<br>N={int(x['katilimci_sayisi'])}" if pd.notnull(x['katilimci_sayisi']) else "", axis=1)
        df['kategori'] = df['kategori'].fillna('Bireysel')
        
        # --- KPI KARTLARI ---
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Toplam Katılımcı", df['kullanici_adi'].nunique())
        kpi2.metric("Toplam Tahmin Sayısı", len(df))
        kpi3.metric("Son Veri Girişi", df['tahmin_tarihi'].max().strftime('%d.%m.%Y'))
        st.markdown("---")

        # Filtreler
        with st.sidebar:
            st.markdown("### 🔍 Filtreleme")
            cat_filter = st.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
            
            # Seçilen kategoriye göre kullanıcı listesi
            users_in_cat = df[df['kategori'].isin(cat_filter)]['gorunen_isim'].unique()
            user_filter = st.multiselect("Katılımcı", sorted(users_in_cat), default=sorted(users_in_cat))
            
            df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
            year_filter = st.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        df_filtered = df[df['kategori'].isin(cat_filter) & df['gorunen_isim'].isin(user_filter) & df['yil'].isin(year_filter)]
        
        if df_filtered.empty: st.warning("Veri bulunamadı."); st.stop()

        # Grafikler
        report_figures = {}
        tab_ts, tab_dev = st.tabs(["📈 Zaman Serisi", "🍭 Medyan Sapma"])

        with tab_ts:
            def plot_w_range(df_sub, y_col, min_c, max_c, title):
                fig = px.line(df_sub, x="donem", y=y_col, color="gorunen_isim", markers=True, title=title, hover_data=["hover_text"])
                fig.update_xaxes(type='category', categoryorder='category ascending')
                df_r = df_sub.dropna(subset=[min_c, max_c])
                if not df_r.empty:
                    for u in df_r['gorunen_isim'].unique():
                        ud = df_r[df_r['gorunen_isim'] == u]
                        fig.add_trace(go.Scatter(x=ud['donem'], y=ud[y_col], mode='markers', error_y=dict(type='data', symmetric=False, array=ud[max_c]-ud[y_col], arrayminus=ud[y_col]-ud[min_c], color='gray', width=3), showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
                return fig

            c1, c2 = st.columns(2)
            with c1: report_figures["PPK"] = plot_w_range(df_filtered, "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Karar")
            with c2: report_figures["Sene Sonu Faiz"] = plot_w_range(df_filtered, "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz", "Sene Sonu Faiz")
            
            c3, c4 = st.columns(2)
            with c3: report_figures["Aylik Enf"] = plot_w_range(df_filtered, "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "Aylık Enflasyon")
            with c4: report_figures["Yil Sonu Enf"] = plot_w_range(df_filtered, "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "Yıl Sonu Enflasyon")

        with tab_dev:
             if not df_filtered.empty:
                per = df_filtered['donem'].max()
                d_p = df_filtered[df_filtered['donem'] == per].copy()
                if len(d_p) > 1:
                    metric_map = {"PPK Karar": "tahmin_ppk_faiz", "Sene Sonu Faiz": "tahmin_yilsonu_faiz", "Aylık Enf": "tahmin_aylik_enf"}
                    sel_met_name = st.radio("Metrik Seç", list(metric_map.keys()), horizontal=True)
                    sel_met = metric_map[sel_met_name]
                    if d_p[sel_met].notnull().sum() > 1:
                        med = d_p[sel_met].median()
                        d_p['sapma'] = d_p[sel_met] - med
                        d_p = d_p.sort_values(by='sapma')
                        fig = go.Figure()
                        for i, r in d_p.iterrows():
                            if pd.isna(r['sapma']): continue
                            c = "crimson" if r['sapma'] < 0 else "seagreen"
                            fig.add_trace(go.Scatter(x=[0, r['sapma']], y=[r['gorunen_isim'], r['gorunen_isim']], mode='lines', line=dict(color=c), showlegend=False))
                            fig.add_trace(go.Scatter(x=[r['sapma']], y=[r['gorunen_isim']], mode='markers', marker=dict(color=c, size=12), name=r['gorunen_isim'], text=f"Tahmin: %{r[sel_met]}", hoverinfo='text'))
                        fig.add_vline(x=0, line_dash="dash")
                        fig.update_layout(title=f"Sapma Analizi ({per})", height=max(400, len(d_p)*30))
                        st.plotly_chart(fig, use_container_width=True)
                        report_figures["Sapma"] = fig

        st.markdown("---")
        if st.button("📄 PDF Rapor Oluştur"):
            pdf_d = create_pdf_report(df_filtered, report_figures)
            st.download_button("⬇️ İndir", pdf_d, "rapor.pdf", "application/pdf")

# ========================================================
# SAYFA: DÜZENLE / SİL
# ========================================================
elif page == "⚙️ Düzenle / Sil":
    st.header("⚙️ Veri Yönetimi")
    res_users = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        df_users['display'] = df_users.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
        name_map = dict(zip(df_users['display'], df_users['ad_soyad']))
        sel_disp = st.selectbox("Kişi Seç", df_users["display"])
        real_name = name_map[sel_disp]
        res_rec = supabase.table(TABLE_TAHMIN).select("*").eq("kullanici_adi", real_name).execute()
        
        df_rec = pd.DataFrame(res_rec.data)
        if not df_rec.empty:
            df_rec = clean_and_sort_data(df_rec).sort_values(by=["donem", "tahmin_tarihi"], ascending=False)
            st.dataframe(df_rec)
            
            rec_opts = {f"{row['donem']} | {row.get('tahmin_tarihi')} (ID: {row['id']})": row for i, row in df_rec.iterrows()}
            sel_key = st.selectbox("Düzenlenecek Kayıt", list(rec_opts.keys()))
            target = rec_opts[sel_key]

            with st.form("edit"):
                st.subheader("Verileri Güncelle")
                curr_date = pd.to_datetime(target.get('tahmin_tarihi')).date() if target.get('tahmin_tarihi') else datetime.date.today()
                new_date = st.date_input("Tarih", curr_date)
                
                # Link düzenleme
                curr_link = target.get('kaynak_link') or ""
                new_link = st.text_input("Link", curr_link)

                def g(k): return float(target.get(k) or 0)
                c1, c2 = st.columns(2)
                with c1: 
                    new_faiz = st.number_input("PPK", value=g('tahmin_ppk_faiz'), step=0.25)
                    new_ys_faiz = st.number_input("YS Faiz", value=g('tahmin_yilsonu_faiz'), step=0.25)
                with c2:
                    new_ay = st.number_input("Ay Enf", value=g('tahmin_aylik_enf'), step=0.1)
                    new_ys = st.number_input("YS Enf", value=g('tahmin_yilsonu_enf'), step=0.1)
                
                c_bt1, c_bt2 = st.columns(2)
                if c_bt1.form_submit_button("💾 Güncelle"):
                    def cv(v): return v if v!=0 else None
                    upd = {
                        "tahmin_tarihi": new_date.strftime('%Y-%m-%d'),
                        "kaynak_link": new_link if new_link else None,
                        "tahmin_ppk_faiz": cv(new_faiz), "tahmin_yilsonu_faiz": cv(new_ys_faiz),
                        "tahmin_aylik_enf": cv(new_ay), "tahmin_yilsonu_enf": cv(new_ys)
                    }
                    supabase.table(TABLE_TAHMIN).update(upd).eq("id", target['id']).execute()
                    st.toast("Güncellendi!")
                
                if c_bt2.form_submit_button("🗑️ Sil") and st.checkbox("Onaylıyorum"):
                     supabase.table(TABLE_TAHMIN).delete().eq("id", target['id']).execute()
                     st.rerun()

# ========================================================
# SAYFA: KATILIMCI YÖNETİMİ
# ========================================================
elif page == "👥 Katılımcı Yönetimi":
    st.header("👥 Katılımcı Yönetimi")
    with st.expander("➕ Yeni Kişi Ekle", expanded=True):
        with st.form("new_kat"):
            c1, c2 = st.columns(2)
            ad = c1.text_input("Ad / Kurum")
            cat = c2.radio("Kategori", ["Bireysel", "Kurumsal"], horizontal=True)
            src = st.text_input("Kaynak (Opsiyonel)")
            if st.form_submit_button("Ekle"):
                if ad:
                    try:
                        supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": normalize_name(ad), "kategori": cat, "anket_kaynagi": src or None}).execute()
                        st.toast("Eklendi")
                    except: st.error("Hata")
    
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        ks = st.selectbox("Silinecek Kişi", df["ad_soyad"].unique())
        if st.button("🚫 Kişiyi ve Tüm Verilerini Sil"):
            supabase.table(TABLE_TAHMIN).delete().eq("kullanici_adi", ks).execute()
            supabase.table(TABLE_KATILIMCI).delete().eq("ad_soyad", ks).execute()
            st.rerun()

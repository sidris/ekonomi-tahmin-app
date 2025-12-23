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

# Custom CSS
st.markdown("""
<style>
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 10px; }
    .row-widget { padding: 10px; border-bottom: 1px solid #eee; }
    .stButton button { width: 100%; border-radius: 8px; font-weight: bold; }
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
    # Aynı gün, aynı dönem, aynı kişi kontrolü (Revizyon Yönetimi)
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
        "kaynak_link": link if link else None
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

# --- 3. ANA UYGULAMA ---
st.title("📈 Makroekonomi Tahmin Merkezi")
st.markdown("---")

with st.sidebar:
    st.header("Menü")
    page = st.radio("Git:", ["📊 Dashboard", "➕ PPK Girişi", "➕ Enflasyon Girişi", "📥 Gelişmiş Veri Havuzu", "⚙️ Düzenle / Sil", "👥 Katılımcı Yönetimi"])

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
# SAYFA: PPK GİRİŞİ
# ========================================================
if page == "➕ PPK Girişi":
    st.subheader("🏦 Faiz Tahmin Girişi")
    with st.container():
        with st.form("ppk_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1: kullanici, kategori, display_name = get_participant_selection()
            with c2: donem = st.selectbox("📅 Dönem", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)
            with c3: tahmin_tarihi = st.date_input("📆 Tahmin Tarihi", datetime.date.today())
            kaynak_link = st.text_input("🔗 Kaynak Web Linki (Opsiyonel)", placeholder="https://...")
            st.markdown("---")
            c_ppk1, c_ppk2 = st.columns(2)
            with c_ppk1:
                st.markdown("### 1. Bu Ayki Karar")
                val_faiz = st.number_input("Medyan %", step=0.25, format="%.2f")
            with c_ppk2:
                st.markdown("### 2. Sene Sonu Beklenti")
                val_ys_faiz = st.number_input("Medyan % (YS)", step=0.25, format="%.2f", key="ys_f")
            
            with st.expander("📉 Min / Max & Katılımcı Sayısı"):
                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    min_faiz = st.number_input("Min %", step=0.25, format="%.2f")
                    max_faiz = st.number_input("Max %", step=0.25, format="%.2f")
                with ec2:
                    min_ys_faiz = st.number_input("Min % (YS)", step=0.25, format="%.2f")
                    max_ys_faiz = st.number_input("Max % (YS)", step=0.25, format="%.2f")
                with ec3:
                    kat_sayisi = st.number_input("Katılımcı (N)", min_value=0, step=1)
            
            if st.form_submit_button("✅ Veriyi Kaydet"):
                if kullanici:
                    data = {"tahmin_ppk_faiz": val_faiz, "min_ppk_faiz": min_faiz, "max_ppk_faiz": max_faiz, "tahmin_yilsonu_faiz": val_ys_faiz, "min_yilsonu_faiz": min_ys_faiz, "max_yilsonu_faiz": max_ys_faiz, "katilimci_sayisi": int(kat_sayisi) if kat_sayisi > 0 else 0}
                    status = upsert_tahmin(kullanici, donem, kategori, tahmin_tarihi, kaynak_link, data)
                    st.toast("Kayıt Başarılı!", icon="🎉" if status == "inserted" else "🔄")
                else: st.error("Katılımcı seçiniz.")

# ========================================================
# SAYFA: ENFLASYON GİRİŞİ
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
            c_main1, c_main2, c_main3 = st.columns(3)
            with c_main1: v_ay = st.number_input("1. Aylık TÜFE (Medyan)", step=0.1, key="v_ay")
            with c_main2: v_yil = st.number_input("2. Yıllık TÜFE (Medyan)", step=0.1, key="v_yi")
            with c_main3: v_ys = st.number_input("3. Yıl Sonu TÜFE (Medyan)", step=0.1, key="v_ys")
            with st.expander("📉 Min / Max & Katılımcı Sayısı"):
                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    min_ay = st.number_input("Min Aylık", step=0.1)
                    max_ay = st.number_input("Max Aylık", step=0.1)
                with ec2:
                    min_yil = st.number_input("Min Yıllık", step=0.1)
                    max_yil = st.number_input("Max Yıllık", step=0.1)
                with ec3:
                    min_ys = st.number_input("Min YS", step=0.1)
                    max_ys = st.number_input("Max YS", step=0.1)
                    st.markdown("---")
                    kat_sayisi = st.number_input("Katılımcı (N)", min_value=0, step=1)
            
            if st.form_submit_button("✅ Veriyi Kaydet"):
                if kullanici:
                    data = {"tahmin_aylik_enf": v_ay, "min_aylik_enf": min_ay, "max_aylik_enf": max_ay, "tahmin_yillik_enf": v_yil, "min_yillik_enf": min_yil, "max_yillik_enf": max_yil, "tahmin_yilsonu_enf": v_ys, "min_yilsonu_enf": min_ys, "max_yilsonu_enf": max_ys, "katilimci_sayisi": int(kat_sayisi) if kat_sayisi > 0 else 0}
                    status = upsert_tahmin(kullanici, donem, kategori, tahmin_tarihi, kaynak_link, data)
                    st.toast("Kayıt Başarılı!", icon="🎉" if status == "inserted" else "🔄")

# ========================================================
# SAYFA: GELİŞMİŞ VERİ HAVUZU VE EXCEL
# ========================================================
elif page == "📥 Gelişmiş Veri Havuzu":
    st.header("🗃️ Gelişmiş Veri Havuzu")
    st.info("Tüm verileri filtreleyebilir ve Excel olarak indirebilirsiniz.")

    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    
    if not df_t.empty:
        df_t = clean_and_sort_data(df_t)
        res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "kategori", "anket_kaynagi").execute()
        df_k = pd.DataFrame(res_k.data)
        
        if not df_k.empty:
            df_full = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
            df_full['kategori'] = df_full['kategori_y'].fillna('Bireysel')
            df_full['anket_kaynagi'] = df_full['anket_kaynagi'].fillna('-')
            df_full['tahmin_tarihi'] = pd.to_datetime(df_full['tahmin_tarihi'])

            with st.expander("🔍 Gelişmiş Filtreleme Seçenekleri", expanded=True):
                f_col1, f_col2, f_col3 = st.columns(3)
                with f_col1:
                    sel_cat = st.selectbox("Kategori", ["Tümü"] + list(df_full['kategori'].unique()))
                    sel_period = st.selectbox("Dönem", ["Tümü"] + sorted(list(df_full['donem'].unique()), reverse=True))
                with f_col2:
                    sel_user = st.selectbox("Katılımcı", ["Tümü"] + sorted(list(df_full['kullanici_adi'].unique())))
                    sel_source = st.selectbox("Kaynak", ["Tümü"] + sorted(list(df_full['anket_kaynagi'].unique())))
                with f_col3:
                    min_date, max_date = df_full['tahmin_tarihi'].min().date(), df_full['tahmin_tarihi'].max().date()
                    date_range = st.date_input("Tarih Aralığı", [min_date, max_date])

            df_filtered = df_full.copy()
            if sel_cat != "Tümü": df_filtered = df_filtered[df_filtered['kategori'] == sel_cat]
            if sel_period != "Tümü": df_filtered = df_filtered[df_filtered['donem'] == sel_period]
            if sel_user != "Tümü": df_filtered = df_filtered[df_filtered['kullanici_adi'] == sel_user]
            if sel_source != "Tümü": df_filtered = df_filtered[df_filtered['anket_kaynagi'] == sel_source]
            if len(date_range) == 2: df_filtered = df_filtered[(df_filtered['tahmin_tarihi'].dt.date >= date_range[0]) & (df_filtered['tahmin_tarihi'].dt.date <= date_range[1])]

            st.markdown(f"### 📋 Sonuç Listesi ({len(df_filtered)} Kayıt)")
            column_cfg = {
                "kaynak_link": st.column_config.LinkColumn("Link", display_text="🔗"),
                "tahmin_tarihi": st.column_config.DateColumn("Giriş Tarihi", format="DD.MM.YYYY"),
                "tahmin_ppk_faiz": st.column_config.NumberColumn("PPK", format="%.2f%%"),
                "tahmin_yilsonu_faiz": st.column_config.NumberColumn("YS Faiz", format="%.2f%%"),
                "tahmin_aylik_enf": st.column_config.NumberColumn("Ay Enf", format="%.2f%%"),
                "tahmin_yilsonu_enf": st.column_config.NumberColumn("YS Enf", format="%.2f%%"),
            }
            display_cols = ['tahmin_tarihi', 'donem', 'kullanici_adi', 'kategori', 'anket_kaynagi', 'kaynak_link', 'tahmin_ppk_faiz', 'tahmin_yilsonu_faiz', 'tahmin_aylik_enf', 'tahmin_yilsonu_enf', 'katilimci_sayisi']
            st.dataframe(df_filtered[[c for c in display_cols if c in df_filtered.columns]].sort_values(by="tahmin_tarihi", ascending=False), column_config=column_cfg, use_container_width=True, height=500)

            st.markdown("---")
            if not df_filtered.empty:
                df_export = df_filtered.copy()
                df_export['tahmin_tarihi'] = df_export['tahmin_tarihi'].dt.strftime('%Y-%m-%d')
                excel_data = to_excel(df_export)
                st.download_button(label="📥 Tabloyu Excel Olarak İndir", data=excel_data, file_name=f"Veri_Havuzu_{datetime.date.today()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    else: st.info("Sistemde henüz hiç veri yok.")

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
        df_tahmin['tahmin_tarihi'] = pd.to_datetime(df_tahmin['tahmin_tarihi'])
        df_tahmin = df_tahmin.sort_values(by='tahmin_tarihi')
        df_latest = df_tahmin.drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
        df = pd.merge(df_latest, df_kat, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        df['gorunen_isim'] = df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)
        df['hover_text'] = df.apply(lambda x: f"Tarih: {x['tahmin_tarihi'].strftime('%d-%m-%Y')}<br>N={int(x['katilimci_sayisi'])}" if pd.notnull(x['katilimci_sayisi']) else "", axis=1)
        df['kategori'] = df['kategori'].fillna('Bireysel')
        
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Toplam Katılımcı", df['kullanici_adi'].nunique())
        kpi2.metric("Toplam Tahmin Sayısı", len(df))
        kpi3.metric("Son Veri Girişi", df['tahmin_tarihi'].max().strftime('%d.%m.%Y'))
        st.markdown("---")

        with st.sidebar:
            st.markdown("### 🔍 Filtreleme")
            cat_filter = st.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
            users_in_cat = df[df['kategori'].isin(cat_filter)]['gorunen_isim'].unique()
            user_filter = st.multiselect("Katılımcı", sorted(users_in_cat), default=sorted(users_in_cat))
            df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
            year_filter = st.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        df_filtered = df[df['kategori'].isin(cat_filter) & df['gorunen_isim'].isin(user_filter) & df['yil'].isin(year_filter)]
        if df_filtered.empty: st.warning("Veri bulunamadı."); st.stop()

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
# SAYFA: DÜZENLE / SİL (ADMIN AUTHENTICATION)
# ========================================================
elif page == "⚙️ Düzenle / Sil":
    st.header("⚙️ Yönetici Paneli")
    
    if 'admin_auth' not in st.session_state: st.session_state['admin_auth'] = False
        
    if not st.session_state['admin_auth']:
        st.info("İşlem yapmak için şifre gereklidir.")
        # Filtreleme
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            res_users = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
            df_users = pd.DataFrame(res_users.data)
            if not df_users.empty:
                df_users['display'] = df_users.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
                name_map = dict(zip(df_users['display'], df_users['ad_soyad']))
                sel_disp = st.selectbox("Katılımcı Filtrele", ["Tümü"] + list(df_users['display']))
        
        if not df_users.empty:
            query = supabase.table(TABLE_TAHMIN).select("*")
            if sel_disp != "Tümü": query = query.eq("kullanici_adi", name_map[sel_disp])
            res_rec = query.execute()
            df_rec = pd.DataFrame(res_rec.data)
            
            if not df_rec.empty:
                df_rec = clean_and_sort_data(df_rec).sort_values(by=["donem", "tahmin_tarihi"], ascending=False)
                col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([2, 1, 3, 0.5, 0.5])
                col_h1.markdown("**Dönem**"); col_h2.markdown("**Kullanıcı**"); col_h3.markdown("**Özet**");
                st.markdown("---")

                for index, row in df_rec.iterrows():
                    c1, c2, c3, c4, c5 = st.columns([2, 1, 3, 0.5, 0.5])
                    c1.write(f"{row['donem']} ({row.get('tahmin_tarihi')})")
                    c2.write(row['kullanici_adi'])
                    c3.caption(f"PPK: {row.get('tahmin_ppk_faiz') or '-'} | YS Faiz: {row.get('tahmin_yilsonu_faiz') or '-'} | Enf: {row.get('tahmin_aylik_enf') or '-'}")
                    if c4.button("✏️", key=f"e_{row['id']}"):
                        st.session_state['target_id'] = row['id']; st.session_state['action'] = 'edit'; st.rerun()
                    if c5.button("🗑️", key=f"d_{row['id']}"):
                        st.session_state['target_id'] = row['id']; st.session_state['action'] = 'del'; st.rerun()

        if 'action' in st.session_state:
            st.markdown("---")
            with st.form("admin"):
                pwd = st.text_input("Admin Şifresi", type="password")
                if st.form_submit_button("Giriş"):
                    if pwd == "Admin": st.session_state['admin_auth'] = True; st.rerun()
                    else: st.error("Hatalı")

    else: # YETKİ VARSA
        if 'target_id' in st.session_state:
            rec_id = st.session_state['target_id']
            target = supabase.table(TABLE_TAHMIN).select("*").eq("id", rec_id).execute().data[0]
            
            if st.session_state['action'] == 'edit':
                st.subheader(f"Düzenle: {target['kullanici_adi']} - {target['donem']}")
                with st.form("edit_auth"):
                    curr_date = pd.to_datetime(target.get('tahmin_tarihi')).date() if target.get('tahmin_tarihi') else datetime.date.today()
                    nd = st.date_input("Tarih", curr_date)
                    nl = st.text_input("Link", target.get('kaynak_link') or "")
                    def g(k): return float(target.get(k) or 0)
                    c1, c2 = st.columns(2)
                    with c1: nf=st.number_input("PPK", value=g('tahmin_ppk_faiz'), step=0.25); nysf=st.number_input("YS Faiz", value=g('tahmin_yilsonu_faiz'), step=0.25)
                    with c2: na=st.number_input("Ay Enf", value=g('tahmin_aylik_enf'), step=0.1); nyse=st.number_input("YS Enf", value=g('tahmin_yilsonu_enf'), step=0.1)
                    
                    if st.form_submit_button("💾 Kaydet"):
                        def cv(v): return v if v!=0 else None
                        upd = {"tahmin_tarihi": nd.strftime('%Y-%m-%d'), "kaynak_link": nl if nl else None, "tahmin_ppk_faiz": cv(nf), "tahmin_yilsonu_faiz": cv(nysf), "tahmin_aylik_enf": cv(na), "tahmin_yilsonu_enf": cv(nyse)}
                        supabase.table(TABLE_TAHMIN).update(upd).eq("id", rec_id).execute()
                        del st.session_state['admin_auth']; del st.session_state['target_id']; del st.session_state['action']; st.rerun()

            elif st.session_state['action'] == 'del':
                st.error(f"SİLİNECEK: {target['kullanici_adi']} - {target['donem']}")
                c1, c2 = st.columns(2)
                if c1.button("✅ Evet"):
                    supabase.table(TABLE_TAHMIN).delete().eq("id", rec_id).execute()
                    del st.session_state['admin_auth']; del st.session_state['target_id']; del st.session_state['action']; st.rerun()
                if c2.button("❌ İptal"):
                    del st.session_state['admin_auth']; del st.session_state['target_id']; del st.session_state['action']; st.rerun()

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

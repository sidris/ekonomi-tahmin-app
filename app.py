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
import time

# --- 1. AYARLAR VE TASARIM ---
st.set_page_config(
    page_title="Finansal Tahmin Terminali", 
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded"
)

# Modern CSS
st.markdown("""
<style>
    .stMetric { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .stButton button { width: 100%; border-radius: 8px; font-weight: 600; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; background-color: white; }
    h1, h2, h3 { color: #2c3e50; }
    div[data-testid="stDataFrame"] { width: 100%; }
</style>
""", unsafe_allow_html=True)

# --- BAĞLANTI ---
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Lütfen secrets ayarlarını kontrol edin.")
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
        "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf",
        "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf",
        "katilimci_sayisi"
    ]
    for col in numeric_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    
    if "donem" in df.columns:
        df["donem_date"] = pd.to_datetime(df["donem"], format="%Y-%m", errors='coerce')
        df = df.sort_values(by="donem_date")
    
    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"])
        
    return df

# --- AKILLI ARALIK AYRIŞTIRICI ---
def parse_range_input(text_input, default_median=0.0):
    if not text_input or text_input.strip() == "":
        return default_median, 0.0, 0.0, False
    try:
        text = text_input.replace(',', '.')
        parts = []
        if '-' in text: parts = text.split('-')
        elif '/' in text: parts = text.split('/')
        
        if len(parts) == 2:
            v1 = float(parts[0].strip())
            v2 = float(parts[1].strip())
            mn = min(v1, v2)
            mx = max(v1, v2)
            md = (mn + mx) / 2
            return md, mn, mx, True
    except:
        pass
    return default_median, 0.0, 0.0, False

def upsert_tahmin(user, period, category, forecast_date, link, data_dict):
    date_str = forecast_date.strftime("%Y-%m-%d")
    check_res = supabase.table(TABLE_TAHMIN).select("id").eq("kullanici_adi", user).eq("donem", period).eq("tahmin_tarihi", date_str).execute()
    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    clean_data.update({
        "kullanici_adi": user, "donem": period, "kategori": category,
        "tahmin_tarihi": date_str, "kaynak_link": link if link else None
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

# --- AUTH ---
if 'giris_yapildi' not in st.session_state: st.session_state['giris_yapildi'] = False
if not st.session_state['giris_yapildi']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("### 🔐 Giriş Paneli")
        if st.button("Giriş Yap", type="primary") and st.text_input("Şifre", type="password") == SITE_SIFRESI:
            st.session_state['giris_yapildi'] = True; st.rerun()
        st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.title("📊 Menü")
    page = st.radio("Git:", ["Gelişmiş Veri Havuzu (Yönetim)", "Dashboard", "PPK Girişi", "Enflasyon Girişi", "Katılımcı Yönetimi"])

def get_participant_selection():
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if df.empty: st.error("Lütfen önce Katılımcı ekleyin."); return None, None, None
    df['disp'] = df.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
    name_map = dict(zip(df['disp'], df['ad_soyad']))
    sel = st.selectbox("Katılımcı Seç", df["disp"].unique())
    row = df[df["ad_soyad"] == name_map[sel]].iloc[0]
    return name_map[sel], row['kategori'], sel

# ========================================================
# SAYFA: GELİŞMİŞ VERİ HAVUZU (YÖNETİM & EXCEL)
# ========================================================
if page == "Gelişmiş Veri Havuzu (Yönetim)":
    st.title("🗃️ Veri Havuzu ve Yönetim Paneli")
    
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
            
            with st.container():
                c1, c2, c3, c4 = st.columns(4)
                sel_cat = c1.selectbox("Kategori", ["Tümü"] + list(df_full['kategori'].unique()))
                sel_period = c2.selectbox("Dönem", ["Tümü"] + sorted(list(df_full['donem'].unique()), reverse=True))
                sel_user = c3.selectbox("Katılımcı", ["Tümü"] + sorted(list(df_full['kullanici_adi'].unique())))
                admin_mode = c4.toggle("🛠️ Yönetici Modu (Düzenle/Sil)")

            df_f = df_full.copy()
            if sel_cat != "Tümü": df_f = df_f[df_f['kategori'] == sel_cat]
            if sel_period != "Tümü": df_f = df_f[df_f['donem'] == sel_period]
            if sel_user != "Tümü": df_f = df_f[df_f['kullanici_adi'] == sel_user]
            
            if not admin_mode:
                st.markdown("---")
                full_view_cols = [
                    "tahmin_tarihi", "donem", "kullanici_adi", "kategori", "anket_kaynagi", "kaynak_link", "katilimci_sayisi",
                    "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz",
                    "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz",
                    "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf",
                    "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf",
                    "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf"
                ]
                final_cols = [c for c in full_view_cols if c in df_f.columns]
                
                col_cfg = {
                    "kaynak_link": st.column_config.LinkColumn("Link", display_text="🔗"),
                    "tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY"),
                    **{c: st.column_config.NumberColumn(c, format="%.2f") for c in final_cols if "tahmin" in c or "min" in c or "max" in c}
                }
                
                st.dataframe(df_f[final_cols].sort_values(by="tahmin_tarihi", ascending=False), column_config=col_cfg, use_container_width=True, height=600)
                
                if not df_f.empty:
                    df_ex = df_f.copy()
                    df_ex['tahmin_tarihi'] = df_ex['tahmin_tarihi'].dt.strftime('%Y-%m-%d')
                    st.download_button("📥 Excel İndir", to_excel(df_ex), f"Veri_Havuzu_{sel_user}_{datetime.date.today()}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

            else:
                if 'admin_ok' not in st.session_state: st.session_state['admin_ok'] = False
                if not st.session_state['admin_ok']:
                    with st.form("admin_login"):
                        st.info("Düzenleme yapmak için yönetici şifresini giriniz.")
                        pwd = st.text_input("Şifre", type="password")
                        if st.form_submit_button("Giriş"):
                            if pwd == "Admin": st.session_state['admin_ok'] = True; st.rerun()
                            else: st.error("Hatalı Şifre")
                else:
                    if 'edit_target' in st.session_state:
                        t = st.session_state['edit_target']
                        st.markdown("---")
                        st.markdown(f"### ✏️ Düzenleniyor: {t['kullanici_adi']} ({t['donem']})")
                        
                        with st.form("full_edit_form"):
                            c1, c2, c3 = st.columns(3)
                            curr_date = pd.to_datetime(t.get('tahmin_tarihi')).date() if t.get('tahmin_tarihi') else datetime.date.today()
                            new_date = c1.date_input("Giriş Tarihi", curr_date)
                            current_donem_idx = tum_donemler.index(t['donem']) if t['donem'] in tum_donemler else 0
                            new_donem = c2.selectbox("Dönem", tum_donemler, index=current_donem_idx)
                            new_link = c3.text_input("Link", t.get('kaynak_link') or "")
                            
                            def g(k): return float(t.get(k) or 0)
                            
                            tab_ppk, tab_enf = st.tabs(["🏦 Faiz Verileri", "🏷️ Enflasyon Verileri"])
                            with tab_ppk:
                                c_p1, c_p2, c_p3 = st.columns(3)
                                n_ppk = c_p1.number_input("PPK Medyan", value=g('tahmin_ppk_faiz'), step=0.25)
                                min_ppk = c_p2.number_input("PPK Min", value=g('min_ppk_faiz'), step=0.25)
                                max_ppk = c_p3.number_input("PPK Max", value=g('max_ppk_faiz'), step=0.25)
                                c_ys1, c_ys2, c_ys3 = st.columns(3)
                                n_ysf = c_ys1.number_input("YS Faiz Medyan", value=g('tahmin_yilsonu_faiz'), step=0.25)
                                min_ysf = c_ys2.number_input("YS Faiz Min", value=g('min_yilsonu_faiz'), step=0.25)
                                max_ysf = c_ys3.number_input("YS Faiz Max", value=g('max_yilsonu_faiz'), step=0.25)
                                n_kat = st.number_input("Katılımcı Sayısı (N)", value=safe_int(t.get('katilimci_sayisi')), step=1)
                            with tab_enf:
                                st.markdown("**Aylık Enflasyon**")
                                ce1, ce2, ce3 = st.columns(3)
                                n_ay = ce1.number_input("Ay Medyan", value=g('tahmin_aylik_enf'), step=0.1)
                                min_ay = ce2.number_input("Ay Min", value=g('min_aylik_enf'), step=0.1)
                                max_ay = ce3.number_input("Ay Max", value=g('max_aylik_enf'), step=0.1)
                                st.markdown("**Yıllık Enflasyon**")
                                cy1, cy2, cy3 = st.columns(3)
                                n_yil = cy1.number_input("Yıllık Medyan", value=g('tahmin_yillik_enf'), step=0.1)
                                min_yil = cy2.number_input("Yıllık Min", value=g('min_yillik_enf'), step=0.1)
                                max_yil = cy3.number_input("Yıllık Max", value=g('max_yillik_enf'), step=0.1)
                                st.markdown("**Yıl Sonu Enflasyon**")
                                cys1, cys2, cys3 = st.columns(3)
                                n_yse = cys1.number_input("YS Enf Medyan", value=g('tahmin_yilsonu_enf'), step=0.1)
                                min_yse = cys2.number_input("YS Enf Min", value=g('min_yilsonu_enf'), step=0.1)
                                max_yse = cys3.number_input("YS Enf Max", value=g('max_yilsonu_enf'), step=0.1)
                            
                            c_b1, c_b2 = st.columns([1,1])
                            if c_b1.form_submit_button("💾 Kaydet ve Listeye Dön", type="primary"):
                                def cv(v): return v if v!=0 else None
                                upd = {
                                    "tahmin_tarihi": new_date.strftime('%Y-%m-%d'), "donem": new_donem,
                                    "kaynak_link": new_link if new_link else None, "katilimci_sayisi": int(n_kat) if n_kat>0 else 0,
                                    "tahmin_ppk_faiz": cv(n_ppk), "min_ppk_faiz": cv(min_ppk), "max_ppk_faiz": cv(max_ppk),
                                    "tahmin_yilsonu_faiz": cv(n_ysf), "min_yilsonu_faiz": cv(min_ysf), "max_yilsonu_faiz": cv(max_ysf),
                                    "tahmin_aylik_enf": cv(n_ay), "min_aylik_enf": cv(min_ay), "max_aylik_enf": cv(max_ay),
                                    "tahmin_yillik_enf": cv(n_yil), "min_yillik_enf": cv(min_yil), "max_yillik_enf": cv(max_yil),
                                    "tahmin_yilsonu_enf": cv(n_yse), "min_yilsonu_enf": cv(min_yse), "max_yilsonu_enf": cv(max_yse),
                                }
                                supabase.table(TABLE_TAHMIN).update(upd).eq("id", int(t['id'])).execute()
                                del st.session_state['edit_target']
                                st.rerun()
                        if st.button("❌ İptal"):
                            del st.session_state['edit_target']
                            st.rerun()
                    else:
                        st.markdown("---")
                        df_f = df_f.sort_values(by="tahmin_tarihi", ascending=False)
                        for idx, row in df_f.iterrows():
                            with st.container():
                                st.markdown(f"""
                                <div style="background:white; padding:15px; border-radius:10px; border-left:5px solid #4CAF50; box-shadow:0 2px 5px rgba(0,0,0,0.1); margin-bottom:10px;">
                                    <div style="display:flex; justify-content:space-between; align-items:center;">
                                        <div><h4 style="margin:0; color:#333;">{row['kullanici_adi']}</h4><small style="color:#666;">📅 {row['donem']} | Giriş: {row['tahmin_tarihi'].strftime('%d-%m-%Y')}</small></div>
                                        <div style="text-align:right;"><span style="background:#e8f5e9; padding:4px 8px; border-radius:4px; font-size:0.85em; color:#2e7d32;">PPK: {row.get('tahmin_ppk_faiz') or '-'}%</span><span style="background:#e3f2fd; padding:4px 8px; border-radius:4px; font-size:0.85em; color:#1565c0; margin-left:5px;">Enf: {row.get('tahmin_aylik_enf') or '-'}%</span></div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                                c_act1, c_act2, c_space = st.columns([1, 1, 6])
                                if c_act1.button("✏️ Düzenle", key=f"e_{row['id']}"):
                                    st.session_state['edit_target'] = row
                                    st.rerun()
                                if c_act2.button("🗑️ Sil", key=f"d_{row['id']}"):
                                    supabase.table(TABLE_TAHMIN).delete().eq("id", int(row['id'])).execute()
                                    st.toast("Kayıt Silindi"); time.sleep(1); st.rerun()

# ========================================================
# SAYFA: DASHBOARD
# ========================================================
elif page == "Dashboard":
    st.header("Piyasa Analiz Dashboardu")
    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_k = pd.DataFrame(res_k.data)

    if not df_t.empty and not df_k.empty:
        df_t = clean_and_sort_data(df_t)
        
        # --- VERİ HAZIRLIĞI ---
        # 1. Full History (Tüm Revizyonlar) - Tek Kullanıcı Analizi İçin
        df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        
        # 2. Latest Data (Sadece En Son Tahminler) - Çoklu Kullanıcı Karşılaştırması İçin
        df_latest_raw = df_t.sort_values(by='tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
        df_latest = pd.merge(df_latest_raw, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        
        # Helper Columns
        for d in [df_history, df_latest]:
            d['gorunen_isim'] = d.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)
            d['hover_text'] = d.apply(lambda x: f"Tarih: {x['tahmin_tarihi'].strftime('%d-%m-%Y')}<br>N={int(x['katilimci_sayisi'])}" if pd.notnull(x['katilimci_sayisi']) else "", axis=1)
            d['kategori'] = d['kategori'].fillna('Bireysel')
            d['anket_kaynagi'] = d['anket_kaynagi'].fillna('-')
            d['yil'] = d['donem'].apply(lambda x: x.split('-')[0])

        c1, c2, c3 = st.columns(3)
        c1.metric("Toplam Katılımcı", df_latest['kullanici_adi'].nunique())
        c2.metric("Güncel Tahmin Sayısı", len(df_latest))
        c3.metric("Son Güncelleme", df_latest['tahmin_tarihi'].max().strftime('%d.%m.%Y'))
        st.markdown("---")

        with st.sidebar:
            st.markdown("### 🔍 Dashboard Filtreleri")
            calc_method = st.radio("Medyan Hesaplama", ["Otomatik", "Manuel"])
            manual_median_val = 0.0
            if calc_method == "Manuel":
                manual_median_val = st.number_input("Manuel Değer", step=0.01, format="%.2f")
            st.markdown("---")
            
            # FILTRELER (df_latest üzerinden seçenekleri doldur)
            cat_filter = st.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
            
            avail_sources = sorted(df_latest[df_latest['kategori'].isin(cat_filter)]['anket_kaynagi'].astype(str).unique())
            source_filter = st.multiselect("Kaynak", avail_sources, default=avail_sources)
            
            users_in_context = df_latest[df_latest['kategori'].isin(cat_filter) & df_latest['anket_kaynagi'].isin(source_filter)]['gorunen_isim'].unique()
            user_filter = st.multiselect("Katılımcı", sorted(users_in_context), default=sorted(users_in_context))
            
            year_filter = st.multiselect("Yıl", sorted(df_latest['yil'].unique()), default=sorted(df_latest['yil'].unique()))

        # --- FİLTRELEME MANTIĞI ---
        # Eğer tek bir kullanıcı seçildiyse: REVIZYON TARİHÇESİNİ GÖSTER (X=Tarih)
        # Eğer birden çok kullanıcı seçildiyse: KARŞILAŞTIRMA GÖSTER (X=Dönem)
        
        is_single_user = (len(user_filter) == 1)
        
        if is_single_user:
            # Tek Kullanıcı Modu -> df_history kullan
            target_df = df_history[
                df_history['gorunen_isim'].isin(user_filter) & 
                df_history['yil'].isin(year_filter)
            ].copy()
            x_axis_col = "tahmin_tarihi"
            x_label = "Tahmin Giriş Tarihi"
            sort_col = "tahmin_tarihi"
            tick_format = "%d-%m-%Y" # Saat gösterme
        else:
            # Çoklu Kullanıcı Modu -> df_latest kullan
            target_df = df_latest[
                df_latest['kategori'].isin(cat_filter) & 
                df_latest['anket_kaynagi'].isin(source_filter) & 
                df_latest['gorunen_isim'].isin(user_filter) & 
                df_latest['yil'].isin(year_filter)
            ].copy()
            x_axis_col = "donem"
            x_label = "Hedef Dönem"
            sort_col = "donem_date" # Sıralama için tarih objesi
            tick_format = None # Dönem string olduğu için formata gerek yok

        if target_df.empty: st.warning("Veri bulunamadı."); st.stop()

        tabs = st.tabs(["📈 Zaman Serisi", "📍 Dağılım Analizi", "📦 Kutu Grafiği"])
        report_figures = {}

        # 1. ZAMAN SERİSİ
        with tabs[0]:
            def plot_chart(y_col, min_c, max_c, title):
                # Sıralama
                chart_data = target_df.sort_values(sort_col)
                
                fig = px.line(
                    chart_data, 
                    x=x_axis_col, 
                    y=y_col, 
                    color="gorunen_isim" if not is_single_user else "donem", # Tek kullanıcıda renkler dönemi göstersin
                    markers=True, 
                    title=f"{title} ({'Revizyon Geçmişi' if is_single_user else 'Dönemsel Karşılaştırma'})", 
                    hover_data=["hover_text"]
                )
                
                # Formatlama
                if tick_format:
                    fig.update_xaxes(tickformat=tick_format)
                
                # Hata Çubukları
                df_r = chart_data.dropna(subset=[min_c, max_c])
                if not df_r.empty:
                    # Grup (Color) bazında iterate et
                    group_col = "donem" if is_single_user else "gorunen_isim"
                    for g in df_r[group_col].unique():
                        ud = df_r[df_r[group_col] == g]
                        fig.add_trace(go.Scatter(
                            x=ud[x_axis_col], y=ud[y_col], 
                            mode='markers', 
                            error_y=dict(type='data', symmetric=False, array=ud[max_c]-ud[y_col], arrayminus=ud[y_col]-ud[min_c], color='gray', width=2), 
                            showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)
                        ))
                
                st.plotly_chart(fig, use_container_width=True)
                return fig

            c1, c2 = st.columns(2)
            with c1: report_figures["PPK"] = plot_chart("tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Karar")
            with c2: report_figures["YS Faiz"] = plot_chart("tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz", "Sene Sonu Faiz")
            c3, c4 = st.columns(2)
            with c3: report_figures["Ay Enf"] = plot_chart("tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "Aylık Enflasyon")
            with c4: report_figures["YS Enf"] = plot_chart("tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "Yıl Sonu Enflasyon")

        # 2. DAĞILIM (Sadece Çoklu Kullanıcıda Anlamlıdır, ama tekte de gösterilebilir)
        with tabs[1]:
            all_periods = sorted(list(target_df['donem'].unique()), reverse=True)
            target_period = st.selectbox("Dönem Seç", all_periods, key="dot_period")
            d_p = target_df[target_df['donem'] == target_period].copy()
            
            if len(d_p) > 0:
                met_map = {"PPK": "tahmin_ppk_faiz", "Enflasyon (Aylık)": "tahmin_aylik_enf", "YS Enflasyon": "tahmin_yilsonu_enf"}
                sel_m = st.radio("Metrik", list(met_map.keys()), horizontal=True)
                m_col = met_map[sel_m]
                d_p = d_p.dropna(subset=[m_col])
                
                if len(d_p) > 0:
                    median_val = manual_median_val if calc_method == "Manuel" else d_p[m_col].median()
                    d_p = d_p.sort_values(by=m_col, ascending=True)
                    
                    fig = go.Figure()
                    # Tek kullanıcı ise noktalar tarihleri temsil eder
                    y_val = d_p['tahmin_tarihi'].dt.strftime('%d-%m-%Y') if is_single_user else d_p['gorunen_isim']
                    
                    fig.add_trace(go.Scatter(
                        x=d_p[m_col], y=y_val, 
                        mode='markers', 
                        marker=dict(size=14, color='#1976D2', line=dict(width=1, color='white')), 
                        name='Tahmin', 
                        text=[f"Değer: %{row[m_col]:.2f}" for i, row in d_p.iterrows()], hoverinfo='text'
                    ))
                    fig.add_vline(x=median_val, line_width=3, line_color="red")
                    fig.add_annotation(x=median_val, y=-0.1, text=f"MEDYAN %{median_val:.2f}", showarrow=False, font=dict(color="red", size=14, weight="bold"), yref="paper")
                    fig.update_layout(title=f"{sel_m} Dağılımı ({target_period})", height=max(500, len(d_p)*35), xaxis_title="Tahmin Değeri (%)")
                    st.plotly_chart(fig, use_container_width=True)
                    report_figures["Dagilim"] = fig
                else: st.info("Veri yok.")
            else: st.info("Veri yok.")

        # 3. KUTU GRAFİĞİ
        with tabs[2]:
            met_map_box = {"PPK": "tahmin_ppk_faiz", "Yıl Sonu Faiz": "tahmin_yilsonu_faiz", "Aylık Enf": "tahmin_aylik_enf", "Yıl Sonu Enf": "tahmin_yilsonu_enf"}
            sel_box_m = st.selectbox("Veri Seti", list(met_map_box.keys()))
            col_box = met_map_box[sel_box_m]
            # X ekseni her zaman dönem olsun ki dağılım görülsün
            fig_box = px.box(target_df.sort_values("donem_date"), x="donem", y=col_box, color="donem", title=f"{sel_box_m} Dağılımı")
            fig_box.update_layout(showlegend=False)
            st.plotly_chart(fig_box, use_container_width=True)
            report_figures["KutuGrafik"] = fig_box

        st.markdown("---")
        if st.button("📄 PDF Rapor Oluştur"):
            st.download_button("⬇️ İndir", create_pdf_report(target_df, report_figures), "Rapor.pdf", "application/pdf")

# ========================================================
# SAYFA: VERİ GİRİŞ EKRANLARI (PPK / ENF)
# ========================================================
elif page in ["PPK Girişi", "Enflasyon Girişi"]:
    st.header(f"➕ {page}")
    with st.container():
        with st.form("entry_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1: user, cat, disp = get_participant_selection()
            with c2: donem = st.selectbox("Dönem", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)
            with c3: tarih = st.date_input("Tarih", datetime.date.today())
            link = st.text_input("Link (Opsiyonel)")
            st.markdown("---")
            data = {}
            kat_sayisi = 0
            
            if page == "PPK Girişi":
                c_p1, c_p2 = st.columns(2)
                with c_p1: 
                    st.markdown("### 1. Bu Ayki Karar")
                    # ARALIK GİRİŞİ 1
                    range_ppk = st.text_input("🧮 Aralık (Örn: 42-45)", key="rng_ppk", help="Burayı doldurursanız sayısal alanlar ezilir.")
                    val_faiz = st.number_input("Medyan %", step=0.25, format="%.2f")
                
                with c_p2:
                    st.markdown("### 2. Sene Sonu")
                    # ARALIK GİRİŞİ 2
                    range_ys = st.text_input("🧮 Aralık (Örn: 30-35)", key="rng_ys", help="Burayı doldurursanız sayısal alanlar ezilir.")
                    val_ys = st.number_input("Medyan % (YS)", step=0.25, format="%.2f", key="ysf")
                
                with st.expander("Detaylar (Min/Max/N)"):
                    ec1, ec2, ec3 = st.columns(3)
                    min_f = ec1.number_input("Min", step=0.25); max_f = ec1.number_input("Max", step=0.25)
                    min_ys = ec2.number_input("Min YS", step=0.25); max_ys = ec2.number_input("Max YS", step=0.25)
                    kat_sayisi = ec3.number_input("N", step=1)
                
                # PARSING LOGIC
                md, mn, mx, ok = parse_range_input(range_ppk, val_faiz)
                if ok: val_faiz, min_f, max_f = md, mn, mx
                md2, mn2, mx2, ok2 = parse_range_input(range_ys, val_ys)
                if ok2: val_ys, min_ys, max_ys = md2, mn2, mx2

                data = {
                    "tahmin_ppk_faiz": val_faiz, "min_ppk_faiz": min_f, "max_ppk_faiz": max_f,
                    "tahmin_yilsonu_faiz": val_ys, "min_yilsonu_faiz": min_ys, "max_yilsonu_faiz": max_ys
                }

            else: # Enflasyon
                cm1, cm2, cm3 = st.columns(3)
                with cm1:
                    r1 = st.text_input("Aralık Ay", key="r1"); va = st.number_input("1. Aylık Medyan", step=0.1)
                with cm2:
                    r2 = st.text_input("Aralık Yıl", key="r2"); vy = st.number_input("2. Yıllık Medyan", step=0.1)
                with cm3:
                    r3 = st.text_input("Aralık YS", key="r3"); vys = st.number_input("3. YS Medyan", step=0.1)
                
                with st.expander("Detaylar (Min/Max/N)"):
                    ec1, ec2, ec3 = st.columns(3)
                    mina=ec1.number_input("Min Ay", step=0.1); maxa=ec1.number_input("Max Ay", step=0.1)
                    miny=ec2.number_input("Min Yıl", step=0.1); maxy=ec2.number_input("Max Yıl", step=0.1)
                    minys=ec3.number_input("Min YS", step=0.1); maxys=ec3.number_input("Max YS", step=0.1)
                    kat_sayisi = st.number_input("N", step=1)
                
                md1, mn1, mx1, ok1 = parse_range_input(r1, va)
                if ok1: va, mina, maxa = md1, mn1, mx1
                md2, mn2, mx2, ok2 = parse_range_input(r2, vy)
                if ok2: vy, miny, maxy = md2, mn2, mx2
                md3, mn3, mx3, ok3 = parse_range_input(r3, vys)
                if ok3: vys, minys, maxys = md3, mn3, mx3

                data = {
                    "tahmin_aylik_enf": va, "min_aylik_enf": mina, "max_aylik_enf": maxa,
                    "tahmin_yillik_enf": vy, "min_yillik_enf": miny, "max_yillik_enf": maxy,
                    "tahmin_yilsonu_enf": vys, "min_yilsonu_enf": minys, "max_yilsonu_enf": maxys
                }

            data["katilimci_sayisi"] = int(kat_sayisi) if kat_sayisi > 0 else 0
            
            if st.form_submit_button("✅ Kaydet"):
                if user:
                    upsert_tahmin(user, donem, cat, tarih, link, data)
                    st.toast("Kaydedildi!", icon="🎉")
                else: st.error("Kullanıcı Seçiniz")

# ========================================================
# SAYFA: KATILIMCI YÖNETİMİ
# ========================================================
elif page == "Katılımcı Yönetimi":
    st.header("👥 Katılımcı Yönetimi")
    with st.expander("➕ Yeni Kişi Ekle", expanded=True):
        with st.form("new_kat"):
            c1, c2 = st.columns(2)
            ad = c1.text_input("Ad / Kurum"); cat = c2.radio("Kategori", ["Bireysel", "Kurumsal"], horizontal=True)
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

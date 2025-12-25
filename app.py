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
    return df

def parse_range_input(text_input, default_median=0.0):
    if not text_input or text_input.strip() == "": return default_median, 0.0, 0.0, False
    try:
        text = text_input.replace(',', '.')
        parts = []
        if '-' in text: parts = text.split('-')
        elif '/' in text: parts = text.split('/')
        if len(parts) == 2:
            v1, v2 = float(parts[0].strip()), float(parts[1].strip())
            return (v1+v2)/2, min(v1, v2), max(v1, v2), True
    except: pass
    return default_median, 0.0, 0.0, False

def upsert_tahmin(user, period, category, forecast_date, link, data_dict):
    date_str = forecast_date.strftime("%Y-%m-%d")
    check_res = supabase.table(TABLE_TAHMIN).select("id").eq("kullanici_adi", user).eq("donem", period).eq("tahmin_tarihi", date_str).execute()
    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    clean_data.update({"kullanici_adi": user, "donem": period, "kategori": category, "tahmin_tarihi": date_str, "kaynak_link": link if link else None})
    if check_res.data:
        record_id = check_res.data[0]['id']
        supabase.table(TABLE_TAHMIN).update(clean_data).eq("id", record_id).execute()
        return "updated"
    else:
        supabase.table(TABLE_TAHMIN).insert(clean_data).execute()
        return "inserted"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer: df.to_excel(writer, index=False, sheet_name='Tahminler')
    return output.getvalue()

def create_pdf_report(dataframe, figures):
    class PDF(FPDF):
        def header(self):
            self.set_font('Helvetica', 'B', 15); self.cell(0, 10, 'Ekonomi Tahmin Raporu', align='C'); self.ln(15)
        def footer(self):
            self.set_y(-15); self.set_font('Helvetica', 'I', 8); self.cell(0, 10, f'Sayfa {self.page_no()}', align='C')
    pdf = PDF(); pdf.add_page(); pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, f"Rapor Tarihi: {pd.Timestamp.now().strftime('%Y-%m-%d')}", ln=True); pdf.ln(5)
    for title, fig in figures.items():
        pdf.add_page(); pdf.set_font("Helvetica", 'B', 14)
        clean_title = title.replace("ı", "i").replace("ğ", "g").replace("ş", "s").replace("İ", "I").replace("ö", "o").replace("ü", "u").replace("ç", "c")
        pdf.cell(0, 10, clean_title, ln=True, align='C')
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
            try: fig.write_image(tmpfile.name, width=800, height=500, scale=2); pdf.image(tmpfile.name, x=10, y=30, w=190)
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
    page = st.radio("Git:", ["Gelişmiş Veri Havuzu (Yönetim)", "Dashboard", "🔥 Isı Haritası", "PPK Girişi", "Enflasyon Girişi", "Katılımcı Yönetimi"])

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
# SAYFA: GELİŞMİŞ VERİ HAVUZU
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
            df_full['tahmin_tarihi'] = pd.to_datetime(df_full['tahmin_tarihi'])

            with st.container():
                c1, c2, c3, c4 = st.columns(4)
                sel_cat = c1.selectbox("Kategori", ["Tümü"] + list(df_full['kategori'].unique()))
                sel_period = c2.selectbox("Dönem", ["Tümü"] + sorted(list(df_full['donem'].unique()), reverse=True))
                sel_user = c3.selectbox("Katılımcı", ["Tümü"] + sorted(list(df_full['kullanici_adi'].unique())))
                admin_mode = c4.toggle("🛠️ Yönetici Modu")

            df_f = df_full.copy()
            if sel_cat != "Tümü": df_f = df_f[df_f['kategori'] == sel_cat]
            if sel_period != "Tümü": df_f = df_f[df_f['donem'] == sel_period]
            if sel_user != "Tümü": df_f = df_f[df_f['kullanici_adi'] == sel_user]
            
            if not admin_mode:
                st.markdown("---")
                cols = ["tahmin_tarihi", "donem", "kullanici_adi", "kategori", "anket_kaynagi", "kaynak_link", "katilimci_sayisi", "tahmin_ppk_faiz", "tahmin_yilsonu_faiz", "tahmin_aylik_enf", "tahmin_yilsonu_enf"]
                final_cols = [c for c in cols if c in df_f.columns]
                col_cfg = {"kaynak_link": st.column_config.LinkColumn("Link", display_text="🔗"), "tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY"), **{c: st.column_config.NumberColumn(c, format="%.2f") for c in final_cols if "tahmin" in c}}
                st.dataframe(df_f[final_cols].sort_values(by="tahmin_tarihi", ascending=False), column_config=col_cfg, use_container_width=True, height=600)
                if not df_f.empty:
                    df_ex = df_f.copy(); df_ex['tahmin_tarihi'] = df_ex['tahmin_tarihi'].dt.strftime('%Y-%m-%d')
                    st.download_button("📥 Excel İndir", to_excel(df_ex), f"Veri_{sel_user}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
            else:
                if 'admin_ok' not in st.session_state: st.session_state['admin_ok'] = False
                if not st.session_state['admin_ok']:
                    with st.form("admin_login"):
                        if st.form_submit_button("Giriş") and st.text_input("Şifre", type="password") == "Admin": st.session_state['admin_ok'] = True; st.rerun()
                else:
                    if 'edit_target' in st.session_state:
                        t = st.session_state['edit_target']
                        with st.form("full_edit_form"):
                            st.subheader(f"Düzenle: {t['kullanici_adi']} ({t['donem']})")
                            c1, c2, c3 = st.columns(3)
                            nd = c1.date_input("Tarih", pd.to_datetime(t.get('tahmin_tarihi')).date())
                            ndo = c2.selectbox("Dönem", tum_donemler, index=tum_donemler.index(t['donem']) if t['donem'] in tum_donemler else 0)
                            nl = c3.text_input("Link", t.get('kaynak_link') or "")
                            
                            def g(k): return float(t.get(k) or 0)
                            tp, te = st.tabs(["Faiz", "Enflasyon"])
                            with tp:
                                c1, c2, c3 = st.columns(3)
                                npk = c1.number_input("PPK", value=g('tahmin_ppk_faiz'), step=0.25)
                                nyf = c2.number_input("YS Faiz", value=g('tahmin_yilsonu_faiz'), step=0.25)
                                nk = c3.number_input("N", value=safe_int(t.get('katilimci_sayisi')), step=1)
                            with te:
                                c1, c2 = st.columns(2)
                                na = c1.number_input("Ay Enf", value=g('tahmin_aylik_enf'), step=0.1)
                                nye = c2.number_input("YS Enf", value=g('tahmin_yilsonu_enf'), step=0.1)
                            
                            if st.form_submit_button("Kaydet"):
                                def cv(v): return v if v!=0 else None
                                upd = {"tahmin_tarihi": nd.strftime('%Y-%m-%d'), "donem": ndo, "kaynak_link": nl if nl else None, "katilimci_sayisi": int(nk), "tahmin_ppk_faiz": cv(npk), "tahmin_yilsonu_faiz": cv(nyf), "tahmin_aylik_enf": cv(na), "tahmin_yilsonu_enf": cv(nye)}
                                supabase.table(TABLE_TAHMIN).update(upd).eq("id", int(t['id'])).execute()
                                del st.session_state['edit_target']; st.rerun()
                        if st.button("İptal"): del st.session_state['edit_target']; st.rerun()
                    else:
                        st.markdown("---")
                        df_f = df_f.sort_values(by="tahmin_tarihi", ascending=False)
                        for idx, row in df_f.iterrows():
                            with st.container():
                                c1, c2, c3 = st.columns([6, 1, 1])
                                c1.markdown(f"**{row['kullanici_adi']}** | {row['donem']}")
                                if c2.button("✏️", key=f"e{row['id']}"): st.session_state['edit_target'] = row; st.rerun()
                                if c3.button("🗑️", key=f"d{row['id']}"): supabase.table(TABLE_TAHMIN).delete().eq("id", int(row['id'])).execute(); st.rerun()

# ========================================================
# SAYFA: ISI HARİTASI (HATA DÜZELTİLDİ)
# ========================================================
elif page == "🔥 Isı Haritası":
    st.header("🔥 Tahmin Isı Haritası")
    st.info("Katılımcıların tahmin değişimlerini renkli tablo olarak izleyin.")

    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_k = pd.DataFrame(res_k.data)

    if not df_t.empty and not df_k.empty:
        df_t = clean_and_sort_data(df_t)
        df_t = df_t.sort_values(by='tahmin_tarihi')
        df_latest = df_t.drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
        df = pd.merge(df_latest, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        df['gorunen_isim'] = df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)

        with st.expander("⚙️ Harita Ayarları", expanded=True):
            c1, c2, c3 = st.columns(3)
            metrics = {"PPK Faizi": "tahmin_ppk_faiz", "Yıl Sonu Faiz": "tahmin_yilsonu_faiz", "Aylık Enflasyon": "tahmin_aylik_enf", "Yıl Sonu Enflasyon": "tahmin_yilsonu_enf"}
            sel_metric_label = c1.selectbox("Veri Seti", list(metrics.keys()))
            sel_metric = metrics[sel_metric_label]
            
            all_users = sorted(df['gorunen_isim'].unique())
            sel_users = c2.multiselect("Katılımcılar", all_users, default=all_users[:5] if len(all_users)>0 else [])
            
            all_periods = sorted(df['donem'].unique())
            sel_periods = c3.multiselect("Dönemler", all_periods, default=all_periods[-6:] if len(all_periods)>0 else [])

        if not sel_users or not sel_periods: st.warning("Lütfen seçim yapınız."); st.stop()

        df_filtered = df[df['gorunen_isim'].isin(sel_users) & df['donem'].isin(sel_periods)]
        pivot_df = df_filtered.pivot(index='gorunen_isim', columns='donem', values=sel_metric)
        # HATA DÜZELTME BURADA: axis=1 KALDIRILDI
        pivot_df = pivot_df.reindex(columns=sorted(pivot_df.columns))

        def highlight_changes(data):
            styles = pd.DataFrame('', index=data.index, columns=data.columns)
            for idx, row in data.iterrows():
                prev_val = None; first_val_found = False
                for col in data.columns:
                    val = row[col]
                    if pd.isna(val): continue
                    style = ''
                    if not first_val_found: style = 'background-color: #FFF9C4; color: black; font-weight: bold;'; first_val_found = True
                    else:
                        if prev_val is not None:
                            if val > prev_val: style = 'background-color: #FFCDD2; color: #B71C1C; font-weight: bold;'
                            elif val < prev_val: style = 'background-color: #C8E6C9; color: #1B5E20; font-weight: bold;'
                    styles.at[idx, col] = style
                    prev_val = val
            return styles

        st.markdown(f"### 🔥 {sel_metric_label} Değişim Tablosu")
        st.dataframe(pivot_df.style.apply(highlight_changes, axis=None).format("{:.2f}"), use_container_width=True, height=len(sel_users)*50+50)
        st.caption("🟡: İlk Tahmin | 🔴: Yükseliş | 🟢: Düşüş")
    else: st.info("Veri yok.")

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
        df_t['tahmin_tarihi'] = pd.to_datetime(df_t['tahmin_tarihi'])
        df_t = df_t.sort_values(by='tahmin_tarihi')
        df_latest = df_t.drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
        df = pd.merge(df_latest, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        
        df['gorunen_isim'] = df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)
        df['hover_text'] = df.apply(lambda x: f"Tarih: {x['tahmin_tarihi'].strftime('%d-%m-%Y')}<br>N={int(x['katilimci_sayisi'])}" if pd.notnull(x['katilimci_sayisi']) else "", axis=1)
        df['kategori'] = df['kategori'].fillna('Bireysel')
        df['anket_kaynagi'] = df['anket_kaynagi'].fillna('-')
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])

        c1, c2, c3 = st.columns(3)
        c1.metric("Toplam Katılımcı", df['kullanici_adi'].nunique())
        c2.metric("Güncel Tahmin Sayısı", len(df))
        c3.metric("Son Güncelleme", df['tahmin_tarihi'].max().strftime('%d.%m.%Y'))
        st.markdown("---")

        with st.sidebar:
            st.markdown("### 🔍 Dashboard Filtreleri")
            calc_method = st.radio("Medyan Hesaplama", ["Otomatik", "Manuel"])
            manual_median_val = 0.0 if calc_method == "Otomatik" else st.number_input("Manuel Değer", step=0.01, format="%.2f")
            
            cat_filter = st.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
            avail_src = sorted(df[df['kategori'].isin(cat_filter)]['anket_kaynagi'].astype(str).unique())
            src_filter = st.multiselect("Kaynak", avail_src, default=avail_src)
            avail_usr = sorted(df[df['kategori'].isin(cat_filter) & df['anket_kaynagi'].isin(src_filter)]['gorunen_isim'].unique())
            usr_filter = st.multiselect("Katılımcı", avail_usr, default=avail_usr)
            yr_filter = st.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        df_f = df[df['kategori'].isin(cat_filter) & df['anket_kaynagi'].isin(src_filter) & df['gorunen_isim'].isin(usr_filter) & df['yil'].isin(yr_filter)]
        if df_f.empty: st.warning("Veri bulunamadı."); st.stop()

        tabs = st.tabs(["📈 Zaman Serisi", "📍 Dağılım", "📦 Kutu Grafiği"])
        
        with tabs[0]:
            def plot(y, min_c, max_c, tit):
                fig = px.line(df_f.sort_values("donem_date"), x="donem", y=y, color="gorunen_isim", markers=True, title=tit, hover_data=["hover_text"])
                dfr = df_f.dropna(subset=[min_c, max_c])
                for u in dfr['gorunen_isim'].unique():
                    ud = dfr[dfr['gorunen_isim'] == u]
                    fig.add_trace(go.Scatter(x=ud['donem'], y=ud[y], mode='markers', error_y=dict(type='data', symmetric=False, array=ud[max_c]-ud[y], arrayminus=ud[y]-ud[min_c], color='gray', width=2), showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
            c1, c2 = st.columns(2); 
            with c1: plot("tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Karar")
            with c2: plot("tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz", "Sene Sonu Faiz")
            c3, c4 = st.columns(2)
            with c3: plot("tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "Aylık Enf")
            with c4: plot("tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "YS Enf")

        with tabs[1]:
            pers = sorted(list(df_f['donem'].unique()), reverse=True)
            tp = st.selectbox("Dönem Seç", pers, key="dp")
            dp = df_f[df_f['donem'] == tp].copy()
            met_map = {"PPK": "tahmin_ppk_faiz", "Ay Enf": "tahmin_aylik_enf", "YS Enf": "tahmin_yilsonu_enf"}
            sm = st.radio("Metrik", list(met_map.keys()), horizontal=True)
            mc = met_map[sm]
            dp = dp.dropna(subset=[mc])
            if len(dp)>0:
                mv = manual_median_val if calc_method == "Manuel" else dp[mc].median()
                dp = dp.sort_values(by=mc)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=dp[mc], y=dp['gorunen_isim'], mode='markers', marker=dict(size=14, color='#1976D2', line=dict(width=1, color='white')), name='Tahmin', text=[f"%{v:.2f}" for v in dp[mc]], hoverinfo='text'))
                fig.add_vline(x=mv, line_width=3, line_color="red")
                fig.add_annotation(x=mv, y=-0.1, text=f"MEDYAN %{mv:.2f}", showarrow=False, font=dict(color="red", size=14, weight="bold"), yref="paper")
                fig.update_layout(title=f"{sm} Dağılım ({tp})", height=max(500, len(dp)*35))
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Veri yok")

        with tabs[2]:
            mb = {"PPK": "tahmin_ppk_faiz", "Ay Enf": "tahmin_aylik_enf", "YS Enf": "tahmin_yilsonu_enf"}
            sb = st.selectbox("Veri Seti", list(mb.keys()))
            fig = px.box(df_f.sort_values("donem_date"), x="donem", y=mb[sb], color="donem", title=f"{sb} Dağılımı")
            st.plotly_chart(fig, use_container_width=True)

# ========================================================
# SAYFA: VERİ GİRİŞ
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
            data = {}; kat_sayisi = 0
            
            if page == "PPK Girişi":
                c1, c2 = st.columns(2)
                r1 = c1.text_input("Aralık (42-45)", key="r1"); v1 = c1.number_input("Medyan %", step=0.25)
                r2 = c2.text_input("Aralık YS", key="r2"); v2 = c2.number_input("YS Medyan %", step=0.25)
                with st.expander("Detaylar"):
                    ec1, ec2, ec3 = st.columns(3)
                    mn1 = ec1.number_input("Min", step=0.25); mx1 = ec1.number_input("Max", step=0.25)
                    mn2 = ec2.number_input("Min YS", step=0.25); mx2 = ec2.number_input("Max YS", step=0.25)
                    kat_sayisi = ec3.number_input("N", step=1)
                
                md, mn, mx, ok = parse_range_input(r1, v1); 
                if ok: v1, mn1, mx1 = md, mn, mx
                md2, mn2, mx2, ok2 = parse_range_input(r2, v2)
                if ok2: v2, mn2, mx2 = md2, mn2, mx2
                data = {"tahmin_ppk_faiz": v1, "min_ppk_faiz": mn1, "max_ppk_faiz": mx1, "tahmin_yilsonu_faiz": v2, "min_yilsonu_faiz": mn2, "max_yilsonu_faiz": mx2}
            
            else:
                c1, c2, c3 = st.columns(3)
                r1 = c1.text_input("Aralık Ay", key="r1"); v1 = c1.number_input("Ay Medyan", step=0.1)
                r2 = c2.text_input("Aralık Yıl", key="r2"); v2 = c2.number_input("Yıl Medyan", step=0.1)
                r3 = c3.text_input("Aralık YS", key="r3"); v3 = c3.number_input("YS Medyan", step=0.1)
                with st.expander("Detaylar"):
                    ec1, ec2, ec3 = st.columns(3)
                    mn1 = ec1.number_input("Min Ay", step=0.1); mx1 = ec1.number_input("Max Ay", step=0.1)
                    mn2 = ec2.number_input("Min Yıl", step=0.1); mx2 = ec2.number_input("Max Yıl", step=0.1)
                    mn3 = ec3.number_input("Min YS", step=0.1); mx3 = ec3.number_input("Max YS", step=0.1)
                    kat_sayisi = st.number_input("N", step=1)
                
                md1, mn1, mx1, ok1 = parse_range_input(r1, v1); 
                if ok1: v1, mn1, mx1 = md1, mn1, mx1
                md2, mn2, mx2, ok2 = parse_range_input(r2, v2)
                if ok2: v2, mn2, mx2 = md2, mn2, mx2
                md3, mn3, mx3, ok3 = parse_range_input(r3, v3)
                if ok3: v3, mn3, mx3 = md3, mn3, mx3
                data = {"tahmin_aylik_enf": v1, "min_aylik_enf": mn1, "max_aylik_enf": mx1, "tahmin_yillik_enf": v2, "min_yillik_enf": mn2, "max_yillik_enf": mx2, "tahmin_yilsonu_enf": v3, "min_yilsonu_enf": mn3, "max_yilsonu_enf": mx3}

            data["katilimci_sayisi"] = int(kat_sayisi) if kat_sayisi > 0 else 0
            if st.form_submit_button("✅ Kaydet"):
                if user: upsert_tahmin(user, donem, cat, tarih, link, data); st.toast("Kaydedildi!", icon="🎉")
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

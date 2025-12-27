import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
from fpdf.fonts import FontFace
import tempfile
import os
import io
import datetime
import time
import requests
import xlsxwriter

# --- EK KÜTÜPHANELER ---
try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    st.error("Lütfen kütüphaneleri yükleyin: pip install python-docx xlsxwriter evds")
    st.stop()

# EVDS Kütüphanesi (Opsiyonel import, hata vermemesi için)
try:
    import evds
except ImportError:
    evds = None

# --- 1. AYARLAR VE TASARIM ---
st.set_page_config(page_title="Finansal Tahmin Terminali", layout="wide", page_icon="📊", initial_sidebar_state="expanded")

st.markdown("""<style>.stMetric { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); } .stButton button { width: 100%; border-radius: 8px; font-weight: 600; } div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; background-color: white; } h1, h2, h3 { color: #2c3e50; } div[data-testid="stDataFrame"] { width: 100%; }</style>""", unsafe_allow_html=True)

# --- BAĞLANTI ---
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    # EVDS Anahtarı Kontrolü
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Lütfen secrets ayarlarını kontrol edin: {e}")
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

def normalize_name(name): return name.strip().title() if name else ""

def safe_int(val):
    try: return int(float(val)) if pd.notnull(val) else 0
    except: return 0

def clean_and_sort_data(df):
    if df.empty: return df
    numeric_cols = ["tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz", "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf", "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "katilimci_sayisi"]
    for col in numeric_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    if "donem" in df.columns:
        df["donem_date"] = pd.to_datetime(df["donem"], format="%Y-%m", errors='coerce')
        df = df.sort_values(by="donem_date")
    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"])
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

# --- YENİ: OTOMATİK VERİ ÇEKME (TCMB EVDS) ---
@st.cache_data(ttl=3600) # 1 saat cache
def fetch_realized_data(api_key):
    """
    TCMB EVDS'den gerçekleşen verileri çeker.
    Döndürür: { '2024-01': {'ppk': 45.0, 'enf_ay': 6.70, 'enf_yil': 64.86}, ... }
    """
    # Eğer API anahtarı yoksa boş dön veya örnek veri koy
    if not api_key or not evds:
        return {} 

    try:
        ev = evds.evdsAPI(api_key)
        # TP.PT.POL : Politika Faizi (1 Hafta Repo)
        # TP.TUFE1YI.AY.O : TÜFE (Aylık Değişim)
        # TP.TUFE1YI.YI.O : TÜFE (Yıllık Değişim)
        
        end_date = datetime.date.today().strftime("%d-%m-%Y")
        data = ev.get_data(['TP.PT.POL', 'TP.TUFE1YI.AY.O', 'TP.TUFE1YI.YI.O'], startdate="01-01-2024", enddate=end_date)
        
        realized_dict = {}
        for _, row in data.iterrows():
            if pd.isna(row['Tarih']): continue
            # Tarih formatı 'YYYY-MM' (Dönem formatımızla aynı olmalı)
            # EVDS bazen gün-ay-yıl döner, pandas to_datetime ile çözeriz
            dt = pd.to_datetime(row['Tarih'])
            donem_str = dt.strftime('%Y-%m')
            
            realized_dict[donem_str] = {
                'ppk': float(row['TP_PT_POL']) if pd.notnull(row.get('TP_PT_POL')) else None,
                'enf_ay': float(row['TP_TUFE1YI_AY_O']) if pd.notnull(row.get('TP_TUFE1YI_AY_O')) else None,
                'enf_yil': float(row['TP_TUFE1YI_YI_O']) if pd.notnull(row.get('TP_TUFE1YI_YI_O')) else None
            }
        return realized_dict
    except Exception as e:
        print(f"EVDS Hatası: {e}")
        return {}

# --- EXCEL MOTORU ---
def create_excel_dashboard(df_source):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    bold = workbook.add_format({'bold': 1})
    date_fmt = workbook.add_format({'num_format': 'dd/mm/yyyy'})
    num_fmt = workbook.add_format({'num_format': '0.00'})
    
    ws_raw = workbook.add_worksheet("Ham Veri")
    ws_raw.write_row('A1', df_source.columns, bold)
    for r, row in enumerate(df_source.values):
        for c, val in enumerate(row):
            if pd.isna(val): ws_raw.write_string(r+1, c, "")
            elif isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): ws_raw.write_datetime(r+1, c, val, date_fmt)
            else: ws_raw.write(r+1, c, val)

    def create_sheet_with_chart(metric_col, sheet_name, chart_title):
        df_sorted = df_source.sort_values("donem_date")
        try: pivot = df_sorted.pivot(index='donem', columns='gorunen_isim', values=metric_col)
        except: return
        ws = workbook.add_worksheet(sheet_name)
        ws.write('A1', 'Dönem', bold)
        ws.write_row('B1', pivot.columns, bold)
        ws.write_column('A2', pivot.index)
        for i, col_name in enumerate(pivot.columns):
            col_data = pivot[col_name]
            for r_idx, val in enumerate(col_data):
                if pd.isna(val): ws.write_string(r_idx+1, i+1, "")
                else: ws.write_number(r_idx+1, i+1, val, num_fmt)
        chart = workbook.add_chart({'type': 'line'})
        for i in range(len(pivot.columns)):
            chart.add_series({'name': [sheet_name, 0, i+1], 'categories': [sheet_name, 1, 0, len(pivot), 0], 'values': [sheet_name, 1, i+1, len(pivot), i+1], 'marker': {'type': 'circle', 'size': 5}, 'line': {'width': 2.25}})
        chart.set_title({'name': chart_title})
        chart.set_size({'width': 800, 'height': 450})
        ws.insert_chart('E2', chart)

    def create_heatmap_sheet(metric_col, sheet_name):
        try:
            df_s = df_source.sort_values("donem_date")
            pivot = df_s.pivot(index='gorunen_isim', columns='donem', values=metric_col)
        except: return
        ws = workbook.add_worksheet(sheet_name)
        ws.write('A1', 'Katılımcı / Dönem', bold)
        ws.write_row('B1', pivot.columns, bold)
        ws.write_column('A2', pivot.index, bold)
        for i, col_name in enumerate(pivot.columns):
            for r_idx, val in enumerate(pivot[col_name]):
                if pd.isna(val): ws.write_string(r_idx+1, i+1, "")
                else: ws.write_number(r_idx+1, i+1, val, num_fmt)
        ws.conditional_format(1, 1, len(pivot), len(pivot.columns), {'type': '3_color_scale', 'min_color': '#63BE7B', 'mid_color': '#FFEB84', 'max_color': '#F8696B'})
        ws.set_column(0, 0, 25)

    create_sheet_with_chart('tahmin_ppk_faiz', 'PPK Analiz', 'PPK Faiz Beklentileri')
    create_sheet_with_chart('tahmin_yilsonu_enf', 'Enflasyon Analiz', 'Yıl Sonu Enflasyon Beklentileri')
    create_heatmap_sheet('tahmin_ppk_faiz', 'Isı Haritası - PPK')
    create_heatmap_sheet('tahmin_yilsonu_enf', 'Isı Haritası - Enf')
    workbook.close()
    return output.getvalue()

# --- WORD RAPOR ---
def create_word_report(report_data):
    doc = Document()
    logo_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/5/58/TCMB_logo.svg/500px-TCMB_logo.svg.png"
    try:
        r = requests.get(logo_url, timeout=5)
        if r.status_code == 200:
            with io.BytesIO(r.content) as image_stream:
                logo_par = doc.add_paragraph(); logo_par.alignment = WD_ALIGN_PARAGRAPH.RIGHT; run = logo_par.add_run(); run.add_picture(image_stream, width=Inches(1.2))
    except: pass
    title = doc.add_heading(report_data['title'], 0); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_info = doc.add_paragraph(); p_info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_info.add_run(report_data['unit'] + "\n").bold = True; p_info.add_run(report_data['date']).italic = True
    doc.add_paragraph("") 
    if report_data['body']: doc.add_paragraph(report_data['body']).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for block in report_data['content_blocks']:
        doc.add_paragraph("")
        if block.get('title'): doc.add_heading(block['title'], level=2).runs[0].font.color.rgb = RGBColor(180, 0, 0)
        if block['type'] == 'chart':
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
                try: block['fig'].write_image(t.name, width=1000, height=500, scale=2); doc.add_picture(t.name, width=Inches(6.5))
                except: pass
            try: os.remove(t.name)
            except: pass
        elif block['type'] == 'table':
            df = block['df']; table = doc.add_table(rows=1, cols=len(df.columns)); table.style = 'Light Shading Accent 1'
            for i, c in enumerate(df.columns): table.rows[0].cells[i].text = str(c)
            for _, row in df.iterrows():
                rc = table.add_row().cells
                for i, item in enumerate(row): rc[i].text = str(item)
    output = io.BytesIO(); doc.save(output); return output.getvalue()

# --- PDF MOTORU ---
def check_and_download_font():
    paths = {"DejaVuSans.ttf": "https://github.com/google/fonts/raw/main/ofl/dejavusans/DejaVuSans-Regular.ttf", "DejaVuSans-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/dejavusans/DejaVuSans-Bold.ttf"}
    try:
        for p, u in paths.items():
            if not os.path.exists(p) or os.path.getsize(p) < 1000:
                r = requests.get(u, timeout=10)
                if r.status_code == 200:
                    with open(p, 'wb') as f: f.write(r.content)
        if os.path.exists("DejaVuSans.ttf"): return "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    except: pass
    return None, None

def safe_str(text, fallback):
    if not isinstance(text, str): return str(text)
    if fallback:
        tr = {'ğ':'g','Ğ':'G','ş':'s','Ş':'S','ı':'i','İ':'I','ö':'o','Ö':'O','ü':'u','Ü':'U','ç':'c','Ç':'C'}
        for k,v in tr.items(): text = text.replace(k,v)
    return text

def create_custom_pdf_report(report_data):
    fr, fb = check_and_download_font(); use_cust = (fr is not None); font = "DejaVu" if use_cust else "Helvetica"; fallback = not use_cust
    class RPT(FPDF):
        def header(self):
            logo_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/5/58/TCMB_logo.svg/500px-TCMB_logo.svg.png"
            if not os.path.exists("logo_tmp.png"):
                try: 
                    r = requests.get(logo_url, headers={'User-Agent':'Mozilla/5.0'}, verify=False, timeout=5)
                    if r.status_code==200:
                        with open("logo_tmp.png",'wb') as f: f.write(r.content)
                except: pass
            if os.path.exists("logo_tmp.png"): self.image("logo_tmp.png", x=170, y=10, w=30)
            self.ln(25)
        def footer(self): self.set_y(-15); self.set_font(font, '', 8); self.set_text_color(128); self.cell(0, 10, f'Sayfa {self.page_no()}', align='C')
    pdf = RPT()
    if use_cust: pdf.add_font("DejaVu", "", fr, uni=True); pdf.add_font("DejaVu", "B", fb, uni=True)
    pdf.add_page(); pdf.set_text_color(0)
    pdf.set_font(font, 'B', 20); pdf.cell(0, 10, safe_str(report_data['title'], fallback), ln=True)
    pdf.set_font(font, '', 12); pdf.set_text_color(80); pdf.cell(0, 8, safe_str(report_data['unit'], fallback), ln=True)
    pdf.set_text_color(0); pdf.set_font(font, '', 10); pdf.cell(0, 8, safe_str(report_data['date'], fallback), ln=True, align='R'); pdf.ln(5)
    if report_data['body']: pdf.set_font(font, '', 11); pdf.multi_cell(0, 6, safe_str(report_data['body'], fallback)); pdf.ln(10)
    for block in report_data['content_blocks']:
        if pdf.get_y() > 240: pdf.add_page()
        if block.get('title'): pdf.set_font(font, 'B', 12); pdf.set_text_color(200, 0, 0); pdf.cell(0, 10, safe_str(block['title'], fallback), ln=True); pdf.set_text_color(0); pdf.ln(2)
        if block['type'] == 'chart':
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
                try: block['fig'].write_image(t.name, width=1000, height=500, scale=2); pdf.image(t.name, x=15, w=180); pdf.ln(5)
                except: pass
            try: os.remove(t.name)
            except: pass
        elif block['type'] == 'table':
            df = block['df']; pdf.set_font(font, '', 8)
            with pdf.table() as tbl:
                r = tbl.row()
                for c in df.columns: r.cell(safe_str(str(c), fallback), style=FontFace(emphasis="BOLD", color=255, fill_color=(200, 50, 50)))
                for _, dr in df.iterrows():
                    r = tbl.row()
                    for item in dr: r.cell(safe_str(str(item), fallback))
            pdf.ln(10)
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
    page = st.radio("Git:", ["Gelişmiş Veri Havuzu (Yönetim)", "Dashboard", "🔥 Isı Haritası", "📄 Rapor Oluştur", "PPK Girişi", "Enflasyon Girişi", "Katılımcı Yönetimi"])

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
                cols = ["tahmin_tarihi", "donem", "kullanici_adi", "kategori", "anket_kaynagi", "kaynak_link", "katilimci_sayisi", "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "tahmin_yilsonu_faiz", "tahmin_aylik_enf", "tahmin_yillik_enf", "tahmin_yilsonu_enf"]
                final_cols = [c for c in cols if c in df_f.columns]
                col_cfg = {"kaynak_link": st.column_config.LinkColumn("Link", display_text="🔗"), "tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY"), **{c: st.column_config.NumberColumn(c, format="%.2f") for c in final_cols if "tahmin" in c or "min" in c or "max" in c}}
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
        
        # GERÇEKLEŞEN VERİLERİ ÇEK
        realized_data = fetch_realized_data(EVDS_API_KEY)
        
        df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        df_latest_raw = df_t.drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
        df_latest = pd.merge(df_latest_raw, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        
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
            x_axis_mode = st.radio("Grafik Görünümü (X Ekseni)", ["📅 Hedef Dönem (Vade)", "⏳ Tahmin Tarihi (Revizyon)"])
            st.markdown("---")
            calc_method = st.radio("Medyan Hesaplama", ["Otomatik", "Manuel"])
            manual_median_val = 0.0 if calc_method == "Otomatik" else st.number_input("Manuel Değer", step=0.01, format="%.2f")
            st.markdown("---")
            cat_filter = st.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
            avail_src = sorted(df_latest[df_latest['kategori'].isin(cat_filter)]['anket_kaynagi'].astype(str).unique())
            src_filter = st.multiselect("Kaynak", avail_src, default=avail_src)
            avail_usr = sorted(df_latest[df_latest['kategori'].isin(cat_filter) & df_latest['anket_kaynagi'].isin(src_filter)]['gorunen_isim'].unique())
            usr_filter = st.multiselect("Katılımcı", avail_usr, default=avail_usr)
            yr_filter = st.multiselect("Yıl", sorted(df_latest['yil'].unique()), default=sorted(df_latest['yil'].unique()))

        is_single_user = (len(usr_filter) == 1)
        
        if is_single_user:
            target_df = df_history[df_history['gorunen_isim'].isin(usr_filter) & df_history['yil'].isin(yr_filter)].copy()
            x_axis_col = "tahmin_tarihi"; x_label = "Tahmin Giriş Tarihi"; sort_col = "tahmin_tarihi"; tick_format = "%d-%m-%Y"
        else:
            target_df = df_latest[
                df_latest['kategori'].isin(cat_filter) & 
                df_latest['anket_kaynagi'].isin(src_filter) & 
                df_latest['gorunen_isim'].isin(usr_filter) & 
                df_latest['yil'].isin(yr_filter)
            ].copy()
            x_axis_col = "donem"; x_label = "Hedef Dönem"; sort_col = "donem_date"; tick_format = None

        if target_df.empty: st.warning("Veri bulunamadı."); st.stop()

        tabs = st.tabs(["📈 Zaman Serisi", "📍 Dağılım Analizi", "📦 Kutu Grafiği"])
        
        with tabs[0]:
            def plot(y, min_c, max_c, tit, real_key=None):
                chart_data = target_df.sort_values(sort_col)
                fig = px.line(chart_data, x=x_axis_col, y=y, color="gorunen_isim" if not is_single_user else "donem", markers=True, title=tit, hover_data=["hover_text"])
                if tick_format: fig.update_xaxes(tickformat=tick_format)
                
                # GERÇEKLEŞMELERİ EKLE (Sadece "Hedef Dönem" modunda anlamlıdır)
                if x_axis_mode.startswith("📅") and real_key and realized_data:
                    # Gerçekleşen verileri DataFrame'e çevir
                    real_df_data = []
                    for d, vals in realized_data.items():
                        if vals.get(real_key) is not None:
                            real_df_data.append({'donem': d, 'deger': vals[real_key]})
                    
                    if real_df_data:
                        real_df = pd.DataFrame(real_df_data).sort_values('donem')
                        # Sadece grafikteki dönem aralığını filtrele
                        min_d = chart_data['donem'].min()
                        max_d = chart_data['donem'].max()
                        real_df = real_df[(real_df['donem'] >= min_d) & (real_df['donem'] <= max_d)]
                        
                        if not real_df.empty:
                            fig.add_trace(go.Scatter(
                                x=real_df['donem'], y=real_df['deger'],
                                mode='lines+markers',
                                name='GERÇEKLEŞME',
                                line=dict(color='black', width=4),
                                marker=dict(size=8, color='black')
                            ))

                dfr = chart_data.dropna(subset=[min_c, max_c])
                if not dfr.empty:
                    grp = "donem" if is_single_user else "gorunen_isim"
                    for g in dfr[grp].unique():
                        ud = dfr[dfr[grp] == g]
                        fig.add_trace(go.Scatter(x=ud[x_axis_col], y=ud[y], mode='markers', error_y=dict(type='data', symmetric=False, array=ud[max_c]-ud[y], arrayminus=ud[y]-ud[min_c], color='gray', width=2), showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
            
            c1, c2 = st.columns(2); 
            # Parametre olarak EVDS anahtarlarını gönderiyoruz (ppk, enf_ay, enf_yil)
            with c1: plot("tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Karar", "ppk")
            with c2: plot("tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz", "Sene Sonu Faiz", None)
            c3, c4 = st.columns(2)
            with c3: plot("tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "Aylık Enf", "enf_ay")
            with c4: plot("tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "YS Enf", "enf_yil")

        with tabs[1]:
            pers = sorted(list(target_df['donem'].unique()), reverse=True)
            tp = st.selectbox("Dönem Seç", pers, key="dp")
            dp = target_df[target_df['donem'] == tp].copy()
            met_map = {"PPK": "tahmin_ppk_faiz", "Ay Enf": "tahmin_aylik_enf", "YS Enf": "tahmin_yilsonu_enf"}
            sm = st.radio("Metrik", list(met_map.keys()), horizontal=True)
            mc = met_map[sm]
            dp = dp.dropna(subset=[mc])
            if len(dp)>0:
                mv = manual_median_val if calc_method == "Manuel" else dp[mc].median()
                dp = dp.sort_values(by=mc)
                fig = go.Figure()
                y_val = dp['tahmin_tarihi'].dt.strftime('%d-%m-%Y') if (is_single_user) else dp['gorunen_isim']
                fig.add_trace(go.Scatter(x=dp[mc], y=y_val, mode='markers', marker=dict(size=14, color='#1976D2', line=dict(width=1, color='white')), name='Tahmin', text=[f"%{v:.2f}" for v in dp[mc]], hoverinfo='text'))
                fig.add_vline(x=mv, line_width=3, line_color="red")
                fig.add_annotation(x=mv, y=-0.1, text=f"MEDYAN %{mv:.2f}", showarrow=False, font=dict(color="red", size=14, weight="bold"), yref="paper")
                fig.update_layout(title=f"{sm} Dağılım ({tp})", height=max(500, len(dp)*35))
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Veri yok")

        with tabs[2]:
            mb = {"PPK": "tahmin_ppk_faiz", "Ay Enf": "tahmin_aylik_enf", "YS Enf": "tahmin_yilsonu_enf"}
            sb = st.selectbox("Veri Seti", list(mb.keys()))
            fig = px.box(target_df.sort_values("donem_date"), x="donem", y=mb[sb], color="donem", title=f"{sb} Dağılımı")
            st.plotly_chart(fig, use_container_width=True)

# ... (ISI HARİTASI, RAPOR OLUŞTUR VE VERİ GİRİŞ SAYFALARI AYNI KALDI - YER KAPLAMAMASI İÇİN TEKRARLAMADIM) ...
# (Önceki yanıttaki kodun devamı buraya gelecek)

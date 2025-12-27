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

# --- KÜTÜPHANE KONTROLÜ ---
try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    st.error("Lütfen gerekli kütüphaneleri yükleyin: pip install python-docx xlsxwriter evds")
    st.stop()

# EVDS Kütüphanesi
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
    # EVDS API Anahtarı
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

# --- GELİŞMİŞ GERÇEKLEŞEN VERİ YÖNETİCİSİ (CACHE & MANUAL FALLBACK) ---
@st.cache_data(ttl=3600)
def fetch_realized_dataframe(api_key, start_date_str="01-01-2024", end_date_str=None):
    """
    EVDS'den verileri çeker ve Pandas DataFrame olarak döndürür.
    API yoksa veya hata olursa manuel veriyi döndürür.
    """
    if not end_date_str:
        end_date_str = datetime.date.today().strftime("%d-%m-%Y")

    # Manuel Veri Seti (Yedek)
    manual_data = [
        {'Tarih': '2024-01', 'PPK Faizi': 45.0, 'Aylık TÜFE': 6.70, 'Yıllık TÜFE': 64.86},
        {'Tarih': '2024-02', 'PPK Faizi': 45.0, 'Aylık TÜFE': 4.53, 'Yıllık TÜFE': 67.07},
        {'Tarih': '2024-03', 'PPK Faizi': 50.0, 'Aylık TÜFE': 3.16, 'Yıllık TÜFE': 68.50},
        {'Tarih': '2024-04', 'PPK Faizi': 50.0, 'Aylık TÜFE': 3.18, 'Yıllık TÜFE': 69.80},
        {'Tarih': '2024-05', 'PPK Faizi': 50.0, 'Aylık TÜFE': 3.37, 'Yıllık TÜFE': 75.45},
        {'Tarih': '2024-06', 'PPK Faizi': 50.0, 'Aylık TÜFE': 1.64, 'Yıllık TÜFE': 71.60},
        {'Tarih': '2024-07', 'PPK Faizi': 50.0, 'Aylık TÜFE': 3.23, 'Yıllık TÜFE': 61.78},
        {'Tarih': '2024-08', 'PPK Faizi': 50.0, 'Aylık TÜFE': 2.47, 'Yıllık TÜFE': 51.97},
        {'Tarih': '2024-09', 'PPK Faizi': 50.0, 'Aylık TÜFE': 2.97, 'Yıllık TÜFE': 49.38},
        {'Tarih': '2024-10', 'PPK Faizi': 50.0, 'Aylık TÜFE': 2.88, 'Yıllık TÜFE': 48.58},
        {'Tarih': '2024-11', 'PPK Faizi': 50.0, 'Aylık TÜFE': 2.24, 'Yıllık TÜFE': 47.09},
    ]
    
    # API Kontrolü
    if api_key and evds:
        try:
            ev = evds.evdsAPI(api_key)
            # TP.PT.POL : Politika Faizi
            # TP.TUFE1YI.AY.O : Aylık TÜFE
            # TP.TUFE1YI.YI.O : Yıllık TÜFE
            data = ev.get_data(['TP.PT.POL', 'TP.TUFE1YI.AY.O', 'TP.TUFE1YI.YI.O'], startdate=start_date_str, enddate=end_date_str)
            
            clean_rows = []
            for _, row in data.iterrows():
                if pd.isna(row['Tarih']): continue
                dt = pd.to_datetime(row['Tarih'])
                
                clean_rows.append({
                    'Tarih': dt.strftime('%Y-%m'),
                    'PPK Faizi': float(row['TP_PT_POL']) if pd.notnull(row.get('TP_PT_POL')) else None,
                    'Aylık TÜFE': float(row['TP_TUFE1YI_AY_O']) if pd.notnull(row.get('TP_TUFE1YI_AY_O')) else None,
                    'Yıllık TÜFE': float(row['TP_TUFE1YI_YI_O']) if pd.notnull(row.get('TP_TUFE1YI_YI_O')) else None
                })
            
            if clean_rows:
                return pd.DataFrame(clean_rows), "API"
        except:
            pass # Hata olursa manuele düş

    return pd.DataFrame(manual_data), "Manuel"

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
        ws.write('A1', 'Dönem', bold); ws.write_row('B1', pivot.columns, bold); ws.write_column('A2', pivot.index)
        for i, col_name in enumerate(pivot.columns):
            for r_idx, val in enumerate(pivot[col_name]):
                if pd.isna(val): ws.write_string(r_idx+1, i+1, "")
                else: ws.write_number(r_idx+1, i+1, val, num_fmt)
        chart = workbook.add_chart({'type': 'line'})
        for i in range(len(pivot.columns)):
            chart.add_series({'name': [sheet_name, 0, i+1], 'categories': [sheet_name, 1, 0, len(pivot), 0], 'values': [sheet_name, 1, i+1, len(pivot), i+1], 'marker': {'type': 'circle', 'size': 5}, 'line': {'width': 2.25}})
        chart.set_title({'name': chart_title}); chart.set_size({'width': 800, 'height': 450})
        ws.insert_chart('E2', chart)

    def create_heatmap_sheet(metric_col, sheet_name):
        try:
            df_s = df_source.sort_values("donem_date")
            pivot = df_s.pivot(index='gorunen_isim', columns='donem', values=metric_col)
        except: return
        ws = workbook.add_worksheet(sheet_name)
        ws.write('A1', 'Katılımcı / Dönem', bold); ws.write_row('B1', pivot.columns, bold); ws.write_column('A2', pivot.index, bold)
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
    page = st.radio("Git:", ["Gelişmiş Veri Havuzu (Yönetim)", "Dashboard", "🔥 Isı Haritası", "📈 Piyasa Verileri (EVDS)", "📄 Rapor Oluştur", "PPK Girişi", "Enflasyon Girişi", "Katılımcı Yönetimi"])

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
        
        # GERÇEKLEŞEN VERİLERİ ÇEK (EVDS veya MANUEL)
        realized_df, data_source = fetch_realized_dataframe(EVDS_API_KEY)
        
        # Gerçekleşen veriyi dict formatına çevir (Hızlı erişim için)
        realized_dict = {}
        if not realized_df.empty:
            for _, row in realized_df.iterrows():
                realized_dict[row['Tarih']] = {
                    'ppk': row['PPK Faizi'],
                    'enf_ay': row['Aylık TÜFE'],
                    'enf_yil': row['Yıllık TÜFE']
                }

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
        c3.metric("Veri Kaynağı", data_source)
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
                
                # GERÇEKLEŞEN ÇİZGİSİ
                if x_axis_mode.startswith("📅") and real_key and realized_dict:
                    real_df_list = []
                    for d, vals in realized_dict.items():
                        if vals.get(real_key) is not None:
                            real_df_list.append({'donem': d, 'deger': vals[real_key]})
                    
                    if real_df_list:
                        rdf = pd.DataFrame(real_df_list).sort_values('donem')
                        # Filtrele (Grafik aralığına göre)
                        # Bu kısım önemli: Geçmiş veriyi de gösterebilmek için filtreyi geniş tutabiliriz veya tam eşleştirebiliriz.
                        # Şimdilik grafik aralığına girenleri alalım.
                        min_d = chart_data['donem'].min()
                        max_d = chart_data['donem'].max()
                        # Eğer geçmiş veri de görünsün isterseniz aşağıdaki filtreyi kaldırabilirsiniz.
                        rdf = rdf[(rdf['donem'] >= min_d) & (rdf['donem'] <= max_d)]
                        
                        if not rdf.empty:
                            fig.add_trace(go.Scatter(
                                x=rdf['donem'], y=rdf['deger'],
                                mode='lines+markers', name='GERÇEKLEŞEN',
                                line=dict(color='black', width=4), marker=dict(size=8, color='black')
                            ))

                dfr = chart_data.dropna(subset=[min_c, max_c])
                if not dfr.empty:
                    grp = "donem" if is_single_user else "gorunen_isim"
                    for g in dfr[grp].unique():
                        ud = dfr[dfr[grp] == g]
                        fig.add_trace(go.Scatter(x=ud[x_axis_col], y=ud[y], mode='markers', error_y=dict(type='data', symmetric=False, array=ud[max_c]-ud[y], arrayminus=ud[y]-ud[min_c], color='gray', width=2), showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
            
            c1, c2 = st.columns(2); 
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

# ========================================================
# SAYFA: ISI HARİTASI
# ========================================================
elif page == "🔥 Isı Haritası":
    st.header("🔥 Tahmin Isı Haritası")
    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_k = pd.DataFrame(res_k.data)

    if not df_t.empty and not df_k.empty:
        df_t = clean_and_sort_data(df_t)
        df_t['tahmin_tarihi'] = pd.to_datetime(df_t['tahmin_tarihi'])
        df_t = df_t.sort_values(by='tahmin_tarihi')
        df_full = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        df_full['gorunen_isim'] = df_full.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)

        with st.expander("⚙️ Harita Ayarları", expanded=True):
            view_mode = st.radio("Görünüm Modu", ["📅 Hedef Dönem Karşılaştırması", "⏳ Zaman İçindeki Değişim (Revizyon)"], horizontal=True)
            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            metrics = {"PPK Faizi": "tahmin_ppk_faiz", "Yıl Sonu Faiz": "tahmin_yilsonu_faiz", "Aylık Enflasyon": "tahmin_aylik_enf", "Yıl Sonu Enflasyon": "tahmin_yilsonu_enf"}
            sel_metric_label = c1.selectbox("Veri Seti", list(metrics.keys()))
            sel_metric = metrics[sel_metric_label]
            
            all_users = sorted(df_full['gorunen_isim'].unique())
            sel_users = c2.multiselect("Katılımcılar", all_users, default=all_users[:10] if len(all_users)>0 else [])
            all_periods = sorted(df_full['donem'].unique(), reverse=True)
            
            if view_mode.startswith("📅"):
                sel_periods = c3.multiselect("Hedef Dönemler", all_periods, default=all_periods[:6] if len(all_periods)>0 else [])
                if not sel_users or not sel_periods: st.stop()
                df_f = df_full[df_full['gorunen_isim'].isin(sel_users) & df_full['donem'].isin(sel_periods)].copy()
                df_f = df_f.sort_values(by='tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
                piv_col = 'donem'
            else:
                target_period = c3.selectbox("Hangi Hedefin Geçmişini İzliceksiniz?", all_periods)
                time_granularity = c3.radio("Zaman Dilimi", ["🗓️ Aylık (Son Veri)", "📆 Günlük (Detaylı)"])
                if not sel_users or not target_period: st.stop()
                df_f = df_full[df_full['gorunen_isim'].isin(sel_users) & (df_full['donem'] == target_period)].copy()
                if "Günlük" in time_granularity: df_f['tahmin_zaman'] = df_f['tahmin_tarihi'].dt.strftime('%Y-%m-%d')
                else: df_f['tahmin_zaman'] = df_f['tahmin_tarihi'].dt.strftime('%Y-%m')
                df_f = df_f.sort_values(by='tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'tahmin_zaman'], keep='last')
                piv_col = 'tahmin_zaman'

        if df_f.empty: st.warning("Veri yok."); st.stop()
        pivot_df = df_f.pivot(index='gorunen_isim', columns=piv_col, values=sel_metric)
        pivot_df = pivot_df.reindex(columns=sorted(pivot_df.columns))

        def highlight(data):
            styles = pd.DataFrame('', index=data.index, columns=data.columns)
            for idx, row in data.iterrows():
                prev = None; first = False
                for col in data.columns:
                    val = row[col]
                    if pd.isna(val): continue
                    st = ''
                    if not first: st='background-color: #FFF9C4; color: black; font-weight: bold; border: 1px solid white;'; first=True
                    else:
                        if prev is not None:
                            if val > prev: st='background-color: #FFCDD2; color: #B71C1C; font-weight: bold; border: 1px solid white;'
                            elif val < prev: st='background-color: #C8E6C9; color: #1B5E20; font-weight: bold; border: 1px solid white;'
                            else: st='background-color: #FFF9C4; color: black; font-weight: bold; border: 1px solid white;'
                    styles.at[idx, col] = st
                    prev = val
            return styles

        st.markdown(f"### 🔥 {sel_metric_label} Analizi")
        st.dataframe(pivot_df.style.apply(highlight, axis=None).format("{:.2f}"), use_container_width=True, height=len(sel_users)*50+100)
        st.caption("🟡: İlk Veri / Değişim Yok | 🔴: Yükseliş | 🟢: Düşüş")
    else: st.info("Veri yok.")

# ========================================================
# SAYFA: PIYASA VERILERI (YENİ EKLENEN SAYFA)
# ========================================================
elif page == "📈 Piyasa Verileri (EVDS)":
    st.header("📈 Gerçekleşen Piyasa Verileri")
    st.info("TCMB EVDS veya tanımlı veri setinden alınan gerçekleşen enflasyon ve faiz oranları.")
    
    with st.sidebar:
        st.markdown("### 📅 Tarih Aralığı")
        sd = st.date_input("Başlangıç", datetime.date(2024, 1, 1))
        ed = st.date_input("Bitiş", datetime.date.today())
        
    df_evds, source = fetch_realized_dataframe(EVDS_API_KEY, sd.strftime("%d-%m-%Y"), ed.strftime("%d-%m-%Y"))
    
    c1, c2 = st.columns([3, 1])
    with c1:
        st.dataframe(df_evds, use_container_width=True, height=500)
    with c2:
        st.metric("Veri Kaynağı", source)
        st.download_button("📥 Excel Olarak İndir", to_excel(df_evds), "PiyasaVerileri.xlsx", type="primary")

# ========================================================
# SAYFA: RAPOR OLUŞTUR
# ========================================================
elif page == "📄 Rapor Oluştur":
    st.header("📄 Profesyonel Rapor Oluşturucu")
    st.info("Raporunuzu Word (Docx) formatında indirip Google Docs ile düzenleyebilirsiniz. Ayrıca editlenebilir Excel grafikleri de alabilirsiniz.")

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
        df['kategori'] = df['kategori'].fillna('Bireysel')
        df['anket_kaynagi'] = df['anket_kaynagi'].fillna('-')
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])

        c_left, c_right = st.columns([1, 2])
        
        with c_left:
            st.subheader("1. Rapor Bilgileri")
            rep_title = st.text_input("Rapor Başlığı", "Piyasa Beklentileri Raporu")
            rep_unit = st.text_input("Birim İsmi", "Reel Sektör İlişkileri")
            rep_date = st.date_input("Rapor Tarihi", datetime.date.today())
            rep_body = st.text_area("Analiz Metni", height=150, placeholder="Analiz metni...")

            st.markdown("---")
            st.subheader("2. İçerik Seçimi")
            inc_ppk_chart = st.checkbox("Grafik: PPK Beklentileri", value=True)
            inc_enf_chart = st.checkbox("Grafik: Enflasyon Beklentileri", value=True)
            inc_box_chart = st.checkbox("Grafik: Dağılım (Box Plot)", value=False)
            inc_summary = st.checkbox("Tablo: Özet İstatistikler", value=True)
            inc_detail = st.checkbox("Tablo: Detaylı Veri", value=False)

            st.markdown("---")
            st.subheader("3. Veri Filtreleri")
            cat_f = st.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Kurumsal"])
            src_f = st.multiselect("Kaynak", sorted(df['anket_kaynagi'].unique()), default=sorted(df['anket_kaynagi'].unique()))
            all_periods_rep = sorted(df['donem'].unique(), reverse=True)
            per_f = st.multiselect("Dönem (Period)", all_periods_rep, default=all_periods_rep[:6] if len(all_periods_rep)>0 else [])

        df_rep = df[df['kategori'].isin(cat_f) & df['anket_kaynagi'].isin(src_f) & df['donem'].isin(per_f)]

        report_blocks = []
        with c_right:
            st.subheader("Önizleme")
            if df_rep.empty: st.warning("Seçilen filtrelerde veri yok.")
            else:
                if inc_ppk_chart:
                    fig1 = px.line(df_rep.sort_values("donem_date"), x="donem", y="tahmin_ppk_faiz", color="gorunen_isim", markers=True, title="PPK Faiz Beklentileri")
                    st.plotly_chart(fig1, use_container_width=True)
                    report_blocks.append({'type': 'chart', 'title': 'PPK Faiz Beklentileri', 'fig': fig1})
                
                if inc_enf_chart:
                    fig2 = px.line(df_rep.sort_values("donem_date"), x="donem", y="tahmin_yilsonu_enf", color="gorunen_isim", markers=True, title="Yıl Sonu Enflasyon Beklentileri")
                    st.plotly_chart(fig2, use_container_width=True)
                    report_blocks.append({'type': 'chart', 'title': 'Yıl Sonu Enflasyon Beklentileri', 'fig': fig2})
                
                if inc_box_chart:
                    fig3 = px.box(df_rep.sort_values("donem_date"), x="donem", y="tahmin_yilsonu_enf", color="donem", title="Enflasyon Dağılımı")
                    st.plotly_chart(fig3, use_container_width=True)
                    report_blocks.append({'type': 'chart', 'title': 'Enflasyon Beklenti Dağılımı', 'fig': fig3})

                if inc_summary:
                    agg_df = df_rep.groupby('donem').agg(Min_PPK=('tahmin_ppk_faiz', 'min'), Max_PPK=('tahmin_ppk_faiz', 'max'), Med_PPK=('tahmin_ppk_faiz', 'median'), Med_Enf=('tahmin_yilsonu_enf', 'median'), Katilimci=('kullanici_adi', 'count')).reset_index().sort_values('donem', ascending=False)
                    for c in ['Min_PPK', 'Max_PPK', 'Med_PPK', 'Med_Enf']: agg_df[c] = agg_df[c].apply(lambda x: f"{x:.2f}" if pd.notnull(x) else "-")
                    st.write("Özet Tablo:"); st.dataframe(agg_df, use_container_width=True)
                    report_blocks.append({'type': 'table', 'title': 'Dönemsel Özet İstatistikler', 'df': agg_df})

                if inc_detail:
                    detail_df = df_rep[['donem', 'gorunen_isim', 'tahmin_ppk_faiz', 'tahmin_yilsonu_enf']].sort_values(['donem', 'gorunen_isim'], ascending=[False, True])
                    detail_df.columns = ['Dönem', 'Kurum', 'PPK', 'Enflasyon (YS)']
                    st.write("Detaylı Veri:"); st.dataframe(detail_df, use_container_width=True)
                    report_blocks.append({'type': 'table', 'title': 'Katılımcı Bazlı Detaylar', 'df': detail_df})

        st.markdown("---")
        
        c_btn1, c_btn2, c_btn3 = st.columns(3)
        if c_btn1.button("📄 PDF İndir (Siyah/Beyaz/Güvenli)"):
            if not df_rep.empty and report_blocks:
                r_data = {'title': rep_title, 'unit': rep_unit, 'date': rep_date.strftime('%d.%m.%Y'), 'body': rep_body, 'content_blocks': report_blocks}
                with st.spinner("PDF hazırlanıyor..."): pdf_bytes = create_custom_pdf_report(r_data)
                st.download_button(label="⬇️ İndir", data=pdf_bytes, file_name="Rapor.pdf", mime="application/pdf")
            else: st.error("İçerik yok.")
            
        if c_btn2.button("📝 Word İndir (Renkli & Logolu)"):
            if not df_rep.empty and report_blocks:
                r_data = {'title': rep_title, 'unit': rep_unit, 'date': rep_date.strftime('%d.%m.%Y'), 'body': rep_body, 'content_blocks': report_blocks}
                with st.spinner("Word dosyası hazırlanıyor..."): word_bytes = create_word_report(r_data)
                st.download_button(label="⬇️ İndir", data=word_bytes, file_name="Rapor.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            else: st.error("İçerik yok.")
            
        if c_btn3.button("📊 Excel Dashboard İndir (Editlenebilir Grafik)"):
            if not df_rep.empty:
                with st.spinner("Excel grafikleri oluşturuluyor..."):
                    excel_bytes = create_excel_dashboard(df_rep)
                st.download_button(label="⬇️ İndir", data=excel_bytes, file_name="Dashboard.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else: st.error("İçerik yok.")

    else: st.info("Veri yok.")

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

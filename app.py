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

# --- 1. AYARLAR VE TASARIM (EN BAŞTA OLMALI) ---
st.set_page_config(page_title="Finansal Tahmin Terminali", layout="wide", page_icon="📊", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .stMetric { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); } 
    .stButton button { width: 100%; border-radius: 8px; font-weight: 600; } 
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; background-color: white; } 
    h1, h2, h3 { color: #2c3e50; } 
    div[data-testid="stDataFrame"] { width: 100%; }
</style>
""", unsafe_allow_html=True)

# --- KÜTÜPHANE KONTROLÜ ---
try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    st.error("Lütfen gerekli kütüphaneleri yükleyin: pip install python-docx xlsxwriter requests fpdf plotly pandas supabase")
    st.stop()

# --- BAĞLANTI ---
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Lütfen secrets ayarlarını kontrol edin: {e}")
    st.stop()

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
EVDS_TUFE_SERIES = "TP.FG.J0"  # TÜFE Serisi

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
    numeric_cols = ["tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "tahmin_yilsonu_faiz", 
                    "min_yilsonu_faiz", "max_yilsonu_faiz", "tahmin_aylik_enf", "min_aylik_enf", 
                    "max_aylik_enf", "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf", 
                    "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "katilimci_sayisi"]
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
    """
    Veri girişindeki 'ezme' (overwrite) sorununu çözen akıllı güncelleme fonksiyonu.
    """
    date_str = forecast_date.strftime("%Y-%m-%d")
    
    # 1. Mevcut kaydı kontrol et
    check_res = supabase.table(TABLE_TAHMIN).select("*").eq("kullanici_adi", user).eq("donem", period).execute()
    
    existing_data = {}
    record_id = None
    
    if check_res.data:
        existing_data = check_res.data[0]
        record_id = existing_data['id']
        # Supabase'den gelen sistem alanlarını temizle
        for k in ['id', 'created_at', 'kullanici_adi', 'donem']: 
            if k in existing_data: del existing_data[k]

    # 2. Yeni gelen verideki 0 veya boş değerleri temizle
    new_input_data = {k: v for k, v in data_dict.items() if v is not None and v != 0 and v != ""}
    
    # 3. Eski veri ile yeniyi birleştir (Yeni veri baskındır)
    final_data = existing_data.copy()
    final_data.update(new_input_data)
    
    final_data.update({
        "kullanici_adi": user, 
        "donem": period, 
        "kategori": category, 
        "tahmin_tarihi": date_str
    })
    
    if link:
        final_data["kaynak_link"] = link

    # 4. Kayıt veya Güncelleme
    if record_id:
        supabase.table(TABLE_TAHMIN).update(final_data).eq("id", record_id).execute()
        return "updated"
    else:
        supabase.table(TABLE_TAHMIN).insert(final_data).execute()
        return "inserted"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer: df.to_excel(writer, index=False, sheet_name='Tahminler')
    return output.getvalue()

# =========================================================
# YENİ VERİ ÇEKME MOTORU (EVDS FORMULAS DÜZELTİLDİ)
# =========================================================

def _evds_headers(api_key: str) -> dict:
    return {"key": api_key, "User-Agent": "Mozilla/5.0"}

def _evds_url_single(series_code: str, start_date: datetime.date, end_date: datetime.date, formulas: int | None) -> str:
    s = start_date.strftime("%d-%m-%Y")
    e = end_date.strftime("%d-%m-%Y")
    url = f"{EVDS_BASE}/series={series_code}&startDate={s}&endDate={e}&type=json"
    if formulas is not None:
        url += f"&formulas={int(formulas)}"
    return url

@st.cache_data(ttl=600)
def fetch_evds_tufe_monthly_yearly(api_key: str, start_date: datetime.date, end_date: datetime.date) -> tuple[pd.DataFrame, str | None]:
    if not api_key:
        return pd.DataFrame(), "EVDS_KEY eksik."
    try:
        results = {}
        # formulas=1 (Aylık), formulas=3 (Yıllık Değişim - DÜZELTİLDİ)
        for formulas, out_col in [(1, "TUFE_Aylik"), (3, "TUFE_Yillik")]:
            url = _evds_url_single(EVDS_TUFE_SERIES, start_date, end_date, formulas=formulas)
            r = requests.get(url, headers=_evds_headers(api_key), timeout=25)
            if r.status_code != 200: continue
            
            js = r.json()
            items = js.get("items", [])
            if not items: continue
            
            df = pd.DataFrame(items)
            if "Tarih" not in df.columns: continue
            
            # Tarih düzeltme
            df["Tarih_dt"] = pd.to_datetime(df["Tarih"], dayfirst=True, errors="coerce")
            if df["Tarih_dt"].isnull().all():
                 df["Tarih_dt"] = pd.to_datetime(df["Tarih"], format="%Y-%m", errors="coerce")
            
            df = df.dropna(subset=["Tarih_dt"]).sort_values("Tarih_dt")
            df["Donem"] = df["Tarih_dt"].dt.strftime("%Y-%m")
            
            val_cols = [c for c in df.columns if c not in ["Tarih", "UNIXTIME", "Tarih_dt", "Donem"]]
            if not val_cols: continue
            
            part = pd.DataFrame({
                "Tarih": df["Tarih_dt"].dt.strftime("%d-%m-%Y"),
                "Donem": df["Donem"],
                out_col: pd.to_numeric(df[val_cols[0]], errors="coerce"),
            })
            results[out_col] = part

        df_m = results.get("TUFE_Aylik", pd.DataFrame())
        df_y = results.get("TUFE_Yillik", pd.DataFrame())
        
        if df_m.empty and df_y.empty: return pd.DataFrame(), "Veri bulunamadı."
        if df_m.empty: out = df_y
        elif df_y.empty: out = df_m
        else: out = pd.merge(df_m, df_y, on=["Tarih", "Donem"], how="outer")
        
        return out.sort_values(["Donem", "Tarih"]), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=600)
def fetch_bis_cbpol_tr(start_date: datetime.date, end_date: datetime.date) -> tuple[pd.DataFrame, str | None]:
    try:
        s = start_date.strftime("%Y-%m-%d")
        e = end_date.strftime("%Y-%m-%d")
        url = f"https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={s}&endPeriod={e}"
        r = requests.get(url, timeout=25)
        if r.status_code >= 400: return pd.DataFrame(), f"BIS HTTP {r.status_code}"
        
        content = r.content.decode("utf-8", errors="ignore")
        if not content.strip(): return pd.DataFrame(), "Boş veri"
        
        df = pd.read_csv(io.StringIO(content))
        df.columns = [c.strip().upper() for c in df.columns]
        if "TIME_PERIOD" not in df.columns: return pd.DataFrame(), "Kolon hatası"
        
        out = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        out["TIME_PERIOD"] = pd.to_datetime(out["TIME_PERIOD"], errors="coerce")
        out = out.dropna(subset=["TIME_PERIOD"])
        out["Donem"] = out["TIME_PERIOD"].dt.strftime("%Y-%m")
        out["Tarih"] = out["TIME_PERIOD"].dt.strftime("%d-%m-%Y")
        out["REPO_RATE"] = pd.to_numeric(out["OBS_VALUE"], errors="coerce")
        return out[["Tarih", "Donem", "REPO_RATE"]].sort_values(["Donem", "Tarih"]), None
    except Exception as e:
        return pd.DataFrame(), str(e)

# --- VERİ ADAPTÖRÜ ---
def fetch_market_data_adapter(api_key, start_date, end_date):
    # 1. Enflasyon (EVDS)
    df_inf, err1 = fetch_evds_tufe_monthly_yearly(api_key, start_date, end_date)
    # 2. Faiz (BIS)
    df_pol, err2 = fetch_bis_cbpol_tr(start_date, end_date)

    if df_inf.empty and df_pol.empty:
        return pd.DataFrame(), f"Veri Yok: {err1} | {err2}"

    combined = pd.DataFrame()
    
    if not df_inf.empty and not df_pol.empty:
        df_pol_monthly = df_pol.groupby("Donem").last().reset_index()[['Donem', 'REPO_RATE']]
        combined = pd.merge(df_inf, df_pol_monthly, on="Donem", how="outer")
    elif not df_inf.empty:
        combined = df_inf
        combined['REPO_RATE'] = None
    elif not df_pol.empty:
        combined = df_pol.rename(columns={'REPO_RATE': 'REPO_RATE'}) 
        combined['TUFE_Aylik'] = None
        combined['TUFE_Yillik'] = None

    mapper = {
        'REPO_RATE': 'PPK Faizi',
        'TUFE_Aylik': 'Aylık TÜFE',
        'TUFE_Yillik': 'Yıllık TÜFE'
    }
    combined = combined.rename(columns=mapper)
    
    if 'Tarih' not in combined.columns and 'Donem' in combined.columns:
        combined['Tarih'] = combined['Donem'] + "-01"
    
    return combined, None

# --- EXCEL DASHBOARD & ISI HARİTASI MOTORU ---
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
            if pd.isna(val):
                ws_raw.write_string(r+1, c, "")
                continue
            if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
                ws_raw.write_datetime(r+1, c, val, date_fmt)
            else:
                ws_raw.write(r+1, c, val)

    def create_sheet_with_chart(metric_col, sheet_name, chart_title):
        df_sorted = df_source.sort_values("donem_date")
        try:
            pivot = df_sorted.pivot(index='donem', columns='gorunen_isim', values=metric_col)
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
        num_rows = len(pivot)
        num_cols = len(pivot.columns)
        
        for i in range(num_cols):
            chart.add_series({
                'name':       [sheet_name, 0, i + 1],
                'categories': [sheet_name, 1, 0, num_rows, 0],
                'values':     [sheet_name, 1, i + 1, num_rows, i + 1],
                'marker':     {'type': 'circle', 'size': 5},
                'line':       {'width': 2.25}
            })
            
        chart.set_title({'name': chart_title})
        chart.set_x_axis({'name': 'Dönem'})
        chart.set_y_axis({'name': 'Oran (%)', 'major_gridlines': {'visible': True}})
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
            col_data = pivot[col_name]
            for r_idx, val in enumerate(col_data):
                if pd.isna(val): ws.write_string(r_idx+1, i+1, "")
                else: ws.write_number(r_idx+1, i+1, val, num_fmt)
        
        last_row = len(pivot)
        last_col = len(pivot.columns)
        
        ws.conditional_format(1, 1, last_row, last_col, {
            'type': '3_color_scale',
            'min_color': '#63BE7B', 'mid_color': '#FFEB84', 'max_color': '#F8696B'
        })
        ws.set_column(0, 0, 25)
        ws.set_column(1, last_col, 10)

    create_sheet_with_chart('tahmin_ppk_faiz', '📈 PPK Grafiği', 'PPK Faiz Beklentileri')
    create_sheet_with_chart('tahmin_yilsonu_enf', '📈 Enflasyon Grafiği', 'Yıl Sonu Enflasyon Beklentileri')
    create_heatmap_sheet('tahmin_ppk_faiz', '🔥 Isı Haritası - PPK')
    create_heatmap_sheet('tahmin_yilsonu_enf', '🔥 Isı Haritası - Enf')

    workbook.close()
    return output.getvalue()

# --- WORD RAPOR OLUŞTURUCU ---
def create_word_report(report_data):
    doc = Document()
    logo_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/5/58/TCMB_logo.svg/500px-TCMB_logo.svg.png"
    try:
        r = requests.get(logo_url, timeout=5)
        if r.status_code == 200:
            with io.BytesIO(r.content) as image_stream:
                logo_par = doc.add_paragraph()
                logo_par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                run = logo_par.add_run()
                run.add_picture(image_stream, width=Inches(1.2))
    except: pass

    title = doc.add_heading(report_data['title'], 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_info = doc.add_paragraph()
    p_info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_unit = p_info.add_run(report_data['unit'] + "\n")
    run_unit.bold = True
    run_unit.font.size = Pt(12)
    run_date = p_info.add_run(report_data['date'])
    run_date.italic = True
    doc.add_paragraph("") 

    if report_data['body']:
        p_body = doc.add_paragraph(report_data['body'])
        p_body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for block in report_data['content_blocks']:
        doc.add_paragraph("")
        if block.get('title'):
            h = doc.add_heading(block['title'], level=2)
            h.runs[0].font.color.rgb = RGBColor(180, 0, 0)

        if block['type'] == 'chart':
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
                try:
                    block['fig'].write_image(tmpfile.name, width=1000, height=500, scale=2)
                    doc.add_picture(tmpfile.name, width=Inches(6.5))
                except: pass
            try: os.remove(tmpfile.name)
            except: pass

        elif block['type'] == 'table':
            df_table = block['df']
            table = doc.add_table(rows=1, cols=len(df_table.columns))
            table.style = 'Light Shading Accent 1'
            hdr_cells = table.rows[0].cells
            for i, col_name in enumerate(df_table.columns):
                hdr_cells[i].text = str(col_name)
            for _, row in df_table.iterrows():
                row_cells = table.add_row().cells
                for i, item in enumerate(row):
                    row_cells[i].text = str(item)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()

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
    fr, fb = check_and_download_font()
    use_cust = (fr is not None)
    font = "DejaVu" if use_cust else "Helvetica"
    fallback = not use_cust

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
        def footer(self):
            self.set_y(-15); self.set_font(font, '', 8); self.set_text_color(128); self.cell(0, 10, f'Sayfa {self.page_no()}', align='C')

    pdf = RPT()
    if use_cust:
        pdf.add_font("DejaVu", "", fr, uni=True)
        pdf.add_font("DejaVu", "B", fb, uni=True)
    pdf.add_page(); pdf.set_text_color(0)

    pdf.set_font(font, 'B', 20); pdf.cell(0, 10, safe_str(report_data['title'], fallback), ln=True)
    pdf.set_font(font, '', 12); pdf.set_text_color(80); pdf.cell(0, 8, safe_str(report_data['unit'], fallback), ln=True)
    pdf.set_text_color(0); pdf.set_font(font, '', 10); pdf.cell(0, 8, safe_str(report_data['date'], fallback), ln=True, align='R'); pdf.ln(5)
    
    if report_data['body']:
        pdf.set_font(font, '', 11); pdf.multi_cell(0, 6, safe_str(report_data['body'], fallback)); pdf.ln(10)

    for block in report_data['content_blocks']:
        if pdf.get_y() > 240: pdf.add_page()
        if block.get('title'):
            pdf.set_font(font, 'B', 12); pdf.set_text_color(200, 0, 0); pdf.cell(0, 10, safe_str(block['title'], fallback), ln=True); pdf.set_text_color(0); pdf.ln(2)
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

# --- GİRİŞ (DÜZELTİLMİŞ) ---
if 'giris_yapildi' not in st.session_state: st.session_state['giris_yapildi'] = False

if not st.session_state['giris_yapildi']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("### 🔐 Giriş Paneli")
        # st.form kullanarak enter tuşunun çalışmasını ve state sorununu çözüyoruz.
        with st.form("login_form"):
            sifre_girdisi = st.text_input("Şifre", type="password")
            giris_butonu = st.form_submit_button("Giriş Yap", type="primary")
            
            if giris_butonu:
                if sifre_girdisi == SITE_SIFRESI:
                    st.session_state['giris_yapildi'] = True
                    st.rerun()
                else:
                    st.error("Hatalı Şifre!")
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
                                c1, c2, c3 = st.columns(3)
                                na = c1.number_input("Ay Enf", value=g('tahmin_aylik_enf'), step=0.1)
                                nyillik = c2.number_input("Yıllık Enf", value=g('tahmin_yillik_enf'), step=0.1)
                                nye = c3.number_input("YS Enf", value=g('tahmin_yilsonu_enf'), step=0.1)
                            
                            if st.form_submit_button("Kaydet"):
                                def cv(v): return v if v!=0 else None
                                upd = {"tahmin_tarihi": nd.strftime('%Y-%m-%d'), "donem": ndo, "kaynak_link": nl if nl else None, "katilimci_sayisi": int(nk), "tahmin_ppk_faiz": cv(npk), "tahmin_yilsonu_faiz": cv(nyf), "tahmin_aylik_enf": cv(na), "tahmin_yillik_enf": cv(nyillik), "tahmin_yilsonu_enf": cv(nye)}
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
        
        # Dashboard için veri çekme
        dash_evds_start = datetime.date(2023, 1, 1)
        dash_evds_end = datetime.date(2025, 12, 31)
        
        realized_df, err = fetch_market_data_adapter(EVDS_API_KEY, dash_evds_start, dash_evds_end)
        
        realized_dict = {}
        if not realized_df.empty:
            for _, row in realized_df.iterrows():
                realized_dict[row['Donem']] = {
                    'ppk': row.get('PPK Faizi'),
                    'enf_ay': row.get('Aylık TÜFE'),
                    'enf_yil': row.get('Yıllık TÜFE')
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
        c3.metric("Son Güncelleme", df_latest['tahmin_tarihi'].max().strftime('%d.%m.%Y'))
        st.markdown("---")

        # --- EN İSABETLİ TAHMİNCİLER (MVP) KARTLARI ---
        st.markdown("### 🏆 Dönemin En İsabetli Tahmincileri")
        if realized_dict:
            sorted_realized_periods = sorted(realized_dict.keys(), reverse=True)
            latest_realized_period = None
            latest_metrics = {}
            for p in sorted_realized_periods:
                vals = realized_dict[p]
                if vals.get('ppk') is not None or vals.get('enf_yil') is not None:
                    latest_realized_period = p
                    latest_metrics = vals
                    break
            
            if latest_realized_period:
                df_mvp = df_latest[df_latest['donem'] == latest_realized_period].copy()
                if not df_mvp.empty:
                    c_mvp1, c_mvp2 = st.columns(2)
                    # 1. PPK
                    if latest_metrics.get('ppk') is not None:
                        actual_ppk = latest_metrics['ppk']
                        df_mvp['err_ppk'] = (df_mvp['tahmin_ppk_faiz'] - actual_ppk).abs()
                        best_ppk = df_mvp.sort_values('err_ppk').head(1)
                        if not best_ppk.empty:
                            winner = best_ppk.iloc[0]
                            c_mvp1.info(f"🎯 **PPK ({latest_realized_period})**\n\n"
                                        f"**Gerçekleşen:** %{actual_ppk}\n\n"
                                        f"**En Yakın:** {winner['gorunen_isim']}\n\n"
                                        f"**Tahmin:** %{winner['tahmin_ppk_faiz']} (Sapma: {winner['err_ppk']:.2f})")
                    else: c_mvp1.warning(f"{latest_realized_period} için PPK yok.")
                    # 2. ENFLASYON (YILLIK)
                    if latest_metrics.get('enf_yil') is not None:
                        actual_enf = latest_metrics['enf_yil']
                        # Öncelikle Yıllık Enflasyon kolonuna bak, yoksa Yıl Sonu kolonuna bak
                        if 'tahmin_yillik_enf' in df_mvp.columns:
                            col_to_use = 'tahmin_yillik_enf'
                        else:
                            col_to_use = 'tahmin_yilsonu_enf'
                        
                        # Boş olmayanları al
                        df_mvp_e = df_mvp.dropna(subset=[col_to_use]).copy()
                        df_mvp_e['err_enf'] = (df_mvp_e[col_to_use] - actual_enf).abs()
                        best_enf = df_mvp_e.sort_values('err_enf').head(1)
                        
                        if not best_enf.empty:
                            winner = best_enf.iloc[0]
                            c_mvp2.success(f"🏷️ **Yıllık Enflasyon ({latest_realized_period})**\n\n"
                                           f"**Gerçekleşen:** %{actual_enf}\n\n"
                                           f"**En Yakın:** {winner['gorunen_isim']}\n\n"
                                           f"**Tahmin:** %{winner[col_to_use]:.2f} (Sapma: {winner['err_enf']:.2f})")
                    else: c_mvp2.warning(f"{latest_realized_period} için Enf yok.")
                else: st.info("Bu dönem için tahmin bulunamadı.")
            else: st.info("Karşılaştırılacak veri bulunamadı.")
        st.markdown("---")

        with st.sidebar:
            st.markdown("### 🔍 Dashboard Filtreleri")
            x_axis_mode = st.radio("Grafik Görünümü (X Ekseni)", ["📅 Hedef Dönem (Vade)", "⏳ Tahmin Tarihi (Revizyon)"])
            st.markdown("---")
            calc_method = st.radio("Medyan Hesaplama", ["Otomatik", "Manuel"])
            manual_median_val = 0.0 if calc_method == "Otomatik" else st.number_input("Manuel Değer", step=0.

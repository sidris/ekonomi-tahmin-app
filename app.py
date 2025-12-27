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

def normalize_name(name): 
    return name.strip().title() if name else ""

def safe_int(val):
    try: 
        return int(float(val)) if pd.notnull(val) else 0
    except: 
        return 0

def clean_and_sort_data(df):
    if df.empty: 
        return df
    numeric_cols = ["tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz", "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf", "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "katilimci_sayisi"]
    for col in numeric_cols:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if "donem" in df.columns:
        df["donem_date"] = pd.to_datetime(df["donem"], format="%Y-%m", errors='coerce')
        df = df.sort_values(by="donem_date")
    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"])
    return df

def parse_range_input(text_input, default_median=0.0):
    if not text_input or text_input.strip() == "": 
        return default_median, 0.0, 0.0, False
    try:
        text = text_input.replace(',', '.')
        parts = []
        if '-' in text: 
            parts = text.split('-')
        elif '/' in text: 
            parts = text.split('/')
        if len(parts) == 2:
            v1, v2 = float(parts[0].strip()), float(parts[1].strip())
            return (v1+v2)/2, min(v1, v2), max(v1, v2), True
    except: 
        pass
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
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer: 
        df.to_excel(writer, index=False, sheet_name='Tahminler')
    return output.getvalue()

# --- EVDS VERİ ÇEKME FONKSİYONU (DÜZELTİLMİŞ) ---
@st.cache_data(ttl=300)
def fetch_evds_data(api_key, start_date_obj, end_date_obj):
    """
    EVDS'den veri çeker. Seriler ayrı ayrı çekilir ve birleştirilir.
    """
    if not api_key:
        return pd.DataFrame(), "API Anahtarı Eksik (secrets.toml)"
    
    if not evds:
        return pd.DataFrame(), "evds kütüphanesi yüklü değil"

    try:
        ev = evds.evdsAPI(api_key)
        s_str = start_date_obj.strftime("%d-%m-%Y")
        e_str = end_date_obj.strftime("%d-%m-%Y")
        
        # Seriler ayrı ayrı çekiliyor
        data_ppk = None
        data_enf = None
        
        try:
            data_ppk = ev.get_data(['TP.PT.POL'], startdate=s_str, enddate=e_str)
        except Exception as e:
            st.warning(f"PPK verisi çekilemedi: {e}")
            
        try:
            data_enf = ev.get_data(['TP.TUFE1YI.AY.O', 'TP.TUFE1YI.YI.O'], startdate=s_str, enddate=e_str)
        except Exception as e:
            st.warning(f"Enflasyon verisi çekilemedi: {e}")
        
        if data_ppk is None and data_enf is None:
            return pd.DataFrame(), "Hiçbir seri çekilemedi"
        
        # Tarih bazlı birleştirme
        data_dict = {}
        
        if data_ppk is not None and not data_ppk.empty:
            for _, row in data_ppk.iterrows():
                tarih = row.get('Tarih')
                if pd.notna(tarih):
                    if tarih not in data_dict:
                        data_dict[tarih] = {}
                    data_dict[tarih]['PPK'] = float(row['TP_PT_POL']) if pd.notnull(row.get('TP_PT_POL')) else None
        
        if data_enf is not None and not data_enf.empty:
            for _, row in data_enf.iterrows():
                tarih = row.get('Tarih')
                if pd.notna(tarih):
                    if tarih not in data_dict:
                        data_dict[tarih] = {}
                    data_dict[tarih]['AylikTUFE'] = float(row['TP_TUFE1YI_AY_O']) if pd.notnull(row.get('TP_TUFE1YI_AY_O')) else None
                    data_dict[tarih]['YillikTUFE'] = float(row['TP_TUFE1YI_YI_O']) if pd.notnull(row.get('TP_TUFE1YI_YI_O')) else None

        # DataFrame oluştur
        clean_rows = []
        for tarih, values in sorted(data_dict.items()):
            try:
                dt = pd.to_datetime(tarih)
                donem_fmt = dt.strftime('%Y-%m')
            except:
                continue

            clean_rows.append({
                'Tarih': tarih,
                'Donem': donem_fmt,
                'PPK Faizi': values.get('PPK'),
                'Aylık TÜFE': values.get('AylikTUFE'),
                'Yıllık TÜFE': values.get('YillikTUFE')
            })
            
        if not clean_rows:
            return pd.DataFrame(), "Veri işlenemedi"
            
        return pd.DataFrame(clean_rows), None

    except Exception as e:
        return pd.DataFrame(), f"EVDS Bağlantı Hatası: {str(e)}"

# --- EXCEL DASHBOARD & ISI HARİTASI ---
def create_excel_dashboard(df_source):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    
    bold = workbook.add_format({'bold': 1})
    date_fmt = workbook.add_format({'num_format': 'dd/mm/yyyy'})
    num_fmt = workbook.add_format({'num_format': '0.00'})
    
    # Ham Veri
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
        except: 
            return
            
        ws = workbook.add_worksheet(sheet_name)
        ws.write('A1', 'Dönem', bold)
        ws.write_row('B1', pivot.columns, bold)
        ws.write_column('A2', pivot.index)
        
        for i, col_name in enumerate(pivot.columns):
            col_data = pivot[col_name]
            for r_idx, val in enumerate(col_data):
                if pd.isna(val): 
                    ws.write_string(r_idx+1, i+1, "")
                else: 
                    ws.write_number(r_idx+1, i+1, val, num_fmt)
            
        chart = workbook.add_chart({'type': 'line'})
        num_rows = len(pivot)
        num_cols = len(pivot.columns)
        
        for i in range(num_cols):
            chart.add_series({
                'name': [sheet_name, 0, i + 1],
                'categories': [sheet_name, 1, 0, num_rows, 0],
                'values': [sheet_name, 1, i + 1, num_rows, i + 1],
                'marker': {'type': 'circle', 'size': 5},
                'line': {'width': 2.25}
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
        except: 
            return

        ws = workbook.add_worksheet(sheet_name)
        ws.write('A1', 'Katılımcı / Dönem', bold)
        ws.write_row('B1', pivot.columns, bold)
        ws.write_column('A2', pivot.index, bold)
        
        for i, col_name in enumerate(pivot.columns):
            col_data = pivot[col_name]
            for r_idx, val in enumerate(col_data):
                if pd.isna(val): 
                    ws.write_string(r_idx+1, i+1, "")
                else: 
                    ws.write_number(r_idx+1, i+1, val, num_fmt)
        
        last_row = len(pivot)
        last_col = len(pivot.columns)
        
        ws.conditional_format(1, 1, last_row, last_col, {
            'type': '3_color_scale',
            'min_color': '#63BE7B', 
            'mid_color': '#FFEB84', 
            'max_color': '#F8696B'
        })
        ws.set_column(0, 0, 25)
        ws.set_column(1, last_col, 10)

    create_sheet_with_chart('tahmin_ppk_faiz', '📈 PPK Grafiği', 'PPK Faiz Beklentileri')
    create_sheet_with_chart('tahmin_yilsonu_enf', '📈 Enflasyon Grafiği', 'Yıl Sonu Enflasyon Beklentileri')
    create_heatmap_sheet('tahmin_ppk_faiz', '🔥 Isı Haritası - PPK')
    create_heatmap_sheet('tahmin_yilsonu_enf', '🔥 Isı Haritası - Enf')

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
                logo_par = doc.add_paragraph()
                logo_par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                run = logo_par.add_run()
                run.add_picture(image_stream, width=Inches(1.2))
    except: 
        pass

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
                except: 
                    pass
            try: 
                os.remove(tmpfile.name)
            except: 
                pass

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
    paths = {
        "DejaVuSans.ttf": "https://github.com/google/fonts/raw/main/ofl/dejavusans/DejaVuSans-Regular.ttf", 
        "DejaVuSans-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/dejavusans/DejaVuSans-Bold.ttf"
    }
    try:
        for p, u in paths.items():
            if not os.path.exists(p) or os.path.getsize(p) < 1000:
                r = requests.get(u, timeout=10)
                if r.status_code == 200:
                    with open(p, 'wb') as f: 
                        f.write(r.content)
        if os.path.exists("DejaVuSans.ttf"): 
            return "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    except: 
        pass
    return None, None

def safe_str(text, fallback):
    if not isinstance(text, str): 
        return str(text)
    if fallback:
        tr = {'ğ':'g','Ğ':'G','ş':'s','Ş':'S','ı':'i','İ':'I','ö':'o','Ö':'O','ü':'u','Ü':'U','ç':'c','Ç':'C'}
        for k,v in tr.items(): 
            text = text.replace(k,v)
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
                        with open("logo_tmp.png",'wb') as f: 
                            f.write(r.content)
                except: 
                    pass
            if os.path.exists("logo_tmp.png"): 
                self.image("logo_tmp.png", x=170, y=10, w=30)
            self.ln(25)
            
        def footer(self):
            self.set_y(-15)
            self.set_font(font, '', 8)
            self.set_text_color(128)
            self.cell(0, 10, f'Sayfa {self.page_no()}', align='C')

    pdf = RPT()
    if use_cust:
        pdf.add_font("DejaVu", "", fr, uni=True)
        pdf.add_font("DejaVu", "B", fb, uni=True)
    pdf.add_page()
    pdf.set_text_color(0)

    pdf.set_font(font, 'B', 20)
    pdf.cell(0, 10, safe_str(report_data['title'], fallback), ln=True)
    pdf.set_font(font, '', 12)
    pdf.set_text_color(80)
    pdf.cell(0, 8, safe_str(report_data['unit'], fallback), ln=True)
    pdf.set_text_color(0)
    pdf.set_font(font, '', 10)
    pdf.cell(0, 8, safe_str(report_data['date'], fallback), ln=True, align='R')
    pdf.ln(5)
    
    if report_data['body']:
        pdf.set_font(font, '', 11)
        pdf.multi_cell(0, 6, safe_str(report_data['body'], fallback))
        pdf.ln(10)

    for block in report_data['content_blocks']:
        if pdf.get_y() > 240: 
            pdf.add_page()
        if block.get('title'):
            pdf.set_font(font, 'B', 12)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 10, safe_str(block['title'], fallback), ln=True)
            pdf.set_text_color(0)
            pdf.ln(2)
        if block['type'] == 'chart':
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
                try: 
                    block['fig'].write_image(t.name, width=1000, height=500, scale=2)
                    pdf.image(t.name, x=15, w=180)
                    pdf.ln(5)
                except: 
                    pass
            try: 
                os.remove(t.name)
            except: 
                pass
        elif block['type'] == 'table':
            df = block['df']
            pdf.set_font(font, '', 8)
            with pdf.table() as tbl:
                r = tbl.row()
                for c in df.columns: 
                    r.cell(safe_str(str(c), fallback), style=FontFace(emphasis="BOLD", color=255, fill_color=(200, 50, 50)))
                for _, dr in df.iterrows():
                    r = tbl.row()
                    for item in dr: 
                        r.cell(safe_str(str(item), fallback))
            pdf.ln(10)
    return bytes(pdf.output())

# --- AUTH ---
if 'giris_yapildi' not in st.session_state: 
    st.session_state['giris_yapildi'] = False
    
if not st.session_state['giris_yapildi']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("### 🔐 Giriş Paneli")
        pwd = st.text_input("Şifre", type="password")
        if st.button("Giriş Yap", type="primary"):
            if pwd == SITE_SIFRESI:
                st.session_state['giris_yapildi'] = True
                st.rerun()
            else:
                st.error("Hatalı şifre")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.title("📊 Menü")
    page = st.radio("Git:", [
        "Gelişmiş Veri Havuzu (Yönetim)", 
        "Dashboard", 
        "🔥 Isı Haritası", 
        "📈 Piyasa Verileri (EVDS)", 
        "📄 Rapor Oluştur", 
        "PPK Girişi", 
        "Enflasyon Girişi", 
        "Katılımcı Yönetimi"
    ])

def get_participant_selection():
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if df.empty: 
        st.error("Lütfen önce Katılımcı ekleyin.")
        return None, None, None
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
            if sel_cat != "Tümü": 
                df_f = df_f[df_f['kategori'] == sel_cat]
            if sel_period != "Tümü": 
                df_f = df_f[df_f['donem'] == sel_period]
            if sel_user != "Tümü": 
                df_f = df_f[df_f['kullanici_adi'] == sel_user]
            
            if not admin_mode:
                st.markdown("---")
                cols = ["tahmin_tarihi", "donem", "kullanici_adi", "kategori", "anket_kaynagi", "kaynak_link", "katilimci_sayisi", "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "tahmin_yilsonu_faiz", "tahmin_aylik_enf", "tahmin_yillik_enf", "tahmin_yilsonu_enf"]
                final_cols = [c for c in cols if c in df_f.columns]
                col_cfg = {
                    "kaynak_link": st.column_config.LinkColumn("Link", display_text="🔗"), 
                    "tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY"), 
                    **{c: st.column_config.NumberColumn(c, format="%.2f") for

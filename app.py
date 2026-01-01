import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import datetime
import time
import requests
import xlsxwriter
import smtplib
from email.mime.text import MIMEText
import random

# --- 1. AYARLAR VE TASARIM ---
st.set_page_config(page_title="Finansal Tahmin Terminali v4", layout="wide", page_icon="📊", initial_sidebar_state="expanded")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .stMetric { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); } 
    .stButton button { width: 100%; border-radius: 8px; font-weight: 600; } 
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; background-color: white; } 
    div[data-testid="stDataFrame"] { width: 100%; }
    .login-container {
        background-color: white; padding: 3rem; border-radius: 15px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.1); text-align: center; margin-top: 50px;
    }
    .login-header { color: #1E3A8A; font-family: 'Helvetica Neue', sans-serif; font-weight: 700; margin-bottom: 1.5rem; }
</style>
""", unsafe_allow_html=True)

# --- BAĞLANTI VE AYARLAR ---
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    SMTP_EMAIL = st.secrets.get("SMTP_EMAIL", None)
    SMTP_PASSWORD = st.secrets.get("SMTP_PASSWORD", None)
    
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Lütfen secrets ayarlarını kontrol edin: {e}")
    st.stop()

# TABLO ADLARI
TABLE_TAHMIN = "beklentiler_takip" 
TABLE_KATILIMCI = "katilimcilar"
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
EVDS_TUFE_SERIES = "TP.FG.J0" 

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

def clean_and_sort_data(df):
    if df.empty: return df
    numeric_cols = ["tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "tahmin_yilsonu_faiz", 
                    "min_yilsonu_faiz", "max_yilsonu_faiz", "tahmin_aylik_enf", "min_aylik_enf", 
                    "max_aylik_enf", "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf", 
                    "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "katilimci_sayisi"]
    for col in numeric_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"], errors='coerce')
    return df

def upsert_tahmin(user, hedef_donemi, category, forecast_date, link, data_dict):
    if isinstance(forecast_date, str):
        date_obj = pd.to_datetime(forecast_date)
        date_str = forecast_date
    else:
        date_obj = pd.to_datetime(forecast_date)
        date_str = forecast_date.strftime("%Y-%m-%d")
    
    anket_donemi = date_obj.strftime("%Y-%m")
    new_input_data = {k: v for k, v in data_dict.items() if v is not None and v != 0 and v != ""}
    
    final_data = {
        "kullanici_adi": user,
        "kategori": category,
        "anket_donemi": anket_donemi, 
        "hedef_donemi": hedef_donemi, 
        "tahmin_tarihi": date_str,
    }
    if link: final_data["kaynak_link"] = link
    final_data.update(new_input_data)

    try:
        supabase.table(TABLE_TAHMIN).upsert(final_data, on_conflict="kullanici_adi, anket_donemi, hedef_donemi").execute()
        return "upserted"
    except Exception as e:
        st.error(f"DB Hatası: {e}")
        return "error"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer: df.to_excel(writer, index=False, sheet_name='Veriler')
    return output.getvalue()

# --- EVDS VE BIS FONKSİYONLARI ---
def _evds_headers(api_key: str) -> dict: return {"key": api_key, "User-Agent": "Mozilla/5.0"}
def _evds_url_single(series_code, start_date, end_date, formulas):
    s = start_date.strftime("%d-%m-%Y"); e = end_date.strftime("%d-%m-%Y")
    url = f"{EVDS_BASE}/series={series_code}&startDate={s}&endDate={e}&type=json"
    if formulas is not None: url += f"&formulas={int(formulas)}"
    return url

@st.cache_data(ttl=600)
def fetch_evds_tufe_monthly_yearly(api_key, start_date, end_date):
    if not api_key: return pd.DataFrame(), "EVDS_KEY eksik."
    try:
        results = {}
        for formulas, out_col in [(1, "TUFE_Aylik"), (3, "TUFE_Yillik")]:
            url = _evds_url_single(EVDS_TUFE_SERIES, start_date, end_date, formulas=formulas)
            r = requests.get(url, headers=_evds_headers(api_key), timeout=25)
            if r.status_code != 200: continue
            js = r.json(); items = js.get("items", [])
            if not items: continue
            df = pd.DataFrame(items)
            if "Tarih" not in df.columns: continue
            df["Tarih_dt"] = pd.to_datetime(df["Tarih"], dayfirst=True, errors="coerce")
            if df["Tarih_dt"].isnull().all(): df["Tarih_dt"] = pd.to_datetime(df["Tarih"], format="%Y-%m", errors="coerce")
            df = df.dropna(subset=["Tarih_dt"]).sort_values("Tarih_dt")
            df["Donem"] = df["Tarih_dt"].dt.strftime("%Y-%m")
            val_cols = [c for c in df.columns if c not in ["Tarih", "UNIXTIME", "Tarih_dt", "Donem"]]
            if not val_cols: continue
            results[out_col] = pd.DataFrame({"Tarih": df["Tarih_dt"].dt.strftime("%d-%m-%Y"), "Donem": df["Donem"], out_col: pd.to_numeric(df[val_cols[0]], errors="coerce")})
        df_m = results.get("TUFE_Aylik", pd.DataFrame()); df_y = results.get("TUFE_Yillik", pd.DataFrame())
        if df_m.empty and df_y.empty: return pd.DataFrame(), "Veri bulunamadı."
        if df_m.empty: out = df_y
        elif df_y.empty: out = df_m
        else: out = pd.merge(df_m, df_y, on=["Tarih", "Donem"], how="outer")
        return out.sort_values(["Donem", "Tarih"]), None
    except Exception as e: return pd.DataFrame(), str(e)

@st.cache_data(ttl=600)
def fetch_bis_cbpol_tr(start_date, end_date):
    try:
        s = start_date.strftime("%Y-%m-%d"); e = end_date.strftime("%Y-%m-%d")
        url = f"https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={s}&endPeriod={e}"
        r = requests.get(url, timeout=25)
        if r.status_code >= 400: return pd.DataFrame(), f"BIS HTTP {r.status_code}"
        df = pd.read_csv(io.StringIO(r.content.decode("utf-8", errors="ignore")))
        df.columns = [c.strip().upper() for c in df.columns]
        out = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        out["TIME_PERIOD"] = pd.to_datetime(out["TIME_PERIOD"], errors="coerce"); out = out.dropna(subset=["TIME_PERIOD"])
        out["Donem"] = out["TIME_PERIOD"].dt.strftime("%Y-%m"); out["REPO_RATE"] = pd.to_numeric(out["OBS_VALUE"], errors="coerce")
        return out[["Donem", "REPO_RATE"]].sort_values(["Donem"]), None
    except Exception as e: return pd.DataFrame(), str(e)

def fetch_market_data_adapter(api_key, start_date, end_date):
    df_inf, err1 = fetch_evds_tufe_monthly_yearly(api_key, start_date, end_date)
    df_pol, err2 = fetch_bis_cbpol_tr(start_date, end_date)
    combined = pd.DataFrame()
    if not df_inf.empty and not df_pol.empty:
        df_pol_monthly = df_pol.groupby("Donem").last().reset_index()[['Donem', 'REPO_RATE']]
        combined = pd.merge(df_inf, df_pol_monthly, on="Donem", how="outer")
    elif not df_inf.empty: combined = df_inf; combined['REPO_RATE'] = None
    elif not df_pol.empty: combined = df_pol.rename(columns={'REPO_RATE': 'REPO_RATE'}); combined['TUFE_Aylik'] = None; combined['TUFE_Yillik'] = None
    combined = combined.rename(columns={'REPO_RATE': 'PPK Faizi', 'TUFE_Aylik': 'Aylık TÜFE', 'TUFE_Yillik': 'Yıllık TÜFE'})
    if 'Tarih' not in combined.columns and 'Donem' in combined.columns: combined['Tarih'] = combined['Donem'] + "-01"
    return combined, None

# --- LOGIN ---
if 'giris_yapildi' not in st.session_state: st.session_state['giris_yapildi'] = False
if not st.session_state['giris_yapildi']:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("""<div class="login-container"><h1 class="login-header">📊 Finansal Tahmin Terminali v4</h1><p style="color: #666; margin-bottom: 20px;">Lütfen erişim için şifrenizi giriniz.</p></div>""", unsafe_allow_html=True)
        with st.form("login_form"):
            pwd = st.text_input("Şifre", type="password")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("Giriş Yap", type="primary"):
                if pwd == SITE_SIFRESI: st.session_state['giris_yapildi'] = True; st.rerun()
                else: st.error("Hatalı Şifre!")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.title("📊 Menü")
    page = st.radio("Git:", ["Dashboard (Analiz)", "📄 Rapor Oluştur", "Gelişmiş Veri Havuzu", "🔥 Isı Haritası", "📥 Toplu Veri Yükleme (Excel)", "PPK Girişi", "Enflasyon Girişi", "Katılımcı Yönetimi"])

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
# SAYFA: DASHBOARD (Analiz)
# ========================================================
if page == "Dashboard (Analiz)":
    st.header("Piyasa Analiz Dashboardu")
    
    # 1. VERİLERİ ÇEK
    with st.spinner("Piyasa verileri ve tahminler harmanlanıyor..."):
        res_t = supabase.table(TABLE_TAHMIN).select("*").order("tahmin_tarihi", desc=True).limit(5000).execute()
        df_t = pd.DataFrame(res_t.data)
        
        # EVDS (Gerçekleşenler)
        dash_evds_start = datetime.date(2023, 1, 1); dash_evds_end = datetime.date(2026, 12, 31)
        realized_df, err = fetch_market_data_adapter(EVDS_API_KEY, dash_evds_start, dash_evds_end)
    
    # KATILIMCI BİLGİLERİNİ EŞLE
    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad, anket_kaynagi, kategori").execute()
    df_k = pd.DataFrame(res_k.data)
    
    if df_t.empty:
        st.warning("Henüz tahmin verisi girilmemiş.")
    else:
        df_t = clean_and_sort_data(df_t)
        
        # Katılımcı bilgilerini Left Join ile birleştir (Silinenler de görünsün)
        if not df_k.empty:
            df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
        else:
            df_history = df_t.copy()
            df_history["kategori"] = "Bireysel"
            df_history["anket_kaynagi"] = None

        df_history['gorunen_isim'] = df_history.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x.get('anket_kaynagi')) and x.get('anket_kaynagi') != '' else x['kullanici_adi'], axis=1)

        # --- FILTRELEME ALANI ---
        with st.sidebar:
            st.markdown("### 🔍 Dashboard Filtreleri")
            
            # 1. Katılımcı Filtresi (ÇOKLU SEÇİM)
            all_users = sorted(df_history['gorunen_isim'].unique())
            selected_users = st.multiselect("Karşılaştırılacak Katılımcılar", all_users, help="Seçim yapmazsanız GENEL MEDYAN gösterilir. Seçerseniz kişileri kıyaslar.")
            
            # 2. Tarih Filtresi
            unique_targets = sorted(df_history['hedef_donemi'].unique())
            min_target_year = unique_targets[0].split("-")[0] if unique_targets else "2024"
            selected_years = st.multiselect("Hangi Yılların Hedefleri?", sorted(list(set([x.split("-")[0] for x in unique_targets]))), default=[min_target_year, "2025"])
            
            # Veriyi Filtrele
            if selected_users:
                # Kullanıcı seçildiyse sadece onları al
                filtered_df = df_history[df_history['gorunen_isim'].isin(selected_users)]
            else:
                # Seçilmediyse herkesi al (Medyan hesabı için)
                filtered_df = df_history.copy()
                
            filtered_df = filtered_df[filtered_df['hedef_donemi'].apply(lambda x: x.split("-")[0] in selected_years)]

        # --- GRAFİK FONKSİYONU ---
        def plot_forecast_vs_realized(metric_label, forecast_col, realized_col, title):
            fig = go.Figure()

            # A) KULLANICI SEÇİLDİYSE: Her kullanıcı için ayrı çizgi
            if selected_users:
                # Hedef döneme göre her kullanıcının son tahminini al
                # (Aynı hedefe birden çok kez tahmin girmiş olabilir, sonuncuyu alalım)
                user_data = filtered_df.sort_values("tahmin_tarihi").drop_duplicates(subset=["gorunen_isim", "hedef_donemi"], keep="last")
                
                for user in selected_users:
                    ud = user_data[user_data['gorunen_isim'] == user].sort_values("hedef_donemi")
                    if not ud.empty:
                        fig.add_trace(go.Scatter(
                            x=ud['hedef_donemi'], y=ud[forecast_col],
                            mode='lines+markers', name=user
                        ))
            
            # B) KULLANICI SEÇİLMEDİYSE: Medyan Çizgisi
            else:
                forecast_agg = filtered_df.groupby("hedef_donemi")[forecast_col].median().reset_index()
                fig.add_trace(go.Scatter(
                    x=forecast_agg['hedef_donemi'], y=forecast_agg[forecast_col],
                    mode='lines+markers', name='Piyasa Medyanı',
                    line=dict(color='blue', width=4), marker=dict(size=8)
                ))

            # C) GERÇEKLEŞEN VERİ (Her durumda göster)
            if not realized_df.empty and realized_col in realized_df.columns:
                real_data = realized_df[['Donem', realized_col]].dropna().sort_values("Donem")
                # Grafik karmaşasını önlemek için sadece seçilen yıllara ait gerçekleşmeleri gösterelim
                real_data = real_data[real_data['Donem'].apply(lambda x: x.split("-")[0] in selected_years)]
                
                if not real_data.empty:
                    fig.add_trace(go.Scatter(
                        x=real_data['Donem'], y=real_data[realized_col],
                        mode='lines+markers', name='Gerçekleşen',
                        line=dict(color='red', width=3, dash='dot'), marker=dict(symbol='x', size=10, color='red')
                    ))

            fig.update_layout(title=title, hovermode="x unified", legend=dict(orientation="h", y=1.1))
            return fig

        # --- GRAFİKLERİ GÖSTER (2x2 GRID) ---
        g1, g2 = st.columns(2)
        with g1:
            st.plotly_chart(plot_forecast_vs_realized("PPK", "tahmin_ppk_faiz", "PPK Faizi", "PPK Beklentisi vs Gerçekleşen"), use_container_width=True)
        with g2:
            st.plotly_chart(plot_forecast_vs_realized("YS PPK", "tahmin_yilsonu_faiz", "PPK Faizi", "Yıl Sonu Faiz Beklentisi"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.plotly_chart(plot_forecast_vs_realized("Aylık Enf", "tahmin_aylik_enf", "Aylık TÜFE", "Aylık TÜFE Beklentisi"), use_container_width=True)
        with g4:
            st.plotly_chart(plot_forecast_vs_realized("Yıllık Enf", "tahmin_yillik_enf", "Yıllık TÜFE", "Yıllık TÜFE Beklentisi"), use_container_width=True)
            
        # --- EN İYİ TAHMİNCİLER (Performans Ligi) ---
        st.markdown("---")
        st.subheader("🏆 En İyi Tahminciler (Performans Ligi)")
        
        if realized_df.empty:
            st.info("Performans hesabı için EVDS verisi (Gerçekleşenler) gerekiyor.")
        else:
            # Mantık: Tahmin edilen 'hedef_donemi' ile gerçekleşen 'Donem' eşleşiyorsa farkı (error) hesapla.
            perf_cols = st.columns(3)
            
            def calculate_best(forecast_col, real_col, title, col_obj):
                # 1. Tahmin ve Gerçekleşeni Birleştir
                df_perf = pd.merge(df_history, realized_df[['Donem', real_col]], left_on="hedef_donemi", right_on="Donem", how="inner")
                if df_perf.empty:
                    col_obj.caption(f"{title}: Yeterli veri yok.")
                    return

                # 2. Farkı Hesapla (Absolute Error)
                df_perf['error'] = (df_perf[forecast_col] - df_perf[real_col]).abs()
                
                # 3. Kişi bazında ortalama hata
                leaderboard = df_perf.groupby('gorunen_isim')[['error', 'hedef_donemi']].agg({'error': 'mean', 'hedef_donemi': 'count'}).reset_index()
                # En az 1 tahmini olanları al, hataya göre sırala (az hata iyi)
                leaderboard = leaderboard.sort_values('error').head(5)
                
                col_obj.markdown(f"**{title}**")
                for i, row in leaderboard.iterrows():
                    col_obj.write(f"{i+1}. **{row['gorunen_isim']}** (Sapma: {row['error']:.2f})")

            calculate_best("tahmin_yilsonu_enf", "Yıllık TÜFE", "🎯 En İyi Yıllık Enf. Tahmini", perf_cols[0])
            calculate_best("tahmin_aylik_enf", "Aylık TÜFE", "🎯 En İyi Aylık Enf. Tahmini", perf_cols[1])
            calculate_best("tahmin_ppk_faiz", "PPK Faizi", "🎯 En İyi PPK Tahmini", perf_cols[2])

# ========================================================
# SAYFA: RAPOR OLUŞTUR (YENİLENEREK GERİ GELDİ)
# ========================================================
elif page == "📄 Rapor Oluştur":
    st.title("📄 Detaylı Rapor Oluştur")
    st.info("Belirli bir hedef tarih için beklentilerin zaman içindeki değişimini (History) inceleyin.")
    
    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    
    if not df_t.empty:
        df_t = clean_and_sort_data(df_t)
        
        # Hedef Dönem Seçimi
        targets = sorted(df_t['hedef_donemi'].unique())
        selected_target = st.selectbox("Hangi Hedef Dönemi Raporlamak İstersiniz?", targets, index=len(targets)-1)
        
        # Filtrele
        report_df = df_t[df_t['hedef_donemi'] == selected_target].copy()
        
        # Katılımcı bilgisini ekle (join)
        res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad, anket_kaynagi").execute()
        df_k = pd.DataFrame(res_k.data)
        if not df_k.empty:
            report_df = pd.merge(report_df, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
            report_df['gorunen_isim'] = report_df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x.get('anket_kaynagi')) else x['kullanici_adi'], axis=1)
        else:
            report_df['gorunen_isim'] = report_df['kullanici_adi']

        # Grafik: Zaman içindeki değişim
        st.subheader(f"{selected_target} Hedefi İçin Beklenti Değişimi")
        
        fig = px.line(report_df.sort_values("tahmin_tarihi"), 
                      x="tahmin_tarihi", y="tahmin_yilsonu_enf", 
                      color="gorunen_isim", markers=True,
                      title="Enflasyon Beklentilerinin Evrimi")
        st.plotly_chart(fig, use_container_width=True)
        
        st.write("Veri Tablosu:")
        st.dataframe(report_df[['tahmin_tarihi', 'gorunen_isim', 'tahmin_yilsonu_enf', 'tahmin_ppk_faiz']].sort_values("tahmin_tarihi", ascending=False), use_container_width=True)

# ========================================================
# SAYFA: GELİŞMİŞ VERİ HAVUZU (TOPLU SİLME MODU)
# ========================================================
elif page == "Gelişmiş Veri Havuzu":
    st.title("🗃️ Gelişmiş Veri Havuzu")
    
    # 1. Verileri Çek
    res_t = supabase.table(TABLE_TAHMIN).select("*").order("tahmin_tarihi", desc=True).limit(2000).execute()
    df_t = pd.DataFrame(res_t.data)
    
    if not df_t.empty:
        df_t = clean_and_sort_data(df_t)
        
        # 2. Silme Modu Anahtarı (Toggle)
        col_header, col_toggle = st.columns([3, 1])
        with col_header:
            st.markdown("### Tüm Kayıtlar")
        with col_toggle:
            silme_modu = st.toggle("🗑️ Kayıt Silme Modunu Aç", help="Listede seçim kutucuklarını aktif eder.")

        # --- SİLME MODU AÇIKSA ---
        if silme_modu:
            st.warning("⚠️ Aşağıdaki listeden silmek istediğiniz kayıtların yanındaki kutucuğu işaretleyin ve en alttaki butona basın.")
            df_t.insert(0, "Sec", False)
            column_order = ["Sec", "id", "kullanici_adi", "anket_donemi", "hedef_donemi", "tahmin_yilsonu_enf", "tahmin_ppk_faiz", "tahmin_tarihi"]
            remaining_cols = [c for c in df_t.columns if c not in column_order]
            final_cols = column_order + remaining_cols
            
            edited_df = st.data_editor(
                df_t[final_cols],
                column_config={
                    "Sec": st.column_config.CheckboxColumn("Sil?", default=False),
                    "tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY"),
                },
                disabled=[c for c in df_t.columns if c != "Sec"], 
                use_container_width=True, hide_index=True, key="editor_silme"
            )
            secilenler = edited_df[edited_df["Sec"] == True]
            if not secilenler.empty:
                st.markdown(f"--- \n🔴 **{len(secilenler)}** adet kayıt seçildi.")
                if st.button("🗑️ SEÇİLENLERİ KALICI OLARAK SİL", type="primary"):
                    ids_to_delete = secilenler["id"].tolist()
                    try:
                        supabase.table(TABLE_TAHMIN).delete().in_("id", ids_to_delete).execute()
                        st.success(f"{len(ids_to_delete)} kayıt başarıyla silindi!")
                        time.sleep(1.5); st.rerun()
                    except Exception as e: st.error(f"Hata: {e}")
            else: st.info("Silmek için listeden kayıt seçiniz.")

        # --- SİLME MODU KAPALIYSA ---
        else:
            display_cols = ["id", "kullanici_adi", "anket_donemi", "hedef_donemi", "tahmin_yilsonu_enf", "tahmin_ppk_faiz", "tahmin_tarihi"]
            st.dataframe(df_t[display_cols], use_container_width=True, column_config={"tahmin_tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY")})
            st.download_button("📥 Excel İndir", to_excel(df_t), "tum_veriler.xlsx", type="primary")

    else:
        st.warning("Veri havuzunda henüz hiç kayıt yok.")

# ========================================================
# SAYFA: ISI HARİTASI
# ========================================================
elif page == "🔥 Isı Haritası":
    st.header("🔥 Beklenti Isı Haritası")
    res_t = supabase.table(TABLE_TAHMIN).select("*").order("tahmin_tarihi", desc=True).execute()
    df_t = pd.DataFrame(res_t.data)
    
    if not df_t.empty:
        df_t['gorunen_isim'] = df_t['kullanici_adi'] 
        metric = st.selectbox("Metrik", ["tahmin_ppk_faiz", "tahmin_yilsonu_enf", "tahmin_aylik_enf"])
        df_latest = df_t.sort_values('anket_donemi').drop_duplicates(subset=['kullanici_adi', 'hedef_donemi'], keep='last')
        pivot = df_latest.pivot(index="gorunen_isim", columns="hedef_donemi", values=metric)
        pivot = pivot.reindex(columns=sorted(pivot.columns))
        st.dataframe(pivot.style.background_gradient(cmap="RdYlGn_r", axis=None).format("{:.2f}"), use_container_width=True, height=600)

# ========================================================
# SAYFA: TOPLU VERİ YÜKLEME (EXCEL)
# ========================================================
elif page == "📥 Toplu Veri Yükleme (Excel)":
    st.header("📥 Toplu Veri Yükleme")
    
    def generate_excel_template():
        cols = ["Katılımcı Adı", "Hedef Dönem (YYYY-AA)", "Tarih (YYYY-AA-GG)", "Kategori", "Link", 
            "PPK Medyan", "PPK Min", "PPK Max", 
            "Yıl Sonu Faiz Medyan", "Yıl Sonu Faiz Min", "Yıl Sonu Faiz Max",
            "Aylık Enf Medyan", "Aylık Enf Min", "Aylık Enf Max",
            "Yıllık Enf Medyan", "Yıllık Enf Min", "Yıllık Enf Max",
            "Yıl Sonu Enf Medyan", "Yıl Sonu Enf Min", "Yıl Sonu Enf Max",
            "N Sayısı", "Gelecek Hedef Dönem", "Gelecek Tahmin (Enf)", "Gelecek Tahmin (PPK)"]
        df_temp = pd.DataFrame(columns=cols)
        df_temp.loc[0] = ["Örnek Banka", "2025-12", "2025-01-15", "Kurumsal", "", 45.0, 42.0, 48.0, 40.0, 38.0, 42.0, 1.5, 1.2, 1.8, 30.0, 28.0, 32.0, 35.0, 33.0, 37.0, 15, "2026-12", 25.0, 35.0]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer: df_temp.to_excel(writer, index=False, sheet_name='Veri_Girisi')
        return output.getvalue()

    st.download_button("📥 Şablon İndir", generate_excel_template(), "Veri_Yukleme_Sablonu_v4.xlsx")
    uploaded_file = st.file_uploader("Excel Yükle", type=["xlsx"])
    
    if uploaded_file:
        df_upload = pd.read_excel(uploaded_file)
        if st.button("🚀 Verileri Veritabanına İşle"):
            existing_users_response = supabase.table(TABLE_KATILIMCI).select("ad_soyad").execute()
            existing_users_set = {r['ad_soyad'] for r in existing_users_response.data}
            
            progress_bar = st.progress(0); success_count = 0
            for index, row in df_upload.iterrows():
                try:
                    user = str(row["Katılımcı Adı"]).strip()
                    hedef_donemi = str(row["Hedef Dönem (YYYY-AA)"]).strip()
                    cat = str(row.get("Kategori", "Bireysel"))
                    link = str(row.get("Link", ""))
                    raw_date = row["Tarih (YYYY-AA-GG)"]
                    if user and (user not in existing_users_set):
                        try:
                            supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": user, "kategori": cat}).execute()
                            existing_users_set.add(user)
                        except: pass
                    
                    def cv(val): 
                        try: v = float(val); return v if pd.notnull(v) else None
                        except: return None
                    
                    data_main = {
                        "tahmin_ppk_faiz": cv(row.get("PPK Medyan")), "min_ppk_faiz": cv(row.get("PPK Min")), "max_ppk_faiz": cv(row.get("PPK Max")),
                        "tahmin_yilsonu_faiz": cv(row.get("Yıl Sonu Faiz Medyan")), "min_yilsonu_faiz": cv(row.get("Yıl Sonu Faiz Min")), "max_yilsonu_faiz": cv(row.get("Yıl Sonu Faiz Max")),
                        "tahmin_aylik_enf": cv(row.get("Aylık Enf Medyan")), "min_aylik_enf": cv(row.get("Aylık Enf Min")), "max_aylik_enf": cv(row.get("Aylık Enf Max")),
                        "tahmin_yillik_enf": cv(row.get("Yıllık Enf Medyan")), "min_yillik_enf": cv(row.get("Yıllık Enf Min")), "max_yillik_enf": cv(row.get("Yıllık Enf Max")),
                        "tahmin_yilsonu_enf": cv(row.get("Yıl Sonu Enf Medyan")), "min_yilsonu_enf": cv(row.get("Yıl Sonu Enf Min")), "max_yilsonu_enf": cv(row.get("Yıl Sonu Enf Max")),
                        "katilimci_sayisi": int(cv(row.get("N Sayısı")) or 1)
                    }
                    upsert_tahmin(user, hedef_donemi, cat, raw_date, link, data_main)
                    
                    fut_period = str(row.get("Gelecek Hedef Dönem", "")).strip()
                    if fut_period and fut_period.lower() != "nan":
                        fut_enf = cv(row.get("Gelecek Tahmin (Enf)"))
                        fut_ppk = cv(row.get("Gelecek Tahmin (PPK)"))
                        if fut_enf or fut_ppk:
                            data_fut = {"katilimci_sayisi": int(cv(row.get("N Sayısı")) or 1)}
                            if fut_enf: data_fut["tahmin_yilsonu_enf"] = fut_enf
                            if fut_ppk: data_fut["tahmin_ppk_faiz"] = fut_ppk
                            upsert_tahmin(user, fut_period, cat, raw_date, link, data_fut)
                    success_count += 1
                except Exception as e: st.error(f"Satır {index+1} hatası: {e}")
                progress_bar.progress((index+1)/len(df_upload))
            st.success(f"{success_count} kayıt başarıyla işlendi (Upsert).")

# ========================================================
# SAYFA: VERİ GİRİŞ EKRANLARI (MANUEL)
# ========================================================
elif page in ["PPK Girişi", "Enflasyon Girişi"]:
    st.header(f"➕ {page}")
    with st.form("entry_form"):
        st.subheader("1. Tahmin Detayları")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1: user, cat, disp = get_participant_selection()
        with c2: hedef_donemi = st.selectbox("Hedef Dönem (Neyi Tahmin Ediyor?)", tum_donemler, index=tum_donemler.index("2025-12") if "2025-12" in tum_donemler else 0)
        with c3: tarih = st.date_input("Veri Giriş Tarihi", datetime.date.today())
        link = st.text_input("Kaynak Linki (Opsiyonel)")
        
        st.markdown("---")
        data = {}; kat_sayisi = 1
        
        # --- MIN / MAX ALANLARI GERİ EKLENDİ ---
        if page == "PPK Girişi":
            c1, c2 = st.columns(2)
            v1 = c1.number_input("Medyan PPK (%)", step=0.25)
            min1 = c1.number_input("Min PPK", step=0.25); max1 = c1.number_input("Max PPK", step=0.25)
            
            v2 = c2.number_input("Yıl Sonu PPK (%)", step=0.25)
            min2 = c2.number_input("Min YS PPK", step=0.25); max2 = c2.number_input("Max YS PPK", step=0.25)
            
            data = {"tahmin_ppk_faiz": v1, "min_ppk_faiz": min1, "max_ppk_faiz": max1,
                    "tahmin_yilsonu_faiz": v2, "min_yilsonu_faiz": min2, "max_yilsonu_faiz": max2}
        else: # Enflasyon
            c1, c2, c3 = st.columns(3)
            v1 = c1.number_input("Aylık Enflasyon (%)", step=0.01, format="%.2f")
            min1 = c1.number_input("Min Aylık", step=0.01); max1 = c1.number_input("Max Aylık", step=0.01)
            
            v2 = c2.number_input("Yıllık Enflasyon (%)", step=0.01, format="%.2f")
            min2 = c2.number_input("Min Yıllık", step=0.01); max2 = c2.number_input("Max Yıllık", step=0.01)
            
            v3 = c3.number_input("Yıl Sonu Enflasyon (%)", step=0.01, format="%.2f")
            min3 = c3.number_input("Min Yıl Sonu", step=0.01); max3 = c3.number_input("Max Yıl Sonu", step=0.01)
            
            data = {"tahmin_aylik_enf": v1, "min_aylik_enf": min1, "max_aylik_enf": max1,
                    "tahmin_yillik_enf": v2, "min_yillik_enf": min2, "max_yillik_enf": max2,
                    "tahmin_yilsonu_enf": v3, "min_yilsonu_enf": min3, "max_yilsonu_enf": max3}
            
        kat_sayisi = st.number_input("Katılımcı Sayısı (N)", value=1)
        data["katilimci_sayisi"] = kat_sayisi
        
        st.markdown("---")
        st.write("Opsiyonel: Gelecek Yıl İçin Ek Tahmin")
        f_col1, f_col2 = st.columns(2)
        future_target = f_col1.selectbox("Gelecek Hedef", tum_donemler, index=tum_donemler.index("2026-12") if "2026-12" in tum_donemler else 0)
        future_val = f_col2.number_input("Değer (%)", step=0.25)
        
        if st.form_submit_button("✅ Kaydet"):
            if user:
                res = upsert_tahmin(user, hedef_donemi, cat, tarih, link, data)
                if future_val > 0:
                    fdata = {"katilimci_sayisi": kat_sayisi}
                    if page == "PPK Girişi": fdata["tahmin_ppk_faiz"] = future_val
                    else: fdata["tahmin_yilsonu_enf"] = future_val
                    upsert_tahmin(user, future_target, cat, tarih, link, fdata)
                st.success(f"İşlem Tamamlandı! ({res})")
            else: st.error("Kullanıcı seçiniz.")

# ========================================================
# SAYFA: KATILIMCI YÖNETİMİ
# ========================================================
elif page == "Katılımcı Yönetimi":
    st.header("👥 Katılımcı Yönetimi")
    
    if st.button("🔄 Veri Havuzundaki Kişileri Buraya Eşle (Sync)"):
        with st.spinner("Taranıyor..."):
            res_t = supabase.table(TABLE_TAHMIN).select("kullanici_adi, kategori").execute()
            all_forecast_users = pd.DataFrame(res_t.data)
            if not all_forecast_users.empty:
                unique_forecast_users = all_forecast_users.drop_duplicates(subset=['kullanici_adi'])
                res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad").execute()
                existing_users = set([r['ad_soyad'] for r in res_k.data])
                added_count = 0
                for _, row in unique_forecast_users.iterrows():
                    user = row['kullanici_adi']; cat = row.get('kategori', 'Bireysel')
                    if user not in existing_users:
                        try:
                            supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": user, "kategori": cat}).execute()
                            added_count += 1
                        except: pass
                if added_count > 0: st.success(f"✅ {added_count} eksik kişi eklendi!"); time.sleep(1.5); st.rerun()
                else: st.info("✅ Liste güncel.")
    
    st.markdown("---")
    with st.expander("➕ Manuel Yeni Kişi Ekle"):
        with st.form("new_kat"):
            ad = st.text_input("Ad / Kurum Adı")
            cat = st.radio("Kategori", ["Bireysel", "Kurumsal"], horizontal=True)
            if st.form_submit_button("Ekle"):
                if ad:
                    clean_name = normalize_name(ad)
                    supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": clean_name, "kategori": cat}).execute()
                    st.success("Eklendi!"); time.sleep(1); st.rerun()
    
    st.markdown("---")
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res.data)
    if not df_kat.empty:
        st.dataframe(df_kat, use_container_width=True)
        
        # --- TEHLİKELİ BÖLGE: TAM SİLME (ŞİFRE KORUMALI) ---
        st.markdown("### 🚨 Tehlikeli Bölge")
        with st.expander("💣 Tüm Veritabanını Sıfırla"):
            st.error("DİKKAT: Bu işlem 'Tahminler' ve 'Katılımcılar' tablolarındaki TÜM verileri kalıcı olarak siler.")
            admin_pwd = st.text_input("Onay için Yönetici Şifresi", type="password")
            if st.button("🔥 HEPSİNİ SİL"):
                if admin_pwd == SITE_SIFRESI:
                    try:
                        # Supabase'de tüm satırları silmek için 'neq' (not equal) mantığı kullanılabilir
                        supabase.table(TABLE_TAHMIN).delete().neq("id", 0).execute()
                        supabase.table(TABLE_KATILIMCI).delete().neq("id", 0).execute()
                        st.success("Tüm veritabanı başarıyla temizlendi."); time.sleep(2); st.rerun()
                    except Exception as e: st.error(f"Hata: {e}")
                else:
                    st.error("Hatalı Şifre!")

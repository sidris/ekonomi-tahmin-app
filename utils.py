import streamlit as st
from supabase import create_client, Client
import pandas as pd
import requests
import io
import datetime

# --- 1. AYARLAR VE BAĞLANTI ---
try:
    # Anahtarları her yerde ara (Supabase altı veya root)
    if "supabase" in st.secrets:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        # EVDS Key önceliği
        EVDS_API_KEY = st.secrets.get("EVDS_KEY")
        if not EVDS_API_KEY:
             EVDS_API_KEY = st.secrets["supabase"].get("EVDS_KEY")
    else:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
        EVDS_API_KEY = st.secrets.get("EVDS_KEY")

    # Supabase Bağlantısı
    if url and key:
        supabase: Client = create_client(url, key)
    else:
        supabase = None

except Exception as e:
    st.error(f"Ayarlar yüklenirken hata: {e}")
    st.stop()

# Sabitler
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
EVDS_TUFE_SERIES = "TP.FG.J0" # TÜFE Endeks Kodu

# --- 2. VERİ ÇEKME FONKSİYONLARI (SİZİN YÖNTEMİNİZ) ---

def _evds_headers(api_key: str) -> dict: 
    return {"key": api_key, "User-Agent": "Mozilla/5.0"}

def _evds_url_single(series_code, start_date, end_date, formulas):
    s = start_date.strftime("%d-%m-%Y")
    e = end_date.strftime("%d-%m-%Y")
    url = f"{EVDS_BASE}/series={series_code}&startDate={s}&endDate={e}&type=json"
    if formulas is not None: 
        url += f"&formulas={int(formulas)}"
    return url

@st.cache_data(ttl=600)
def fetch_evds_tufe_monthly_yearly(api_key, start_date, end_date):
    """
    Sizin kodunuzdaki yöntem: TP.FG.J0 endeksini çekip,
    Formula 1 (Aylık) ve Formula 3 (Yıllık) uygulayarak getirir.
    """
    if not api_key: return pd.DataFrame(), "EVDS_KEY eksik."
    
    try:
        results = {}
        # 1: Aylık Değişim, 3: Yıllık Değişim
        for formulas, out_col in [(1, "TUFE_Aylik"), (3, "TUFE_Yillik")]:
            url = _evds_url_single(EVDS_TUFE_SERIES, start_date, end_date, formulas=formulas)
            r = requests.get(url, headers=_evds_headers(api_key), timeout=25)
            
            if r.status_code != 200: continue
            
            js = r.json()
            items = js.get("items", [])
            if not items: continue
            
            df = pd.DataFrame(items)
            if "Tarih" not in df.columns: continue
            
            # Tarih işleme
            df["Tarih_dt"] = pd.to_datetime(df["Tarih"], dayfirst=True, errors="coerce")
            if df["Tarih_dt"].isnull().all():
                df["Tarih_dt"] = pd.to_datetime(df["Tarih"], format="%Y-%m", errors="coerce")
            
            df = df.dropna(subset=["Tarih_dt"]).sort_values("Tarih_dt")
            df["Donem"] = df["Tarih_dt"].dt.strftime("%Y-%m")
            
            # Değer kolonu (Genelde TP_FG_J0 olur ama formül uygulanınca değişebilir)
            # İçinde UNIXTIME, Tarih, Donem olmayan ilk kolonu değer kabul et
            val_cols = [c for c in df.columns if c not in ["Tarih", "UNIXTIME", "Tarih_dt", "Donem"]]
            if not val_cols: continue
            
            # Sonuç DataFrame'i oluştur
            results[out_col] = pd.DataFrame({
                "Tarih": df["Tarih_dt"].dt.strftime("%d-%m-%Y"), 
                "Donem": df["Donem"], 
                out_col: pd.to_numeric(df[val_cols[0]], errors="coerce")
            })
            
        df_m = results.get("TUFE_Aylik", pd.DataFrame())
        df_y = results.get("TUFE_Yillik", pd.DataFrame())
        
        if df_m.empty and df_y.empty: 
            return pd.DataFrame(), "Veri bulunamadı."
        
        if df_m.empty: out = df_y
        elif df_y.empty: out = df_m
        else: out = pd.merge(df_m, df_y, on=["Tarih", "Donem"], how="outer")
        
        return out.sort_values(["Donem", "Tarih"]), None
        
    except Exception as e: return pd.DataFrame(), str(e)

@st.cache_data(ttl=600)
def fetch_bis_cbpol_tr(start_date, end_date):
    """
    Sizin kodunuzdaki yöntem: BIS'ten CSV olarak çekme.
    """
    try:
        s = start_date.strftime("%Y-%m-%d")
        e = end_date.strftime("%Y-%m-%d")
        url = f"https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={s}&endPeriod={e}"
        
        r = requests.get(url, timeout=25)
        if r.status_code >= 400: return pd.DataFrame(), f"BIS HTTP {r.status_code}"
        
        df = pd.read_csv(io.StringIO(r.content.decode("utf-8", errors="ignore")))
        df.columns = [c.strip().upper() for c in df.columns]
        
        out = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        out["TIME_PERIOD"] = pd.to_datetime(out["TIME_PERIOD"], errors="coerce")
        out = out.dropna(subset=["TIME_PERIOD"])
        
        out["Donem"] = out["TIME_PERIOD"].dt.strftime("%Y-%m")
        out["REPO_RATE"] = pd.to_numeric(out["OBS_VALUE"], errors="coerce")
        
        # Aylık bazda son veriyi al
        out = out.sort_values("TIME_PERIOD").groupby("Donem").last().reset_index()
        
        return out[["Donem", "REPO_RATE"]], None
        
    except Exception as e: return pd.DataFrame(), str(e)

def fetch_market_data_adapter(start_date, end_date):
    """
    Dashboard'un çağırdığı ana fonksiyon
    """
    # 1. Enflasyon
    df_inf, err1 = fetch_evds_tufe_monthly_yearly(EVDS_API_KEY, start_date, end_date)
    # 2. Faiz
    df_pol, err2 = fetch_bis_cbpol_tr(start_date, end_date)
    
    combined = pd.DataFrame()
    
    # Birleştirme
    if not df_inf.empty and not df_pol.empty:
        combined = pd.merge(df_inf, df_pol, on="Donem", how="outer")
    elif not df_inf.empty: 
        combined = df_inf
        combined['REPO_RATE'] = None
    elif not df_pol.empty: 
        combined = df_pol.rename(columns={'REPO_RATE': 'REPO_RATE'})
        combined['TUFE_Aylik'] = None
        combined['TUFE_Yillik'] = None
        
    if combined.empty:
        return pd.DataFrame(), f"Hata: {err1} | {err2}"

    # Kolon İsimlerini Standartlaştır
    combined = combined.rename(columns={'REPO_RATE': 'PPK Faizi', 'TUFE_Aylik': 'Aylık TÜFE', 'TUFE_Yillik': 'Yıllık TÜFE'})
    
    # Tarih yoksa oluştur (Grafik için)
    if 'Tarih' not in combined.columns and 'Donem' in combined.columns:
        combined['Tarih'] = pd.to_datetime(combined['Donem'] + "-01")
    elif 'Tarih' in combined.columns:
        combined['Tarih'] = pd.to_datetime(combined['Tarih'], dayfirst=True)
        
    return combined, None

# --- 3. VERİTABANI İŞLEMLERİ (HAWKISH APP İÇİN) ---

def fetch_all_data():
    if not supabase: return pd.DataFrame()
    res = supabase.table("market_logs").select("*").order("period_date", desc=True).execute()
    return pd.DataFrame(res.data)

def delete_entry(record_id):
    if supabase: supabase.table("market_logs").delete().eq("id", record_id).execute()

def update_entry(record_id, date, text, source, score_dict, score_abg, score_fb, fb_label):
    if supabase:
        data = {
            "period_date": str(date), "text_content": text, "source": source,
            "score_dict": score_dict, "score_abg": score_abg, 
            "score_finbert": score_fb, "finbert_label": fb_label
        }
        supabase.table("market_logs").update(data).eq("id", record_id).execute()

def insert_entry(date, text, source, score_dict, score_abg, score_fb, fb_label):
    if supabase:
        data = {
            "period_date": str(date), "text_content": text, "source": source,
            "score_dict": score_dict, "score_abg": score_abg, 
            "score_finbert": score_fb, "finbert_label": fb_label
        }
        supabase.table("market_logs").insert(data).execute()

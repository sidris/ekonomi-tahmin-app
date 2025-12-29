import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import datetime
import requests
import numpy as np

# --- OPSİYONEL KÜTÜPHANE KONTROLÜ ---
try:
    from docx import Document
except ImportError:
    pass

# =========================================================
# 1) AYARLAR
# =========================================================
st.set_page_config(
    page_title="Ekonomi Tahmin Terminali",
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.stMetric { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.stButton button { width: 100%; border-radius: 8px; font-weight: 600; }
div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; background-color: white; }
h1, h2, h3 { color: #2c3e50; }
div[data-testid="stDataFrame"] { width: 100%; }
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 2) SECRETS + SUPABASE
# =========================================================
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"secrets.toml hatası veya eksik bilgi: {e}")
    st.stop()

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
EVDS_TUFE_SERIES = "TP.FG.J0"  # Doğru TÜFE Kodu

# =========================================================
# 3) YARDIMCI FONKSİYONLAR
# =========================================================
def get_period_list():
    years = range(2024, 2033)
    months = [f"{i:02d}" for i in range(1, 13)]
    return [f"{y}-{m}" for y in years for m in months]

tum_donemler = get_period_list()

def normalize_name(name):
    return name.strip().title() if name else ""

def clean_and_sort_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    numeric_cols = [
        "tahmin_ppk_faiz","min_ppk_faiz","max_ppk_faiz",
        "tahmin_yilsonu_faiz","min_yilsonu_faiz","max_yilsonu_faiz",
        "tahmin_aylik_enf","min_aylik_enf","max_aylik_enf",
        "tahmin_yillik_enf","min_yillik_enf","max_yillik_enf",
        "tahmin_yilsonu_enf","min_yilsonu_enf","max_yilsonu_enf",
        "katilimci_sayisi",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "donem" in df.columns:
        df["donem_date"] = pd.to_datetime(df["donem"], format="%Y-%m", errors="coerce")
        df = df.sort_values(by="donem_date")

    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"], errors="coerce")

    return df

def parse_range_input(text_input, default_median=0.0):
    if not text_input or text_input.strip() == "":
        return default_median, 0.0, 0.0, False
    try:
        text = text_input.replace(",", ".")
        parts = []
        if "-" in text:
            parts = text.split("-")
        elif "/" in text:
            parts = text.split("/")
        if len(parts) == 2:
            v1, v2 = float(parts[0].strip()), float(parts[1].strip())
            return (v1 + v2) / 2, min(v1, v2), max(v1, v2), True
    except Exception:
        pass
    return default_median, 0.0, 0.0, False

def upsert_tahmin(user, period, category, forecast_date, link, data_dict):
    date_str = forecast_date.strftime("%Y-%m-%d")
    
    # 1. Önce ID'yi kontrol et
    check_res = (
        supabase.table(TABLE_TAHMIN)
        .select("id")
        .eq("kullanici_adi", user)
        .eq("donem", period)
        .eq("tahmin_tarihi", date_str)
        .execute()
    )

    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    clean_data.update({
        "kullanici_adi": user,
        "donem": period,
        "kategori": category,
        "tahmin_tarihi": date_str,
        "kaynak_link": link if link else None,
    })

    # 2. Varsa Update, Yoksa Insert
    if check_res.data:
        record_id = check_res.data[0]["id"]
        supabase.table(TABLE_TAHMIN).update(clean_data).eq("id", record_id).execute()
    else:
        supabase.table(TABLE_TAHMIN).insert(clean_data).execute()

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    return output.getvalue()

# =========================================================
# 4) EVDS & BIS (VERİ ÇEKME)
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
        for formulas, out_col in [(1, "TUFE_Aylik"), (2, "TUFE_Yillik")]:
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

# =========================================================
# 5) AUTH
# =========================================================
if "giris_yapildi" not in st.session_state:
    st.session_state["giris_yapildi"] = False

if not st.session_state["giris_yapildi"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("### 🔐 Giriş Paneli")
        pw = st.text_input("Şifre", type="password")
        if st.button("Giriş Yap", type="primary"):
            if pw == SITE_SIFRESI:
                st.session_state["giris_yapildi"] = True
                st.rerun()
            else:
                st.error("Şifre hatalı.")
        st.stop()

# =========================================================
# 6) SIDEBAR
# =========================================================
with st.sidebar:
    st.title("📊 Menü")
    page = st.radio("Git:", [
        "Dashboard", 
        "📈 Piyasa Verileri", 
        "PPK Girişi", 
        "Enflasyon Girişi", 
        "Katılımcı Yönetimi"
    ])

# =========================================================
# SAYFA: DASHBOARD (DÜZELTİLMİŞ & GELİŞMİŞ)
# =========================================================
if page == "Dashboard":
    st.header("Piyasa Analiz Dashboardu")

    # 1. Verileri Çek
    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    
    # Kategori bilgisini garanti almak için select("*") yapıyoruz
    res_k = supabase.table(TABLE_KATILIMCI).select("*").execute()
    df_k = pd.DataFrame(res_k.data)

    if df_t.empty or df_k.empty:
        st.info("Henüz yeterli veri girişi yok.")
        st.stop()

    # 2. Veri Temizliği
    df_t = clean_and_sort_data(df_t)
    
    # 3. Merge İşlemi (KeyError'u önleyen sağlam yapı)
    # Kolon isimlerini garantiye alalım
    if "ad_soyad" in df_k.columns:
        df_k = df_k.rename(columns={"ad_soyad": "kullanici_adi_key"})
    
    # Merge
    df_merged = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="kullanici_adi_key", how="left")
    
    # KeyError Çözümü: Kolonlar oluşmadıysa manuel oluştur
    if "kategori" not in df_merged.columns:
        df_merged["kategori"] = "Bireysel"
    if "anket_kaynagi" not in df_merged.columns:
        df_merged["anket_kaynagi"] = "-"
        
    # Eksik verileri doldur
    df_merged["kategori"] = df_merged["kategori"].fillna("Bireysel")
    df_merged["anket_kaynagi"] = df_merged["anket_kaynagi"].fillna("-")
    
    # Görinen İsim Oluşturma
    df_merged["gorunen_isim"] = df_merged.apply(
        lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" 
        if x['anket_kaynagi'] not in ["-", None, ""] else x['kullanici_adi'], 
        axis=1
    )
    
    df_merged["yil"] = df_merged["donem"].apply(lambda x: str(x).split("-")[0])

    # En güncel tahminleri bul
    df_latest = df_merged.sort_values("tahmin_tarihi").drop_duplicates(subset=["kullanici_adi", "donem"], keep="last")

    # --- ÜST METRİKLER ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Katılımcı", df_latest["kullanici_adi"].nunique())
    m2.metric("Toplam Tahmin", len(df_latest))
    
    avg_ppk = df_latest[df_latest["donem"] == "2025-01"]["tahmin_ppk_faiz"].median()
    m3.metric("Ocak '25 PPK Medyan", f"%{avg_ppk}" if pd.notnull(avg_ppk) else "-")
    
    avg_inf = df_latest[df_latest["donem"] == "2025-01"]["tahmin_aylik_enf"].median()
    m4.metric("Ocak '25 Enflasyon Medyan", f"%{avg_inf}" if pd.notnull(avg_inf) else "-")
    
    st.markdown("---")

    # --- FİLTRELER ---
    with st.sidebar:
        st.markdown("### 🔍 Filtreler")
        param_type = st.selectbox("Analiz Parametresi", [
            "tahmin_ppk_faiz", "tahmin_yilsonu_faiz", 
            "tahmin_aylik_enf", "tahmin_yilsonu_enf"
        ], format_func=lambda x: x.replace("tahmin_", "").replace("_", " ").upper())
        
        cats = st.multiselect("Kategori", sorted(df_latest["kategori"].unique()), default=sorted(df_latest["kategori"].unique()))
        
        # Filtreli veri
        df_filtered = df_latest[df_latest["kategori"].isin(cats)]
        
        users = st.multiselect("Katılımcılar", sorted(df_filtered["gorunen_isim"].unique()), default=sorted(df_filtered["gorunen_isim"].unique()))
        
        target_df = df_filtered[df_filtered["gorunen_isim"].isin(users)].copy()

    # --- GRAFİK 1: ZAMAN SERİSİ (TREND) ---
    st.subheader("📈 Tahmin Trendleri")
    if not target_df.empty:
        fig_line = px.line(
            target_df.sort_values("donem_date"),
            x="donem", 
            y=param_type, 
            color="gorunen_isim",
            markers=True,
            title=f"{param_type.replace('_', ' ').title()} - Dönemsel Değişim",
            hover_data=["tahmin_tarihi"]
        )
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("Seçilen kriterlere uygun veri yok.")

    # --- GRAFİK 2: ISI HARİTASI (HEATMAP) - GERİ GELDİ! ---
    st.subheader("🔥 Tahmin Isı Haritası")
    if not target_df.empty:
        try:
            # Pivot table: Satırlar=Katılımcı, Sütunlar=Dönem, Değer=Tahmin
            pivot_df = target_df.pivot_table(index="gorunen_isim", columns="donem", values=param_type)
            
            fig_heat = px.imshow(
                pivot_df,
                labels=dict(x="Dönem", y="Katılımcı", color="Değer"),
                x=pivot_df.columns,
                y=pivot_df.index,
                aspect="auto",
                color_continuous_scale="RdBu_r",
                text_auto=".2f",
                title=f"{param_type} Isı Haritası"
            )
            fig_heat.update_xaxes(side="top")
            st.plotly_chart(fig_heat, use_container_width=True)
        except Exception as e:
            st.error(f"Isı haritası oluşturulamadı: {e}")

    # --- GRAFİK 3: DAĞILIM (BOXPLOT) - YENİ! ---
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📦 Tahmin Dağılımı (Boxplot)")
        if not target_df.empty:
            fig_box = px.box(
                target_df, 
                x="donem", 
                y=param_type, 
                points="all",
                color="donem",
                title="Dönem Bazlı Tahmin Dağılımı"
            )
            st.plotly_chart(fig_box, use_container_width=True)

    # --- GRAFİK 4: SON DURUM BAR ---
    with c2:
        st.subheader("📊 Son Dönem Karşılaştırma")
        last_period = target_df["donem"].max()
        df_last_p = target_df[target_df["donem"] == last_period]
        
        if not df_last_p.empty:
            fig_bar = px.bar(
                df_last_p.sort_values(param_type),
                x="gorunen_isim",
                y=param_type,
                color="kategori",
                text_auto=".2f",
                title=f"{last_period} Dönemi İçin Tahminler"
            )
            st.plotly_chart(fig_bar, use_container_width=True)

# =========================================================
# SAYFA: PİYASA VERİLERİ (EVDS + BIS)
# =========================================================
elif page == "📈 Piyasa Verileri":
    st.header("📈 Gerçekleşen Veriler (EVDS & BIS)")
    
    with st.sidebar:
        sd = st.date_input("Başlangıç", datetime.date(2025, 1, 1))
        ed = st.date_input("Bitiş", datetime.date(2025, 12, 31))

    # EVDS
    st.subheader("TÜFE Enflasyonu (TCMB)")
    if EVDS_API_KEY:
        with st.spinner("EVDS verisi çekiliyor..."):
            df_evds, err = fetch_evds_tufe_monthly_yearly(EVDS_API_KEY, sd, ed)
        if err: st.error(err)
        elif not df_evds.empty:
            st.dataframe(df_evds, use_container_width=True)
            fig = go.Figure()
            if "TUFE_Aylik" in df_evds.columns:
                fig.add_trace(go.Scatter(x=df_evds["Tarih"], y=df_evds["TUFE_Aylik"], name="Aylık %"))
            if "TUFE_Yillik" in df_evds.columns:
                fig.add_trace(go.Scatter(x=df_evds["Tarih"], y=df_evds["TUFE_Yillik"], name="Yıllık %", line=dict(dash='dot')))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("EVDS API Key girilmemiş.")

    st.markdown("---")

    # BIS
    st.subheader("Politika Faizi (BIS)")
    with st.spinner("BIS verisi çekiliyor..."):
        df_bis, err_bis = fetch_bis_cbpol_tr(sd, ed)
    if err_bis: st.error(err_bis)
    elif not df_bis.empty:
        st.dataframe(df_bis, use_container_width=True)
        fig2 = px.line(df_bis, x="Tarih", y="REPO_RATE", markers=True, title="TCMB Politika Faizi")
        st.plotly_chart(fig2, use_container_width=True)

# =========================================================
# SAYFA: DİĞERLERİ (KATILIMCI & GİRİŞ)
# =========================================================
elif page == "Katılımcı Yönetimi":
    st.header("👥 Katılımcı Yönetimi")
    with st.expander("➕ Yeni Ekle"):
        with st.form("add_p"):
            c1,c2 = st.columns(2)
            ad = c1.text_input("Ad")
            cat = c2.radio("Tip", ["Bireysel","Kurumsal"])
            src = st.text_input("Kaynak")
            if st.form_submit_button("Ekle") and ad:
                supabase.table(TABLE_KATILIMCI).insert({"ad_soyad":normalize_name(ad),"kategori":cat,"anket_kaynagi":src or None}).execute()
                st.success("Eklendi")

    res = supabase.table(TABLE_KATILIMCI).select("*").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        to_del = st.selectbox("Sil", df["ad_soyad"].unique())
        if st.button("Sil"):
            supabase.table(TABLE_TAHMIN).delete().eq("kullanici_adi",to_del).execute()
            supabase.table(TABLE_KATILIMCI).delete().eq("ad_soyad",to_del).execute()
            st.rerun()

elif page in ["PPK Girişi", "Enflasyon Girişi"]:
    st.header(f"📝 {page}")
    
    # Katılımcı Seçimi
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_users = pd.DataFrame(res.data)
    if df_users.empty:
        st.error("Önce katılımcı ekleyin.")
        st.stop()
        
    df_users["disp"] = df_users.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
    
    with st.form("entry"):
        c1, c2, c3 = st.columns(3)
        sel_u = c1.selectbox("Katılımcı", df_users["disp"].unique())
        real_u = df_users[df_users["disp"]==sel_u].iloc[0]["ad_soyad"]
        cat_u = df_users[df_users["disp"]==sel_u].iloc[0]["kategori"]
        
        donem = c2.selectbox("Dönem", tum_donemler)
        tarih = c3.date_input("Tarih", datetime.date.today())
        link = st.text_input("Link")
        
        data = {}
        if page == "PPK Girişi":
            col1, col2 = st.columns(2)
            v1 = col1.number_input("PPK Tahmin %", step=0.25)
            v2 = col2.number_input("Yıl Sonu Faiz %", step=0.25)
            data = {"tahmin_ppk_faiz":v1, "tahmin_yilsonu_faiz":v2}
        else:
            c1,c2,c3 = st.columns(3)
            v1 = c1.number_input("Aylık Enf %", step=0.1)
            v2 = c2.number_input("Yıllık Enf %", step=0.1)
            v3 = c3.number_input("Yıl Sonu Enf %", step=0.1)
            data = {"tahmin_aylik_enf":v1, "tahmin_yillik_enf":v2, "tahmin_yilsonu_enf":v3}
            
        if st.form_submit_button("Kaydet"):
            upsert_tahmin(real_u, donem, cat_u, tarih, link, data)
            st.success("Kaydedildi!")

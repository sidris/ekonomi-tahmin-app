import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import datetime
import requests

# --- İSTEĞE BAĞLI KÜTÜPHANE KONTROLÜ (HATA VERMEMESİ İÇİN) ---
try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    pass

# =========================================================
# 1) AYARLAR
# =========================================================
st.set_page_config(
    page_title="Finansal Tahmin Terminali",
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

# DÜZELTİLEN KISIM: Sadece TÜFE Genel Endeksi (Hatasız Kod)
EVDS_TUFE_SERIES = "TP.FG.J0"  

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

def safe_int(val):
    try:
        return int(float(val)) if pd.notnull(val) else 0
    except Exception:
        return 0

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
    check_res = (
        supabase.table(TABLE_TAHMIN)
        .select("id")
        .eq("kullanici_adi", user)
        .eq("donem", period)
        .eq("tahmin_tarihi", date_str)
        .execute()
    )

    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    clean_data.update(
        {
            "kullanici_adi": user,
            "donem": period,
            "kategori": category,
            "tahmin_tarihi": date_str,
            "kaynak_link": link if link else None,
        }
    )

    if check_res.data:
        record_id = check_res.data[0]["id"]
        supabase.table(TABLE_TAHMIN).update(clean_data).eq("id", record_id).execute()
        return "updated"
    else:
        supabase.table(TABLE_TAHMIN).insert(clean_data).execute()
        return "inserted"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    return output.getvalue()

# =========================================================
# 4) EVDS (TÜFE AYLIK+YILLIK) - HATASIZ URL YAPISI
# =========================================================
def _evds_headers(api_key: str) -> dict:
    return {
        "key": api_key,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }

def _evds_url_single(series_code: str, start_date: datetime.date, end_date: datetime.date, formulas: int | None) -> str:
    # EVDS, "DD-MM-YYYY" formatını sever
    s = start_date.strftime("%d-%m-%Y")
    e = end_date.strftime("%d-%m-%Y")
    url = f"{EVDS_BASE}/series={series_code}&startDate={s}&endDate={e}&type=json"
    if formulas is not None:
        url += f"&formulas={int(formulas)}"
    return url

def _evds_get_json(url: str, api_key: str, timeout: int = 25) -> dict:
    r = requests.get(url, headers=_evds_headers(api_key), timeout=timeout)
    # Hata kontrolü
    if r.status_code != 200:
        raise requests.HTTPError(f"EVDS Hatası (Kod: {r.status_code})")
    return r.json()

@st.cache_data(ttl=300)
def fetch_evds_tufe_monthly_yearly(api_key: str, start_date: datetime.date, end_date: datetime.date) -> tuple[pd.DataFrame, str | None]:
    """
    Sadece 'TP.FG.J0' (TÜFE) serisi kullanılır.
    formulas=1 -> Aylık Değişim
    formulas=2 -> Yıllık Değişim
    """
    if not api_key:
        return pd.DataFrame(), "EVDS_KEY eksik (secrets.toml)"

    try:
        results = {}
        # 1: Aylık, 2: Yıllık
        for formulas, out_col in [(1, "TUFE_Aylik"), (2, "TUFE_Yillik")]:
            url = _evds_url_single(EVDS_TUFE_SERIES, start_date, end_date, formulas=formulas)
            js = _evds_get_json(url, api_key)
            items = js.get("items", [])
            
            if not items:
                # Veri yoksa boş geç
                continue

            df = pd.DataFrame(items)
            
            if "Tarih" not in df.columns:
                continue

            # Tarih parse etme (DayFirst=True önemli)
            df["Tarih_dt"] = pd.to_datetime(df["Tarih"], dayfirst=True, errors="coerce")
            
            # Eğer yukarıdaki çalışmazsa yedek (YYYY-MM)
            if df["Tarih_dt"].isnull().all():
                 df["Tarih_dt"] = pd.to_datetime(df["Tarih"], format="%Y-%m", errors="coerce")

            df = df.dropna(subset=["Tarih_dt"]).sort_values("Tarih_dt")
            df["Donem"] = df["Tarih_dt"].dt.strftime("%Y-%m")
            
            # Değer kolonunu bul (Tarih, UNIXTIME vb olmayan ilk kolon)
            val_cols = [c for c in df.columns if c not in ["Tarih", "UNIXTIME", "Tarih_dt", "Donem"]]
            if not val_cols:
                continue
            val_col = val_cols[0]

            part = pd.DataFrame({
                "Tarih": df["Tarih_dt"].dt.strftime("%d-%m-%Y"),
                "Donem": df["Donem"],
                out_col: pd.to_numeric(df[val_col], errors="coerce"),
            })

            results[out_col] = part

        # İki tabloyu (Aylık ve Yıllık) birleştir
        df_monthly = results.get("TUFE_Aylik", pd.DataFrame())
        df_yearly = results.get("TUFE_Yillik", pd.DataFrame())

        if df_monthly.empty and df_yearly.empty:
            return pd.DataFrame(), "Seçilen tarih aralığında EVDS verisi bulunamadı."
        
        if df_monthly.empty:
            out = df_yearly
        elif df_yearly.empty:
            out = df_monthly
        else:
            out = pd.merge(df_monthly, df_yearly, on=["Tarih", "Donem"], how="outer")

        out = out.sort_values(["Donem", "Tarih"]).reset_index(drop=True)
        return out, None

    except Exception as e:
        return pd.DataFrame(), f"EVDS İşlem Hatası: {e}"


# =========================================================
# 5) BIS (REPO/POLICY RATE)
# =========================================================
@st.cache_data(ttl=300)
def fetch_bis_cbpol_tr(start_date: datetime.date, end_date: datetime.date) -> tuple[pd.DataFrame, str | None]:
    """
    BIS: WS_CBPOL / D.TR (policy rate)
    """
    try:
        s = start_date.strftime("%Y-%m-%d")
        e = end_date.strftime("%Y-%m-%d")
        url = f"https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={s}&endPeriod={e}"

        r = requests.get(url, timeout=25)
        if r.status_code >= 400:
            return pd.DataFrame(), f"BIS HTTP Hatası: {r.status_code}"

        content = r.content.decode("utf-8", errors="ignore")
        if not content.strip():
             return pd.DataFrame(), "BIS boş veri döndü."

        # CSV'yi oku
        df = pd.read_csv(io.StringIO(content))
        
        # Kolon isimlerini standartlaştır
        df.columns = [c.strip().upper() for c in df.columns]

        # Gerekli kolonlar var mı?
        if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
            return pd.DataFrame(), f"BIS kolon hatası. Gelen kolonlar: {list(df.columns)}"

        out = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        out["TIME_PERIOD"] = pd.to_datetime(out["TIME_PERIOD"], errors="coerce")
        out = out.dropna(subset=["TIME_PERIOD"])
        
        out["Donem"] = out["TIME_PERIOD"].dt.strftime("%Y-%m")
        out["Tarih"] = out["TIME_PERIOD"].dt.strftime("%d-%m-%Y")
        out["REPO_RATE"] = pd.to_numeric(out["OBS_VALUE"], errors="coerce")
        
        out = out[["Tarih", "Donem", "REPO_RATE"]].sort_values(["Donem", "Tarih"]).reset_index(drop=True)

        return out, None

    except Exception as e:
        return pd.DataFrame(), f"BIS Hatası: {e}"


# =========================================================
# 6) AUTH (GİRİŞ)
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
# 7) SIDEBAR MENÜ
# =========================================================
with st.sidebar:
    st.title("📊 Menü")
    page = st.radio(
        "Git:",
        [
            "Dashboard",
            "📈 Piyasa Verileri (EVDS & BIS)",
            "PPK Girişi",
            "Enflasyon Girişi",
            "Katılımcı Yönetimi",
        ],
    )

# Katılımcı seçim yardımcı fonksiyonu
def get_participant_selection():
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if df.empty:
        st.error("Lütfen önce Katılımcı ekleyin.")
        return None, None, None
    df["disp"] = df.apply(
        lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x.get("anket_kaynagi") else x["ad_soyad"],
        axis=1,
    )
    name_map = dict(zip(df["disp"], df["ad_soyad"]))
    sel = st.selectbox("Katılımcı Seç", df["disp"].unique())
    row = df[df["ad_soyad"] == name_map[sel]].iloc[0]
    return name_map[sel], row.get("kategori", "Bireysel"), sel


# =========================================================
# SAYFA: DASHBOARD
# =========================================================
if page == "Dashboard":
    st.header("Piyasa Analiz Dashboardu")

    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)

    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi", "kategori").execute()
    df_k = pd.DataFrame(res_k.data)

    if df_t.empty or df_k.empty:
        st.info("Henüz veri girişi yapılmamış.")
        st.stop()

    df_t = clean_and_sort_data(df_t)
    df_t["tahmin_tarihi"] = pd.to_datetime(df_t["tahmin_tarihi"], errors="coerce")
    df_t = df_t.sort_values(by="tahmin_tarihi")

    df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
    df_latest_raw = df_t.drop_duplicates(subset=["kullanici_adi", "donem"], keep="last")
    df_latest = pd.merge(df_latest_raw, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")

    for d in [df_history, df_latest]:
        d["gorunen_isim"] = d.apply(
            lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})"
            if pd.notnull(x["anket_kaynagi"]) and x["anket_kaynagi"] != ""
            else x["kullanici_adi"],
            axis=1,
        )
        d["hover_text"] = d.apply(
            lambda x: f"Tarih: {x['tahmin_tarihi'].strftime('%d-%m-%Y')}<br>N={int(x['katilimci_sayisi'])}"
            if pd.notnull(x.get("katilimci_sayisi")) and pd.notnull(x.get("tahmin_tarihi"))
            else "",
            axis=1,
        )
        d["kategori"] = d["kategori"].fillna("Bireysel")
        d["anket_kaynagi"] = d["anket_kaynagi"].fillna("-")
        d["yil"] = d["donem"].apply(lambda x: str(x).split("-")[0] if isinstance(x, str) else "")

    c1, c2, c3 = st.columns(3)
    c1.metric("Toplam Katılımcı", df_latest["kullanici_adi"].nunique())
    c2.metric("Güncel Tahmin Sayısı", len(df_latest))
    last_dt = df_latest["tahmin_tarihi"].max()
    c3.metric("Son Güncelleme", last_dt.strftime("%d.%m.%Y") if pd.notnull(last_dt) else "-")
    st.markdown("---")

    with st.sidebar:
        st.markdown("### 🔍 Filtreler")
        x_axis_mode = st.radio("X Ekseni", ["📅 Hedef Dönem", "⏳ Tahmin Tarihi"])
        
        # Filtre mantığı
        all_cats = sorted(df_latest["kategori"].unique())
        cat_filter = st.multiselect("Kategori", all_cats, default=all_cats)
        
        subset_cat = df_latest[df_latest["kategori"].isin(cat_filter)]
        avail_src = sorted(subset_cat["anket_kaynagi"].astype(str).unique())
        src_filter = st.multiselect("Kaynak", avail_src, default=avail_src)
        
        subset_src = subset_cat[subset_cat["anket_kaynagi"].astype(str).isin(src_filter)]
        avail_usr = sorted(subset_src["gorunen_isim"].unique())
        usr_filter = st.multiselect("Katılımcı", avail_usr, default=avail_usr)
        
        avail_yrs = sorted(subset_src["yil"].unique())
        yr_filter = st.multiselect("Yıl", avail_yrs, default=avail_yrs)

    is_single_user = len(usr_filter) == 1

    if is_single_user:
        target_df = df_history[df_history["gorunen_isim"].isin(usr_filter) & df_history["yil"].isin(yr_filter)].copy()
        x_axis_col = "tahmin_tarihi"
        sort_col = "tahmin_tarihi"
        tick_format = "%d-%m-%Y"
    else:
        target_df = df_latest[
            df_latest["kategori"].isin(cat_filter)
            & df_latest["anket_kaynagi"].isin(src_filter)
            & df_latest["gorunen_isim"].isin(usr_filter)
            & df_latest["yil"].isin(yr_filter)
        ].copy()
        x_axis_col = "donem"
        sort_col = "donem_date"
        tick_format = None

    if target_df.empty:
        st.warning("Seçilen filtrelere uygun veri yok.")
        st.stop()

    def plot(y, min_c, max_c, tit):
        chart_data = target_df.sort_values(sort_col)
        # Verisi olmayan kolonları çizdirmemek için kontrol
        if chart_data[y].isnull().all():
            st.info(f"{tit} için veri yok.")
            return

        fig = px.line(
            chart_data,
            x=x_axis_col,
            y=y,
            color="gorunen_isim" if not is_single_user else "donem",
            markers=True,
            title=tit,
            hover_data=["hover_text"],
        )
        if tick_format:
            fig.update_xaxes(tickformat=tick_format)

        st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        plot("tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Faiz Tahmini")
    with c2:
        plot("tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "Yıl Sonu Enflasyon Tahmini")


# =========================================================
# SAYFA: PIYASA VERILERI (EVDS + BIS)
# =========================================================
elif page == "📈 Piyasa Verileri (EVDS & BIS)":
    st.header("📈 Gerçekleşen Piyasa Verileri")
    st.info("Enflasyon verisi TCMB EVDS'den, Politika Faizi BIS veritabanından çekilmektedir.")

    with st.sidebar:
        st.markdown("### 📅 Tarih Aralığı")
        sd = st.date_input("Başlangıç", datetime.date(2025, 1, 1))
        ed = st.date_input("Bitiş", datetime.date(2025, 12, 31))

        if EVDS_API_KEY:
            st.markdown("---")
            st.caption("EVDS Bağlantısı: Aktif ✅")

    # 1. EVDS: ENFLASYON
    st.subheader("1. Enflasyon (TÜFE - Kaynak: EVDS)")
    if not EVDS_API_KEY:
        st.error("EVDS API Anahtarı bulunamadı (secrets.toml dosyasını kontrol edin).")
        df_evds = pd.DataFrame()
    else:
        with st.spinner("TCMB EVDS'den veri çekiliyor..."):
            df_evds, err_evds = fetch_evds_tufe_monthly_yearly(EVDS_API_KEY, sd, ed)
        
        if err_evds:
            st.error(err_evds)

    if df_evds is not None and not df_evds.empty:
        st.dataframe(df_evds, use_container_width=True, height=300)
        st.download_button("📥 Enflasyon Verisini İndir (Excel)", to_excel(df_evds), "EVDS_ENFLASYON.xlsx", type="primary")

        fig = go.Figure()
        if "TUFE_Aylik" in df_evds.columns:
            fig.add_trace(go.Scatter(x=df_evds["Tarih"], y=df_evds["TUFE_Aylik"], mode="lines+markers", name="Aylık Enflasyon (%)"))
        if "TUFE_Yillik" in df_evds.columns:
            fig.add_trace(go.Scatter(x=df_evds["Tarih"], y=df_evds["TUFE_Yillik"], mode="lines+markers", name="Yıllık Enflasyon (%)", line=dict(dash='dot', color='firebrick')))
        
        fig.update_layout(title="TÜFE Enflasyon Oranları", xaxis_title="Tarih", yaxis_title="Oran (%)", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # 2. BIS: POLİTİKA FAİZİ
    st.subheader("2. Politika Faizi (Repo - Kaynak: BIS)")
    with st.spinner("BIS Veritabanından veri çekiliyor..."):
        df_bis, err_bis = fetch_bis_cbpol_tr(sd, ed)
    
    if err_bis:
        st.error(err_bis)

    if not df_bis.empty:
        st.dataframe(df_bis, use_container_width=True, height=300)
        st.download_button("📥 Faiz Verisini İndir (Excel)", to_excel(df_bis), "BIS_FAIZ_TR.xlsx", type="primary")
        
        fig2 = px.line(df_bis, x="Tarih", y="REPO_RATE", markers=True, title="TCMB Politika Faizi")
        fig2.update_traces(line_color='#1E88E5', line_width=3)
        st.plotly_chart(fig2, use_container_width=True)


# =========================================================
# SAYFA: KATILIMCI YÖNETİMİ
# =========================================================
elif page == "Katılımcı Yönetimi":
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
                        supabase.table(TABLE_KATILIMCI).insert(
                            {"ad_soyad": normalize_name(ad), "kategori": cat, "anket_kaynagi": src or None}
                        ).execute()
                        st.toast("Kişi başarıyla eklendi.")
                    except Exception as e:
                        st.error(f"Ekleme hatası: {e}")

    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        ks = st.selectbox("Silinecek Kişi Seçin", df["ad_soyad"].unique())
        if st.button("🚫 Seçili Kişiyi ve Verilerini Sil"):
            try:
                supabase.table(TABLE_TAHMIN).delete().eq("kullanici_adi", ks).execute()
                supabase.table(TABLE_KATILIMCI).delete().eq("ad_soyad", ks).execute()
                st.success("Silindi!")
                st.rerun()
            except Exception as e:
                st.error(f"Silme hatası: {e}")


# =========================================================
# SAYFA: VERİ GİRİŞİ
# =========================================================
elif page in ["PPK Girişi", "Enflasyon Girişi"]:
    st.header(f"➕ {page}")
    with st.container():
        with st.form("entry_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                user, cat, disp = get_participant_selection()
            with c2:
                # Varsayılan olarak bugünün ayını seçmeye çalış
                current_month = datetime.date.today().strftime("%Y-%m")
                idx = tum_donemler.index(current_month) if current_month in tum_donemler else 0
                donem = st.selectbox("Dönem", tum_donemler, index=idx)
            with c3:
                tarih = st.date_input("Tahmin Tarihi", datetime.date.today())

            link = st.text_input("Link (Opsiyonel)")
            st.markdown("---")
            data = {}
            kat_sayisi = 0

            # PPK FORMU
            if page == "PPK Girişi":
                c1, c2 = st.columns(2)
                st.caption("Örnek Aralık Girişi: 42-45 veya 42/45")
                r1 = c1.text_input("PPK Faiz Aralığı", key="r1")
                v1 = c1.number_input("PPK Faiz Medyan %", step=0.25)
                
                r2 = c2.text_input("Yıl Sonu Faiz Aralığı", key="r2")
                v2 = c2.number_input("Yıl Sonu Faiz Medyan %", step=0.25)
                
                with st.expander("Gelişmiş / Min-Max Girişi"):
                    ec1, ec2, ec3 = st.columns(3)
                    mn1 = ec1.number_input("Min PPK", step=0.25)
                    mx1 = ec1.number_input("Max PPK", step=0.25)
                    mn2 = ec2.number_input("Min Yıl Sonu", step=0.25)
                    mx2 = ec2.number_input("Max Yıl Sonu", step=0.25)
                    kat_sayisi = ec3.number_input("Katılımcı Sayısı (N)", step=1)

                # Parse işlemleri
                md, mn, mx, ok = parse_range_input(r1, v1)
                if ok: v1, mn1, mx1 = md, mn, mx
                
                md2, mn2_, mx2_, ok2 = parse_range_input(r2, v2)
                if ok2: v2, mn2, mx2 = md2, mn2_, mx2_

                data = {
                    "tahmin_ppk_faiz": v1,
                    "min_ppk_faiz": mn1,
                    "max_ppk_faiz": mx1,
                    "tahmin_yilsonu_faiz": v2,
                    "min_yilsonu_faiz": mn2,
                    "max_yilsonu_faiz": mx2,
                }
            
            # ENFLASYON FORMU
            else:
                c1, c2, c3 = st.columns(3)
                r1 = c1.text_input("Aylık Enflasyon Aralığı", key="r1")
                v1 = c1.number_input("Aylık Medyan %", step=0.1)
                
                r2 = c2.text_input("Yıllık Enflasyon Aralığı", key="r2")
                v2 = c2.number_input("Yıllık Medyan %", step=0.1)
                
                r3 = c3.text_input("Yıl Sonu Enflasyon Aralığı", key="r3")
                v3 = c3.number_input("Yıl Sonu Medyan %", step=0.1)
                
                with st.expander("Gelişmiş / Min-Max Girişi"):
                    ec1, ec2, ec3 = st.columns(3)
                    mn1 = ec1.number_input("Min Aylık", step=0.1)
                    mx1 = ec1.number_input("Max Aylık", step=0.1)
                    mn2 = ec2.number_input("Min Yıllık", step=0.1)
                    mx2 = ec2.number_input("Max Yıllık", step=0.1)
                    mn3 = ec3.number_input("Min Yıl Sonu", step=0.1)
                    mx3 = ec3.number_input("Max Yıl Sonu", step=0.1)
                    kat_sayisi = st.number_input("Katılımcı Sayısı (N)", step=1)

                md1, mn1_, mx1_, ok1 = parse_range_input(r1, v1)
                if ok1: v1, mn1, mx1 = md1, mn1_, mx1_
                md2, mn2_, mx2_, ok2 = parse_range_input(r2, v2)
                if ok2: v2, mn2, mx2 = md2, mn2_, mx2_
                md3, mn3_, mx3_, ok3 = parse_range_input(r3, v3)
                if ok3: v3, mn3, mx3 = md3, mn3_, mx3_

                data = {
                    "tahmin_aylik_enf": v1, "min_aylik_enf": mn1, "max_aylik_enf": mx1,
                    "tahmin_yillik_enf": v2, "min_yillik_enf": mn2, "max_yillik_enf": mx2,
                    "tahmin_yilsonu_enf": v3, "min_yilsonu_enf": mn3, "max_yilsonu_enf": mx3,
                }

            data["katilimci_sayisi"] = int(kat_sayisi) if kat_sayisi and kat_sayisi > 0 else 0

            if st.form_submit_button("✅ Kaydet"):
                if user:
                    upsert_tahmin(user, donem, cat, tarih, link, data)
                    st.toast("Veri başarıyla kaydedildi!", icon="🎉")
                else:
                    st.error("Lütfen bir kullanıcı seçiniz.")

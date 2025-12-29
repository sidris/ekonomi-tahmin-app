import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import datetime
import requests

# =========================================================
# 0) UI
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
# 1) SECRETS
# =========================================================
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"secrets.toml kontrol: {e}")
    st.stop()

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"

# =========================================================
# 2) CONSTANTS
# =========================================================
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
EVDS_TUFE_SERIES = "TP.FG.J0"  # TÜFE tek seri; formulas=1 (aylık), formulas=3 (yıllık)

BIS_TR_POLICY = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR"

# =========================================================
# 3) HELPERS
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
# 4) EVDS TÜFE (formulas=1/3)
#    Curl çıktına göre:
#      formulas=1 => kolon: TP_FG_J0-1
#      formulas=3 => kolon: TP_FG_J0-3
#    Tarih formatı: "2025-1"
# =========================================================
def _evds_headers(api_key: str) -> dict:
    return {"key": api_key, "User-Agent": "Mozilla/5.0", "Accept": "application/json"}

def _evds_url(series_code: str, start_date: datetime.date, end_date: datetime.date, formulas: int) -> str:
    s = start_date.strftime("%d-%m-%Y")
    e = end_date.strftime("%d-%m-%Y")
    return f"{EVDS_BASE}/series={series_code}&startDate={s}&endDate={e}&type=json&formulas={formulas}"

def _parse_evds_period(tarih_raw: str) -> tuple[str | None, pd.Timestamp | None]:
    # '2025-1' -> Donem='2025-01', Tarih_dt=2025-01-01
    if not isinstance(tarih_raw, str) or "-" not in tarih_raw:
        return None, None
    try:
        y, m = tarih_raw.split("-", 1)
        y = int(y.strip())
        m = int(m.strip())
        donem = f"{y:04d}-{m:02d}"
        dt = pd.Timestamp(year=y, month=m, day=1)
        return donem, dt
    except Exception:
        return None, None

def _evds_fetch_formula(api_key: str, start_date: datetime.date, end_date: datetime.date, formulas: int, out_col: str) -> tuple[pd.DataFrame, str | None]:
    url = _evds_url(EVDS_TUFE_SERIES, start_date, end_date, formulas=formulas)

    try:
        r = requests.get(url, headers=_evds_headers(api_key), timeout=25)
    except Exception as e:
        return pd.DataFrame(), f"EVDS bağlantı hatası: {e}"

    ct = (r.headers.get("Content-Type") or "").lower()
    if "text/html" in ct:
        return pd.DataFrame(), f"EVDS HTML (HTTP {r.status_code}). Url: {url}. İlk500: {(r.text or '')[:500]}"

    if r.status_code >= 400:
        return pd.DataFrame(), f"EVDS HTTP {r.status_code}. Url: {url}. İlk500: {(r.text or '')[:500]}"

    try:
        js = r.json()
    except Exception:
        return pd.DataFrame(), f"EVDS JSON parse edilemedi. Url: {url}. İlk500: {(r.text or '')[:500]}"

    items = js.get("items", [])
    if not items:
        return pd.DataFrame(), f"EVDS boş döndü. Url: {url}"

    df = pd.DataFrame(items)
    if "Tarih" not in df.columns:
        return pd.DataFrame(), f"EVDS 'Tarih' yok. Kolonlar: {list(df.columns)[:30]}"

    expected_val_col = f"TP_FG_J0-{formulas}"
    if expected_val_col not in df.columns:
        return pd.DataFrame(), f"Beklenen kolon yok: {expected_val_col}. Kolonlar: {list(df.columns)[:30]}"

    donem_list, dt_list = [], []
    for t in df["Tarih"].astype(str).tolist():
        donem, dt = _parse_evds_period(t)
        donem_list.append(donem)
        dt_list.append(dt)

    out = pd.DataFrame({
        "Donem": donem_list,
        "Tarih_dt": dt_list,
        out_col: pd.to_numeric(df[expected_val_col], errors="coerce"),
    }).dropna(subset=["Donem", "Tarih_dt"]).sort_values("Tarih_dt").reset_index(drop=True)

    out["Tarih"] = out["Tarih_dt"].dt.strftime("%Y-%m")
    return out[["Tarih", "Donem", "Tarih_dt", out_col]], None

@st.cache_data(ttl=300)
def fetch_evds_tufe(api_key: str, start_date: datetime.date, end_date: datetime.date) -> tuple[pd.DataFrame, str | None]:
    if not api_key:
        return pd.DataFrame(), "EVDS_KEY eksik (secrets.toml)"

    m_df, m_err = _evds_fetch_formula(api_key, start_date, end_date, formulas=1, out_col="TUFE_Aylik")
    if m_err:
        return pd.DataFrame(), m_err

    y_df, y_err = _evds_fetch_formula(api_key, start_date, end_date, formulas=3, out_col="TUFE_Yillik")
    if y_err:
        return pd.DataFrame(), y_err

    out = pd.merge(
        m_df[["Donem", "Tarih_dt", "TUFE_Aylik"]],
        y_df[["Donem", "Tarih_dt", "TUFE_Yillik"]],
        on=["Donem", "Tarih_dt"],
        how="outer",
    ).sort_values("Tarih_dt").reset_index(drop=True)

    out["Tarih"] = out["Tarih_dt"].dt.strftime("%Y-%m")
    return out[["Tarih", "Donem", "TUFE_Aylik", "TUFE_Yillik", "Tarih_dt"]], None

# =========================================================
# 5) BIS Repo/Policy Rate (TR)
# =========================================================
@st.cache_data(ttl=300)
def fetch_bis_repo_tr(start_date: datetime.date, end_date: datetime.date) -> tuple[pd.DataFrame, str | None]:
    try:
        s = start_date.strftime("%Y-%m-%d")
        e = end_date.strftime("%Y-%m-%d")
        url = f"{BIS_TR_POLICY}?format=csv&startPeriod={s}&endPeriod={e}"

        r = requests.get(url, timeout=25)
        if r.status_code >= 400:
            return pd.DataFrame(), f"BIS HTTP {r.status_code}. İlk500: {(r.text or '')[:500]}"

        content = r.content.decode("utf-8", errors="ignore")
        df = pd.read_csv(io.StringIO(content))
        df.columns = [c.upper() for c in df.columns]

        if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
            return pd.DataFrame(), f"BIS kolonları farklı: {list(df.columns)[:30]}"

        out = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        out["TIME_PERIOD"] = pd.to_datetime(out["TIME_PERIOD"], errors="coerce")
        out = out.dropna(subset=["TIME_PERIOD"])

        out["Donem"] = out["TIME_PERIOD"].dt.strftime("%Y-%m")
        out["Tarih"] = out["TIME_PERIOD"].dt.strftime("%Y-%m-%d")
        out["REPO_RATE"] = pd.to_numeric(out["OBS_VALUE"], errors="coerce")
        out = out[["Tarih", "Donem", "REPO_RATE"]].sort_values("Tarih").reset_index(drop=True)

        return out, None
    except Exception as e:
        return pd.DataFrame(), f"BIS Hatası: {e}"

# =========================================================
# 6) AUTH
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
# 7) SIDEBAR
# =========================================================
with st.sidebar:
    st.title("📊 Menü")
    page = st.radio(
        "Git:",
        [
            "Dashboard",
            "📈 Piyasa Verileri (EVDS TÜFE + BIS Repo)",
            "PPK Girişi",
            "Enflasyon Girişi",
            "Katılımcı Yönetimi",
        ],
    )

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
# 8) PAGES
# =========================================================
if page == "Dashboard":
    st.header("Piyasa Analiz Dashboardu")

    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)

    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi", "kategori").execute()
    df_k = pd.DataFrame(res_k.data)

    if df_t.empty or df_k.empty:
        st.info("Veri yok.")
        st.stop()

    df_t = clean_and_sort_data(df_t)
    df_t["tahmin_tarihi"] = pd.to_datetime(df_t["tahmin_tarihi"], errors="coerce")
    df_t = df_t.sort_values(by="tahmin_tarihi")

    df_latest_raw = df_t.drop_duplicates(subset=["kullanici_adi", "donem"], keep="last")
    df_latest = pd.merge(df_latest_raw, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")

    df_latest["gorunen_isim"] = df_latest.apply(
        lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})"
        if pd.notnull(x["anket_kaynagi"]) and x["anket_kaynagi"] != ""
        else x["kullanici_adi"],
        axis=1,
    )
    df_latest["kategori"] = df_latest["kategori"].fillna("Bireysel")
    df_latest["anket_kaynagi"] = df_latest["anket_kaynagi"].fillna("-")
    df_latest["yil"] = df_latest["donem"].apply(lambda x: str(x).split("-")[0] if isinstance(x, str) else "")

    c1, c2, c3 = st.columns(3)
    c1.metric("Toplam Katılımcı", df_latest["kullanici_adi"].nunique())
    c2.metric("Güncel Tahmin Sayısı", len(df_latest))
    last_dt = df_latest["tahmin_tarihi"].max()
    c3.metric("Son Güncelleme", last_dt.strftime("%d.%m.%Y") if pd.notnull(last_dt) else "-")
    st.markdown("---")

    with st.sidebar:
        st.markdown("### 🔍 Filtreler")
        cat_filter = st.multiselect("Kategori", sorted(df_latest["kategori"].unique()), default=sorted(df_latest["kategori"].unique()))
        avail_src = sorted(df_latest[df_latest["kategori"].isin(cat_filter)]["anket_kaynagi"].astype(str).unique())
        src_filter = st.multiselect("Kaynak", avail_src, default=avail_src)
        avail_usr = sorted(df_latest[df_latest["kategori"].isin(cat_filter) & df_latest["anket_kaynagi"].isin(src_filter)]["gorunen_isim"].unique())
        usr_filter = st.multiselect("Katılımcı", avail_usr, default=avail_usr)
        yr_filter = st.multiselect("Yıl", sorted(df_latest["yil"].unique()), default=sorted(df_latest["yil"].unique()))

    target_df = df_latest[
        df_latest["kategori"].isin(cat_filter)
        & df_latest["anket_kaynagi"].isin(src_filter)
        & df_latest["gorunen_isim"].isin(usr_filter)
        & df_latest["yil"].isin(yr_filter)
    ].copy()

    if target_df.empty:
        st.warning("Veri bulunamadı.")
        st.stop()

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(target_df.sort_values("donem_date"), x="donem", y="tahmin_ppk_faiz", color="gorunen_isim", markers=True, title="PPK Beklentileri")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.line(target_df.sort_values("donem_date"), x="donem", y="tahmin_yilsonu_enf", color="gorunen_isim", markers=True, title="Yıl Sonu Enflasyon Beklentileri")
        st.plotly_chart(fig, use_container_width=True)

elif page == "📈 Piyasa Verileri (EVDS TÜFE + BIS Repo)":
    st.header("📈 Gerçekleşen Piyasa Verileri")
    st.info("EVDS: TÜFE Aylık/Yıllık (TP.FG.J0 formulas=1/3). Repo: sadece BIS (WS_CBPOL / D.TR).")

    with st.sidebar:
        st.markdown("### 📅 Tarih Aralığı")
        sd = st.date_input("Başlangıç", datetime.date(2025, 1, 1))
        ed = st.date_input("Bitiş", datetime.date(2025, 12, 31))

        st.markdown("---")
        if EVDS_API_KEY:
            st.caption("EVDS URL örnekleri:")
            st.code(_evds_url(EVDS_TUFE_SERIES, sd, ed, formulas=1))
            st.code(_evds_url(EVDS_TUFE_SERIES, sd, ed, formulas=3))
        st.caption("BIS URL örneği:")
        st.code(f"{BIS_TR_POLICY}?format=csv&startPeriod={sd:%Y-%m-%d}&endPeriod={ed:%Y-%m-%d}")

    # EVDS TÜFE
    st.subheader("EVDS: TÜFE (Aylık & Yıllık)")
    if not EVDS_API_KEY:
        st.error("EVDS_KEY secrets.toml içinde yok.")
    else:
        with st.spinner("EVDS çekiliyor..."):
            df_tufe, err = fetch_evds_tufe(EVDS_API_KEY, sd, ed)

        if err:
            st.error(err)
        elif df_tufe.empty:
            st.warning("EVDS veri boş döndü.")
        else:
            st.dataframe(df_tufe.drop(columns=["Tarih_dt"]), use_container_width=True, height=420)
            st.download_button(
                "📥 EVDS TÜFE Excel",
                to_excel(df_tufe.drop(columns=["Tarih_dt"])),
                "EVDS_TUFE.xlsx",
                type="primary"
            )

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_tufe["Tarih_dt"], y=df_tufe["TUFE_Aylik"], mode="lines+markers", name="TÜFE Aylık"))
            fig.add_trace(go.Scatter(x=df_tufe["Tarih_dt"], y=df_tufe["TUFE_Yillik"], mode="lines+markers", name="TÜFE Yıllık"))
            fig.update_layout(title="EVDS TÜFE (TP.FG.J0) - formulas 1/3", xaxis_title="Tarih", yaxis_title="Değer")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # BIS Repo
    st.subheader("BIS: Repo/Policy Rate (TR)")
    with st.spinner("BIS çekiliyor..."):
        df_repo, err2 = fetch_bis_repo_tr(sd, ed)

    if err2:
        st.error(err2)
    elif df_repo.empty:
        st.warning("BIS veri boş döndü.")
    else:
        st.dataframe(df_repo, use_container_width=True, height=420)
        st.download_button("📥 BIS Repo Excel", to_excel(df_repo), "BIS_REPO_TR.xlsx", type="primary")
        fig2 = px.line(df_repo, x="Tarih", y="REPO_RATE", markers=True, title="TR Repo/Policy Rate (BIS WS_CBPOL)")
        st.plotly_chart(fig2, use_container_width=True)

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
                        st.toast("Eklendi")
                    except Exception:
                        st.error("Ekleme hatası")

    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        ks = st.selectbox("Silinecek Kişi", df["ad_soyad"].unique())
        if st.button("🚫 Kişiyi ve Tüm Verilerini Sil"):
            supabase.table(TABLE_TAHMIN).delete().eq("kullanici_adi", ks).execute()
            supabase.table(TABLE_KATILIMCI).delete().eq("ad_soyad", ks).execute()
            st.rerun()

elif page in ["PPK Girişi", "Enflasyon Girişi"]:
    st.header(f"➕ {page}")
    with st.container():
        with st.form("entry_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                user, cat, disp = get_participant_selection()
            with c2:
                donem = st.selectbox(
                    "Dönem",
                    tum_donemler,
                    index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0
                )
            with c3:
                tarih = st.date_input("Tarih", datetime.date.today())

            link = st.text_input("Link (Opsiyonel)")
            st.markdown("---")
            data = {}
            kat_sayisi = 0

            if page == "PPK Girişi":
                c1, c2 = st.columns(2)
                r1 = c1.text_input("Aralık (42-45)", key="r1")
                v1 = c1.number_input("Medyan %", step=0.25)
                r2 = c2.text_input("Aralık YS", key="r2")
                v2 = c2.number_input("YS Medyan %", step=0.25)

                with st.expander("Detaylar"):
                    ec1, ec2, ec3 = st.columns(3)
                    mn1 = ec1.number_input("Min", step=0.25)
                    mx1 = ec1.number_input("Max", step=0.25)
                    mn2 = ec2.number_input("Min YS", step=0.25)
                    mx2 = ec2.number_input("Max YS", step=0.25)
                    kat_sayisi = ec3.number_input("N", step=1)

                md, mn, mx, ok = parse_range_input(r1, v1)
                if ok:
                    v1, mn1, mx1 = md, mn, mx
                md2, mn2_, mx2_, ok2 = parse_range_input(r2, v2)
                if ok2:
                    v2, mn2, mx2 = md2, mn2_, mx2_

                data = {
                    "tahmin_ppk_faiz": v1,
                    "min_ppk_faiz": mn1,
                    "max_ppk_faiz": mx1,
                    "tahmin_yilsonu_faiz": v2,
                    "min_yilsonu_faiz": mn2,
                    "max_yilsonu_faiz": mx2,
                }

            else:
                c1, c2, c3 = st.columns(3)
                r1 = c1.text_input("Aralık Ay", key="r1")
                v1 = c1.number_input("Ay Medyan", step=0.1)
                r2 = c2.text_input("Aralık Yıl", key="r2")
                v2 = c2.number_input("Yıl Medyan", step=0.1)
                r3 = c3.text_input("Aralık YS", key="r3")
                v3 = c3.number_input("YS Medyan", step=0.1)

                with st.expander("Detaylar"):
                    ec1, ec2, ec3 = st.columns(3)
                    mn1 = ec1.number_input("Min Ay", step=0.1)
                    mx1 = ec1.number_input("Max Ay", step=0.1)
                    mn2 = ec2.number_input("Min Yıl", step=0.1)
                    mx2 = ec2.number_input("Max Yıl", step=0.1)
                    mn3 = ec3.number_input("Min YS", step=0.1)
                    mx3 = ec3.number_input("Max YS", step=0.1)
                    kat_sayisi = st.number_input("N", step=1)

                md1, mn1_, mx1_, ok1 = parse_range_input(r1, v1)
                if ok1:
                    v1, mn1, mx1 = md1, mn1_, mx1_
                md2, mn2_, mx2_, ok2 = parse_range_input(r2, v2)
                if ok2:
                    v2, mn2, mx2 = md2, mn2_, mx2_
                md3, mn3_, mx3_, ok3 = parse_range_input(r3, v3)
                if ok3:
                    v3, mn3, mx3 = md3, mn3_, mx3_

                data = {
                    "tahmin_aylik_enf": v1,
                    "min_aylik_enf": mn1,
                    "max_aylik_enf": mx1,
                    "tahmin_yillik_enf": v2,
                    "min_yillik_enf": mn2,
                    "max_yillik_enf": mx2,
                    "tahmin_yilsonu_enf": v3,
                    "min_yilsonu_enf": mn3,
                    "max_yilsonu_enf": mx3,
                }

            data["katilimci_sayisi"] = int(kat_sayisi) if kat_sayisi and kat_sayisi > 0 else 0

            if st.form_submit_button("✅ Kaydet"):
                if user:
                    upsert_tahmin(user, donem, cat, tarih, link, data)
                    st.toast("Kaydedildi!", icon="🎉")
                else:
                    st.error("Kullanıcı seçiniz.")

import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import datetime
import requests

# --- OPSİYONEL KÜTÜPHANE ---
try:
    from docx import Document
except ImportError:
    pass

# =========================================================
# 1) AYARLAR & CSS
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
.stMetric { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 15px; border-radius: 8px; }
div[data-testid="stExpander"] { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; }
h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', sans-serif; }
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 2) BAĞLANTILAR
# =========================================================
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Bağlantı Hatası: {e}")
    st.stop()

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
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
    """İsim eşleşmesi için: boşlukları sil, baş harfleri büyüt."""
    if pd.isnull(name): return ""
    return str(name).strip().title()

def clean_and_sort_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df

    # Sayısal dönüşümler
    cols = [c for c in df.columns if "tahmin" in c or "min" in c or "max" in c or "sayisi" in c]
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Tarih dönüşümleri
    if "donem" in df.columns:
        df["donem_date"] = pd.to_datetime(df["donem"], format="%Y-%m", errors="coerce")
        df["yil"] = df["donem"].apply(lambda x: str(x).split("-")[0] if pd.notnull(x) else "")
        df = df.sort_values(by="donem_date")

    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"], errors="coerce")

    # Normalize edilmiş isim sütunu (Merge için kritik)
    if "kullanici_adi" in df.columns:
        df["kullanici_adi_norm"] = df["kullanici_adi"].apply(normalize_name)

    return df

def upsert_tahmin(user, period, category, forecast_date, link, data_dict):
    date_str = forecast_date.strftime("%Y-%m-%d")
    check_res = supabase.table(TABLE_TAHMIN).select("id").eq("kullanici_adi", user).eq("donem", period).eq("tahmin_tarihi", date_str).execute()

    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    clean_data.update({
        "kullanici_adi": user, "donem": period, "kategori": category,
        "tahmin_tarihi": date_str, "kaynak_link": link or None
    })

    if check_res.data:
        rid = check_res.data[0]["id"]
        supabase.table(TABLE_TAHMIN).update(clean_data).eq("id", rid).execute()
    else:
        supabase.table(TABLE_TAHMIN).insert(clean_data).execute()

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    return output.getvalue()

# =========================================================
# 4) VERİ ÇEKME
# =========================================================
@st.cache_data(ttl=600)
def fetch_evds_tufe(api_key, s_date, e_date):
    if not api_key: return pd.DataFrame(), "API Key Yok"
    try:
        url_m = f"{EVDS_BASE}/series={EVDS_TUFE_SERIES}&startDate={s_date.strftime('%d-%m-%Y')}&endDate={e_date.strftime('%d-%m-%Y')}&type=json&formulas=1"
        r = requests.get(url_m, headers={"key": api_key}, timeout=20)
        if r.status_code!=200: return pd.DataFrame(), "Hata"
        items = r.json().get("items", [])
        if not items: return pd.DataFrame(), "Veri Yok"
        df = pd.DataFrame(items)
        df["Tarih_dt"] = pd.to_datetime(df["Tarih"], dayfirst=True, errors="coerce")
        df = df.dropna(subset=["Tarih_dt"]).sort_values("Tarih_dt")
        col = [c for c in df.columns if c not in ["Tarih","UNIXTIME","Tarih_dt"]][0]
        return df[["Tarih", col]].rename(columns={col: "Aylik_Enflasyon"}), None
    except Exception as e: return pd.DataFrame(), str(e)

@st.cache_data(ttl=600)
def fetch_bis_rate(s_date, e_date):
    try:
        url = f"https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={s_date}&endPeriod={e_date}"
        df = pd.read_csv(url)
        df.columns = [c.upper() for c in df.columns]
        return df[["TIME_PERIOD", "OBS_VALUE"]].rename(columns={"TIME_PERIOD":"Tarih", "OBS_VALUE":"Faiz"}), None
    except: return pd.DataFrame(), "Hata"

# =========================================================
# 5) AUTH
# =========================================================
if "giris_yapildi" not in st.session_state: st.session_state["giris_yapildi"] = False
if not st.session_state["giris_yapildi"]:
    _, c2, _ = st.columns([1,2,1])
    with c2:
        if st.button("Giriş Yap (Şifre: 1234)", type="primary") or SITE_SIFRESI == "": # Geçici kolay giriş
             st.session_state["giris_yapildi"] = True
             st.rerun()
        pw = st.text_input("Şifre", type="password")
        if pw == SITE_SIFRESI:
            st.session_state["giris_yapildi"] = True
            st.rerun()
    st.stop()

# =========================================================
# 6) ANA UYGULAMA
# =========================================================
with st.sidebar:
    st.title("Ekonomi Terminali")
    page = st.radio("Menü", ["Dashboard", "Piyasa Verileri", "Veri Girişi", "Katılımcı Yönetimi"])

if page == "Dashboard":
    st.title("📊 Piyasa Beklenti Analizi")

    # 1. VERİ ÇEKME
    df_t = pd.DataFrame(supabase.table(TABLE_TAHMIN).select("*").execute().data)
    df_k = pd.DataFrame(supabase.table(TABLE_KATILIMCI).select("*").execute().data)

    if df_t.empty:
        st.warning("Henüz veri yok.")
        st.stop()

    # 2. TEMİZLİK & MERGE (KURUMSAL SORUNU ÇÖZÜMÜ)
    df_t = clean_and_sort_data(df_t)
    
    if not df_k.empty:
        # İsimleri normalize et (Boşlukları al, baş harfleri büyüt)
        df_k["ad_soyad_norm"] = df_k["ad_soyad"].apply(normalize_name)
        
        # Merge işlemini normalize edilmiş sütunlar üzerinden yap
        df_merged = pd.merge(df_t, df_k, left_on="kullanici_adi_norm", right_on="ad_soyad_norm", how="left", suffixes=("", "_k"))
        
        # Kategori bilgisini al (Eğer boşsa 'Bireysel' yap)
        # Önemli: df_k'daki kategori sütunu gelmeli
        if "kategori_k" in df_merged.columns:
            df_merged["kategori"] = df_merged["kategori_k"].fillna("Bireysel")
        elif "kategori" not in df_merged.columns: # df_k'da kategori yoksa
             df_merged["kategori"] = "Bireysel"
             
        if "anket_kaynagi" not in df_merged.columns and "anket_kaynagi_k" in df_merged.columns:
             df_merged["anket_kaynagi"] = df_merged["anket_kaynagi_k"]
             
    else:
        df_merged = df_t.copy()
        df_merged["kategori"] = "Bireysel"

    # Görinen İsim
    df_merged["gorunen_isim"] = df_merged.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x.get('anket_kaynagi')) else x['kullanici_adi'], axis=1)

    # En güncel tahminler (Son durumu görmek için)
    df_latest = df_merged.sort_values("tahmin_tarihi").drop_duplicates(subset=["kullanici_adi", "donem"], keep="last")

    # --- SIDEBAR FİLTRELERİ ---
    with st.sidebar:
        st.markdown("---")
        st.markdown("### ⚙️ Analiz Ayarları")
        
        param = st.selectbox("Analiz Değişkeni", 
                             ["tahmin_ppk_faiz", "tahmin_yilsonu_faiz", "tahmin_aylik_enf", "tahmin_yilsonu_enf"],
                             format_func=lambda x: x.replace("tahmin_", "").upper().replace("_", " "))
        
        # 1. Yıl ve Dönem Filtresi
        all_years = sorted(df_latest["yil"].unique())
        sel_years = st.multiselect("Yıllar", all_years, default=all_years)
        
        subset_y = df_latest[df_latest["yil"].isin(sel_years)]
        all_periods = sorted(subset_y["donem"].unique())
        sel_periods = st.multiselect("Dönemler", all_periods, default=all_periods)
        
        # 2. Kategori Filtresi (Kurumsal Burada Olmalı)
        subset_p = subset_y[subset_y["donem"].isin(sel_periods)]
        all_cats = sorted(subset_p["kategori"].dropna().unique())
        sel_cats = st.multiselect("Kategori", all_cats, default=all_cats)
        
        # 3. Katılımcı Filtresi
        subset_c = subset_p[subset_p["kategori"].isin(sel_cats)]
        all_users = sorted(subset_c["gorunen_isim"].unique())
        sel_users = st.multiselect("Katılımcılar", all_users, default=all_users)
        
        # Filtrelenmiş Ana Veri Seti (Tarihsel veriler dahil)
        # Sadece son veri değil, tüm geçmişi alıyoruz ki değişim grafiği çalışsın
        target_df = df_merged[
            (df_merged["donem"].isin(sel_periods)) & 
            (df_merged["kategori"].isin(sel_cats)) & 
            (df_merged["gorunen_isim"].isin(sel_users))
        ].copy()

    if target_df.empty:
        st.info("Seçilen filtrelerde veri yok.")
        st.stop()

    # --- GRAFİK 1: HEDEF DÖNEME GÖRE ISI HARİTASI ---
    # Satır: Katılımcı, Sütun: Hangi döneme tahmin yapıyor?
    st.subheader(f"🔥 {param} - Beklenti Isı Haritası")
    try:
        # Sadece en son tahminleri kullan
        latest_view = target_df.sort_values("tahmin_tarihi").drop_duplicates(subset=["kullanici_adi", "donem"], keep="last")
        pivot_target = latest_view.pivot_table(index="gorunen_isim", columns="donem", values=param)
        
        fig1 = px.imshow(pivot_target, aspect="auto", text_auto=".2f", color_continuous_scale="RdBu_r",
                         labels=dict(x="Hedeflenen Dönem", y="Katılımcı"))
        st.plotly_chart(fig1, use_container_width=True)
    except: st.write("Veri yetersiz.")

    # --- GRAFİK 2: ZAMAN İÇİNDE DEĞİŞİM (İSTEDİĞİNİZ ÖZELLİK) ---
    st.markdown("---")
    st.subheader("⏳ Tahminlerin Zaman İçindeki Değişimi (History)")
    st.info("Bu grafik, katılımcıların tahminlerini hangi tarihlerde nasıl değiştirdiğini gösterir.")
    
    # Kullanıcı buradan "Hangi Hedef Dönemi" incelemek istediğini seçsin
    target_period_select = st.selectbox("İncelenecek Hedef Dönemi Seçin:", sel_periods)
    
    # Sadece o hedef döneme ait verileri al
    history_df = target_df[target_df["donem"] == target_period_select].sort_values("tahmin_tarihi")
    
    if not history_df.empty:
        # Pivot: Satır=Katılımcı, Sütun=Tahmin Giriş Tarihi, Değer=Tahmin
        # Not: Tarihler çok dağınık olabilir, bu yüzden 'tahmin_tarihi'ni string yapıyoruz
        history_df["Tarih_Str"] = history_df["tahmin_tarihi"].dt.strftime("%Y-%m-%d")
        
        pivot_history = history_df.pivot_table(index="gorunen_isim", columns="Tarih_Str", values=param)
        
        # NaN olan yerleri (tahmin değiştirmediği günler) gösterme veya önceki değerle doldurma stratejisi
        # Isı haritasında NaN'lar boş görünür, bu değişim noktalarını vurgular.
        
        fig_hist = px.imshow(
            pivot_history, 
            aspect="auto", 
            text_auto=".2f", 
            color_continuous_scale="Viridis",
            title=f"{target_period_select} Dönemi İçin Tahminlerin Evrimi",
            labels=dict(x="Tahmin Girilen Tarih", y="Katılımcı", color="Değer")
        )
        st.plotly_chart(fig_hist, use_container_width=True)
        
        # Alternatif: Çizgi Grafik (Daha net okunabilir)
        with st.expander("Alternatif: Çizgi Grafik Görünümü"):
            fig_line = px.line(history_df, x="tahmin_tarihi", y=param, color="gorunen_isim", markers=True, 
                               title="Tahmin Değişim Çizgisi")
            st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning(f"{target_period_select} dönemi için geçmiş veri bulunamadı.")

    # --- GRAFİK 3: SON DURUM TABLOSU ---
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📦 Tahmin Dağılımı")
        fig_box = px.box(latest_view, x="donem", y=param, points="all", color="kategori")
        st.plotly_chart(fig_box, use_container_width=True)
        
    with c2:
        st.subheader("🏆 Sıralama")
        fig_bar = px.bar(latest_view[latest_view["donem"]==target_period_select].sort_values(param), 
                         x="gorunen_isim", y=param, color="kategori", text_auto=True)
        st.plotly_chart(fig_bar, use_container_width=True)


elif page == "Piyasa Verileri":
    st.title("📈 Piyasa Verileri")
    d1 = st.date_input("Başlangıç", datetime.date(2025,1,1))
    d2 = st.date_input("Bitiş", datetime.date(2025,12,31))
    
    if EVDS_API_KEY:
        df_evds, _ = fetch_evds_tufe(EVDS_API_KEY, d1, d2)
        if not df_evds.empty:
            st.write("TÜFE Enflasyon")
            st.line_chart(df_evds.set_index("Tarih"))
            
    df_bis, _ = fetch_bis_rate(d1, d2)
    if not df_bis.empty:
        st.write("Politika Faizi")
        st.line_chart(df_bis.set_index("Tarih"))

elif page == "Veri Girişi":
    st.header("Veri Girişi")
    # Katılımcı seçimi
    users = pd.DataFrame(supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute().data)
    if users.empty: st.stop()
    
    users["disp"] = users.apply(lambda x: f"{x['ad_soyad']} ({x.get('anket_kaynagi','')})", axis=1)
    
    with st.form("veri_giris"):
        who = st.selectbox("Kim?", users["disp"].unique())
        # Seçilen kişinin gerçek verilerini al
        sel_row = users[users["disp"]==who].iloc[0]
        real_name = sel_row["ad_soyad"]
        real_cat = sel_row["kategori"] # Kategoriyi buradan alıp tahmin tablosuna yazacağız
        
        col1, col2 = st.columns(2)
        donem = col1.selectbox("Dönem", tum_donemler)
        tarih = col2.date_input("Tarih", datetime.date.today())
        
        c1, c2, c3 = st.columns(3)
        ppk = c1.number_input("PPK", step=0.25)
        enf_ay = c2.number_input("Ay Enf", step=0.1)
        enf_yil = c3.number_input("Yıl Enf", step=0.1)
        
        if st.form_submit_button("Kaydet"):
            upsert_tahmin(real_name, donem, real_cat, tarih, "", {
                "tahmin_ppk_faiz": ppk, "tahmin_aylik_enf": enf_ay, "tahmin_yilsonu_enf": enf_yil
            })
            st.success("Kaydedildi")

elif page == "Katılımcı Yönetimi":
    st.header("Katılımcı Yönetimi")
    with st.form("add_user"):
        ad = st.text_input("Ad Soyad / Kurum")
        cat = st.radio("Tip", ["Bireysel", "Kurumsal"])
        src = st.text_input("Kaynak")
        if st.form_submit_button("Ekle"):
            supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": normalize_name(ad), "kategori": cat, "anket_kaynagi": src}).execute()
            st.success("Eklendi")
    
    st.dataframe(pd.DataFrame(supabase.table(TABLE_KATILIMCI).select("*").execute().data))

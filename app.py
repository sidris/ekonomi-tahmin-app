import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import datetime
import requests

# =========================================================
# 1) AYARLAR
# =========================================================
st.set_page_config(page_title="Finansal Tahmin Terminali", layout="wide", page_icon="📊")

# CSS: Kartlar ve metrikler için
st.markdown("""
<style>
.stMetric { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; }
div[data-testid="stExpander"] { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2) BAĞLANTILAR (SUPABASE + API'LER)
# =========================================================
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    EVDS_API_KEY = st.secrets.get("EVDS_KEY", None)
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Ayar Hatası: {e}")
    st.stop()

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"
EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"

# =========================================================
# 3) FONKSİYONLAR (VERİ ÇEKME VE İŞLEME)
# =========================================================
def normalize_name(name):
    """İsim eşleşmesi için standartlaştırma"""
    return str(name).strip().title() if pd.notnull(name) else ""

def clean_data(df):
    if df.empty: return df
    # Sayısal dönüşüm
    cols = [c for c in df.columns if "tahmin" in c or "min" in c or "max" in c]
    for c in cols: df[c] = pd.to_numeric(df[c], errors="coerce")
    
    # Tarih dönüşüm
    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"], errors="coerce")
        df["tahmin_tarihi_str"] = df["tahmin_tarihi"].dt.strftime("%d-%m-%Y") # Grafik için string tarih
        
    if "donem" in df.columns:
        df["yil"] = df["donem"].apply(lambda x: str(x).split("-")[0])
        
    if "kullanici_adi" in df.columns:
        df["kullanici_adi_norm"] = df["kullanici_adi"].apply(normalize_name)
        
    return df

# --- YENİ EKLENEN: PIYASA VERİLERİ ÇEKME ---
@st.cache_data(ttl=600)
def fetch_market_data(start_date, end_date, api_key):
    """EVDS (TÜFE) ve BIS (Politika Faizi) verilerini çeker"""
    s_str = start_date.strftime("%d-%m-%Y")
    e_str = end_date.strftime("%d-%m-%Y")
    s_bis = start_date.strftime("%Y-%m-%d")
    e_bis = end_date.strftime("%Y-%m-%d")
    
    df_tufe, df_repo = pd.DataFrame(), pd.DataFrame()
    
    # 1. EVDS (TP.FG.J0 -> TÜFE)
    if api_key:
        try:
            # Formulas=1 (Aylık), Formulas=2 (Yıllık)
            url = f"{EVDS_BASE}/series=TP.FG.J0&startDate={s_str}&endDate={e_str}&type=json&formulas=1"
            r = requests.get(url, headers={"key": api_key}, timeout=10)
            if r.status_code == 200:
                data = r.json().get("items", [])
                if data:
                    df = pd.DataFrame(data)
                    df["Tarih"] = pd.to_datetime(df["Tarih"], dayfirst=True)
                    # Kolon adını bul (TP_FG_J0...)
                    val_col = [c for c in df.columns if c not in ["Tarih", "UNIXTIME"]][0]
                    df_tufe = df[["Tarih", val_col]].rename(columns={val_col: "Aylık Enflasyon (%)"})
        except Exception as e:
            st.warning(f"EVDS Hatası: {e}")

    # 2. BIS (Politika Faizi)
    try:
        url_bis = f"https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={s_bis}&endPeriod={e_bis}"
        df = pd.read_csv(url_bis)
        df.columns = [c.upper() for c in df.columns] # TIME_PERIOD, OBS_VALUE
        df["Tarih"] = pd.to_datetime(df["TIME_PERIOD"])
        df_repo = df[["Tarih", "OBS_VALUE"]].rename(columns={"OBS_VALUE": "Politika Faizi (%)"})
    except Exception as e:
        st.warning(f"BIS Hatası: {e}")
        
    return df_tufe, df_repo

# =========================================================
# 4) LOGIN
# =========================================================
if "auth" not in st.session_state: st.session_state["auth"] = False
if not st.session_state["auth"]:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        pw = st.text_input("Şifre", type="password")
        if st.button("Giriş") and pw == SITE_SIFRESI:
            st.session_state["auth"] = True
            st.rerun()
    st.stop()

# =========================================================
# 5) ANA UYGULAMA
# =========================================================
with st.sidebar:
    st.title("Menü")
    page = st.radio("Sayfalar", ["Dashboard", "Piyasa Verileri", "Veri Girişi", "Yönetim"])

if page == "Dashboard":
    st.header("🔍 Piyasa Beklenti Analizi")

    # 1. Veri Çekme
    df_t = pd.DataFrame(supabase.table(TABLE_TAHMIN).select("*").execute().data)
    df_k = pd.DataFrame(supabase.table(TABLE_KATILIMCI).select("*").execute().data)

    if df_t.empty:
        st.warning("Veri bulunamadı.")
        st.stop()

    # 2. Temizleme ve Merge (Eski Sağlam Yöntem)
    df_t = clean_data(df_t)
    
    if not df_k.empty:
        df_k["ad_soyad_norm"] = df_k["ad_soyad"].apply(normalize_name)
        # Kurumsal kategorisini kaybetmemek için left join
        df_merged = pd.merge(df_t, df_k, left_on="kullanici_adi_norm", right_on="ad_soyad_norm", how="left", suffixes=("", "_k"))
        
        # Kategori ve Kaynak bilgisini birleştir
        if "kategori_k" in df_merged.columns:
            df_merged["kategori"] = df_merged["kategori_k"].fillna("Bireysel")
        else:
            df_merged["kategori"] = "Bireysel"
            
        if "anket_kaynagi_k" in df_merged.columns:
            df_merged["anket_kaynagi"] = df_merged["anket_kaynagi_k"].fillna("-")
    else:
        df_merged = df_t.copy()
        df_merged["kategori"] = "Bireysel"
        df_merged["anket_kaynagi"] = "-"

    # Görinen İsim (Kaynaklı)
    df_merged["gorunen_isim"] = df_merged.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] not in ["-", None] else x['kullanici_adi'], axis=1)

    # 3. Filtreler (Sidebar)
    with st.sidebar:
        st.markdown("---")
        st.subheader("Filtreler")
        
        param = st.selectbox("Analiz Parametresi", 
            ["tahmin_ppk_faiz", "tahmin_yilsonu_faiz", "tahmin_aylik_enf", "tahmin_yilsonu_enf"],
            format_func=lambda x: x.replace("tahmin_", "").upper().replace("_", " "))
        
        # Yıl ve Dönem
        all_years = sorted(df_merged["yil"].unique())
        sel_years = st.multiselect("Yıl", all_years, default=all_years)
        
        df_y = df_merged[df_merged["yil"].isin(sel_years)]
        all_periods = sorted(df_y["donem"].unique())
        sel_periods = st.multiselect("Dönem", all_periods, default=all_periods)
        
        # Kategori ve Kaynak
        df_p = df_y[df_y["donem"].isin(sel_periods)]
        all_cats = sorted(df_p["kategori"].dropna().unique())
        sel_cats = st.multiselect("Kategori", all_cats, default=all_cats)
        
        # Katılımcı
        df_c = df_p[df_p["kategori"].isin(sel_cats)]
        all_users = sorted(df_c["gorunen_isim"].unique())
        sel_users = st.multiselect("Katılımcılar", all_users, default=all_users)
        
        target_df = df_c[df_c["gorunen_isim"].isin(sel_users)].copy()

    if target_df.empty:
        st.info("Filtreye uygun veri yok.")
        st.stop()

    # --- KPI ---
    latest_df = target_df.sort_values("tahmin_tarihi").drop_duplicates(subset=["kullanici_adi", "donem"], keep="last")
    c1, c2, c3 = st.columns(3)
    c1.metric("Tahmin Sayısı", len(latest_df))
    c2.metric("Katılımcı Sayısı", latest_df["kullanici_adi"].nunique())
    med_val = latest_df[param].median()
    c3.metric(f"Medyan {param.split('_')[1].upper()}", f"{med_val:.2f}" if pd.notnull(med_val) else "-")

    # --- GRAFİK 1: ISI HARİTASI (Kişi vs Dönem) ---
    st.subheader(f"🔥 {param} Isı Haritası (Dönem Bazlı)")
    try:
        pivot = latest_df.pivot_table(index="gorunen_isim", columns="donem", values=param)
        fig = px.imshow(pivot, text_auto=".2f", aspect="auto", color_continuous_scale="RdBu_r")
        st.plotly_chart(fig, use_container_width=True)
    except: st.write("Yetersiz veri.")

    # --- GRAFİK 2: TARİHSEL DEĞİŞİM (SENİN İSTEDİĞİN GRAFİK) ---
    st.markdown("---")
    st.subheader(f"📅 Zaman İçindeki Değişim (History)")
    st.info("Bir hedef dönem seçin ve katılımcıların tahminlerini hangi tarihlerde değiştirdiğini görün.")
    
    target_period = st.selectbox("İncelenecek Dönemi Seç:", sel_periods, key="hist_per")
    
    hist_data = target_df[target_df["donem"] == target_period].sort_values("tahmin_tarihi")
    
    if not hist_data.empty:
        # Pivot: Satır=Kişi, Sütun=Tahmin Tarihi
        # Tarihi string yapıyoruz ki grafik düzgün çıksın
        pivot_hist = hist_data.pivot_table(index="gorunen_isim", columns="tahmin_tarihi_str", values=param)
        
        fig_hist = px.imshow(pivot_hist, text_auto=".2f", aspect="auto", color_continuous_scale="Viridis",
                             title=f"{target_period} Tahminlerinin Giriş Tarihine Göre Değişimi")
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.write("Bu dönem için geçmiş verisi yok.")

    # --- GRAFİK 3: KUTU GRAFİĞİ ---
    st.markdown("---")
    fig_box = px.box(latest_df, x="donem", y=param, color="donem", points="all", title="Tahmin Dağılımı")
    st.plotly_chart(fig_box, use_container_width=True)


elif page == "Piyasa Verileri":
    st.header("📈 Gerçekleşen Piyasa Verileri")
    st.info("Bu sayfa EVDS ve BIS verilerini canlı çeker.")
    
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Başlangıç", datetime.date(2025, 1, 1))
    d2 = c2.date_input("Bitiş", datetime.date(2025, 12, 31))
    
    # Butona basınca çeksin ki sayfa her açıldığında yük olmasın
    if st.button("Verileri Getir"):
        with st.spinner("TCMB ve BIS verileri çekiliyor..."):
            df_tufe, df_repo = fetch_market_data(d1, d2, EVDS_API_KEY)
            
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("TÜFE (Aylık %)")
            if not df_tufe.empty:
                st.dataframe(df_tufe, hide_index=True)
                st.line_chart(df_tufe.set_index("Tarih"))
            else:
                st.write("Veri yok veya API Key eksik.")
                
        with col2:
            st.subheader("Politika Faizi (%)")
            if not df_repo.empty:
                st.dataframe(df_repo, hide_index=True)
                st.line_chart(df_repo.set_index("Tarih"))
            else:
                st.write("BIS verisi alınamadı.")


elif page == "Veri Girişi":
    st.header("📝 Tahmin Girişi")
    # Kullanıcı Listesi
    users = pd.DataFrame(supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute().data)
    if users.empty: st.stop()
    
    users["disp"] = users.apply(lambda x: f"{x['ad_soyad']} ({x.get('anket_kaynagi','')})", axis=1)
    
    with st.form("entry"):
        who = st.selectbox("Katılımcı", users["disp"].unique())
        # Gerçek verileri bul
        real_row = users[users["disp"]==who].iloc[0]
        real_u = real_row["ad_soyad"]
        real_c = real_row.get("kategori", "Bireysel")
        
        c1, c2 = st.columns(2)
        donem = c1.selectbox("Dönem", ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-12"])
        tarih = c2.date_input("Giriş Tarihi", datetime.date.today())
        
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        ppk = c1.number_input("PPK Faiz %", step=0.25)
        ay_enf = c2.number_input("Aylık Enf %", step=0.1)
        yil_enf = c3.number_input("Yıl Sonu Enf %", step=0.1)
        
        if st.form_submit_button("Kaydet"):
            data = {"tahmin_ppk_faiz": ppk, "tahmin_aylik_enf": ay_enf, "tahmin_yilsonu_enf": yil_enf}
            # Basit Upsert Logic
            try:
                # Önce sil (basit upsert taktiği)
                supabase.table(TABLE_TAHMIN).delete().eq("kullanici_adi", real_u).eq("donem", donem).eq("tahmin_tarihi", str(tarih)).execute()
                # Sonra ekle
                data.update({"kullanici_adi": real_u, "donem": donem, "tahmin_tarihi": str(tarih), "kategori": real_c})
                supabase.table(TABLE_TAHMIN).insert(data).execute()
                st.success("Kaydedildi!")
            except Exception as e:
                st.error(f"Hata: {e}")


elif page == "Yönetim":
    st.header("👥 Katılımcı Yönetimi")
    with st.form("add"):
        ad = st.text_input("Ad Soyad")
        cat = st.radio("Tip", ["Bireysel", "Kurumsal"])
        src = st.text_input("Kaynak")
        if st.form_submit_button("Ekle") and ad:
            supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": normalize_name(ad), "kategori": cat, "anket_kaynagi": src}).execute()
            st.success("Eklendi")
            
    st.dataframe(pd.DataFrame(supabase.table(TABLE_KATILIMCI).select("*").execute().data))

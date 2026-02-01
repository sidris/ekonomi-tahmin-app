import streamlit as st
from supabase import create_client, Client
import pandas as pd
import requests
import io

TABLE_TAHMIN = "beklentiler_takip"
TABLE_KATILIMCI = "katilimcilar"

EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
EVDS_TUFE_SERIES = "TP.FG.J0"

def _get_secrets():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    app_password = st.secrets["APP_PASSWORD"]
    evds_key = st.secrets.get("EVDS_KEY", None)
    return url, key, app_password, evds_key

@st.cache_resource
def get_supabase() -> Client:
    url, key, _, _ = _get_secrets()
    return create_client(url, key)

def get_app_password() -> str:
    _, _, app_password, _ = _get_secrets()
    return app_password

def get_evds_key():
    _, _, _, evds_key = _get_secrets()
    return evds_key

def check_login() -> bool:
    if "giris_yapildi" not in st.session_state:
        st.session_state["giris_yapildi"] = False
    return st.session_state["giris_yapildi"]

def clean_numeric_and_dates(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    numeric_cols = [
        "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz",
        "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz",
        "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf",
        "tahmin_yillik_enf", "min_yillik_enf", "max_yillik_enf",
        "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf",
        "katilimci_sayisi", "versiyon"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "tahmin_tarihi" in df.columns:
        df["tahmin_tarihi"] = pd.to_datetime(df["tahmin_tarihi"], errors="coerce")

    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    return df

@st.cache_data(ttl=600)
def get_all_forecasts(limit: int = 5000) -> pd.DataFrame:
    sb = get_supabase()
    res = sb.table(TABLE_TAHMIN).select("*").order("created_at", desc=True).limit(limit).execute()
    return clean_numeric_and_dates(pd.DataFrame(res.data))

def get_participants() -> pd.DataFrame:
    sb = get_supabase()
    res = sb.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    return pd.DataFrame(res.data)

def _next_version(user: str, hedef_donemi: str, tahmin_tarihi: str) -> int:
    """Aynı gün aynı hedef dönem için sıradaki versiyon."""
    sb = get_supabase()
    res = (
        sb.table(TABLE_TAHMIN)
        .select("versiyon")
        .eq("kullanici_adi", user)
        .eq("hedef_donemi", hedef_donemi)
        .eq("tahmin_tarihi", tahmin_tarihi)
        .order("versiyon", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        v = res.data[0].get("versiyon")
        return int(v) + 1 if v is not None else 2
    return 1

def insert_tahmin(
    user: str,
    hedef_donemi: str,
    category: str,
    forecast_date,   # date/datetime/str
    link: str | None,
    data_dict: dict
):
    sb = get_supabase()

    date_obj = pd.to_datetime(forecast_date, errors="coerce")
    if pd.isna(date_obj):
        return False, "Tahmin tarihi okunamadı."

    tahmin_tarihi = date_obj.strftime("%Y-%m-%d")
    anket_donemi = date_obj.strftime("%Y-%m")

    clean_inputs = {k: v for k, v in data_dict.items() if v not in (None, "")}

    versiyon = _next_version(user, hedef_donemi, tahmin_tarihi)

    payload = {
        "kullanici_adi": user,
        "kategori": category,
        "anket_donemi": anket_donemi,
        "hedef_donemi": hedef_donemi,
        "tahmin_tarihi": tahmin_tarihi,
        "versiyon": versiyon,
        **clean_inputs,
    }
    if link:
        payload["kaynak_link"] = link

    try:
        sb.table(TABLE_TAHMIN).insert(payload).execute()
        return True, f"Kayıt başarılı (v{versiyon})."
    except Exception as e:
        return False, str(e)

def update_tahmin_by_id(row_id: str, updates: dict):
    sb = get_supabase()
    clean_updates = {k: v for k, v in updates.items() if v is not None}
    try:
        sb.table(TABLE_TAHMIN).update(clean_updates).eq("id", row_id).execute()
        return True, "Güncellendi"
    except Exception as e:
        return False, str(e)

def sync_participants_from_forecasts():
    sb = get_supabase()
    res_t = sb.table(TABLE_TAHMIN).select("kullanici_adi, kategori").execute()
    df_t = pd.DataFrame(res_t.data)
    if df_t.empty:
        return 0, "Tahmin verisi yok."

    res_k = sb.table(TABLE_KATILIMCI).select("ad_soyad").execute()
    existing = {r["ad_soyad"].strip().lower() for r in (res_k.data or []) if r.get("ad_soyad")}

    unique_users = df_t.dropna(subset=["kullanici_adi"]).drop_duplicates(subset=["kullanici_adi"])
    added = 0
    for _, row in unique_users.iterrows():
        user = str(row["kullanici_adi"]).strip()
        key = user.lower()
        if key in existing:
            continue

        cat = row.get("kategori") or "Bireysel"
        try:
            sb.table(TABLE_KATILIMCI).insert({"ad_soyad": user, "kategori": cat}).execute()
            added += 1
            existing.add(key)
        except:
            pass

    return added, f"{added} yeni kişi eklendi."

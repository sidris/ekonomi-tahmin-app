"""
utils.py — Finansal Tahmin Terminali ortak yardımcıları.
"""

from __future__ import annotations

import io
import random
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st
from supabase import Client, create_client

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
TABLE_TAHMIN = "beklentiler_takip"
TABLE_KATILIMCI = "katilimcilar"

KATEGORILER = ["Bireysel", "Kurumsal", "Anket"]
MINMAX_KATEGORI = {"Anket"}

# TÜFE serileri: hibrit yapı
EVDS_TUFE_OLD = "TP.FE.OKTG01"          # 2003=100, geçmiş
EVDS_TUFE_NEW = "TP.TUKFIY2025.GENEL"   # 2025=100, 2026+
# PPK faizi BIS'ten çekilir (EVDS yerine daha temiz seri)
BIS_PPK_URL = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.TR?format=csv&startPeriod={start}&endPeriod={end}"


# ---------------------------------------------------------------------------
# Secrets & Supabase
# ---------------------------------------------------------------------------
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
    return _get_secrets()[2]


def get_evds_key() -> Optional[str]:
    return _get_secrets()[3]


class _SupabaseProxy:
    def __getattr__(self, name):
        return getattr(get_supabase(), name)


supabase = _SupabaseProxy()


# ---------------------------------------------------------------------------
# Oturum
# ---------------------------------------------------------------------------
def check_login() -> bool:
    if "giris_yapildi" not in st.session_state:
        st.session_state["giris_yapildi"] = False
    return bool(st.session_state["giris_yapildi"])


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def get_period_list(yil_geri: int = 2, yil_ileri: int = 2) -> list[str]:
    today = date.today()
    periods = pd.date_range(
        start=date(today.year - yil_geri, 1, 1),
        end=date(today.year + yil_ileri, 12, 1),
        freq="MS",
    )
    return [d.strftime("%Y-%m") for d in periods]


def is_minmax_allowed(kategori: str) -> bool:
    return kategori in MINMAX_KATEGORI


def clean_numeric_and_dates(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    numeric_cols = [
        "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz",
        "tahmin_yilsonu_faiz", "min_yilsonu_faiz", "max_yilsonu_faiz",
        "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf",
        "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf",
        "katilimci_sayisi",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for dcol in ("tahmin_tarihi", "created_at"):
        if dcol in df.columns:
            df[dcol] = pd.to_datetime(df[dcol], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Katılımcı CRUD
# ---------------------------------------------------------------------------
def get_participants() -> pd.DataFrame:
    sb = get_supabase()
    res = sb.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    return pd.DataFrame(res.data or [])


def add_participant(ad_soyad: str, kategori: str) -> Tuple[bool, str]:
    ad_soyad = (ad_soyad or "").strip()
    if not ad_soyad:
        return False, "İsim boş olamaz."
    if kategori not in KATEGORILER:
        return False, f"Geçersiz kategori: {kategori}"
    try:
        get_supabase().table(TABLE_KATILIMCI).insert(
            {"ad_soyad": ad_soyad, "kategori": kategori}
        ).execute()
        return True, "Eklendi."
    except Exception as e:
        return False, str(e)


def update_participant(
    row_id: str, new_name: str, new_category: str, old_name: Optional[str] = None
) -> Tuple[bool, str]:
    sb = get_supabase()
    new_name = (new_name or "").strip()
    if not new_name:
        return False, "İsim boş olamaz."
    if new_category not in KATEGORILER:
        return False, f"Geçersiz kategori: {new_category}"

    try:
        sb.table(TABLE_KATILIMCI).update(
            {"ad_soyad": new_name, "kategori": new_category}
        ).eq("id", row_id).execute()

        if old_name and old_name != new_name:
            sb.table(TABLE_TAHMIN).update(
                {"kullanici_adi": new_name, "kategori": new_category}
            ).eq("kullanici_adi", old_name).execute()

        return True, "Güncellendi."
    except Exception as e:
        return False, str(e)


def delete_participant(row_id: str) -> Tuple[bool, str]:
    try:
        get_supabase().table(TABLE_KATILIMCI).delete().eq("id", row_id).execute()
        return True, "Silindi."
    except Exception as e:
        return False, str(e)


def sync_participants_from_forecasts() -> Tuple[int, str]:
    sb = get_supabase()
    res_t = sb.table(TABLE_TAHMIN).select("kullanici_adi, kategori").execute()
    df_t = pd.DataFrame(res_t.data or [])
    if df_t.empty:
        return 0, "Tahmin verisi yok."

    res_k = sb.table(TABLE_KATILIMCI).select("ad_soyad").execute()
    existing = {
        (r["ad_soyad"] or "").strip().lower()
        for r in (res_k.data or []) if r.get("ad_soyad")
    }

    unique_users = (
        df_t.dropna(subset=["kullanici_adi"]).drop_duplicates(subset=["kullanici_adi"])
    )
    added = 0
    for _, row in unique_users.iterrows():
        user = str(row["kullanici_adi"]).strip()
        if user.lower() in existing:
            continue
        cat = row.get("kategori") or "Bireysel"
        if cat not in KATEGORILER:
            cat = "Bireysel"
        try:
            sb.table(TABLE_KATILIMCI).insert(
                {"ad_soyad": user, "kategori": cat}
            ).execute()
            added += 1
            existing.add(user.lower())
        except Exception:
            pass

    return added, f"{added} yeni kişi eklendi."


# ---------------------------------------------------------------------------
# Tahmin CRUD
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def get_all_forecasts(limit: int = 20000) -> pd.DataFrame:
    sb = get_supabase()
    res = (
        sb.table(TABLE_TAHMIN).select("*")
        .order("tahmin_tarihi", desc=True).limit(limit).execute()
    )
    return clean_numeric_and_dates(pd.DataFrame(res.data or []))


def get_latest_per_user_period(df: pd.DataFrame) -> pd.DataFrame:
    """
    Her (kullanici, hedef_donemi) için en son tahmin_tarihi olan satırı döner.
    Isı haritası ve 'şu an beklenti' analizleri için.
    """
    if df is None or df.empty:
        return df
    return (
        df.sort_values("tahmin_tarihi")
        .drop_duplicates(subset=["kullanici_adi", "hedef_donemi"], keep="last")
    )


def get_latest_as_of(df: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """
    Belirli bir ayın (YYYY-MM) sonuna kadar girilmiş tahminlerden
    her (kullanici, hedef_donemi) için en sonuncusunu döner.
    """
    if df is None or df.empty:
        return df

    as_of_ts = pd.Timestamp(f"{as_of}-01") + pd.offsets.MonthEnd(0)
    filtered = df[df["tahmin_tarihi"] <= as_of_ts]
    if filtered.empty:
        return filtered
    return (
        filtered.sort_values("tahmin_tarihi")
        .drop_duplicates(subset=["kullanici_adi", "hedef_donemi"], keep="last")
    )


def _strip_minmax_if_not_allowed(kategori: str, data: dict) -> dict:
    if is_minmax_allowed(kategori):
        return data
    out = dict(data)
    for k in list(out.keys()):
        if k.startswith(("min_", "max_")):
            out[k] = None
    return out


def upsert_tahmin(
    user: str, hedef_donemi: str, kategori: str,
    forecast_date, link: Optional[str], data_dict: dict,
) -> Tuple[bool, str]:
    sb = get_supabase()

    date_obj = pd.to_datetime(forecast_date, errors="coerce")
    if pd.isna(date_obj):
        return False, "Tahmin tarihi okunamadı."

    tahmin_tarihi = date_obj.strftime("%Y-%m-%d")
    anket_donemi = date_obj.strftime("%Y-%m")

    clean = {
        k: (None if (isinstance(v, float) and pd.isna(v)) else v)
        for k, v in data_dict.items()
    }
    clean = {k: v for k, v in clean.items() if v not in (None, "")}
    clean = _strip_minmax_if_not_allowed(kategori, clean)

    payload = {
        "kullanici_adi": user,
        "kategori": kategori,
        "anket_donemi": anket_donemi,
        "hedef_donemi": hedef_donemi,
        "tahmin_tarihi": tahmin_tarihi,
        **clean,
    }
    if link:
        payload["kaynak_link"] = link

    try:
        existing = (
            sb.table(TABLE_TAHMIN).select("id")
            .eq("kullanici_adi", user)
            .eq("hedef_donemi", hedef_donemi)
            .eq("tahmin_tarihi", tahmin_tarihi)
            .limit(1).execute()
        )
        if existing.data:
            row_id = existing.data[0]["id"]
            sb.table(TABLE_TAHMIN).update(payload).eq("id", row_id).execute()
            msg = "Aynı tarih için güncellendi."
        else:
            sb.table(TABLE_TAHMIN).insert(payload).execute()
            msg = "Yeni kayıt eklendi."

        get_all_forecasts.clear()
        return True, msg
    except Exception as e:
        return False, str(e)


def update_tahmin_by_id(row_id: str, updates: dict) -> Tuple[bool, str]:
    sb = get_supabase()
    clean = {k: v for k, v in updates.items() if v is not None}
    try:
        sb.table(TABLE_TAHMIN).update(clean).eq("id", row_id).execute()
        get_all_forecasts.clear()
        return True, "Güncellendi"
    except Exception as e:
        return False, str(e)


def delete_tahmin_by_ids(ids: list) -> Tuple[bool, str]:
    try:
        get_supabase().table(TABLE_TAHMIN).delete().in_("id", ids).execute()
        get_all_forecasts.clear()
        return True, f"{len(ids)} kayıt silindi."
    except Exception as e:
        return False, str(e)


def reset_all_data(participants_too: bool = True) -> Tuple[bool, str]:
    """Tüm tahminleri (ve isteğe bağlı katılımcıları) siler."""
    sb = get_supabase()
    try:
        sb.table(TABLE_TAHMIN).delete().not_.is_("id", "null").execute()
        msg = "Tüm tahminler silindi."
        if participants_too:
            sb.table(TABLE_KATILIMCI).delete().not_.is_("id", "null").execute()
            msg += " Katılımcılar da silindi."
        get_all_forecasts.clear()
        return True, msg
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# EVDS + BIS — Piyasa verisi
# ---------------------------------------------------------------------------
def _evds_to_pct(evds_client, series_code: str, fetch_start: str, fetch_end: str) -> pd.DataFrame:
    try:
        raw = evds_client.get_data(
            [series_code],
            startdate=fetch_start,
            enddate=fetch_end,
            frequency=5,
        )
        if raw is None or raw.empty:
            return pd.DataFrame()

        raw["dt"] = pd.to_datetime(raw["Tarih"], format="%Y-%m", errors="coerce")
        raw = raw.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)

        val_col = [c for c in raw.columns if c not in ("Tarih", "dt")][0]
        raw[val_col] = pd.to_numeric(raw[val_col], errors="coerce")
        raw = raw.dropna(subset=[val_col])

        raw["Aylık TÜFE"] = raw[val_col].pct_change(1) * 100
        raw["Yıllık TÜFE"] = raw[val_col].pct_change(12) * 100
        raw["Donem"] = raw["dt"].dt.strftime("%Y-%m")
        return raw[["Donem", "Aylık TÜFE", "Yıllık TÜFE"]].copy()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def fetch_market_data_adapter(start_date, end_date) -> Tuple[pd.DataFrame, Optional[str]]:
    """TÜFE (EVDS hibrit) + PPK Faizi (BIS) → aylık master tablo."""
    empty_df = pd.DataFrame(columns=["Donem", "Aylık TÜFE", "Yıllık TÜFE", "PPK Faizi", "SortDate"])
    api_key = get_evds_key()

    if not api_key:
        return empty_df, "EVDS_KEY secrets içinde tanımlı değil."

    # --- TÜFE (hibrit) ---
    df_inf = pd.DataFrame()
    try:
        from evds import evdsAPI
        evds_client = evdsAPI(api_key)
        ts_start = pd.Timestamp(start_date)
        ts_end = pd.Timestamp(end_date)

        fetch_start_old = (ts_start - pd.DateOffset(months=13)).replace(day=1).strftime("%d-%m-%Y")
        fetch_end_old = "01-12-2025"
        df_old = _evds_to_pct(evds_client, EVDS_TUFE_OLD, fetch_start_old, fetch_end_old)

        fetch_end_new = ts_end.replace(day=1).strftime("%d-%m-%Y")
        df_new = _evds_to_pct(evds_client, EVDS_TUFE_NEW, "01-01-2025", fetch_end_new)
        if not df_new.empty:
            df_new = df_new[df_new["Donem"] >= "2026-01"].copy()

        df_combined = pd.concat([df_old, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["Donem"], keep="last")
        df_combined = df_combined.sort_values("Donem").reset_index(drop=True)

        cutoff = ts_start.strftime("%Y-%m")
        end_cutoff = ts_end.strftime("%Y-%m")
        df_inf = df_combined[
            (df_combined["Donem"] >= cutoff) & (df_combined["Donem"] <= end_cutoff)
        ].copy()
        df_inf["Aylık TÜFE"] = pd.to_numeric(df_inf["Aylık TÜFE"], errors="coerce").round(2)
        df_inf["Yıllık TÜFE"] = pd.to_numeric(df_inf["Yıllık TÜFE"], errors="coerce").round(2)
        df_inf = df_inf.dropna(subset=["Aylık TÜFE", "Yıllık TÜFE"]).reset_index(drop=True)
    except Exception as e:
        return empty_df, f"EVDS hatası: {e}"

    # --- PPK (BIS) ---
    df_pol = pd.DataFrame()
    try:
        s = pd.Timestamp(start_date).strftime("%Y-%m-%d")
        e = pd.Timestamp(end_date).strftime("%Y-%m-%d")
        r = requests.get(BIS_PPK_URL.format(start=s, end=e), timeout=20)
        if r.status_code == 200:
            tmp = pd.read_csv(
                io.StringIO(r.content.decode("utf-8")),
                usecols=["TIME_PERIOD", "OBS_VALUE"],
            )
            tmp["dt"] = pd.to_datetime(tmp["TIME_PERIOD"])
            tmp["Donem"] = tmp["dt"].dt.strftime("%Y-%m")
            tmp["PPK Faizi"] = pd.to_numeric(tmp["OBS_VALUE"], errors="coerce")
            df_pol = (
                tmp.sort_values("dt").groupby("Donem").last().reset_index()
                [["Donem", "PPK Faizi"]]
            )
    except Exception:
        pass

    if not df_inf.empty and not df_pol.empty:
        master = pd.merge(df_inf, df_pol, on="Donem", how="left")
        master["PPK Faizi"] = master["PPK Faizi"].ffill()
    elif not df_inf.empty:
        master = df_inf.copy()
    elif not df_pol.empty:
        master = df_pol.copy()
    else:
        return empty_df, "Veri bulunamadı"

    for c in ["Aylık TÜFE", "Yıllık TÜFE", "PPK Faizi"]:
        if c not in master.columns:
            master[c] = np.nan

    master["SortDate"] = pd.to_datetime(master["Donem"] + "-01")
    return master.sort_values("SortDate").reset_index(drop=True), None


# ---------------------------------------------------------------------------
# DEMO VERİ ÜRETİCİ
# ---------------------------------------------------------------------------
DEMO_KATILIMCILAR = [
    ("Ak Yatırım", "Kurumsal"),
    ("Garanti BBVA", "Kurumsal"),
    ("İş Yatırım", "Kurumsal"),
    ("Yapı Kredi Yatırım", "Kurumsal"),
    ("QNB Finansinvest", "Kurumsal"),
    ("HSBC", "Kurumsal"),
    ("Goldman Sachs", "Kurumsal"),
    ("JP Morgan", "Kurumsal"),
    ("TCMB Piyasa Katılımcıları Anketi", "Anket"),
    ("AA Finans Anketi", "Anket"),
    ("Reuters Anketi", "Anket"),
    ("Haluk Bürümcekçi", "Bireysel"),
    ("Enver Erkan", "Bireysel"),
    ("Özlem Derici Şengül", "Bireysel"),
    ("Mahfi Eğilmez", "Bireysel"),
    ("Uğur Gürses", "Bireysel"),
]


def _round_step(x: float, step: float = 0.25) -> float:
    return round(round(x / step) * step, 2)


def generate_demo_data(seed: int = 42) -> Tuple[int, int, str]:
    """Son 12 ay için gerçekçi demo verisi üretir."""
    rng = np.random.default_rng(seed)
    random.seed(seed)

    existing = get_participants()
    existing_names = (
        set(existing["ad_soyad"].str.strip().str.lower())
        if not existing.empty else set()
    )

    added_p = 0
    for name, cat in DEMO_KATILIMCILAR:
        if name.lower() in existing_names:
            continue
        ok, _ = add_participant(name, cat)
        if ok:
            added_p += 1

    today = date.today()
    months = []
    for i in range(12, 0, -1):
        d = today.replace(day=15) - timedelta(days=30 * i)
        months.append(d.replace(day=15))

    baselines = {}
    for i, m in enumerate(months):
        t = i / max(1, len(months) - 1)
        baselines[m.strftime("%Y-%m")] = {
            "ppk": 50 - 10 * t + rng.normal(0, 0.8),
            "aylik_enf": 3.5 - 1.5 * t + rng.normal(0, 0.4),
            "yillik_enf": 70 - 25 * t + rng.normal(0, 1.5),
            "yilsonu_enf": 38 + rng.normal(0, 2),
            "yilsonu_faiz": 32 + rng.normal(0, 1.5),
        }

    # Önce tüm payloadları hazırla, sonra batch halinde gönder
    all_payloads = []

    for forecast_month in months:
        month_key = forecast_month.strftime("%Y-%m")
        base = baselines[month_key]

        target_periods = [
            forecast_month.strftime("%Y-%m"),
            (forecast_month + pd.DateOffset(months=1)).strftime("%Y-%m"),
            (forecast_month + pd.DateOffset(months=3)).strftime("%Y-%m"),
            f"{forecast_month.year}-12",
        ]
        target_periods = list(dict.fromkeys(target_periods))

        for name, cat in DEMO_KATILIMCILAR:
            bias = {
                "Goldman Sachs": -0.5, "HSBC": -0.3, "JP Morgan": -0.4,
                "Haluk Bürümcekçi": 0.5, "Uğur Gürses": 0.3,
            }.get(name, 0.0)

            if cat == "Bireysel":
                n_updates = int(rng.integers(2, 4))
                days = sorted(rng.choice(range(1, 28), size=n_updates, replace=False))
                forecast_dates = [forecast_month.replace(day=int(d)) for d in days]
            elif cat == "Anket":
                forecast_dates = [forecast_month.replace(day=15)]
            else:
                forecast_dates = [forecast_month.replace(day=int(rng.choice([5, 10, 15, 20])))]

            for fdate in forecast_dates:
                for tp in target_periods:
                    months_ahead = (
                        pd.Timestamp(tp + "-01").to_period("M").ordinal
                        - pd.Timestamp(month_key + "-01").to_period("M").ordinal
                    )
                    noise_scale = 1.0 + 0.3 * abs(months_ahead)

                    ppk = _round_step(
                        base["ppk"] + bias + rng.normal(0, 1.0) * noise_scale, 0.25
                    )
                    aylik = round(
                        max(0.1, base["aylik_enf"] + rng.normal(0, 0.5) * noise_scale), 2
                    )
                    yilsonu_enf = round(
                        base["yilsonu_enf"] + bias * 2 + rng.normal(0, 2), 1
                    )
                    yilsonu_faiz = _round_step(
                        base["yilsonu_faiz"] + bias + rng.normal(0, 1.5), 0.25
                    )

                    payload = {
                        "kullanici_adi": name,
                        "kategori": cat,
                        "anket_donemi": fdate.strftime("%Y-%m"),
                        "hedef_donemi": tp,
                        "tahmin_tarihi": fdate.strftime("%Y-%m-%d"),
                        "tahmin_ppk_faiz": ppk,
                        "tahmin_aylik_enf": aylik,
                        "tahmin_yilsonu_enf": yilsonu_enf,
                        "tahmin_yilsonu_faiz": yilsonu_faiz,
                    }

                    if cat == "Anket":
                        spread_ppk = abs(rng.normal(2, 0.5))
                        spread_enf = abs(rng.normal(3, 1))
                        spread_aylik = abs(rng.normal(0.8, 0.3))
                        payload.update({
                            "min_ppk_faiz": _round_step(ppk - spread_ppk, 0.25),
                            "max_ppk_faiz": _round_step(ppk + spread_ppk, 0.25),
                            "min_aylik_enf": round(max(0.1, aylik - spread_aylik), 2),
                            "max_aylik_enf": round(aylik + spread_aylik, 2),
                            "min_yilsonu_enf": round(yilsonu_enf - spread_enf, 1),
                            "max_yilsonu_enf": round(yilsonu_enf + spread_enf, 1),
                            "min_yilsonu_faiz": _round_step(yilsonu_faiz - spread_ppk, 0.25),
                            "max_yilsonu_faiz": _round_step(yilsonu_faiz + spread_ppk, 0.25),
                            "katilimci_sayisi": int(rng.integers(15, 30)),
                        })

                    all_payloads.append(payload)

    # Aynı (kullanici, hedef, tarih) varsa dedupe — sonuncuyu tut
    seen = {}
    for p in all_payloads:
        k = (p["kullanici_adi"], p["hedef_donemi"], p["tahmin_tarihi"])
        seen[k] = p
    all_payloads = list(seen.values())

    # Batch insert (Supabase 500'lük grup kabul ediyor)
    sb = get_supabase()
    added_f = 0
    errors = []
    BATCH = 500
    for i in range(0, len(all_payloads), BATCH):
        chunk = all_payloads[i:i + BATCH]
        try:
            sb.table(TABLE_TAHMIN).insert(chunk).execute()
            added_f += len(chunk)
        except Exception as e:
            # Batch başarısızsa tek tek dene
            err_first = str(e)[:100]
            for p in chunk:
                try:
                    sb.table(TABLE_TAHMIN).insert(p).execute()
                    added_f += 1
                except Exception as e2:
                    errors.append(str(e2)[:100])
            if not errors:
                errors.append(f"batch hatası: {err_first}")

    get_all_forecasts.clear()
    msg = f"{added_p} katılımcı + {added_f} tahmin eklendi."
    if errors:
        msg += f" ({len(errors)} hata; örn: {errors[0]})"
    return added_p, added_f, msg

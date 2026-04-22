import datetime
import streamlit as st
import utils

st.set_page_config(page_title="Veri Girişi", layout="wide")
utils.apply_theme()

utils.require_login_page()

utils.page_header("➕ Manuel Veri Girişi", "Tek bir tahmin kaydı ekle veya güncelle")

df_kat = utils.get_participants()
if df_kat.empty:
    st.error("Lütfen önce **Katılımcı Yönetimi** sayfasından katılımcı ekleyin.")
    st.stop()

# ---- Üst satır ----
col_u1, col_u2, col_u3 = st.columns([2, 1, 1])
users_list = df_kat["ad_soyad"].tolist()
selected_user = col_u1.selectbox("Katılımcı", users_list)

user_row = df_kat[df_kat["ad_soyad"] == selected_user].iloc[0]
user_cat = user_row.get("kategori", "Bireysel")
minmax_ok = utils.is_minmax_allowed(user_cat)

periods = utils.get_period_list()
today_period = datetime.date.today().strftime("%Y-%m")
default_idx = periods.index(today_period) if today_period in periods else len(periods) // 2
hedef_donem = col_u2.selectbox("Hedef Dönem", periods, index=default_idx)
tarih = col_u3.date_input("Tarih", datetime.date.today())

link = st.text_input("Kaynak Link (opsiyonel)", placeholder="https://...")

# Bilgi satırı
info_text = {
    "Bireysel": "Tek nokta tahmin — min/max alanları devre dışı",
    "Kurumsal": "Tek nokta tahmin — min/max alanları devre dışı",
    "Anket": "Anket verisi — medyan + min + max + N (katılımcı sayısı) girilir",
}.get(user_cat, "")

st.markdown(
    f"""
    <div class="soft-card" style="padding:12px 16px;margin-top:8px;">
      {utils.category_badge(user_cat)}
      <span style="margin-left:10px;color:#94A3B8;font-size:13px;">{info_text}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")

with st.form("entry_form"):
    # FAİZ
    st.markdown("#### 🏦 Faiz Tahminleri")
    fc1, fc2, fc3 = st.columns(3)
    ppk_val = fc1.number_input("PPK Faizi (%)", value=None, step=0.25, format="%.2f")
    ppk_min = fc2.number_input("Min PPK", value=None, step=0.25, format="%.2f", disabled=not minmax_ok)
    ppk_max = fc3.number_input("Max PPK", value=None, step=0.25, format="%.2f", disabled=not minmax_ok)

    ys_faiz = fc1.number_input("Yıl Sonu Faizi (%)", value=None, step=0.25, format="%.2f")
    ys_min = fc2.number_input("Min YS Faiz", value=None, step=0.25, format="%.2f", disabled=not minmax_ok)
    ys_max = fc3.number_input("Max YS Faiz", value=None, step=0.25, format="%.2f", disabled=not minmax_ok)

    st.markdown("#### 💸 Enflasyon Tahminleri")
    ec1, ec2, ec3 = st.columns(3)
    aylik_enf = ec1.number_input("Aylık Enflasyon (%)", value=None, step=0.1, format="%.2f")
    aylik_min = ec2.number_input("Min Aylık", value=None, step=0.1, format="%.2f", disabled=not minmax_ok)
    aylik_max = ec3.number_input("Max Aylık", value=None, step=0.1, format="%.2f", disabled=not minmax_ok)

    ys_enf = ec1.number_input("Yıl Sonu Enflasyon (%)", value=None, step=0.1, format="%.2f")
    ys_enf_min = ec2.number_input("Min YS Enf", value=None, step=0.1, format="%.2f", disabled=not minmax_ok)
    ys_enf_max = ec3.number_input("Max YS Enf", value=None, step=0.1, format="%.2f", disabled=not minmax_ok)

    if minmax_ok:
        n_sayisi = st.number_input("Katılımcı Sayısı (N)", value=1, min_value=1)
    else:
        n_sayisi = None

    submitted = st.form_submit_button("✅ Kaydet", type="primary", use_container_width=True)

    if submitted:
        data = {
            "tahmin_ppk_faiz": ppk_val, "min_ppk_faiz": ppk_min, "max_ppk_faiz": ppk_max,
            "tahmin_yilsonu_faiz": ys_faiz, "min_yilsonu_faiz": ys_min, "max_yilsonu_faiz": ys_max,
            "tahmin_aylik_enf": aylik_enf, "min_aylik_enf": aylik_min, "max_aylik_enf": aylik_max,
            "tahmin_yilsonu_enf": ys_enf, "min_yilsonu_enf": ys_enf_min, "max_yilsonu_enf": ys_enf_max,
            "katilimci_sayisi": n_sayisi,
        }
        success, msg = utils.upsert_tahmin(
            selected_user, hedef_donem, user_cat, tarih, link, data
        )
        if success:
            st.success(f"✅ {msg}")
        else:
            st.error(f"❌ {msg}")

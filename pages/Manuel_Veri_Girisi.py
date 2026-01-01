import streamlit as st
import datetime
import utils

st.set_page_config(page_title="Veri Girişi", layout="wide")

if not utils.check_login():
    st.warning("Giriş yapınız.")
    st.stop()

st.header("➕ Manuel Veri Girişi")

# Katılımcı Seçimi
df_kat = utils.get_participants()
if df_kat.empty:
    st.error("Lütfen önce 'Katılımcı Yönetimi' sayfasından katılımcı ekleyin.")
    st.stop()

# Seçim Kutuları
col_u1, col_u2, col_u3 = st.columns([2, 1, 1])
users_list = df_kat['ad_soyad'].tolist()
selected_user = col_u1.selectbox("Katılımcı Seç", users_list)

# Kullanıcı detaylarını bul
user_row = df_kat[df_kat['ad_soyad'] == selected_user].iloc[0]
user_cat = user_row.get('kategori', 'Bireysel')
is_anket = (user_cat == "Anket") # Anket ise Min/Max açık olacak

hedef_donem = col_u2.selectbox("Hedef Dönem (YYYY-AA)", utils.get_period_list(), index=12)
tarih = col_u3.date_input("Veri Tarihi", datetime.date.today())
link = st.text_input("Kaynak Link (Opsiyonel)")

st.markdown("---")

with st.form("entry_form"):
    # FAİZ BÖLÜMÜ
    st.subheader("🏦 Faiz Tahminleri")
    fc1, fc2, fc3 = st.columns(3)
    ppk_val = fc1.number_input("PPK Faizi (%)", step=0.25, format="%.2f")
    ppk_min = fc2.number_input("Min PPK", step=0.25, disabled=not is_anket)
    ppk_max = fc3.number_input("Max PPK", step=0.25, disabled=not is_anket)
    
    ys_faiz = fc1.number_input("Yıl Sonu Faizi (%)", step=0.25, format="%.2f")
    ys_min = fc2.number_input("Min YS Faiz", step=0.25, disabled=not is_anket)
    ys_max = fc3.number_input("Max YS Faiz", step=0.25, disabled=not is_anket)

    st.markdown("---")
    
    # ENFLASYON BÖLÜMÜ
    st.subheader("💸 Enflasyon Tahminleri")
    ec1, ec2, ec3 = st.columns(3)
    
    aylik_enf = ec1.number_input("Aylık Enflasyon (%)", step=0.1, format="%.2f")
    aylik_min = ec2.number_input("Min Aylık", step=0.1, disabled=not is_anket)
    aylik_max = ec3.number_input("Max Aylık", step=0.1, disabled=not is_anket)
    
    ys_enf = ec1.number_input("Yıl Sonu Enflasyon (%)", step=0.1, format="%.2f")
    ys_enf_min = ec2.number_input("Min YS Enf", step=0.1, disabled=not is_anket)
    ys_enf_max = ec3.number_input("Max YS Enf", step=0.1, disabled=not is_anket)
    
    st.markdown("---")
    n_sayisi = st.number_input("Katılımcı Sayısı (N)", value=1, min_value=1)
    
    submitted = st.form_submit_button("✅ Veriyi Kaydet", type="primary")
    
    if submitted:
        data = {
            "tahmin_ppk_faiz": ppk_val, "min_ppk_faiz": ppk_min, "max_ppk_faiz": ppk_max,
            "tahmin_yilsonu_faiz": ys_faiz, "min_yilsonu_faiz": ys_min, "max_yilsonu_faiz": ys_max,
            "tahmin_aylik_enf": aylik_enf, "min_aylik_enf": aylik_min, "max_aylik_enf": aylik_max,
            "tahmin_yilsonu_enf": ys_enf, "min_yilsonu_enf": ys_enf_min, "max_yilsonu_enf": ys_enf_max,
            "katilimci_sayisi": n_sayisi
        }
        
        success, msg = utils.upsert_tahmin(selected_user, hedef_donem, user_cat, tarih, link, data)
        if success:
            st.success(f"Başarılı: {msg}")
        else:
            st.error(f"Hata: {msg}")

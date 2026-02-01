import streamlit as st
import time
import utils

st.set_page_config(
    page_title="Finansal Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Login gate: giriş yoksa devam etme ---
if not utils.check_login():
    st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarCollapsedControl"] {display: none;}
    </style>
    """, unsafe_allow_html=True)

    st.markdown("<h1 style='text-align:center;'>📊 Finansal Tahmin Terminali</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#6B7280;'>Kurumsal ve Bireysel Beklenti Yönetim Sistemi</p>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        with st.form("login_form"):
            pwd = st.text_input("Erişim Şifresi", type="password")
            submit = st.form_submit_button("Giriş Yap", type="primary", use_container_width=True)

        if submit:
            if pwd == utils.get_app_password():
                st.session_state["giris_yapildi"] = True
                st.success("Giriş başarılı!")
                time.sleep(0.2)
                st.rerun()
            else:
                st.error("Hatalı şifre.")

    st.stop()  # ✅ kritik: login yoksa burada kes

# --- Buradan sonrası sadece login olmuş kullanıcı ---
st.markdown("<h2>👋 Hoşgeldiniz</h2>", unsafe_allow_html=True)

if st.button("🚪 Çıkış Yap"):
    st.session_state["giris_yapildi"] = False
    st.rerun()

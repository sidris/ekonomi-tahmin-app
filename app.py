import streamlit as st
import utils
import time

st.set_page_config(page_title="Finansal Terminal", page_icon="📊", layout="wide")

st.markdown("""
<style>
    .login-container { text-align: center; padding: 50px; background-color: #f0f2f6; border-radius: 10px; margin-top: 50px;}
    .big-font { font-size: 30px !important; font-weight: bold; color: #1E3A8A; }
</style>
""", unsafe_allow_html=True)

if not utils.check_login():
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown('<div class="login-container"><p class="big-font">🔐 Finansal Tahmin Terminali v5</p></div>', unsafe_allow_html=True)
        st.write("")
        with st.form("login_form"):
            pwd = st.text_input("Erişim Şifresi", type="password")
            submit = st.form_submit_button("Giriş Yap", type="primary", use_container_width=True)
            
            if submit:
                if pwd == utils.APP_PASSWORD:
                    st.session_state['giris_yapildi'] = True
                    st.success("Giriş Başarılı! Yönlendiriliyorsunuz...")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Hatalı Şifre!")
else:
    st.markdown('<div class="login-container"><p class="big-font">👋 Hoşgeldiniz</p></div>', unsafe_allow_html=True)
    st.info("✅ Oturumunuz açık. Sol taraftaki menüyü kullanarak işlemlerinizi yapabilirsiniz.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        ### 🚀 Hızlı Erişim
        * **Dashboard:** Piyasa analizlerini inceleyin.
        * **Veri Girişi:** Tekil tahmin girin.
        * **Excel Yükleme:** Toplu veri aktarın.
        """)
    with col2:
        if st.button("🚪 Çıkış Yap", type="secondary"):
            st.session_state['giris_yapildi'] = False
            st.rerun()

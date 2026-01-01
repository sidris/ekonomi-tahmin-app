import streamlit as st
import utils
import time

# Sayfa ayarı
st.set_page_config(page_title="Finansal Terminal", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

# --- CSS: GİRİŞ YAPILMADIYSA MENÜYÜ GİZLE ---
if not utils.check_login():
    st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarCollapsedControl"] {display: none;}
    </style>
    """, unsafe_allow_html=True)

# CSS Tasarımı
st.markdown("""
<style>
    .main-header { text-align: center; color: #1E3A8A; font-family: 'Helvetica Neue', sans-serif; font-weight: 800; font-size: 40px; margin-top: 20px;}
    .sub-header { text-align: center; color: #6B7280; font-size: 18px; margin-bottom: 40px;}
    .feature-card { background-color: #ffffff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; height: 100%; border: 1px solid #e5e7eb; transition: transform 0.3s; }
    .feature-card:hover { transform: translateY(-5px); box-shadow: 0 10px 15px rgba(0,0,0,0.1); }
    .icon { font-size: 40px; margin-bottom: 10px; }
    .feature-title { font-weight: bold; font-size: 18px; color: #111827; margin-bottom: 5px; }
    .feature-desc { color: #4B5563; font-size: 14px; }
</style>
""", unsafe_allow_html=True)

# --- 1. GİRİŞ EKRANI (SADE) ---
if not utils.check_login():
    st.markdown('<div class="main-header">📊 Finansal Tahmin Terminali</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Kurumsal ve Bireysel Beklenti Yönetim Sistemi</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        with st.form("login_form"):
            st.write("Erişim Şifresi")
            pwd = st.text_input("", type="password", label_visibility="collapsed")
            submit = st.form_submit_button("Giriş Yap", type="primary", use_container_width=True)
            
            if submit:
                if pwd == utils.APP_PASSWORD:
                    st.session_state['giris_yapildi'] = True
                    st.success("Giriş Başarılı!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Hatalı Şifre!")

# --- 2. HOŞGELDİNİZ EKRANI (ZENGİN İÇERİK) ---
else:
    st.markdown('<div class="main-header">👋 Hoşgeldiniz</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Sistem aktif ve kullanıma hazır. Yapmak istediğiniz işlemi soldaki menüden seçebilirsiniz.</div>', unsafe_allow_html=True)
    
    # Özellik Tanıtım Kartları
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("""
        <div class="feature-card">
            <div class="icon">📈</div>
            <div class="feature-title">Piyasa Analizi</div>
            <div class="feature-desc">PPK faiz ve enflasyon beklentilerini gerçekleşmelerle karşılaştırın.</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="feature-card">
            <div class="icon">🏆</div>
            <div class="feature-title">Liderlik Tablosu</div>
            <div class="feature-desc">Hangi kurum veya analist en iyi tahmini yaptı? Sapmaları analiz edin.</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="feature-card">
            <div class="icon">📥</div>
            <div class="feature-title">Excel Entegrasyonu</div>
            <div class="feature-desc">Toplu tahmin verilerini tek tıkla sisteme yükleyin ve işleyin.</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown("""
        <div class="feature-card">
            <div class="icon">💾</div>
            <div class="feature-title">Veri Arşivi</div>
            <div class="feature-desc">TCMB ve BIS kaynaklı resmi verilere tablolardan erişin.</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    if st.button("🚪 Çıkış Yap", type="secondary"):
        st.session_state['giris_yapildi'] = False
        st.rerun()

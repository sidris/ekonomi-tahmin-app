import time
import streamlit as st
import utils

# ------------------------------------------------------------
# Page config
# ------------------------------------------------------------
st.set_page_config(
    page_title="Finansal Tahmin Terminali",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# Small helper so you can reuse this in pages/*
# In pages:  from app import require_login  (or copy this function to utils)
# ------------------------------------------------------------
def require_login():
    """Call at the top of each page to block access if not logged in."""
    if not utils.check_login():
        # Sidebar gizle + login sayfasına dön
        st.markdown(
            """
            <style>
              [data-testid="stSidebar"] {display: none;}
              [data-testid="stSidebarCollapsedControl"] {display: none;}
            </style>
            """,
            unsafe_allow_html=True,
        )
        render_login()
        st.stop()


# ------------------------------------------------------------
# Styling
# ------------------------------------------------------------
st.markdown(
    """
    <style>
      .app-title {
        text-align:center;
        margin-top: 8px;
        margin-bottom: 0px;
      }
      .app-subtitle {
        text-align:center;
        color:#6B7280;
        font-size: 18px;
        margin-top: 6px;
        margin-bottom: 22px;
      }
      .card {
        padding: 18px 18px 14px 18px;
        border-radius: 14px;
        border: 1px solid rgba(148,163,184,0.25);
        background: rgba(15,23,42,0.55);
        box-shadow: 0 8px 22px rgba(0,0,0,0.12);
        height: 100%;
      }
      .card h3 {
        margin: 0 0 8px 0;
        font-size: 18px;
      }
      .card ul {
        margin: 0;
        padding-left: 18px;
        color: rgba(226,232,240,0.92);
      }
      .login-box {
        padding: 18px;
        border-radius: 14px;
        border: 1px solid rgba(148,163,184,0.25);
        background: rgba(2,6,23,0.50);
        box-shadow: 0 10px 26px rgba(0,0,0,0.18);
      }
      .hint {
        color:#94A3B8;
        font-size: 13px;
        text-align:center;
        margin-top: 8px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# Login renderer
# ------------------------------------------------------------
def render_login():
    st.markdown("<h1 class='app-title'>📊 Finansal Tahmin Terminali</h1>", unsafe_allow_html=True)
    st.markdown(
        "<div class='app-subtitle'>Kurumsal, medya ve bireysel tahminleri arşivleyin • karşılaştırın • analiz edin</div>",
        unsafe_allow_html=True,
    )

    # Feature cards
    c1, c2, c3 = st.columns(3, gap="large")

    with c1:
        st.markdown(
            """
            <div class="card">
              <h3>📈 Tahmin Arşivi</h3>
              <ul>
                <li>Kurum & medya tahminleri</li>
                <li>Bireysel yorumcular</li>
                <li>Aynı döneme çoklu tahmin</li>
              </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            """
            <div class="card">
              <h3>🧠 Performans Analizi</h3>
              <ul>
                <li>Zaman içinde kıyas</li>
                <li>Son tahmin / tüm versiyonlar</li>
                <li>Liderlik tabloları</li>
              </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            """
            <div class="card">
              <h3>📊 Veri Entegrasyonu</h3>
              <ul>
                <li>TCMB EVDS verileri</li>
                <li>Otomatik temizleme</li>
                <li>Dashboard görselleştirme</li>
              </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")
    st.write("")

    # Login form centered
    left, mid, right = st.columns([1.2, 1, 1.2])
    with mid:
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)
        with st.form("login_form", clear_on_submit=True):
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
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='hint'>Şifreyi doğru girince menü ve sayfalar açılır.</div>", unsafe_allow_html=True)


# ------------------------------------------------------------
# MAIN: Gate everything behind login
# ------------------------------------------------------------
if not utils.check_login():
    # Hide sidebar on login screen
    st.markdown(
        """
        <style>
          [data-testid="stSidebar"] {display: none;}
          [data-testid="stSidebarCollapsedControl"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    render_login()
    st.stop()

# ------------------------------------------------------------
# Logged-in Home
# ------------------------------------------------------------
st.sidebar.markdown("### 📌 Menü")
st.sidebar.caption("Sayfalar için sol menüyü kullanın (pages/ klasörü).")

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state["giris_yapildi"] = False
    st.rerun()

st.markdown("## 👋 Hoş geldiniz")
st.write(
    "Sol menüden Dashboard ve diğer sayfalara geçebilirsiniz. "
    "Eğer bir sayfada ‘giriş yapmadan erişim’ olmasını istemiyorsanız, "
    "o sayfanın en üstüne `require_login()` ekleyin."
)

st.info("İpucu: pages/Dashboard.py gibi her sayfanın en üstüne `from app import require_login; require_login()` koy.")

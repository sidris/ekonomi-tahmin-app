import time
import streamlit as st
import utils

st.set_page_config(
    page_title="Finansal Tahmin Terminali",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
utils.apply_theme()


def require_login():
    if not utils.check_login():
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


def render_login():
    st.markdown("<div class='app-title'>📊 Finansal Tahmin Terminali</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='app-subtitle'>Kurumsal, anket ve bireysel tahminleri arşivle • karşılaştır • analiz et</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        st.markdown(
            """
            <div class="soft-card">
              <h3>📈 Tahmin Arşivi</h3>
              <ul>
                <li>Kurumsal & anket tahminleri</li>
                <li>Bireysel yorumcular</li>
                <li>Aynı döneme çoklu revizyon</li>
              </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            """
            <div class="soft-card">
              <h3>🧠 Performans Analizi</h3>
              <ul>
                <li>Gerçekleşene karşı kıyas</li>
                <li>Dönem bazlı liderlik tabloları</li>
                <li>Tahmin revizyonu takibi</li>
              </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            """
            <div class="soft-card">
              <h3>📊 Veri Entegrasyonu</h3>
              <ul>
                <li>TCMB EVDS (TÜFE hibrit)</li>
                <li>BIS (politika faizi)</li>
                <li>Excel toplu yükleme</li>
              </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")
    left, mid, right = st.columns([1.2, 1, 1.2])
    with mid:
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)
        with st.form("login_form", clear_on_submit=True):
            pwd = st.text_input("Erişim Şifresi", type="password")
            submit = st.form_submit_button(
                "Giriş Yap", type="primary", use_container_width=True
            )
        if submit:
            if pwd == utils.get_app_password():
                st.session_state["giris_yapildi"] = True
                st.success("Giriş başarılı!")
                time.sleep(0.2)
                st.rerun()
            else:
                st.error("Hatalı şifre.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='hint'>Şifreyi doğru girince menü ve sayfalar açılır.</div>",
            unsafe_allow_html=True,
        )


# Ana akış
if not utils.check_login():
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

# ----------- Logged-in home -----------
st.sidebar.markdown("### 📌 Menü")
st.sidebar.caption("Sayfalar için sol menüyü kullanın.")
st.sidebar.markdown("---")

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state["giris_yapildi"] = False
    st.rerun()

st.markdown("<div class='app-title' style='font-size:32px;'>👋 Hoş geldiniz</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='app-subtitle'>Aşağıda sistem özetini görebilir, sol menüden ilgili sayfalara geçebilirsiniz.</div>",
    unsafe_allow_html=True,
)

# Özet metrikler
try:
    df = utils.get_all_forecasts(limit=20000)
    df_k = utils.get_participants()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Tahmin", f"{len(df):,}")
    c2.metric("Katılımcı", f"{len(df_k)}")
    if not df.empty:
        c3.metric("Hedef Dönem", f"{df['hedef_donemi'].nunique()}")
        c4.metric("Kategori", f"{df['kategori'].nunique()}")
    else:
        c3.metric("Hedef Dönem", "—")
        c4.metric("Kategori", "—")

    if not df_k.empty and "kategori" in df_k.columns:
        st.markdown("#### Katılımcı Dağılımı")
        kat_counts = df_k["kategori"].value_counts()
        kc1, kc2, kc3 = st.columns(3)
        for col, kat in zip([kc1, kc2, kc3], ["Anket", "Kurumsal", "Bireysel"]):
            n = int(kat_counts.get(kat, 0))
            col.metric(kat, f"{n}")
except Exception as e:
    st.info(f"İstatistikler yüklenemedi: {e}")

st.markdown("---")

# Hızlı eylemler
st.markdown("### ⚡ Hızlı Eylemler")
a1, a2, a3 = st.columns(3)
with a1:
    st.markdown(
        """
        <div class="soft-card">
          <h3>➕ Veri Girişi</h3>
          <div style="color:#94A3B8;font-size:13px;">
            Sol menüden <b>Manuel Veri Girişi</b> veya <b>Excel Yükleme</b> sayfasına gidin.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with a2:
    st.markdown(
        """
        <div class="soft-card">
          <h3>📈 Dashboard</h3>
          <div style="color:#94A3B8;font-size:13px;">
            Liderlik tablosu, zaman serisi ve ısı haritası için <b>Dashboard</b> sayfasına gidin.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with a3:
    st.markdown(
        """
        <div class="soft-card">
          <h3>⚙️ Sistem Yönetimi</h3>
          <div style="color:#94A3B8;font-size:13px;">
            <b>Sistem Yönetimi</b> sayfasından demo verisi üretebilir veya sıfırlama yapabilirsiniz.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

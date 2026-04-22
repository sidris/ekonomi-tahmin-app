import time
import streamlit as st
import utils
from theme import apply_theme, page_header

st.set_page_config(page_title="Sistem Yönetimi", layout="wide")
apply_theme()

if not utils.check_login():
    st.warning("Lütfen giriş yapınız.")
    st.stop()

page_header(
    "⚙️ Sistem Yönetimi",
    "Demo verisi üretme, veritabanı sıfırlama ve senkronizasyon",
)

# =================================================================
# BÖLÜM 1: DEMO VERİSİ
# =================================================================
st.markdown("### 🎬 Demo Verisi Üret")
st.markdown(
    """
    Sistemi yönetime göstermek için **son 12 ay** için gerçekçi tahmin verileri üretir:
    - **16 katılımcı** (8 kurumsal, 3 anket, 5 bireysel yorumcu)
    - Her ay için her katılımcıdan tahminler (bireyseller ayda 2-3 kez, diğerleri 1 kez)
    - Her tahminde 3-4 farklı hedef dönem
    - Anket kategorisi için Min/Max/N değerleri dahil
    - PPK faizi, aylık/yıllık/yıl sonu enflasyon, yıl sonu faiz — hepsi
    """
)

col_demo1, col_demo2 = st.columns([1, 2])
with col_demo1:
    seed = st.number_input("Seed (tekrarlanabilirlik)", value=42, step=1)

with col_demo2:
    st.markdown(
        "<div style='padding-top:28px;color:#94A3B8;font-size:13px;'>"
        "💡 Aynı seed her zaman aynı veriyi üretir. Farklı bir tablo görmek için seed değiştirin."
        "</div>",
        unsafe_allow_html=True,
    )

if st.button("🚀 Demo Verisi Üret", type="primary", use_container_width=True):
    with st.spinner("Demo verisi oluşturuluyor... (bu 30-60 saniye sürebilir)"):
        added_p, added_f, msg = utils.generate_demo_data(seed=int(seed))
    st.success(f"✅ {msg}")
    st.balloons()
    time.sleep(0.5)
    st.rerun()

st.markdown("---")

# =================================================================
# BÖLÜM 2: SENKRONİZASYON
# =================================================================
st.markdown("### 🔄 Katılımcı Senkronizasyonu")
st.caption(
    "Tahmin tablosunda olup katılımcı listesinde olmayan isimleri katılımcı tablosuna ekler. "
    "Excel yüklemelerinden sonra işe yarar."
)

if st.button("🔄 Senkronize Et", use_container_width=True):
    with st.spinner("Taranıyor..."):
        count, msg = utils.sync_participants_from_forecasts()
    if count > 0:
        st.success(f"✅ {msg}")
    else:
        st.info("Liste zaten güncel.")
    time.sleep(0.8)
    st.rerun()

st.markdown("---")

# =================================================================
# BÖLÜM 3: SIFIRLAMA (DANGER ZONE)
# =================================================================
st.markdown("### 🔥 Sıfırlama — Dikkat!")

st.markdown(
    """
    <div class="danger-zone">
    <b style="color:#FCA5A5;">⚠️ Tehlike Bölgesi</b><br>
    <span style="color:#94A3B8;font-size:13px;">
    Aşağıdaki işlemler <b>geri alınamaz</b>. Demo sonrası gerçek veriye geçmek istediğinde kullan.
    </span>
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")

with st.expander("🗑️ Veri Sıfırlama Seçenekleri", expanded=False):
    reset_mode = st.radio(
        "Ne silinsin?",
        [
            "Sadece tahminler (katılımcılar kalsın)",
            "Hepsi (tahminler + katılımcılar)",
        ],
        key="reset_mode",
    )

    confirm = st.text_input(
        "Onaylamak için **SIL** yazınız (büyük harf)",
        placeholder="SIL",
        key="reset_confirm",
    )

    if st.button("🔥 Sıfırlamayı Başlat", type="primary", disabled=(confirm != "SIL")):
        participants_too = (reset_mode == "Hepsi (tahminler + katılımcılar)")
        with st.spinner("Siliniyor..."):
            ok, msg = utils.reset_all_data(participants_too=participants_too)
        if ok:
            st.success(f"✅ {msg}")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"Hata: {msg}")

    if confirm and confirm != "SIL":
        st.caption("❌ Onay kelimesi tam olarak **SIL** olmalı (büyük harf).")

st.markdown("---")

# =================================================================
# BÖLÜM 4: MEVCUT DURUM
# =================================================================
st.markdown("### 📊 Mevcut Durum")

try:
    df = utils.get_all_forecasts()
    df_k = utils.get_participants()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Tahmin", f"{len(df):,}")
    c2.metric("Katılımcı", f"{len(df_k)}")
    if not df.empty:
        c3.metric("Hedef Dönem", f"{df['hedef_donemi'].nunique()}")
        earliest = df["tahmin_tarihi"].min()
        latest = df["tahmin_tarihi"].max()
        if earliest and latest:
            c4.metric(
                "Tarih Aralığı",
                f"{earliest.strftime('%Y-%m')} — {latest.strftime('%Y-%m')}",
            )
except Exception as e:
    st.error(f"Durum alınamadı: {e}")

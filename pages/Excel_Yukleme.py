import io
import pandas as pd
import streamlit as st
import utils

st.set_page_config(page_title="Excel Yükleme", layout="wide")
utils.apply_theme()

utils.require_login_page()

utils.page_header("📥 Toplu Excel Yükleme", "Bir Excel dosyasıyla toplu tahmin ekle")

st.markdown(
    """
    <div class="soft-card">
      <h3>📋 Önemli Notlar</h3>
      <ul>
        <li><b>Kategori</b> sütunu: <code>Bireysel</code>, <code>Kurumsal</code>, <code>Anket</code></li>
        <li><b>Min/Max ve N</b> sadece <b>Anket</b> kategorisi için kullanılır, diğerlerinde yoksayılır</li>
        <li>Aynı (katılımcı, hedef dönem, tarih) kombinasyonu zaten varsa <b>güncellenir</b></li>
        <li>Bilinmeyen katılımcı varsa otomatik olarak katılımcı tablosuna eklenir</li>
      </ul>
    </div>
    """,
    unsafe_allow_html=True,
)


def generate_template() -> bytes:
    cols = [
        "Katılımcı Adı", "Hedef Dönem (YYYY-AA)", "Tarih (YYYY-AA-GG)", "Kategori", "Link",
        "PPK Medyan", "PPK Min", "PPK Max",
        "Yıl Sonu Faiz Medyan", "Yıl Sonu Faiz Min", "Yıl Sonu Faiz Max",
        "Aylık Enf Medyan", "Aylık Enf Min", "Aylık Enf Max",
        "Yıl Sonu Enf Medyan", "Yıl Sonu Enf Min", "Yıl Sonu Enf Max",
        "N Sayısı",
    ]
    df = pd.DataFrame(columns=cols)
    df.loc[0] = ["Örnek Anket", "2026-12", "2026-04-15", "Anket", "",
                 45.0, 42.0, 48.0, 40.0, 38.0, 42.0,
                 1.5, 1.2, 1.8, 35.0, 33.0, 37.0, 15]
    df.loc[1] = ["Örnek Banka", "2026-12", "2026-04-15", "Kurumsal", "",
                 45.0, None, None, 40.0, None, None,
                 1.5, None, None, 35.0, None, None, None]
    df.loc[2] = ["Örnek Yorumcu", "2026-12", "2026-04-15", "Bireysel", "",
                 45.0, None, None, 40.0, None, None,
                 1.5, None, None, 35.0, None, None, None]

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Sablon")
    return out.getvalue()


st.download_button(
    "📥 Excel Şablonu İndir",
    generate_template(),
    "Veri_Yukleme_Sablonu.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=False,
)

st.markdown("---")

uploaded_file = st.file_uploader("Excel Dosyası Seç", type=["xlsx"])


def _safe_float(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val):
    f = _safe_float(val)
    return int(f) if f is not None else None


if uploaded_file:
    try:
        df_upload = pd.read_excel(uploaded_file)
        st.markdown(f"**Yüklenen:** {len(df_upload)} satır")
        st.dataframe(df_upload.head(5), use_container_width=True)

        if st.button("🚀 Veritabanına Yükle", type="primary"):
            progress_bar = st.progress(0)
            status = st.empty()
            success_count = 0
            errors = []

            existing = utils.get_participants()
            existing_names = (
                set(existing["ad_soyad"].str.strip().str.lower())
                if not existing.empty else set()
            )

            total = len(df_upload)
            for index, row in df_upload.iterrows():
                try:
                    user = str(row["Katılımcı Adı"]).strip()
                    hedef = str(row["Hedef Dönem (YYYY-AA)"]).strip()
                    tarih = row["Tarih (YYYY-AA-GG)"]
                    cat = str(row.get("Kategori", "Bireysel")).strip()
                    if cat not in utils.KATEGORILER:
                        cat = "Bireysel"
                    link = row.get("Link")
                    if isinstance(link, float) and pd.isna(link):
                        link = None

                    if user.lower() not in existing_names:
                        ok, _ = utils.add_participant(user, cat)
                        if ok:
                            existing_names.add(user.lower())

                    data = {
                        "tahmin_ppk_faiz": _safe_float(row.get("PPK Medyan")),
                        "min_ppk_faiz": _safe_float(row.get("PPK Min")),
                        "max_ppk_faiz": _safe_float(row.get("PPK Max")),
                        "tahmin_yilsonu_faiz": _safe_float(row.get("Yıl Sonu Faiz Medyan")),
                        "min_yilsonu_faiz": _safe_float(row.get("Yıl Sonu Faiz Min")),
                        "max_yilsonu_faiz": _safe_float(row.get("Yıl Sonu Faiz Max")),
                        "tahmin_aylik_enf": _safe_float(row.get("Aylık Enf Medyan")),
                        "min_aylik_enf": _safe_float(row.get("Aylık Enf Min")),
                        "max_aylik_enf": _safe_float(row.get("Aylık Enf Max")),
                        "tahmin_yilsonu_enf": _safe_float(row.get("Yıl Sonu Enf Medyan")),
                        "min_yilsonu_enf": _safe_float(row.get("Yıl Sonu Enf Min")),
                        "max_yilsonu_enf": _safe_float(row.get("Yıl Sonu Enf Max")),
                        "katilimci_sayisi": _safe_int(row.get("N Sayısı")),
                    }

                    ok, msg = utils.upsert_tahmin(user, hedef, cat, tarih, link, data)
                    if ok:
                        success_count += 1
                    else:
                        errors.append(f"Satır {index + 2}: {msg}")

                except Exception as e:
                    errors.append(f"Satır {index + 2}: {e}")

                progress_bar.progress((index + 1) / total)
                status.text(f"İşlenen: {index + 1}/{total}")

            st.success(f"✅ {success_count}/{total} kayıt işlendi.")
            if errors:
                with st.expander(f"⚠️ {len(errors)} hata detayı"):
                    for err in errors[:50]:
                        st.text(err)
                    if len(errors) > 50:
                        st.text(f"... ve {len(errors) - 50} hata daha")

    except Exception as e:
        st.error(f"Dosya okuma hatası: {e}")

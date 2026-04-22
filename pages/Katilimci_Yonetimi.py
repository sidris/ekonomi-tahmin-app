import time
import pandas as pd
import streamlit as st
import utils

st.set_page_config(page_title="Katılımcı Yönetimi", layout="wide")
utils.apply_theme()

utils.require_login_page()

utils.page_header("👥 Katılımcı Yönetimi", "Kurumsal, anket ve bireysel katılımcıları düzenle")

col1, col2 = st.columns([1, 2], gap="large")

# ---- SOL: Yeni Ekleme ----
with col1:
    st.markdown(
        """
        <div class="soft-card">
          <h3>➕ Yeni Katılımcı</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("add_user_form", clear_on_submit=True):
        new_user = st.text_input("Ad / Kurum Adı")
        cat = st.selectbox(
            "Kategori",
            utils.KATEGORILER,
            help="Anket = min/max/N gerekir. Diğerleri tek nokta tahmin.",
        )
        submit = st.form_submit_button("Ekle", type="primary", use_container_width=True)

        if submit:
            ok, msg = utils.add_participant(new_user, cat)
            if ok:
                st.success(msg)
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(f"Hata: {msg}")

    # Özet
    df_summary = utils.get_participants()
    if not df_summary.empty:
        st.markdown("##### Dağılım")
        for kat in utils.KATEGORILER:
            n = (df_summary["kategori"] == kat).sum()
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:6px 0;"
                f"border-bottom:1px solid rgba(148,163,184,0.1);'>"
                f"<span style='color:#94A3B8;font-size:13px;'>{kat}</span>"
                f"<b style='font-variant-numeric:tabular-nums;'>{n}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )

# ---- SAĞ: Düzenleme ----
with col2:
    st.markdown("#### ✏️ Mevcut Liste")
    df = utils.get_participants()

    if df.empty:
        st.info("Henüz katılımcı eklenmemiş. Soldan ekleyebilirsiniz.")
    else:
        # Filtreleme
        fc1, fc2 = st.columns([2, 1])
        search = fc1.text_input("🔍 Ara", placeholder="İsim ara...")
        cat_filter = fc2.multiselect(
            "Kategori",
            utils.KATEGORILER,
            default=utils.KATEGORILER,
        )

        df_view = df[df["kategori"].isin(cat_filter)].copy()
        if search:
            df_view = df_view[
                df_view["ad_soyad"].str.contains(search, case=False, na=False)
            ]

        display_cols = [c for c in df_view.columns if c != "created_at"]
        edited_df = st.data_editor(
            df_view[display_cols],
            column_config={
                "id": None,
                "ad_soyad": st.column_config.TextColumn("Katılımcı Adı", required=True),
                "kategori": st.column_config.SelectboxColumn(
                    "Kategori",
                    width="medium",
                    options=utils.KATEGORILER,
                    required=True,
                ),
            },
            hide_index=True,
            use_container_width=True,
            key="participant_editor",
            num_rows="fixed",
            height=min(500, 50 + 35 * len(df_view)),
        )

        sc1, sc2 = st.columns([1, 1])
        with sc1:
            if st.button("💾 Değişiklikleri Kaydet", type="primary", use_container_width=True):
                progress = st.progress(0)
                total = len(edited_df)
                errors = []
                df_old_indexed = df.set_index("id")
                changed = 0

                for i, (_, row) in enumerate(edited_df.iterrows()):
                    row_id = row["id"]
                    new_name = row["ad_soyad"]
                    new_cat = row["kategori"]

                    try:
                        old_name = df_old_indexed.loc[row_id, "ad_soyad"]
                        old_cat = df_old_indexed.loc[row_id, "kategori"]
                        if old_name != new_name or old_cat != new_cat:
                            ok, msg = utils.update_participant(
                                row_id=row_id,
                                new_name=new_name,
                                new_category=new_cat,
                                old_name=old_name,
                            )
                            if ok:
                                changed += 1
                            else:
                                errors.append(f"{new_name}: {msg}")
                    except KeyError:
                        errors.append(f"{new_name}: ID bulunamadı")
                    except Exception as e:
                        errors.append(f"{new_name}: {e}")

                    progress.progress((i + 1) / total)

                if not errors:
                    st.success(f"✅ {changed} değişiklik kaydedildi!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Bazı hatalar oluştu:\n" + "\n".join(errors))

        with sc2:
            if st.button("🗑️ Seçili Katılımcıları Sil", use_container_width=True):
                st.warning(
                    "Silmek için aşağıdaki akordeonu kullanın — tek tek onay gerekir."
                )

        # Silme paneli
        with st.expander("🗑️ Katılımcı Sil (onay gerektirir)"):
            del_target = st.selectbox(
                "Silinecek katılımcı",
                df_view["ad_soyad"].tolist(),
                key="del_select",
            )
            if st.button("Sil", key="del_btn", type="secondary"):
                target_id = df_view[df_view["ad_soyad"] == del_target]["id"].iloc[0]
                ok, msg = utils.delete_participant(target_id)
                if ok:
                    st.success(msg)
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)

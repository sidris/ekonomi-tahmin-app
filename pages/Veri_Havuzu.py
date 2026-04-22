import streamlit as st
import utils

st.set_page_config(page_title="Veri Havuzu", layout="wide")
utils.apply_theme()

utils.require_login_page()

utils.page_header("🗃️ Veri Havuzu", "Tüm tahminleri görüntüle, filtrele ve sil")

df = utils.get_all_forecasts()

if df.empty:
    st.warning("Veri bulunamadı.")
    st.stop()

# ---- Filtreler ----
with st.container():
    st.markdown("#### 🔍 Filtreler")
    fc1, fc2, fc3 = st.columns(3)
    cats = sorted(df["kategori"].dropna().unique().tolist()) if "kategori" in df.columns else []
    sel_cats = fc1.multiselect("Kategori", cats, default=cats)

    users = sorted(df["kullanici_adi"].dropna().unique().tolist())
    sel_users = fc2.multiselect("Katılımcı", users)

    periods = sorted(df["hedef_donemi"].dropna().unique().tolist())
    sel_periods = fc3.multiselect("Hedef Dönem", periods)

df_view = df.copy()
if sel_cats:
    df_view = df_view[df_view["kategori"].isin(sel_cats)]
if sel_users:
    df_view = df_view[df_view["kullanici_adi"].isin(sel_users)]
if sel_periods:
    df_view = df_view[df_view["hedef_donemi"].isin(sel_periods)]

st.caption(f"📊 Gösterilen: **{len(df_view):,}** / {len(df):,} kayıt")

col1, col2 = st.columns([4, 1])
with col1:
    st.markdown(
        "<div style='color:#94A3B8;font-size:13px;'>"
        "Silmek için sağdaki toggle'ı açın ve satırları seçin."
        "</div>",
        unsafe_allow_html=True,
    )
with col2:
    delete_mode = st.toggle("🗑️ Silme Modu")

if delete_mode:
    st.warning("⚠️ Seçilen satırlar kalıcı olarak silinir.")

    df_sel = df_view.copy()
    df_sel.insert(0, "Sec", False)

    edited = st.data_editor(
        df_sel,
        column_config={"Sec": st.column_config.CheckboxColumn(required=True)},
        disabled=[c for c in df_sel.columns if c != "Sec"],
        hide_index=True,
        use_container_width=True,
        key="editor_delete",
        height=600,
    )

    selected_rows = edited[edited["Sec"] == True]

    if not selected_rows.empty:
        st.write(f"**{len(selected_rows)}** satır seçildi.")
        if st.button("🔥 Seçilenleri Sil", type="primary"):
            ids_to_delete = selected_rows["id"].tolist()
            ok, msg = utils.delete_tahmin_by_ids(ids_to_delete)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(f"Silme hatası: {msg}")
else:
    st.dataframe(df_view, use_container_width=True, height=600)

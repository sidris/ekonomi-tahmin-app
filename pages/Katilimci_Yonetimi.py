import streamlit as st
import utils
import pandas as pd

st.set_page_config(page_title="Katılımcı Yönetimi")
if not utils.check_login(): st.stop()

st.header("👥 Katılımcı Yönetimi")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Yeni Ekle")
    with st.form("add_user"):
        new_user = st.text_input("Ad Soyad / Kurum")
        cat = st.selectbox("Kategori", ["Bireysel", "Kurumsal", "Anket"])
        if st.form_submit_button("Ekle"):
            try:
                utils.supabase.table(utils.TABLE_KATILIMCI).insert({"ad_soyad": new_user, "kategori": cat}).execute()
                st.success(f"{new_user} eklendi!")
                st.rerun()
            except Exception as e:
                st.error(str(e))

with col2:
    st.subheader("Mevcut Liste")
    df = utils.get_participants()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Kimse yok.")
        
st.markdown("---")
st.caption("Not: Katılımcı silmek veri bütünlüğünü bozabileceği için şimdilik devre dışı bırakılmıştır. Veritabanı yöneticisi ile görüşün.")

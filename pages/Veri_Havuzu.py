import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="Veri Havuzu", layout="wide")
if not utils.check_login(): st.stop()

st.title("🗃️ Veri Havuzu (Düzenle & Sil)")

# Verileri Çek
df = utils.get_all_forecasts()

if df.empty:
    st.warning("Veri bulunamadı.")
    st.stop()

# Silme Modu Toggle
col1, col2 = st.columns([4, 1])
with col1: st.info("Hücrelere çift tıklayarak düzenleyebilirsiniz (Şu an sadece görseldir, düzenleme için veritabanı API'si gerekir). Silmek için sağdaki butonu kullanın.")
with col2: delete_mode = st.toggle("🗑️ Silme Modunu Aç")

if delete_mode:
    st.error("DİKKAT: Seçilen satırlar kalıcı olarak silinecektir!")
    
    # Checkbox sütunu ekle
    df_with_selections = df.copy()
    df_with_selections.insert(0, "Sec", False)
    
    # Data Editor ile seçim yapma
    edited = st.data_editor(
        df_with_selections,
        column_config={"Sec": st.column_config.CheckboxColumn(required=True)},
        disabled=[c for c in df.columns if c != "Sec"],
        hide_index=True,
        use_container_width=True,
        key="editor_delete"
    )
    
    selected_rows = edited[edited["Sec"] == True]
    
    if not selected_rows.empty:
        st.write(f"{len(selected_rows)} satır seçildi.")
        if st.button("🔥 SEÇİLENLERİ SİL"):
            ids_to_delete = selected_rows['id'].tolist()
            try:
                utils.supabase.table(utils.TABLE_TAHMIN).delete().in_("id", ids_to_delete).execute()
                st.success("Kayıtlar silindi!")
                st.cache_data.clear() # Cache temizle ki liste güncellensin
                st.rerun()
            except Exception as e:
                st.error(f"Silme hatası: {e}")
else:
    # Sadece Görüntüleme Modu
    st.dataframe(df, use_container_width=True, height=600)

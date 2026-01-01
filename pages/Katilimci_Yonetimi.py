import streamlit as st
import utils
import pandas as pd
import time

st.set_page_config(page_title="Katılımcı Yönetimi", layout="wide")
if not utils.check_login(): st.stop()

st.title("👥 Katılımcı Yönetimi")

# --- 1. EŞLEME (SYNC) BÖLÜMÜ ---
st.info("💡 **İpucu:** Excel ile yüklediğiniz kişiler listede görünmüyorsa aşağıdaki butona basarak veritabanını eşleyiniz.")

if st.button("🔄 Listeyi Veri Havuzuyla Eşle (Sync)"):
    with st.spinner("Tahmin tablosu taranıyor ve eksik kişiler ekleniyor..."):
        count, msg = utils.sync_participants_from_forecasts()
        if count > 0:
            st.success(f"İşlem Tamam! {msg}")
            time.sleep(1)
            st.rerun()
        else:
            st.success("Liste zaten güncel.")

st.markdown("---")

# --- 2. DÜZENLEME VE LİSTELEME BÖLÜMÜ ---
col1, col2 = st.columns([1, 2])

# SOL KOLON: Yeni Ekleme
with col1:
    st.subheader("➕ Yeni Kişi Ekle")
    with st.form("add_user_form"):
        new_user = st.text_input("Ad Soyad / Kurum Adı")
        cat = st.selectbox("Kategori", ["Bireysel", "Kurumsal", "Anket"])
        submit = st.form_submit_button("Ekle")
        
        if submit:
            if new_user:
                try:
                    utils.supabase.table(utils.TABLE_KATILIMCI).insert({"ad_soyad": new_user, "kategori": cat}).execute()
                    st.success("Eklendi!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")
            else:
                st.warning("İsim boş olamaz.")

# SAĞ KOLON: Düzenlenebilir Liste
with col2:
    st.subheader("✏️ Mevcut Listeyi Düzenle")
    
    # Veriyi veritabanından çek
    df = utils.get_participants()
    
    if not df.empty:
        # ID sütununu gizleyip, Kategori sütununu Selectbox yapalım
        edited_df = st.data_editor(
            df,
            column_config={
                "id": None, # ID'yi gizle (kullanıcı değiştirmesin)
                "ad_soyad": "Katılımcı Adı",
                "kategori": st.column_config.SelectboxColumn(
                    "Kategori",
                    help="Kategoriyi değiştirmek için seçiniz",
                    width="medium",
                    options=[
                        "Bireysel",
                        "Kurumsal",
                        "Anket"
                    ],
                    required=True
                )
            },
            disabled=["created_at"], # Tarih değiştirilemesin
            hide_index=True,
            use_container_width=True,
            key="participant_editor"
        )

        st.caption("⚠️ Tablo üzerinde değişiklik yaptıktan sonra kaydetmek için aşağıdaki butona basınız.")
        
        if st.button("💾 Değişiklikleri Kaydet"):
            # Değişiklikleri algıla
            # Streamlit data_editor tüm tabloyu döndürür. Veritabanı ile karşılaştırıp farkları bulmak yerine
            # daha güvenli bir yöntem olarak: Dataframe'deki her satırı ID'sine göre güncelleyebiliriz.
            # Ancak performans için sadece değişenleri bulmak daha iyidir ama basitlik adına loop kuralım.
            
            progress = st.progress(0)
            total = len(edited_df)
            errors = []
            
            for index, row in edited_df.iterrows():
                # Orjinal veriden farklı mı diye kontrol etmek (Pandas merge) karmaşık olabilir.
                # Kullanıcı sayısı az olduğu için (muhtemelen <1000) her satırı upsert/update yapmak sorun olmaz.
                
                # Eski ismi bulmamız lazım (İsim değişikliği varsa forecast tablosunu da güncellemek için)
                # Bu örnekte karmaşıklığı önlemek için veritabanındaki ID'ye göre işlem yapıyoruz.
                try:
                    # Orjinal isme ihtiyacımız var, bunun için df'den (eski veri) ID ile çekelim
                    old_row = df[df['id'] == row['id']].iloc[0]
                    old_name = old_row['ad_soyad']
                    
                    utils.update_participant(
                        old_name=old_name, 
                        new_name=row['ad_soyad'], 
                        new_category=row['kategori'], 
                        row_id=row['id']
                    )
                except Exception as e:
                    errors.append(f"{row['ad_soyad']} güncellenemedi: {e}")
                
                progress.progress((index + 1) / total)
            
            if not errors:
                st.success("✅ Tüm değişiklikler başarıyla kaydedildi!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"Bazı hatalar oluştu: {errors}")

    else:
        st.info("Henüz katılımcı eklenmemiş.")

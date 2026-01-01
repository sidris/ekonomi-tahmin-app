import streamlit as st
import pandas as pd
import io
import utils

st.set_page_config(page_title="Excel Yükleme", layout="wide")
if not utils.check_login(): st.stop()

st.title("📥 Toplu Veri Yükleme (Excel)")

# Şablon Oluşturma
def generate_template():
    df = pd.DataFrame(columns=[
        "Katılımcı Adı", "Hedef Dönem (YYYY-AA)", "Tarih (YYYY-AA-GG)", "Kategori", "Link",
        "PPK Medyan", "PPK Min", "PPK Max",
        "Yıl Sonu Faiz Medyan", "Yıl Sonu Faiz Min", "Yıl Sonu Faiz Max",
        "Aylık Enf Medyan", "Aylık Enf Min", "Aylık Enf Max",
        "Yıl Sonu Enf Medyan", "Yıl Sonu Enf Min", "Yıl Sonu Enf Max",
        "N Sayısı"
    ])
    # Örnek Satır
    df.loc[0] = ["Örnek Banka", "2025-12", "2025-01-15", "Kurumsal", "", 45.0, 42.0, 48.0, 40.0, 38.0, 42.0, 1.5, 1.2, 1.8, 35.0, 33.0, 37.0, 15]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

st.download_button("📥 Excel Şablonunu İndir", generate_template(), "Veri_Yukleme_Sablonu.xlsx")

uploaded_file = st.file_uploader("Excel Dosyası Seç", type=["xlsx"])

if uploaded_file:
    try:
        df_upload = pd.read_excel(uploaded_file)
        st.write("Yüklenen Veri Önizlemesi:", df_upload.head(3))
        
        if st.button("🚀 Veritabanına Yükle"):
            progress_bar = st.progress(0)
            success_count = 0
            
            # Mevcut katılımcıları al ki tekrar tekrar eklemeye çalışmayalım (Basit kontrol)
            existing_participants = set(utils.get_participants()['ad_soyad'].tolist())

            for index, row in df_upload.iterrows():
                try:
                    user = str(row["Katılımcı Adı"]).strip()
                    hedef = str(row["Hedef Dönem (YYYY-AA)"]).strip()
                    tarih = row["Tarih (YYYY-AA-GG)"]
                    cat = str(row.get("Kategori", "Bireysel"))
                    link = str(row.get("Link", ""))
                    
                    # Kullanıcı yoksa ekle
                    if user not in existing_participants:
                        utils.supabase.table(utils.TABLE_KATILIMCI).insert({"ad_soyad": user, "kategori": cat}).execute()
                        existing_participants.add(user)

                    # Helper: Güvenli Float Çevirme
                    def get_float(col_name):
                        val = row.get(col_name)
                        try:
                            f = float(val)
                            return f if pd.notnull(f) else None
                        except: return None

                    data = {
                        "tahmin_ppk_faiz": get_float("PPK Medyan"),
                        "min_ppk_faiz": get_float("PPK Min"),
                        "max_ppk_faiz": get_float("PPK Max"),
                        "tahmin_yilsonu_faiz": get_float("Yıl Sonu Faiz Medyan"),
                        "min_yilsonu_faiz": get_float("Yıl Sonu Faiz Min"),
                        "max_yilsonu_faiz": get_float("Yıl Sonu Faiz Max"),
                        "tahmin_aylik_enf": get_float("Aylık Enf Medyan"),
                        "min_aylik_enf": get_float("Aylık Enf Min"),
                        "max_aylik_enf": get_float("Aylık Enf Max"),
                        "tahmin_yilsonu_enf": get_float("Yıl Sonu Enf Medyan"),
                        "min_yilsonu_enf": get_float("Yıl Sonu Enf Min"),
                        "max_yilsonu_enf": get_float("Yıl Sonu Enf Max"),
                        "katilimci_sayisi": int(get_float("N Sayısı") or 1)
                    }
                    
                    utils.upsert_tahmin(user, hedef, cat, tarih, link, data)
                    success_count += 1
                except Exception as e:
                    st.error(f"Satır {index+1} hatası: {e}")
                
                progress_bar.progress((index + 1) / len(df_upload))
            
            st.success(f"✅ {success_count} kayıt başarıyla işlendi.")
            
    except Exception as e:
        st.error(f"Dosya okuma hatası: {e}")

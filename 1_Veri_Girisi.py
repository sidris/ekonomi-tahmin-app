import streamlit as st
# Supabase bağlantı kodlarınız burada olacak...

st.header("Tahmin Girişi")

# Katılımcı Seçimi (Veritabanından çekilir)
participants = supabase.table("participants").select("*").execute().data
participant_names = [p['name'] for p in participants]
selected_name = st.selectbox("Katılımcı Seçiniz", participant_names)

# Seçilen kişinin türünü bul
selected_type = next(item['type'] for item in participants if item['name'] == selected_name)

st.divider()

# Form Alanı
col1, col2 = st.columns(2)
with col1:
    category = st.selectbox("Veri Tipi", ["Enflasyon", "Faiz"])
    term = st.selectbox("Vade", ["Aylık", "Yıl Sonu"])
with col2:
    target_date = st.date_input("Hedef Dönem (Ay/Yıl)")

st.subheader("Tahmin Değerleri")

# DİNAMİK FORM MANTIĞI
if selected_type == "anket":
    c1, c2, c3 = st.columns(3)
    val_min = c1.number_input("Min Tahmin", format="%.2f")
    val_med = c2.number_input("Medyan Tahmin", format="%.2f")
    val_max = c3.number_input("Max Tahmin", format="%.2f")
    val_single = None
else:
    # Bireysel veya Kurumsal
    val_single = st.number_input(f"{selected_name} Tahmini", format="%.2f")
    val_min, val_med, val_max = None, None, None

# Kaydet Butonu
if st.button("Kaydet"):
    # Supabase insert işlemi...
    # Veriyi 'forecasts' tablosuna uygun sütunlara yazacağız.
    st.success("Tahmin başarıyla kaydedildi!")

# Excel Yükleme Alanı
st.divider()
st.subheader("Toplu Yükleme (Excel)")
uploaded_file = st.file_uploader("Excel dosyasını sürükleyin", type=["xlsx"])
if uploaded_file:
    # pandas ile oku ve veritabanı formatına çevirip toplu insert et
    pass

import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import tempfile
import os

# --- 1. AYARLAR VE BAĞLANTI ---
st.set_page_config(page_title="Ekonomi Tahmin Platformu", layout="wide")

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    SITE_SIFRESI = st.secrets["APP_PASSWORD"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Lütfen secrets ayarlarınızı kontrol edin.")
    st.stop()

TABLE_TAHMIN = "tahminler4"
TABLE_KATILIMCI = "katilimcilar"

# --- YARDIMCI FONKSİYONLAR ---
def get_period_list():
    years = range(2024, 2033)
    months = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    period_list = []
    for y in years:
        for m in months:
            period_list.append(f"{y}-{m}")
    return period_list

tum_donemler = get_period_list()

def normalize_name(name):
    return name.strip().title() if name else ""

# --- PDF RAPOR OLUŞTURMA FONKSİYONU ---
def create_pdf_report(dataframe, figures):
    class PDF(FPDF):
        def header(self):
            self.set_font('Helvetica', 'B', 15)
            self.cell(0, 10, 'Ekonomi Tahmin Raporu', align='C')
            self.ln(15)
        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.cell(0, 10, f'Sayfa {self.page_no()}', align='C')

    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Rapor Tarihi: {pd.Timestamp.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.cell(0, 10, f"Toplam Tahmin Sayisi: {len(dataframe)}", ln=True)
    pdf.ln(5)
    
    for title, fig in figures.items():
        pdf.add_page()
        pdf.set_font("Helvetica", 'B', 14)
        clean_title = title.replace("ı", "i").replace("ğ", "g").replace("ş", "s").replace("İ", "I").replace("ö", "o").replace("ü", "u").replace("ç", "c")
        pdf.cell(0, 10, clean_title, ln=True, align='C')
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
            try:
                fig.write_image(tmpfile.name, width=800, height=500, scale=2)
                pdf.image(tmpfile.name, x=10, y=30, w=190)
            except Exception as e:
                st.error(f"Grafik işlenirken hata: {e}")
        try: os.remove(tmpfile.name)
        except: pass
            
    return bytes(pdf.output())

# --- 2. GİRİŞ KONTROLÜ ---
if 'giris_yapildi' not in st.session_state:
    st.session_state['giris_yapildi'] = False

def sifre_kontrol():
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("### 🔐 Giriş Paneli")
        sifre = st.text_input("Giriş Şifresi", type="password")
        if st.button("Giriş Yap", use_container_width=True):
            if sifre == SITE_SIFRESI:
                st.session_state['giris_yapildi'] = True
                st.rerun()
            else:
                st.error("Hatalı şifre!")

if not st.session_state['giris_yapildi']:
    sifre_kontrol()
    st.stop()

# --- 3. ANA UYGULAMA ---
st.title("📈 Makroekonomi Tahmin Merkezi")
st.markdown("---")

page = st.sidebar.radio("Menü", ["➕ Tahmin Ekle", "✏️ Düzenle / İncele", "👥 Katılımcı Yönetimi", "📊 Genel Dashboard"])

# ========================================================
# SAYFA 0: KATILIMCI YÖNETİMİ
# ========================================================
if page == "👥 Katılımcı Yönetimi":
    st.header("Katılımcı Listesi ve Ekleme")
    
    with st.form("yeni_kisi_form"):
        st.subheader("Yeni Katılımcı Tanımla")
        c1, c2 = st.columns(2)
        yeni_ad = c1.text_input("Ad Soyad / Kurum Adı (Örn: AlBaraka)")
        yeni_kat = c2.radio("Kategori", ["Bireysel", "Kurumsal"], horizontal=True)
        
        # YENİ ALAN: ANKET KAYNAĞI
        anket_kaynagi = st.text_input("Anket Kaynağı (Opsiyonel - Örn: Reuters, Bloomberg)", placeholder="Boş bırakılabilir")
        
        if st.form_submit_button("Listeye Ekle"):
            if yeni_ad:
                clean_ad = normalize_name(yeni_ad)
                anket_val = anket_kaynagi.strip() if anket_kaynagi else None
                
                try:
                    data = {"ad_soyad": clean_ad, "kategori": yeni_kat, "anket_kaynagi": anket_val}
                    supabase.table(TABLE_KATILIMCI).insert(data).execute()
                    st.success(f"{clean_ad} başarıyla eklendi!")
                except Exception as e:
                    st.warning("Bu isim zaten listede olabilir.")
            else:
                st.warning("İsim boş olamaz.")
    
    st.markdown("---")
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res.data)
    
    if not df_kat.empty:
        st.subheader("Mevcut Katılımcılar")
        # Anket kaynağını da tabloda gösterelim
        st.dataframe(df_kat[["ad_soyad", "kategori", "anket_kaynagi"]], use_container_width=True)
        
        with st.expander("🗑️ Kişi Silme Paneli"):
            kisi_sil = st.selectbox("Silinecek Kişiyi Seç", df_kat["ad_soyad"].unique())
            if st.button("Seçili Kişiyi Sil"):
                supabase.table(TABLE_KATILIMCI).delete().eq("ad_soyad", kisi_sil).execute()
                st.success("Silindi! Sayfayı yenileyin.")
    else:
        st.info("Listeniz boş.")

# ========================================================
# SAYFA 1: YENİ VERİ GİRİŞİ
# ========================================================
elif page == "➕ Tahmin Ekle":
    st.header("Veri Girişi")

    res_kat = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res_kat.data)

    if df_kat.empty:
        st.error("Lütfen önce 'Katılımcı Yönetimi' menüsünden katılımcı ekleyin.")
        st.stop()

    with st.form("tahmin_formu"):
        c_sel, c_don = st.columns(2)
        with c_sel:
            # Görselleştirme için ismi "Ad (Kaynak)" formatına çeviriyoruz ama seçince sadece adı alacağız
            df_kat['display_text'] = df_kat.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
            
            # Dictionary ile display_text -> ad_soyad eşleştirmesi
            name_map = dict(zip(df_kat['display_text'], df_kat['ad_soyad']))
            
            selected_display = st.selectbox("Katılımcı Seç", df_kat["display_text"].unique())
            selected_real_name = name_map[selected_display] # Veritabanına gidecek gerçek isim
            
            # Seçilen kişinin detayları
            person_row = df_kat[df_kat["ad_soyad"] == selected_real_name].iloc[0]
            st.caption(f"Kategori: **{person_row['kategori']}** | Kaynak: **{person_row['anket_kaynagi'] or '-'}**")

        with c_don:
            donem = st.selectbox("Tahmin Dönemi", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)

        st.markdown("---")
        
        # --- 1. GRUP: AYLIK ENFLASYON ---
        st.markdown("#### 📅 1. Aylık Enflasyon Tahmini")
        col_m1, col_m2, col_m3 = st.columns([2, 1, 1])
        val_aylik = col_m1.number_input("Medyan %", key="v_ay", step=0.1, format="%.2f")
        min_aylik = col_m2.number_input("Min %", key="min_ay", step=0.1, format="%.2f")
        max_aylik = col_m3.number_input("Max %", key="max_ay", step=0.1, format="%.2f")

        # --- 2. GRUP: YILLIK ENFLASYON ---
        st.markdown("#### 📉 2. Yıllık Enflasyon Tahmini")
        col_y1, col_y2, col_y3 = st.columns([2, 1, 1])
        val_yillik = col_y1.number_input("Medyan %", key="v_yil", step=0.1, format="%.2f")
        min_yillik = col_y2.number_input("Min %", key="min_yil", step=0.1, format="%.2f")
        max_yillik = col_y3.number_input("Max %", key="max_yil", step=0.1, format="%.2f")
        
        # --- 3. GRUP: YIL SONU ---
        st.markdown("#### 🏁 3. Yıl Sonu Enflasyon Tahmini")
        col_ys1, col_ys2, col_ys3 = st.columns([2, 1, 1])
        val_yilsonu = col_ys1.number_input("Medyan %", key="v_ysonu", step=0.1, format="%.2f")
        min_yilsonu = col_ys2.number_input("Min %", key="min_ysonu", step=0.1, format="%.2f")
        max_yilsonu = col_ys3.number_input("Max %", key="max_ysonu", step=0.1, format="%.2f")

        # --- 4. GRUP: FAİZ ---
        st.markdown("#### 🏦 4. PPK Faiz Kararı")
        col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
        val_faiz = col_f1.number_input("Medyan %", key="v_faiz", step=0.25, format="%.2f")
        min_faiz = col_f2.number_input("Min %", key="min_faiz", step=0.25, format="%.2f")
        max_faiz = col_f3.number_input("Max %", key="max_faiz", step=0.25, format="%.2f")

        if st.form_submit_button("💾 Kaydet"):
            check_res = supabase.table(TABLE_TAHMIN).select("id").eq("kullanici_adi", selected_real_name).eq("donem", donem).execute()
            
            if check_res.data:
                st.warning(f"⚠️ {selected_display} için {donem} kaydı zaten var.")
            else:
                def clean_val(val): return val if val != 0 else None
                yeni_veri = {
                    "kullanici_adi": selected_real_name, "donem": donem, "kategori": person_row['kategori'],
                    "tahmin_aylik_enf": val_aylik, "tahmin_yillik_enf": val_yillik, "tahmin_yilsonu_enf": val_yilsonu, "tahmin_ppk_faiz": val_faiz,
                    "min_aylik_enf": clean_val(min_aylik), "max_aylik_enf": clean_val(max_aylik),
                    "min_yillik_enf": clean_val(min_yillik), "max_yillik_enf": clean_val(max_yillik),
                    "min_yilsonu_enf": clean_val(min_yilsonu), "max_yilsonu_enf": clean_val(max_yilsonu),
                    "min_ppk_faiz": clean_val(min_faiz), "max_ppk_faiz": clean_val(max_faiz),
                }
                supabase.table(TABLE_TAHMIN).insert(yeni_veri).execute()
                st.success(f"✅ {selected_display} verisi başarıyla eklendi!")

# ========================================================
# SAYFA 2: DÜZENLEME
# ========================================================
elif page == "✏️ Düzenle / İncele":
    st.header("Kayıt Düzenleme")
    res_users = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        # İsimleri formatlı göster
        df_users['display_text'] = df_users.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
        name_map = dict(zip(df_users['display_text'], df_users['ad_soyad']))
        
        selected_display = st.selectbox("Düzenlenecek Kişi/Kurum:", df_users["display_text"])
        selected_real_name = name_map[selected_display]

        res_records = supabase.table(TABLE_TAHMIN).select("*").eq("kullanici_adi", selected_real_name).order("donem", desc=True).execute()
        df_records = pd.DataFrame(res_records.data)

        if not df_records.empty:
            st.dataframe(df_records, use_container_width=True)
            record_options = {f"{row['donem']}": row for index, row in df_records.iterrows()}
            selected_period_key = st.selectbox("Dönem Seç:", list(record_options.keys()))
            target_record = record_options[selected_period_key]

            with st.form("edit_single_form"):
                st.subheader(f"{target_record['donem']} Verilerini Düzenle")
                def get_val(rec, key): return float(rec.get(key) or 0)

                st.markdown("**1. Aylık Enflasyon**")
                c1, c2, c3 = st.columns([2,1,1])
                e_aylik = c1.number_input("Medyan", value=get_val(target_record, 'tahmin_aylik_enf'), step=0.1)
                em_min_ay = c2.number_input("Min", value=get_val(target_record, 'min_aylik_enf'), step=0.1)
                em_max_ay = c3.number_input("Max", value=get_val(target_record, 'max_aylik_enf'), step=0.1)

                st.markdown("**2. Yıl Sonu Enflasyon**")
                c1, c2, c3 = st.columns([2,1,1])
                e_yilsonu = c1.number_input("Medyan", value=get_val(target_record, 'tahmin_yilsonu_enf'), step=0.1)
                em_min_ys = c2.number_input("Min", value=get_val(target_record, 'min_yilsonu_enf'), step=0.1)
                em_max_ys = c3.number_input("Max", value=get_val(target_record, 'max_yilsonu_enf'), step=0.1)

                st.markdown("**3. PPK Faiz**")
                c1, c2, c3 = st.columns([2,1,1])
                e_faiz = c1.number_input("Medyan", value=get_val(target_record, 'tahmin_ppk_faiz'), step=0.25)
                em_min_faiz = c2.number_input("Min", value=get_val(target_record, 'min_ppk_faiz'), step=0.25)
                em_max_faiz = c3.number_input("Max", value=get_val(target_record, 'max_ppk_faiz'), step=0.25)

                if st.form_submit_button("Güncelle"):
                    def clean_val(val): return val if val != 0 else None
                    upd_data = {
                        "tahmin_aylik_enf": e_aylik, "min_aylik_enf": clean_val(em_min_ay), "max_aylik_enf": clean_val(em_max_ay),
                        "tahmin_yilsonu_enf": e_yilsonu, "min_yilsonu_enf": clean_val(em_min_ys), "max_yilsonu_enf": clean_val(em_max_ys),
                        "tahmin_ppk_faiz": e_faiz, "min_ppk_faiz": clean_val(em_min_faiz), "max_ppk_faiz": clean_val(em_max_faiz)
                    }
                    supabase.table(TABLE_TAHMIN).update(upd_data).eq("id", target_record['id']).execute()
                    st.success("Kayıt başarıyla güncellendi!")

# ========================================================
# SAYFA 3: DASHBOARD
# ========================================================
elif page == "📊 Genel Dashboard":
    st.header("Piyasa Analiz Dashboardu")

    # 1. Tahminleri ve 2. Katılımcıları Çekip Birleştireceğiz (Merge)
    res_tahmin = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_tahmin = pd.DataFrame(res_tahmin.data)
    
    res_kat = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_kat = pd.DataFrame(res_kat.data)

    if not df_tahmin.empty and not df_kat.empty:
        # PANDAS MERGE (SQL JOIN GİBİ): İki tabloyu ad_soyad üzerinden birleştir
        df = pd.merge(df_tahmin, df_kat, left_on="kullanici_adi", right_on="ad_soyad", how="left")
        
        # GÖRÜNEN İSİM OLUŞTURMA: Varsa kaynağı ekle, yoksa sadece isim
        df['gorunen_isim'] = df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)
        
        df['kategori'] = df['kategori'].fillna('Bireysel')
        df = df.sort_values(by="donem")

        st.sidebar.header("🔍 Filtreler")
        cat_filter = st.sidebar.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
        
        # Filtrelerde de "Görünen İsim" kullanıyoruz
        available_users = sorted(df[df['kategori'].isin(cat_filter)]['gorunen_isim'].unique())
        user_filter = st.sidebar.multiselect("Katılımcı", available_users, default=available_users)
        
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
        year_filter = st.sidebar.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        # Ana Filtreleme (Görünen isme göre)
        df_filtered = df[df['kategori'].isin(cat_filter) & df['gorunen_isim'].isin(user_filter) & df['yil'].isin(year_filter)]

        if df_filtered.empty: st.stop()

        report_figures = {}
        tab_ts, tab_dev = st.tabs(["📈 Zaman Serisi", "🍭 Medyan Sapma"])

        with tab_ts:
            def plot_with_range(df_sub, y_col, min_col, max_col, title):
                # Renk ayrımında 'gorunen_isim' kullanıyoruz
                fig = px.line(df_sub, x="donem", y=y_col, color="gorunen_isim", markers=True, title=title)
                
                df_range = df_sub.dropna(subset=[min_col, max_col])
                if not df_range.empty:
                    for user in df_range['gorunen_isim'].unique():
                        user_data = df_range[df_range['gorunen_isim'] == user]
                        fig.add_trace(go.Scatter(x=user_data['donem'], y=user_data[y_col], mode='markers', 
                                                 error_y=dict(type='data', symmetric=False, array=user_data[max_col] - user_data[y_col], arrayminus=user_data[y_col] - user_data[min_col], color='gray', width=3), 
                                                 showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
                return fig 

            c1, c2 = st.columns(2)
            with c1: report_figures["Aylik Enflasyon"] = plot_with_range(df_filtered, "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "Aylık Enflasyon")
            with c2: report_figures["Yil Sonu Enflasyon"] = plot_with_range(df_filtered, "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "Yıl Sonu Enf.")
            st.markdown("---")
            c3, c4 = st.columns(2)
            with c3: report_figures["PPK Faiz Orani"] = plot_with_range(df_filtered, "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Faiz")
            with c4: st.dataframe(df_filtered[['donem', 'gorunen_isim', 'kategori', 'tahmin_aylik_enf', 'tahmin_yilsonu_enf', 'tahmin_ppk_faiz']], use_container_width=True)

        with tab_dev:
            if not df_filtered.empty:
                last_period = df_filtered['donem'].max()
                df_period = df_filtered[df_filtered['donem'] == last_period].copy()
                if len(df_period) > 1:
                    metric = "tahmin_ppk_faiz"
                    median_val = df_period[metric].median()
                    df_period['sapma'] = df_period[metric] - median_val
                    df_period = df_period.sort_values(by='sapma')
                    fig_loli = go.Figure()
                    for i, row in df_period.iterrows():
                        color = "crimson" if row['sapma'] < 0 else "seagreen"
                        fig_loli.add_trace(go.Scatter(x=[0, row['sapma']], y=[row['gorunen_isim'], row['gorunen_isim']], mode='lines', line=dict(color=color), showlegend=False))
                        fig_loli.add_trace(go.Scatter(x=[row['sapma']], y=[row['gorunen_isim']], mode='markers', marker=dict(color=color, size=12), name=row['gorunen_isim'], text=f"Tahmin: %{row[metric]}", hoverinfo='text'))
                    fig_loli.add_vline(x=0, line_dash="dash", annotation_text="Medyan")
                    fig_loli.update_layout(title=f"PPK Faiz - Sapma ({last_period})", height=max(400, len(df_period)*30))
                    st.plotly_chart(fig_loli, use_container_width=True)
                    report_figures["Son Donem Sapma"] = fig_loli

        st.markdown("---")
        st.subheader("🖨️ Raporlama")
        if st.button("📄 PDF Raporu Oluştur"):
            with st.spinner("Hazırlanıyor..."):
                try:
                    pdf_data = create_pdf_report(df_filtered, report_figures)
                    st.download_button(label="⬇️ PDF İndir", data=pdf_data, file_name="rapor.pdf", mime="application/pdf")
                    st.success("Hazır!")
                except Exception as e:
                    st.error(f"Hata: {e}")

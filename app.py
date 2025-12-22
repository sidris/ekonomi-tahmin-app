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

# --- AKILLI KAYIT FONKSİYONU (UPSERT) ---
def upsert_tahmin(user, period, category, data_dict):
    """
    Bu fonksiyon:
    1. Önce bu kişi ve dönem için kayıt var mı diye bakar.
    2. Varsa: Sadece yeni gelen alanları GÜNCELLER (Update).
    3. Yoksa: Yeni bir satır EKLER (Insert).
    Böylece PPK ve Enflasyon ayrı girilse bile aynı satırda birleşir.
    """
    # 1. Kontrol Et
    check_res = supabase.table(TABLE_TAHMIN).select("id").eq("kullanici_adi", user).eq("donem", period).execute()
    
    # Boş değerleri None yap (Veritabanı temizliği için)
    clean_data = {k: (v if v != 0 else None) for k, v in data_dict.items()}
    
    # Kategori bilgisini de ekle
    clean_data["kullanici_adi"] = user
    clean_data["donem"] = period
    clean_data["kategori"] = category

    if check_res.data:
        # 2. Varsa Güncelle (ID üzerinden)
        record_id = check_res.data[0]['id']
        # ID hariç güncelle
        supabase.table(TABLE_TAHMIN).update(clean_data).eq("id", record_id).execute()
        return "updated"
    else:
        # 3. Yoksa Ekle
        supabase.table(TABLE_TAHMIN).insert(clean_data).execute()
        return "inserted"

# --- PDF FONKSİYONU ---
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
    pdf.cell(0, 10, f"Veri Sayisi: {len(dataframe)}", ln=True)
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
            except: pass
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

# YENİ MENÜ YAPISI
menu_items = ["📊 Dashboard", "➕ PPK Verisi Gir", "➕ Enflasyon Verisi Gir", "✏️ Düzenle / Sil", "👥 Katılımcı Yönetimi"]
page = st.sidebar.radio("Menü", menu_items)

# Ortak Katılımcı Seçim Fonksiyonu
def get_participant_selection():
    res_kat = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_kat = pd.DataFrame(res_kat.data)
    if df_kat.empty:
        st.error("Lütfen önce Katılımcı ekleyin.")
        return None, None, None
    
    df_kat['display'] = df_kat.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
    name_map = dict(zip(df_kat['display'], df_kat['ad_soyad']))
    
    sel_disp = st.selectbox("Katılımcı Seç", df_kat["display"].unique())
    real_name = name_map[sel_disp]
    row = df_kat[df_kat["ad_soyad"] == real_name].iloc[0]
    
    st.caption(f"Kategori: **{row['kategori']}** | Kaynak: {row['anket_kaynagi'] or '-'}")
    return real_name, row['kategori'], sel_disp

# ========================================================
# SAYFA: PPK VERİSİ GİR (AYRI)
# ========================================================
if page == "➕ PPK Verisi Gir":
    st.header("🏦 PPK Faiz Tahmini Girişi")
    
    with st.form("ppk_form"):
        c1, c2 = st.columns(2)
        with c1:
            kullanici, kategori, display_name = get_participant_selection()
        with c2:
            donem = st.selectbox("Dönem", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)

        st.markdown("---")
        
        # Sadece PPK Alanları
        col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
        val_faiz = col_f1.number_input("Medyan (Beklenti) %", step=0.25, format="%.2f")
        min_faiz = col_f2.number_input("Min %", step=0.25, format="%.2f")
        max_faiz = col_f3.number_input("Max %", step=0.25, format="%.2f")

        # Katılımcı Sayısı
        st.markdown("---")
        kat_sayisi = st.number_input("Anket Katılımcı Sayısı (N)", min_value=0, step=1, help="Sadece kurumlar için, kaç kişinin katıldığı.")

        if st.form_submit_button("PPK Verisini Kaydet"):
            if kullanici:
                data = {
                    "tahmin_ppk_faiz": val_faiz,
                    "min_ppk_faiz": min_faiz,
                    "max_ppk_faiz": max_faiz,
                    "katilimci_sayisi": int(kat_sayisi) if kat_sayisi > 0 else 0
                }
                status = upsert_tahmin(kullanici, donem, kategori, data)
                if status == "inserted":
                    st.success(f"✅ {display_name} için yeni kayıt oluşturuldu ve PPK eklendi.")
                else:
                    st.info(f"🔄 {display_name} için mevcut kayıt bulundu ve PPK verisi güncellendi.")
            else:
                st.stop()

# ========================================================
# SAYFA: ENFLASYON VERİSİ GİR (AYRI)
# ========================================================
elif page == "➕ Enflasyon Verisi Gir":
    st.header("🏷️ Enflasyon Tahmini Girişi")
    
    with st.form("enf_form"):
        c1, c2 = st.columns(2)
        with c1:
            kullanici, kategori, display_name = get_participant_selection()
        with c2:
            donem = st.selectbox("Dönem", tum_donemler, index=tum_donemler.index("2025-01") if "2025-01" in tum_donemler else 0)

        st.markdown("---")
        
        st.subheader("1. Aylık Enflasyon")
        c_a1, c_a2, c_a3 = st.columns([2,1,1])
        v_ay = c_a1.number_input("Aylık Medyan", step=0.1, key="v_ay")
        min_ay = c_a2.number_input("Min", step=0.1, key="m_ay")
        max_ay = c_a3.number_input("Max", step=0.1, key="mx_ay")
        
        st.subheader("2. Yıllık Enflasyon")
        c_y1, c_y2, c_y3 = st.columns([2,1,1])
        v_yil = c_y1.number_input("Yıllık Medyan", step=0.1, key="v_yi")
        min_yil = c_y2.number_input("Min", step=0.1, key="m_yi")
        max_yil = c_y3.number_input("Max", step=0.1, key="mx_yi")

        st.subheader("3. Yıl Sonu Beklentisi")
        c_ys1, c_ys2, c_ys3 = st.columns([2,1,1])
        v_ys = c_ys1.number_input("Yıl Sonu Medyan", step=0.1, key="v_ys")
        min_ys = c_ys2.number_input("Min", step=0.1, key="m_ys")
        max_ys = c_ys3.number_input("Max", step=0.1, key="mx_ys")

        st.markdown("---")
        kat_sayisi = st.number_input("Anket Katılımcı Sayısı (N)", min_value=0, step=1)

        if st.form_submit_button("Enflasyon Verisini Kaydet"):
            if kullanici:
                data = {
                    "tahmin_aylik_enf": v_ay, "min_aylik_enf": min_ay, "max_aylik_enf": max_ay,
                    "tahmin_yillik_enf": v_yil, "min_yillik_enf": min_yil, "max_yillik_enf": max_yil,
                    "tahmin_yilsonu_enf": v_ys, "min_yilsonu_enf": min_ys, "max_yilsonu_enf": max_ys,
                    "katilimci_sayisi": int(kat_sayisi) if kat_sayisi > 0 else 0
                }
                status = upsert_tahmin(kullanici, donem, kategori, data)
                if status == "inserted":
                    st.success(f"✅ {display_name} için yeni kayıt oluşturuldu ve Enflasyon eklendi.")
                else:
                    st.info(f"🔄 {display_name} için mevcut kayıt bulundu ve Enflasyon verisi güncellendi.")

# ========================================================
# SAYFA: DÜZENLE / SİL (GÜNCELLENDİ)
# ========================================================
elif page == "✏️ Düzenle / Sil":
    st.header("Kayıt Düzenle veya Sil")
    
    res_users = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df_users = pd.DataFrame(res_users.data)
    
    if not df_users.empty:
        df_users['display'] = df_users.apply(lambda x: f"{x['ad_soyad']} ({x['anket_kaynagi']})" if x['anket_kaynagi'] else x['ad_soyad'], axis=1)
        name_map = dict(zip(df_users['display'], df_users['ad_soyad']))
        
        sel_disp = st.selectbox("Kişi/Kurum Seç", df_users["display"])
        real_name = name_map[sel_disp]

        # Kişinin kayıtlarını çek
        res_rec = supabase.table(TABLE_TAHMIN).select("*").eq("kullanici_adi", real_name).order("donem", desc=True).execute()
        df_rec = pd.DataFrame(res_rec.data)

        if not df_rec.empty:
            st.dataframe(df_rec, use_container_width=True)
            
            rec_opts = {f"{row['donem']} (ID: {row['id']})": row for i, row in df_rec.iterrows()}
            sel_key = st.selectbox("İşlem Yapılacak Kayıt", list(rec_opts.keys()))
            target = rec_opts[sel_key]

            st.markdown("---")
            
            # --- DÜZENLEME FORMU ---
            with st.form("edit_delete_form"):
                st.subheader(f"{target['donem']} Verilerini Düzenle")
                
                # Tüm verileri (PPK + Enflasyon) burada gösteriyoruz
                def g(k): return float(target.get(k) or 0)
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("**PPK**")
                    new_faiz = st.number_input("Medyan", value=g('tahmin_ppk_faiz'), step=0.25)
                    new_kat = st.number_input("Katılımcı (N)", value=int(target.get('katilimci_sayisi') or 0), step=1)
                with c2:
                    st.markdown("**Aylık Enf.**")
                    new_ay = st.number_input("Ay Medyan", value=g('tahmin_aylik_enf'), step=0.1)
                with c3:
                    st.markdown("**Yıl Sonu Enf.**")
                    new_ys = st.number_input("YS Medyan", value=g('tahmin_yilsonu_enf'), step=0.1)
                
                # Diğer min/max detayları da eklenebilir ama kod uzamasın diye özet geçtim
                
                col_btn1, col_btn2 = st.columns([1, 1])
                with col_btn1:
                    update_btn = st.form_submit_button("💾 Değişiklikleri Kaydet", type="primary", use_container_width=True)
                
                with col_btn2:
                    # SİLME MEKANİZMASI
                    st.markdown("⚠️ **Silme Bölgesi**")
                    delete_check = st.checkbox("Bu kaydı kalıcı olarak sil")
                    delete_btn = st.form_submit_button("🗑️ KAYDI SİL", type="secondary", use_container_width=True)

                if update_btn:
                    def cv(v): return v if v!=0 else None
                    upd = {
                        "tahmin_ppk_faiz": cv(new_faiz),
                        "tahmin_aylik_enf": cv(new_ay),
                        "tahmin_yilsonu_enf": cv(new_ys),
                        "katilimci_sayisi": int(new_kat) if new_kat > 0 else 0
                    }
                    supabase.table(TABLE_TAHMIN).update(upd).eq("id", target['id']).execute()
                    st.success("Güncellendi!")
                
                if delete_btn:
                    if delete_check:
                        supabase.table(TABLE_TAHMIN).delete().eq("id", target['id']).execute()
                        st.success("Kayıt başarıyla silindi! Sayfa yenileniyor...")
                        st.rerun()
                    else:
                        st.error("Silmek için onay kutusunu işaretleyin.")

# ========================================================
# SAYFA: DASHBOARD
# ========================================================
elif page == "📊 Dashboard":
    st.header("Piyasa Analiz Dashboardu")
    
    res_tahmin = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_tahmin = pd.DataFrame(res_tahmin.data)
    res_kat = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_kat = pd.DataFrame(res_kat.data)

    if not df_tahmin.empty and not df_kat.empty:
        df = pd.merge(df_tahmin, df_kat, left_on="kullanici_adi", right_on="ad_soyad", how="left")
        df['gorunen_isim'] = df.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)
        
        # Tooltip için Katılımcı Sayısını (N) metne ekleyelim
        df['hover_text'] = df.apply(lambda x: f"N={int(x['katilimci_sayisi'])}" if x['katilimci_sayisi'] and x['katilimci_sayisi'] > 0 else "", axis=1)
        
        df['kategori'] = df['kategori'].fillna('Bireysel')
        df = df.sort_values(by="donem")

        st.sidebar.header("🔍 Filtreler")
        cat_filter = st.sidebar.multiselect("Kategori", ["Bireysel", "Kurumsal"], default=["Bireysel", "Kurumsal"])
        available_users = sorted(df[df['kategori'].isin(cat_filter)]['gorunen_isim'].unique())
        user_filter = st.sidebar.multiselect("Katılımcı", available_users, default=available_users)
        df['yil'] = df['donem'].apply(lambda x: x.split('-')[0])
        year_filter = st.sidebar.multiselect("Yıl", sorted(df['yil'].unique()), default=sorted(df['yil'].unique()))

        df_filtered = df[df['kategori'].isin(cat_filter) & df['gorunen_isim'].isin(user_filter) & df['yil'].isin(year_filter)]

        if df_filtered.empty: st.stop()

        # PDF İçin
        report_figures = {}
        tab_ts, tab_dev = st.tabs(["📈 Zaman Serisi", "🍭 Medyan Sapma"])

        with tab_ts:
            def plot_w_range(df_sub, y_col, min_c, max_c, title):
                fig = px.line(df_sub, x="donem", y=y_col, color="gorunen_isim", markers=True, title=title, 
                              hover_data=["hover_text"]) # N sayısını göster
                
                df_r = df_sub.dropna(subset=[min_c, max_c])
                if not df_r.empty:
                    for u in df_r['gorunen_isim'].unique():
                        ud = df_r[df_r['gorunen_isim'] == u]
                        fig.add_trace(go.Scatter(x=ud['donem'], y=ud[y_col], mode='markers', error_y=dict(type='data', symmetric=False, array=ud[max_c]-ud[y_col], arrayminus=ud[y_col]-ud[min_c], color='gray', width=3), showlegend=False, hoverinfo='skip', marker=dict(size=0, opacity=0)))
                st.plotly_chart(fig, use_container_width=True)
                return fig

            c1, c2 = st.columns(2)
            with c1: report_figures["Aylik Enflasyon"] = plot_w_range(df_filtered, "tahmin_aylik_enf", "min_aylik_enf", "max_aylik_enf", "Aylık Enflasyon")
            with c2: report_figures["Yil Sonu Enflasyon"] = plot_w_range(df_filtered, "tahmin_yilsonu_enf", "min_yilsonu_enf", "max_yilsonu_enf", "Yıl Sonu Enf.")
            st.markdown("---")
            c3, c4 = st.columns(2)
            with c3: report_figures["PPK Faiz"] = plot_w_range(df_filtered, "tahmin_ppk_faiz", "min_ppk_faiz", "max_ppk_faiz", "PPK Faiz")
            with c4: st.dataframe(df_filtered[['donem', 'gorunen_isim', 'tahmin_ppk_faiz', 'katilimci_sayisi']], use_container_width=True)

        with tab_dev:
            # Lolipop (Aynı mantık)
            if not df_filtered.empty:
                per = df_filtered['donem'].max()
                d_p = df_filtered[df_filtered['donem'] == per].copy()
                if len(d_p) > 1:
                    med = d_p["tahmin_ppk_faiz"].median()
                    d_p['sapma'] = d_p["tahmin_ppk_faiz"] - med
                    d_p = d_p.sort_values(by='sapma')
                    fig = go.Figure()
                    for i, r in d_p.iterrows():
                        c = "crimson" if r['sapma'] < 0 else "seagreen"
                        fig.add_trace(go.Scatter(x=[0, r['sapma']], y=[r['gorunen_isim'], r['gorunen_isim']], mode='lines', line=dict(color=c), showlegend=False))
                        fig.add_trace(go.Scatter(x=[r['sapma']], y=[r['gorunen_isim']], mode='markers', marker=dict(color=c, size=12), name=r['gorunen_isim'], text=f"Tahmin: %{r['tahmin_ppk_faiz']}", hoverinfo='text'))
                    fig.add_vline(x=0, line_dash="dash")
                    fig.update_layout(title=f"PPK Faiz Sapma ({per})", height=max(400, len(d_p)*30))
                    st.plotly_chart(fig, use_container_width=True)
                    report_figures["Sapma Analizi"] = fig
        
        st.markdown("---")
        if st.button("📄 PDF İndir"):
            pdf_d = create_pdf_report(df_filtered, report_figures)
            st.download_button("⬇️ İndir", pdf_d, "rapor.pdf", "application/pdf")

# ========================================================
# SAYFA: KATILIMCI YÖNETİMİ (AYNI)
# ========================================================
elif page == "👥 Katılımcı Yönetimi":
    st.header("Katılımcı Yönetimi")
    with st.form("new_kat"):
        c1, c2 = st.columns(2)
        ad = c1.text_input("Ad / Kurum")
        cat = c2.radio("Kategori", ["Bireysel", "Kurumsal"], horizontal=True)
        src = st.text_input("Kaynak (Opsiyonel)")
        if st.form_submit_button("Ekle"):
            if ad:
                try:
                    supabase.table(TABLE_KATILIMCI).insert({"ad_soyad": normalize_name(ad), "kategori": cat, "anket_kaynagi": src or None}).execute()
                    st.success("Eklendi")
                except: st.warning("Hata")
    
    res = supabase.table(TABLE_KATILIMCI).select("*").order("ad_soyad").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        st.dataframe(df)
        ks = st.selectbox("Silinecek", df["ad_soyad"].unique())
        if st.button("Sil"):
            supabase.table(TABLE_KATILIMCI).delete().eq("ad_soyad", ks).execute()
            st.rerun()

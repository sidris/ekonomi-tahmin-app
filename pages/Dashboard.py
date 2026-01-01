import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import utils

st.set_page_config(page_title="Dashboard", layout="wide")

if not utils.check_login():
    st.warning("Lütfen giriş yapınız.")
    st.stop()

st.title("📈 Piyasa Analiz Dashboardu")

# Verileri Çek
df_t = utils.get_all_forecasts()
df_k = utils.get_participants()

if df_t.empty:
    st.info("Henüz veri girilmemiş.")
    st.stop()

# Veri Zenginleştirme (Kategori ve Kaynak bilgisi ekle)
if not df_k.empty:
    df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
    # Kategori boşsa "Bireysel" ata
    df_history['kategori'] = df_history['kategori_y'].fillna(df_history['kategori_x']).fillna('Bireysel')
else:
    df_history = df_t.copy()

# Görünen İsim Ayarı
df_history['gorunen_isim'] = df_history['kullanici_adi']

# --- TAB YAPISI (Grafikler ve Isı Haritası) ---
tab1, tab2 = st.tabs(["📊 Zaman Serisi Analizi", "🔥 Isı Haritası"])

with tab1:
    # Filtreler
    with st.expander("🔍 Filtreleri Göster", expanded=True):
        c1, c2 = st.columns(2)
        users = c1.multiselect("Katılımcılar", sorted(df_history['gorunen_isim'].unique()))
        
        all_periods = sorted(df_history['hedef_donemi'].unique())
        selected_periods = c2.multiselect("Hedef Dönemler", all_periods, default=all_periods[-5:] if len(all_periods)>5 else all_periods)

    # Filtreleme
    df_filtered = df_history[df_history['hedef_donemi'].isin(selected_periods)]
    
    def plot_metric(metric_col, title):
        fig = go.Figure()
        
        if users:
            # Seçili kullanıcıları çiz
            user_data = df_filtered[df_filtered['gorunen_isim'].isin(users)]
            for u in users:
                d = user_data[user_data['gorunen_isim'] == u].sort_values("hedef_donemi")
                fig.add_trace(go.Scatter(x=d['hedef_donemi'], y=d[metric_col], mode='lines+markers', name=u))
        else:
            # Medyan çiz
            agg = df_filtered.groupby("hedef_donemi")[metric_col].median().reset_index()
            fig.add_trace(go.Scatter(x=agg['hedef_donemi'], y=agg[metric_col], mode='lines+markers', name='Piyasa Medyanı', line=dict(color='blue', width=4)))
            
        fig.update_layout(title=title, hovermode="x unified", legend=dict(orientation="h", y=1.1))
        return fig

    c1, c2 = st.columns(2)
    with c1: st.plotly_chart(plot_metric("tahmin_ppk_faiz", "PPK Faiz Beklentisi"), use_container_width=True)
    with c2: st.plotly_chart(plot_metric("tahmin_yilsonu_enf", "Yıl Sonu Enflasyon Beklentisi"), use_container_width=True)

with tab2:
    st.subheader("Beklenti Isı Haritası")
    metric = st.selectbox("Harita Metriği", ["tahmin_ppk_faiz", "tahmin_yilsonu_enf", "tahmin_aylik_enf"])
    
    # En son tahminleri al
    df_latest = df_history.sort_values('tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'hedef_donemi'], keep='last')
    
    pivot = df_latest.pivot(index="gorunen_isim", columns="hedef_donemi", values=metric)
    pivot = pivot.reindex(columns=sorted(pivot.columns))
    
    st.dataframe(pivot.style.background_gradient(cmap="RdYlGn_r", axis=None).format("{:.2f}"), use_container_width=True, height=600)

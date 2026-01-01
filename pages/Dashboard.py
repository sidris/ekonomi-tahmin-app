import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import utils
import datetime

st.set_page_config(page_title="Dashboard", layout="wide")

if not utils.check_login():
    st.warning("Lütfen giriş yapınız.")
    st.stop()

st.title("📈 Piyasa Analiz Dashboardu")

# --- VERİLERİ ÇEK ---
with st.spinner("Veriler güncelleniyor..."):
    # 1. Tahminleri Çek
    df_t = utils.get_all_forecasts()
    df_k = utils.get_participants()
    
    # 2. Piyasa Verilerini (Gerçekleşen) Çek
    # Son 3 yılı çekiyoruz
    start_date = datetime.date(2023, 1, 1)
    end_date = datetime.date.today()
    realized_df, real_err = utils.fetch_market_data_adapter(start_date, end_date)

if df_t.empty:
    st.info("Henüz tahmin verisi girilmemiş.")
    st.stop()

if real_err:
    st.warning(f"Piyasa verileri çekilemedi (EVDS/BIS): {real_err}")

# Veri Zenginleştirme
if not df_k.empty:
    df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
    df_history['kategori'] = df_history['kategori_y'].fillna(df_history['kategori_x']).fillna('Bireysel')
else:
    df_history = df_t.copy()

df_history['gorunen_isim'] = df_history['kullanici_adi']

# --- TAB YAPISI ---
tab1, tab2 = st.tabs(["📊 Zaman Serisi Analizi", "🔥 Isı Haritası"])

with tab1:
    with st.expander("🔍 Filtreleri Göster", expanded=True):
        c1, c2 = st.columns(2)
        users = c1.multiselect("Katılımcılar", sorted(df_history['gorunen_isim'].unique()))
        
        all_periods = sorted(df_history['hedef_donemi'].unique())
        selected_periods = c2.multiselect("Hedef Dönemler", all_periods, default=all_periods[-5:] if len(all_periods)>5 else all_periods)

    df_filtered = df_history[df_history['hedef_donemi'].isin(selected_periods)]
    
    # Grafik Çizim Fonksiyonu (Gerçekleşen Veri Destekli)
    def plot_metric(forecast_col, realized_col, title):
        fig = go.Figure()
        
        # A) TAHMİNLER
        if users:
            user_data = df_filtered[df_filtered['gorunen_isim'].isin(users)]
            for u in users:
                d = user_data[user_data['gorunen_isim'] == u].sort_values("hedef_donemi")
                fig.add_trace(go.Scatter(x=d['hedef_donemi'], y=d[forecast_col], mode='lines+markers', name=u))
        else:
            agg = df_filtered.groupby("hedef_donemi")[forecast_col].median().reset_index()
            fig.add_trace(go.Scatter(x=agg['hedef_donemi'], y=agg[forecast_col], mode='lines+markers', name='Piyasa Medyanı', line=dict(color='blue', width=4)))

        # B) GERÇEKLEŞEN (VARSA)
        if not realized_df.empty and realized_col in realized_df.columns:
            # Sadece seçilen dönemlere ait gerçekleşenleri gösterelim
            real_data = realized_df[realized_df['Donem'].isin(selected_periods)].sort_values("Donem")
            
            if not real_data.empty:
                fig.add_trace(go.Scatter(
                    x=real_data['Donem'], 
                    y=real_data[realized_col], 
                    mode='lines+markers', 
                    name=f'Gerçekleşen ({realized_col})', 
                    line=dict(color='red', width=3, dash='dot'),
                    marker=dict(symbol='x', size=10, color='red')
                ))

        fig.update_layout(title=title, hovermode="x unified", legend=dict(orientation="h", y=1.1))
        return fig

    c1, c2 = st.columns(2)
    # Parametreler: (Tahmin Kolonu, Gerçekleşen Kolonu, Başlık)
    with c1: st.plotly_chart(plot_metric("tahmin_ppk_faiz", "PPK Faizi", "PPK Faiz Beklentisi vs Gerçekleşen"), use_container_width=True)
    with c2: st.plotly_chart(plot_metric("tahmin_yilsonu_enf", "Yıllık TÜFE", "Yıl Sonu Enflasyon Beklentisi vs Gerçekleşen"), use_container_width=True)

with tab2:
    st.subheader("Beklenti Isı Haritası")
    metric = st.selectbox("Harita Metriği", ["tahmin_ppk_faiz", "tahmin_yilsonu_enf", "tahmin_aylik_enf"])
    
    df_latest = df_history.sort_values('tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'hedef_donemi'], keep='last')
    pivot = df_latest.pivot(index="gorunen_isim", columns="hedef_donemi", values=metric)
    pivot = pivot.reindex(columns=sorted(pivot.columns))
    
    st.dataframe(pivot.style.background_gradient(cmap="RdYlGn_r", axis=None).format("{:.2f}"), use_container_width=True, height=600)

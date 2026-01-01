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
with st.spinner("Piyasa verileri ve tahminler analiz ediliyor..."):
    # 1. Tahminler
    df_t = utils.get_all_forecasts()
    df_k = utils.get_participants()
    
    # 2. Gerçekleşen Veriler (EVDS)
    # Geniş bir aralık çekelim ki eşleşme şansı artsın
    start_date = datetime.date(2023, 1, 1)
    end_date = datetime.date.today()
    realized_df, real_err = utils.fetch_market_data_adapter(start_date, end_date)

if df_t.empty:
    st.info("Henüz tahmin verisi girilmemiş.")
    st.stop()

# Katılımcı isimlerini birleştir
if not df_k.empty:
    df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
    df_history['gorunen_isim'] = df_history['kullanici_adi']
else:
    df_history = df_t.copy()
    df_history['gorunen_isim'] = df_history['kullanici_adi']

# ==============================================================================
# 🏆 ŞAMPİYONLAR LİGİ (EN İYİ TAHMİNCİLER)
# ==============================================================================
st.markdown("### 🏆 Son Dönem Performans Liderleri")

if not realized_df.empty:
    # 1. En son hangi dönemin verisi açıklanmış onu bulalım (Enflasyon verisi genellikle ayın 3'ünde gelir)
    # Gerçekleşen verisi olan son dönemi bul (Sırala ve sonuncuyu al)
    valid_periods = realized_df.dropna(subset=['Aylık TÜFE', 'PPK Faizi'], how='all')['Donem'].sort_values().unique()
    
    if len(valid_periods) > 0:
        latest_period = valid_periods[-1] # En son açıklanan dönem (Örn: 2024-12)
        st.caption(f"📅 Analiz Dönemi: **{latest_period}** (Açıklanan en son veriler baz alınmıştır)")
        
        # O döneme ait gerçek verileri al
        latest_real_row = realized_df[realized_df['Donem'] == latest_period].iloc[0]
        
        # O döneme ait tahminleri al
        period_forecasts = df_history[df_history['hedef_donemi'] == latest_period].copy()

        if not period_forecasts.empty:
            
            # --- Yardımcı Fonksiyon: Liderlik Tablosu Kartı ---
            def display_leaderboard(col_obj, title, forecast_col, real_val_col):
                real_val = latest_real_row.get(real_val_col)
                
                # Çerçeve
                with col_obj:
                    st.markdown(f"#### {title}")
                    
                    if pd.isna(real_val):
                        st.warning(f"{title} verisi henüz açıklanmadı.")
                        return

                    st.markdown(f"**Gerçekleşen:** `{real_val:.2f}`")
                    
                    # O metrik için tahmini olanları filtrele
                    valid_f = period_forecasts.dropna(subset=[forecast_col]).copy()
                    
                    if valid_f.empty:
                        st.info("Bu veri için tahmin girilmemiş.")
                    else:
                        # Sapmayı Hesapla (Mutlak Değer)
                        valid_f['sapma'] = (valid_f[forecast_col] - real_val).abs()
                        # Sapmaya göre sırala (En az sapma en iyi)
                        leaders = valid_f.sort_values('sapma').head(3)
                        
                        medals = ["🥇", "🥈", "🥉"]
                        for i, (index, row) in enumerate(leaders.iterrows()):
                            medal = medals[i] if i < 3 else f"{i+1}."
                            tahmin = row[forecast_col]
                            sapma = row['sapma']
                            isim = row['gorunen_isim']
                            
                            st.success(f"{medal} **{isim}**\n\nTahmin: `{tahmin:.2f}` | Sapma: `{sapma:.2f}`")

            # 3 Kolonlu Yapı
            lc1, lc2, lc3 = st.columns(3)
            
            # 1. PPK
            display_leaderboard(lc1, "🏦 PPK Faizi", "tahmin_ppk_faiz", "PPK Faizi")
            
            # 2. Aylık Enflasyon
            display_leaderboard(lc2, "📅 Aylık Enflasyon", "tahmin_aylik_enf", "Aylık TÜFE")
            
            # 3. Yıllık Enflasyon (TÜFE)
            display_leaderboard(lc3, "ERROR: Yıllık Enflasyon", "tahmin_yilsonu_enf", "Yıllık TÜFE") 
            # Not: Kullanıcı "Yıl Sonu Enflasyon" girmiş olabilir ama biz bunu yıllık gerçekleşme ile kıyaslıyoruz.
            
        else:
            st.info(f"{latest_period} dönemi için sistemde kayıtlı tahmin bulunamadı.")
    else:
        st.warning("Henüz eşleşen bir gerçekleşme verisi (EVDS) bulunamadı.")
else:
    st.warning("EVDS verisi çekilemediği için liderlik tablosu hesaplanamıyor.")

st.markdown("---")

# ==============================================================================
# 📊 GRAFİK BÖLÜMÜ (ESKİ KODLARINIZ)
# ==============================================================================
tab1, tab2 = st.tabs(["📊 Zaman Serisi Analizi", "🔥 Isı Haritası"])

with tab1:
    with st.expander("🔍 Filtreleri Göster", expanded=False):
        c1, c2 = st.columns(2)
        users = c1.multiselect("Katılımcılar", sorted(df_history['gorunen_isim'].unique()))
        
        all_periods = sorted(df_history['hedef_donemi'].unique())
        selected_periods = c2.multiselect("Hedef Dönemler", all_periods, default=all_periods[-5:] if len(all_periods)>5 else all_periods)

    df_filtered = df_history[df_history['hedef_donemi'].isin(selected_periods)]
    
    def plot_metric(forecast_col, realized_col, title):
        fig = go.Figure()
        
        if users:
            user_data = df_filtered[df_filtered['gorunen_isim'].isin(users)]
            for u in users:
                d = user_data[user_data['gorunen_isim'] == u].sort_values("hedef_donemi")
                fig.add_trace(go.Scatter(x=d['hedef_donemi'], y=d[forecast_col], mode='lines+markers', name=u))
        else:
            agg = df_filtered.groupby("hedef_donemi")[forecast_col].median().reset_index()
            fig.add_trace(go.Scatter(x=agg['hedef_donemi'], y=agg[forecast_col], mode='lines+markers', name='Piyasa Medyanı', line=dict(color='blue', width=4)))

        if not realized_df.empty and realized_col in realized_df.columns:
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
    with c1: st.plotly_chart(plot_metric("tahmin_ppk_faiz", "PPK Faizi", "PPK Faiz Beklentisi"), use_container_width=True)
    with c2: st.plotly_chart(plot_metric("tahmin_yilsonu_enf", "Yıllık TÜFE", "Enflasyon Beklentisi"), use_container_width=True)

with tab2:
    st.subheader("Beklenti Isı Haritası")
    metric = st.selectbox("Harita Metriği", ["tahmin_ppk_faiz", "tahmin_yilsonu_enf", "tahmin_aylik_enf"])
    
    df_latest = df_history.sort_values('tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'hedef_donemi'], keep='last')
    pivot = df_latest.pivot(index="gorunen_isim", columns="hedef_donemi", values=metric)
    pivot = pivot.reindex(columns=sorted(pivot.columns))
    
    st.dataframe(pivot.style.background_gradient(cmap="RdYlGn_r", axis=None).format("{:.2f}"), use_container_width=True, height=600)

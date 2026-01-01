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
    df_t = utils.get_all_forecasts()
    df_k = utils.get_participants()
    
    # Gerçekleşen Veriler (EVDS - Son 3 Yıl)
    start_date = datetime.date(2023, 1, 1)
    end_date = datetime.date.today()
    realized_df, real_err = utils.fetch_market_data_adapter(start_date, end_date)

if df_t.empty:
    st.info("Henüz tahmin verisi girilmemiş.")
    st.stop()

# İsim Birleştirme
if not df_k.empty:
    df_history = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="left")
    df_history['gorunen_isim'] = df_history['kullanici_adi']
else:
    df_history = df_t.copy()
    df_history['gorunen_isim'] = df_history['kullanici_adi']

# ==============================================================================
# 🏆 SEÇİLEBİLİR LİDERLİK TABLOSU
# ==============================================================================
st.markdown("### 🏆 Performans Liderleri (Şampiyonlar Ligi)")

if not realized_df.empty:
    # Gerçekleşen verisi (TÜFE veya PPK) olan dönemleri bul
    # Hem Enflasyon hem PPK sütunlarının tamamen boş olmadığı satırları al
    valid_periods = realized_df.dropna(subset=['Aylık TÜFE', 'PPK Faizi'], how='all')['Donem'].sort_values(ascending=False).unique()
    
    if len(valid_periods) > 0:
        # KULLANICI SEÇİMİ
        col_sel1, col_sel2 = st.columns([1, 3])
        with col_sel1:
            selected_leader_period = st.selectbox("📅 Dönem Seçiniz", valid_periods, index=0)
        
        # Seçilen döneme ait gerçek veriler
        target_real_row = realized_df[realized_df['Donem'] == selected_leader_period].iloc[0]
        
        # Seçilen döneme ait tahminler
        period_forecasts = df_history[df_history['hedef_donemi'] == selected_leader_period].copy()

        if not period_forecasts.empty:
            
            # Kart Gösterim Fonksiyonu
            def display_leaderboard(col_obj, title, forecast_col, real_val_col):
                real_val = target_real_row.get(real_val_col)
                with col_obj:
                    st.markdown(f"#### {title}")
                    
                    if pd.isna(real_val):
                        st.warning("Veri açıklanmadı.")
                        return

                    st.markdown(f"**Gerçekleşen:** `{real_val:.2f}`")
                    
                    # Filtrele ve Sırala
                    valid_f = period_forecasts.dropna(subset=[forecast_col]).copy()
                    
                    if valid_f.empty:
                        st.caption("Bu metrik için tahmin yok.")
                    else:
                        valid_f['sapma'] = (valid_f[forecast_col] - real_val).abs()
                        leaders = valid_f.sort_values('sapma').head(3)
                        
                        medals = ["🥇", "🥈", "🥉"]
                        for i, (index, row) in enumerate(leaders.iterrows()):
                            medal = medals[i] if i < 3 else f"{i+1}."
                            st.success(f"{medal} **{row['gorunen_isim']}**\n\nTahmin: `{row[forecast_col]:.2f}` | Sapma: `{row['sapma']:.2f}`")

            # 3'lü Izgara
            lc1, lc2, lc3 = st.columns(3)
            display_leaderboard(lc1, "🏦 PPK Faizi", "tahmin_ppk_faiz", "PPK Faizi")
            display_leaderboard(lc2, "📅 Aylık Enf.", "tahmin_aylik_enf", "Aylık TÜFE")
            display_leaderboard(lc3, "📅 Yıllık Enf.", "tahmin_yilsonu_enf", "Yıllık TÜFE")
            
        else:
            st.info(f"{selected_leader_period} dönemi için sistemde hiç tahmin bulunamadı.")
    else:
        st.warning("Henüz karşılaştırma yapılabilecek bir gerçekleşme verisi yok.")
else:
    st.warning("Piyasa verileri (EVDS) çekilemedi.")

st.markdown("---")

# ==============================================================================
# 📊 GRAFİK BÖLÜMÜ
# ==============================================================================
tab1, tab2 = st.tabs(["📊 Zaman Serisi Analizi", "🔥 Isı Haritası"])

with tab1:
    with st.expander("🔍 Grafik Filtreleri", expanded=False):
        c1, c2 = st.columns(2)
        users = c1.multiselect("Katılımcılar", sorted(df_history['gorunen_isim'].unique()))
        all_periods = sorted(df_history['hedef_donemi'].unique())
        # Varsayılan olarak son 5 dönem
        default_periods = all_periods[-6:] if len(all_periods) > 6 else all_periods
        selected_periods = c2.multiselect("Hedef Dönemler (Grafik)", all_periods, default=default_periods)

    df_filtered = df_history[df_history['hedef_donemi'].isin(selected_periods)]
    
    def plot_metric(forecast_col, realized_col, title):
        fig = go.Figure()
        
        # Tahminler
        if users:
            user_data = df_filtered[df_filtered['gorunen_isim'].isin(users)]
            for u in users:
                d = user_data[user_data['gorunen_isim'] == u].sort_values("hedef_donemi")
                fig.add_trace(go.Scatter(x=d['hedef_donemi'], y=d[forecast_col], mode='lines+markers', name=u))
        else:
            agg = df_filtered.groupby("hedef_donemi")[forecast_col].median().reset_index()
            fig.add_trace(go.Scatter(x=agg['hedef_donemi'], y=agg[forecast_col], mode='lines+markers', name='Piyasa Medyanı', line=dict(color='blue', width=4)))

        # Gerçekleşenler
        if not realized_df.empty and realized_col in realized_df.columns:
            real_data = realized_df[realized_df['Donem'].isin(selected_periods)].sort_values("Donem")
            if not real_data.empty:
                fig.add_trace(go.Scatter(
                    x=real_data['Donem'], 
                    y=real_data[realized_col], 
                    mode='lines+markers', 
                    name=f'Gerçekleşen', 
                    line=dict(color='red', width=3, dash='dot'),
                    marker=dict(symbol='x', size=10, color='red')
                ))

        fig.update_layout(title=title, hovermode="x unified", legend=dict(orientation="h", y=1.1))
        return fig

    c1, c2 = st.columns(2)
    with c1: st.plotly_chart(plot_metric("tahmin_ppk_faiz", "PPK Faizi", "PPK Faiz Beklentisi"), use_container_width=True)
    with c2: st.plotly_chart(plot_metric("tahmin_yilsonu_enf", "Yıllık TÜFE", "Yıl Sonu Enflasyon Beklentisi"), use_container_width=True)

with tab2:
    st.subheader("Beklenti Isı Haritası")
    metric = st.selectbox("Harita Metriği", ["tahmin_ppk_faiz", "tahmin_yilsonu_enf", "tahmin_aylik_enf"])
    
    df_latest = df_history.sort_values('tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'hedef_donemi'], keep='last')
    pivot = df_latest.pivot(index="gorunen_isim", columns="hedef_donemi", values=metric)
    pivot = pivot.reindex(columns=sorted(pivot.columns))
    
    st.dataframe(pivot.style.background_gradient(cmap="RdYlGn_r", axis=None).format("{:.2f}"), use_container_width=True, height=600)

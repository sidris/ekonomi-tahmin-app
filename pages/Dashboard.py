import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import utils

st.set_page_config(page_title="Dashboard", layout="wide")
utils.apply_theme()

utils.require_login_page()

utils.page_header("📈 Piyasa Analiz Dashboardu", "Tahminler, gerçekleşen veriler ve performans kıyaslamaları")

# =============================================================
# Veriler
# =============================================================
with st.spinner("Veriler yükleniyor..."):
    df_all = utils.get_all_forecasts()
    df_k = utils.get_participants()

    start_date = datetime.date(datetime.date.today().year - 3, 1, 1)
    end_date = datetime.date.today()
    realized_df, real_err = utils.fetch_market_data_adapter(start_date, end_date)

if df_all.empty:
    st.info("Henüz tahmin verisi yok. **Sistem Yönetimi** sayfasından demo verisi üretebilirsiniz.")
    st.stop()

# Görünen isim kolonu
df_all["gorunen_isim"] = df_all["kullanici_adi"]

# =============================================================
# KONTROL PANELİ: As-of tarihi seçimi
# =============================================================
st.markdown("### 🎛️ Görünüm Ayarları")

# Mevcut tahminlerin olduğu ayları bul (as-of seçimi için)
df_all_dates = df_all.dropna(subset=["tahmin_tarihi"])
all_forecast_months = sorted(
    df_all_dates["tahmin_tarihi"].dt.strftime("%Y-%m").unique(),
    reverse=True,
)

ctrl1, ctrl2 = st.columns([1, 2])
with ctrl1:
    as_of_mode = st.radio(
        "Tahmin görünümü",
        ["En güncel tahminler", "Belirli bir aya göre"],
        help="Belirli bir aya göre: o ayın sonuna kadar girilen en son tahminler kullanılır.",
        horizontal=True,
    )

with ctrl2:
    if as_of_mode == "Belirli bir aya göre" and all_forecast_months:
        as_of_month = st.selectbox(
            "As-of ayı (bu ayın sonunda piyasa ne bekliyordu?)",
            all_forecast_months,
            index=0,
        )
        df_latest = utils.get_latest_as_of(df_all, as_of_month)
        st.caption(f"💡 {as_of_month} sonuna kadar girilen tahminlerin en son hali gösteriliyor.")
    else:
        as_of_month = None
        df_latest = utils.get_latest_per_user_period(df_all)

st.markdown("---")

# =============================================================
# 🏆 LİDERLİK TABLOSU
# =============================================================
st.markdown("### 🏆 Performans Liderleri")

if realized_df is None or realized_df.empty:
    if real_err:
        st.warning(f"Piyasa verisi çekilemedi: {real_err}")
    else:
        st.warning("Piyasa verileri boş.")
else:
    valid_periods = (
        realized_df.dropna(subset=["Aylık TÜFE", "PPK Faizi"], how="all")["Donem"]
        .sort_values(ascending=False).unique().tolist()
    )

    if not valid_periods:
        st.warning("Henüz karşılaştırma yapılabilecek gerçekleşme verisi yok.")
    else:
        col_sel, col_info = st.columns([1, 3])
        with col_sel:
            sel_period = st.selectbox("📅 Dönem", valid_periods, index=0, key="leader_period")
        with col_info:
            st.markdown(
                f"<div style='padding-top:30px;color:#94A3B8;font-size:13px;'>"
                f"Seçilen dönem için gerçekleşen değerler ile tahminler karşılaştırılıyor. "
                f"Her katılımcının <b>o döneme verdiği en son tahmin</b> kullanılır."
                f"</div>",
                unsafe_allow_html=True,
            )

        target_real = realized_df[realized_df["Donem"] == sel_period].iloc[0]
        period_forecasts = df_latest[df_latest["hedef_donemi"] == sel_period].copy()

        def leaderboard_card(col_obj, title, forecast_col, real_val_col):
            real_val = target_real.get(real_val_col)
            with col_obj:
                st.markdown(f"#### {title}")
                if pd.isna(real_val):
                    st.info("Gerçekleşen veri henüz yok.")
                    return

                st.markdown(
                    f"<div class='actual-box'><b>Gerçekleşen:</b> "
                    f"<span style='font-size:20px;font-weight:700;'>{real_val:.2f}%</span></div>",
                    unsafe_allow_html=True,
                )

                valid = period_forecasts.dropna(subset=[forecast_col]).copy()
                if valid.empty:
                    st.caption("Bu metrik için tahmin yok.")
                    return

                valid["sapma"] = (valid[forecast_col] - real_val).abs()
                leaders = valid.sort_values("sapma").head(5)

                medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                for i, (_, row) in enumerate(leaders.iterrows()):
                    medal = medals[i] if i < 5 else f"{i+1}."
                    kat = row.get("kategori", "")
                    st.markdown(
                        f"""
                        <div class="leader-card">
                          <span class="leader-rank">{medal}</span>
                          <span class="leader-name">{row['gorunen_isim']}</span>
                          {utils.category_badge(kat) if kat else ''}
                          <div class="leader-meta">
                            Tahmin: <b>{row[forecast_col]:.2f}</b> &nbsp;•&nbsp;
                            Sapma: <b>{row['sapma']:.2f}</b>
                          </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        if period_forecasts.empty:
            st.info(f"{sel_period} dönemi için sistemde tahmin bulunamadı.")
        else:
            lc1, lc2, lc3 = st.columns(3)
            leaderboard_card(lc1, "🏦 PPK Faizi", "tahmin_ppk_faiz", "PPK Faizi")
            leaderboard_card(lc2, "📅 Aylık Enflasyon", "tahmin_aylik_enf", "Aylık TÜFE")
            leaderboard_card(lc3, "📆 Yıllık Enflasyon", "tahmin_yilsonu_enf", "Yıllık TÜFE")

st.markdown("---")

# =============================================================
# 📊 GRAFİKLER
# =============================================================
tab1, tab2, tab3 = st.tabs(["📊 Zaman Serisi", "🔥 Isı Haritası", "📈 Tahmin Revizyonu"])

# ----------- TAB 1: Zaman Serisi -----------
with tab1:
    with st.expander("🔍 Grafik Filtreleri", expanded=False):
        c1, c2 = st.columns(2)
        users = c1.multiselect(
            "Katılımcılar (boşsa medyan)",
            sorted(df_all["gorunen_isim"].unique()),
        )
        all_periods = sorted(df_all["hedef_donemi"].dropna().unique().tolist())
        default_periods = all_periods[-12:] if len(all_periods) > 12 else all_periods
        selected_periods = c2.multiselect(
            "Hedef Dönemler", all_periods, default=default_periods
        )

    df_filtered = df_latest[df_latest["hedef_donemi"].isin(selected_periods)]

    def plot_metric(forecast_col: str, realized_col: str, title: str):
        fig = go.Figure()

        if users:
            user_data = df_filtered[df_filtered["gorunen_isim"].isin(users)]
            for u in users:
                d = user_data[user_data["gorunen_isim"] == u].sort_values("hedef_donemi")
                if not d.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=d["hedef_donemi"], y=d[forecast_col],
                            mode="lines+markers", name=u,
                            line=dict(width=2), marker=dict(size=7),
                        )
                    )
        else:
            # Medyan + IQR bandı
            grp = df_filtered.groupby("hedef_donemi")[forecast_col]
            agg = pd.DataFrame({
                "median": grp.median(),
                "q1": grp.quantile(0.25),
                "q3": grp.quantile(0.75),
            }).reset_index().sort_values("hedef_donemi")

            # IQR bandı (dolgu)
            fig.add_trace(go.Scatter(
                x=list(agg["hedef_donemi"]) + list(agg["hedef_donemi"][::-1]),
                y=list(agg["q3"]) + list(agg["q1"][::-1]),
                fill="toself", fillcolor="rgba(59,130,246,0.15)",
                line=dict(width=0), showlegend=True, name="Piyasa IQR (Q1-Q3)",
                hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=agg["hedef_donemi"], y=agg["median"],
                mode="lines+markers", name="Piyasa Medyanı",
                line=dict(color="#3B82F6", width=3), marker=dict(size=8),
            ))

        # Gerçekleşen
        if realized_df is not None and not realized_df.empty and realized_col in realized_df.columns:
            real_data = (
                realized_df[realized_df["Donem"].isin(selected_periods)]
                .sort_values("Donem")
            )
            if not real_data.empty:
                fig.add_trace(
                    go.Scatter(
                        x=real_data["Donem"], y=real_data[realized_col],
                        mode="lines+markers", name="Gerçekleşen",
                        line=dict(color="#EF4444", width=3, dash="dot"),
                        marker=dict(symbol="x", size=11, color="#EF4444"),
                    )
                )

        fig.update_layout(
            title=dict(text=title, font=dict(size=16)),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            height=420,
            margin=dict(l=10, r=10, t=60, b=40),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(gridcolor="rgba(148,163,184,0.12)"),
            yaxis=dict(gridcolor="rgba(148,163,184,0.12)"),
        )
        return fig

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            plot_metric("tahmin_ppk_faiz", "PPK Faizi", "PPK Faiz Beklentisi"),
            use_container_width=True,
        )
    with c2:
        st.plotly_chart(
            plot_metric("tahmin_yilsonu_enf", "Yıllık TÜFE", "Yıl Sonu Enflasyon"),
            use_container_width=True,
        )

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(
            plot_metric("tahmin_aylik_enf", "Aylık TÜFE", "Aylık Enflasyon"),
            use_container_width=True,
        )
    with c4:
        st.plotly_chart(
            plot_metric("tahmin_yilsonu_faiz", None, "Yıl Sonu Faiz Beklentisi"),
            use_container_width=True,
        )

# ----------- TAB 2: Isı Haritası -----------
with tab2:
    st.subheader("Beklenti Isı Haritası")
    st.caption(
        "Her hücre, satırdaki katılımcının sütundaki hedef döneme verdiği "
        + ("**en son tahmini** gösterir." if as_of_month is None
           else f"**{as_of_month} sonuna kadar** verdiği en son tahmini gösterir.")
    )

    metric_opts = {
        "PPK Faizi": "tahmin_ppk_faiz",
        "Yıl Sonu Enflasyon": "tahmin_yilsonu_enf",
        "Aylık Enflasyon": "tahmin_aylik_enf",
        "Yıl Sonu Faiz": "tahmin_yilsonu_faiz",
    }
    hc1, hc2 = st.columns([1, 2])
    metric_label = hc1.selectbox("Metrik", list(metric_opts.keys()))
    metric = metric_opts[metric_label]

    cat_filter = hc2.multiselect(
        "Kategori filtresi",
        utils.KATEGORILER,
        default=utils.KATEGORILER,
    )

    if metric not in df_latest.columns:
        st.info("Bu metrik için veri yok.")
    else:
        df_heat = df_latest[df_latest["kategori"].isin(cat_filter)].copy()
        pivot = df_heat.pivot_table(
            index="gorunen_isim", columns="hedef_donemi",
            values=metric, aggfunc="last",
        )

        if pivot.empty:
            st.info("Gösterilecek veri yok.")
        else:
            pivot = pivot.reindex(columns=sorted(pivot.columns))
            # Satırları alfabetik sırala
            pivot = pivot.sort_index()

            st.dataframe(
                pivot.style.background_gradient(cmap="RdYlGn_r", axis=None).format(
                    "{:.2f}", na_rep="—"
                ),
                use_container_width=True,
                height=min(600, 50 + 35 * len(pivot)),
            )

            # Altına özet
            st.caption(
                f"📊 {len(pivot)} katılımcı × {len(pivot.columns)} dönem • "
                f"Renk: **kırmızı = yüksek**, **yeşil = düşük**"
            )

# ----------- TAB 3: Tahmin Revizyonu -----------
with tab3:
    st.subheader("Bir Katılımcının Tahmin Revizyonu")
    st.caption(
        "Seçilen katılımcının aynı hedef dönem için zaman içinde verdiği "
        "tahminlerin nasıl değiştiğini gösterir."
    )

    rc1, rc2, rc3 = st.columns([2, 1, 1])
    user_sel = rc1.selectbox(
        "Katılımcı",
        sorted(df_all["gorunen_isim"].unique()),
        key="rev_user",
    )
    user_df = df_all[df_all["gorunen_isim"] == user_sel]
    available_targets = sorted(user_df["hedef_donemi"].dropna().unique().tolist())
    if not available_targets:
        st.info("Bu katılımcı için hedef dönem bulunamadı.")
    else:
        target_sel = rc2.selectbox("Hedef dönem", available_targets, key="rev_target")
        metric_sel_label = rc3.selectbox(
            "Metrik", list(metric_opts.keys()), key="rev_metric"
        )
        metric_sel = metric_opts[metric_sel_label]

        rev_df = (
            user_df[user_df["hedef_donemi"] == target_sel]
            .dropna(subset=[metric_sel])
            .sort_values("tahmin_tarihi")
        )

        if rev_df.empty:
            st.info("Bu kombinasyon için veri yok.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=rev_df["tahmin_tarihi"], y=rev_df[metric_sel],
                mode="lines+markers+text",
                name=user_sel,
                line=dict(color="#3B82F6", width=2),
                marker=dict(size=9),
                text=[f"{v:.2f}" for v in rev_df[metric_sel]],
                textposition="top center",
            ))

            # Gerçekleşeni ekle
            if realized_df is not None and not realized_df.empty:
                realized_map = {
                    "tahmin_ppk_faiz": "PPK Faizi",
                    "tahmin_aylik_enf": "Aylık TÜFE",
                    "tahmin_yilsonu_enf": "Yıllık TÜFE",
                }
                real_col = realized_map.get(metric_sel)
                if real_col:
                    real_row = realized_df[realized_df["Donem"] == target_sel]
                    if not real_row.empty and real_col in real_row.columns:
                        real_val = real_row[real_col].iloc[0]
                        if not pd.isna(real_val):
                            fig.add_hline(
                                y=real_val, line_dash="dot", line_color="#EF4444",
                                annotation_text=f"Gerçekleşen: {real_val:.2f}",
                                annotation_position="right",
                            )

            fig.update_layout(
                title=f"{user_sel} — {target_sel} için {metric_sel_label} revizyonu",
                hovermode="x unified",
                showlegend=False,
                height=400,
                margin=dict(l=10, r=10, t=60, b=40),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title="Tahmin Tarihi", gridcolor="rgba(148,163,184,0.12)"),
                yaxis=dict(title=metric_sel_label, gridcolor="rgba(148,163,184,0.12)"),
            )
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("**Tüm revizyonlar:**")
            show_cols = ["tahmin_tarihi", metric_sel, "kaynak_link"]
            show_cols = [c for c in show_cols if c in rev_df.columns]
            st.dataframe(
                rev_df[show_cols].rename(columns={
                    "tahmin_tarihi": "Tarih",
                    metric_sel: metric_sel_label,
                    "kaynak_link": "Kaynak",
                }),
                use_container_width=True,
                hide_index=True,
            )

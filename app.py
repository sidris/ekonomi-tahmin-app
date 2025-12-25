# ========================================================
# SAYFA: ISI HARİTASI (GELİŞMİŞ VERSİYON)
# ========================================================
elif page == "🔥 Isı Haritası":
    st.header("🔥 Tahmin Isı Haritası")
    st.info("Katılımcıların tahminlerini veya revizyon tarihçelerini renkli tablo olarak izleyin.")

    res_t = supabase.table(TABLE_TAHMIN).select("*").execute()
    df_t = pd.DataFrame(res_t.data)
    res_k = supabase.table(TABLE_KATILIMCI).select("ad_soyad", "anket_kaynagi").execute()
    df_k = pd.DataFrame(res_k.data)

    if not df_t.empty and not df_k.empty:
        df_t = clean_and_sort_data(df_t)
        # Tarih formatı ve sıralama (Revizyon takibi için kritik)
        df_t['tahmin_tarihi'] = pd.to_datetime(df_t['tahmin_tarihi'])
        df_t = df_t.sort_values(by='tahmin_tarihi')
        
        # Tam veri setini birleştir (Filtreleme aşağıda yapılacak)
        df_full = pd.merge(df_t, df_k, left_on="kullanici_adi", right_on="ad_soyad", how="inner")
        df_full['gorunen_isim'] = df_full.apply(lambda x: f"{x['kullanici_adi']} ({x['anket_kaynagi']})" if pd.notnull(x['anket_kaynagi']) and x['anket_kaynagi'] != '' else x['kullanici_adi'], axis=1)

        # --- AYARLAR PANELI ---
        with st.expander("⚙️ Harita Ayarları", expanded=True):
            # MOD SEÇİMİ
            view_mode = st.radio("Görünüm Modu", ["📅 Hedef Dönem Karşılaştırması", "⏳ Zaman İçindeki Değişim (Revizyon)"], horizontal=True)
            st.markdown("---")
            
            c1, c2, c3 = st.columns(3)
            
            # 1. Metrik Seçimi (Ortak)
            metrics = {"PPK Faizi": "tahmin_ppk_faiz", "Yıl Sonu Faiz": "tahmin_yilsonu_faiz", "Aylık Enflasyon": "tahmin_aylik_enf", "Yıl Sonu Enflasyon": "tahmin_yilsonu_enf"}
            sel_metric_label = c1.selectbox("Veri Seti", list(metrics.keys()))
            sel_metric = metrics[sel_metric_label]
            
            # 2. Katılımcı Seçimi (Ortak)
            all_users = sorted(df_full['gorunen_isim'].unique())
            sel_users = c2.multiselect("Katılımcılar", all_users, default=all_users[:10] if len(all_users)>0 else [])

            # 3. Dönem Seçimi (Moda göre değişir)
            all_periods = sorted(df_full['donem'].unique(), reverse=True)
            
            if view_mode == "📅 Hedef Dönem Karşılaştırması":
                # Sütunlar: Hedef Dönemler (Örn: 2025-01, 2025-02...)
                # Her dönem için EN SON girilen tahmini alır.
                sel_periods = c3.multiselect("Hedef Dönemler", all_periods, default=all_periods[:6] if len(all_periods)>0 else [])
                
                if not sel_users or not sel_periods: st.stop()
                
                # Veriyi Hazırla: Her hedef dönem için en son kaydı tut
                df_filtered = df_full[df_full['gorunen_isim'].isin(sel_users) & df_full['donem'].isin(sel_periods)].copy()
                df_filtered = df_filtered.sort_values(by='tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'donem'], keep='last')
                
                pivot_col = 'donem'
                
            else: # "⏳ Zaman İçindeki Değişim (Revizyon)"
                # Sütunlar: Tahmin Yapılan Aylar (Ekim, Kasım, Aralık...)
                # Kullanıcı TEK BİR hedef dönem seçmeli (Örn: Sadece 2025 Yıl Sonu tahminlerinin gelişimi)
                target_period = c3.selectbox("Hangi Hedefin Geçmişini İzliceksiniz?", all_periods)
                
                if not sel_users or not target_period: st.stop()
                
                # Veriyi Hazırla: Sadece seçilen hedef döneme ait verileri al
                df_filtered = df_full[df_full['gorunen_isim'].isin(sel_users) & (df_full['donem'] == target_period)].copy()
                
                # Tahmin Tarihini "Yıl-Ay" formatına çevir (Sütunlar bu olacak)
                df_filtered['tahmin_ayi'] = df_filtered['tahmin_tarihi'].dt.strftime('%Y-%m')
                
                # Aynı ay içinde birden fazla tahmin varsa, o ayın SON tahminini al
                df_filtered = df_filtered.sort_values(by='tahmin_tarihi').drop_duplicates(subset=['kullanici_adi', 'tahmin_ayi'], keep='last')
                
                pivot_col = 'tahmin_ayi'

        # --- PIVOT VE GÖRSELLEŞTİRME ---
        if df_filtered.empty:
            st.warning("Seçilen kriterlere uygun veri bulunamadı.")
            st.stop()

        # Pivot Tablo Oluştur
        pivot_df = df_filtered.pivot(index='gorunen_isim', columns=pivot_col, values=sel_metric)
        # Sütunları sırala
        pivot_df = pivot_df.reindex(columns=sorted(pivot_df.columns))

        # Renklendirme Fonksiyonu
        def highlight_changes(data):
            styles = pd.DataFrame('', index=data.index, columns=data.columns)
            for idx, row in data.iterrows():
                prev_val = None
                first_val_found = False
                
                for col in data.columns:
                    val = row[col]
                    if pd.isna(val): continue
                    
                    style = ''
                    if not first_val_found:
                        # İlk veri (Başlangıç noktası) - SARI
                        style = 'background-color: #FFF9C4; color: black; font-weight: bold; border: 1px solid white;'
                        first_val_found = True
                    else:
                        if prev_val is not None:
                            if val > prev_val:
                                # Yükseliş - KIRMIZI
                                style = 'background-color: #FFCDD2; color: #B71C1C; font-weight: bold; border: 1px solid white;'
                            elif val < prev_val:
                                # Düşüş - YEŞİL
                                style = 'background-color: #C8E6C9; color: #1B5E20; font-weight: bold; border: 1px solid white;'
                            else:
                                # Değişim Yok - Gri/Nötr
                                style = 'color: #555;'
                    
                    styles.at[idx, col] = style
                    prev_val = val
            return styles

        st.markdown(f"### 🔥 {sel_metric_label} - {'Hedef Analizi' if view_mode.startswith('📅') else f'{target_period} Revizyon Tarihçesi'}")
        
        st.dataframe(
            pivot_df.style.apply(highlight_changes, axis=None).format("{:.2f}"), 
            use_container_width=True, 
            height=len(sel_users)*50 + 100
        )
        
        st.caption("""
        **Renklerin Anlamı:**
        🟡 **Sarı:** Kurumun o seri için verdiği ilk tahmin.
        🔴 **Kırmızı:** Bir önceki döneme göre tahmini **yükselmiş**.
        🟢 **Yeşil:** Bir önceki döneme göre tahmini **düşmüş**.
        ⚪ **Beyaz:** Tahmin değişmemiş.
        """)
        
    else:
        st.info("Veri yok.")

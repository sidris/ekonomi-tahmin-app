# Finansal Tahmin Terminali

## 1. GitHub Repo Yapısı

```
ekonomi-tahmin-app/           ← repo root
├── app.py
├── utils.py                  ← Tüm yardımcılar + UI tema burada
├── requirements.txt
├── schema.sql                ← Sadece referans, Streamlit çalıştırmaz
├── README.md
├── .streamlit/
│   └── secrets.toml          ← Streamlit Cloud'a yüklenmez! Cloud panelinden gir
└── pages/
    ├── Dashboard.py
    ├── Manuel_Veri_Girisi.py
    ├── Katilimci_Yonetimi.py
    ├── Excel_Yukleme.py
    ├── Piyasa_Verileri.py
    ├── Veri_Havuzu.py
    └── Sistem_Yonetimi.py
```

**Önemli:**
- `schema.sql` dosyası uygulama tarafından **okunmaz**. Repo içinde durabilir (sadece referans için). Streamlit Cloud onu görmez bile.
- `theme.py` diye ayrı bir dosya **yok**; tüm UI tema fonksiyonları `utils.py` içinde. Bu Streamlit Cloud'da `pages/` import yolu sorununu önler.

## 2. Streamlit Cloud'a Deploy

1. Bu dosyaları GitHub reposuna push et.
2. Streamlit Cloud panelinde **New app** → repoyu seç → main file: `app.py`.
3. App ayarlarından **Secrets** bölümüne şunları ekle:

```toml
SUPABASE_URL = "https://<proje-id>.supabase.co"
SUPABASE_KEY = "<service_role veya anon key>"
APP_PASSWORD = "istediğin-şifre"
EVDS_KEY = "<TCMB EVDS API anahtarın>"
```

4. Deploy'u tetikle.

## 3. Supabase Kurulumu

Supabase projesinde **SQL Editor**'a git, `schema.sql` içindeki SQL'i yapıştır ve çalıştır.

### Eski şemadan geçiyorsan (migration)

`schema.sql`'in sonundaki migration bloğunu yorumdan çıkar:

```sql
alter table public.beklentiler_takip drop column if exists versiyon;
alter table public.beklentiler_takip drop constraint if exists beklentiler_unique;
alter table public.beklentiler_takip
    add constraint beklentiler_unique unique (kullanici_adi, hedef_donemi, tahmin_tarihi);
```

## 4. Lokal Çalıştırma

```bash
pip install -r requirements.txt
# .streamlit/secrets.toml dosyasını oluştur (yukarıdaki örnek)
streamlit run app.py
```

## 5. Demo → Gerçek Veri Akışı

1. Giriş yap → sol menüden **Sistem Yönetimi**.
2. **🚀 Demo Verisi Üret** → ~30 saniyede 16 katılımcı, ~1000 tahmin.
3. **Dashboard** sayfasında liderlik tablosu, zaman serisi, ısı haritası, tahmin revizyonu görüntüle.
4. Yönetime gösterim bittiğinde → **Sistem Yönetimi → Sıfırlama** → "Hepsi" seç → onaya **SIL** yaz → sıfırla.
5. Artık gerçek veri girişine başla (**Manuel Veri Girişi** veya **Excel Yükleme**).

## 6. Veri Modeli

- **Bireysel, Kurumsal:** tek nokta tahmin. Min/Max UI'da kapalı, DB'ye `NULL`.
- **Anket:** Medyan + Min + Max + N.
- Her `(katılımcı, hedef_donem, tarih)` tek satır. Aynı tarihte revizyon `UPDATE`, farklı tarih yeni `INSERT`.

## 7. Piyasa Verisi (EVDS + BIS)

- **TÜFE hibrit:**
  - `TP.FE.OKTG01` (2003=100) — 2025 sonuna kadar
  - `TP.TUKFIY2025.GENEL` (2025=100) — 2026 Ocak'tan itibaren
  - Aylık/yıllık % değişim seviyeden hesaplanır.
- **Politika faizi:** BIS `WS_CBPOL/D.TR`.

## 8. Sık Karşılaşılan Sorunlar

- **`ModuleNotFoundError: theme`:** artık olmamalı (tema `utils.py`'ye taşındı). Eğer görürsen eski `theme.py` dosyası repoda kalmış demektir — sil.
- **RLS hatası (`new row violates row-level security policy`):** Supabase'de RLS açıksa ya `service_role` key kullan ya da policy aç.
- **EVDS paket hatası:** `pip install evds` — büyük/küçük harf olabilir, işe yaramazsa `pip install EVDS` dene.
- **Giriş yapılmış görünmüyor:** her sayfa `utils.require_login_page()` çağırıyor. Session state `giris_yapildi` key'iyle yönetiliyor, Streamlit sayfalar arası geçişte kaybolmaz.

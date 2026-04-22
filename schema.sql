-- =========================================================
-- Finansal Tahmin Terminali — Supabase Şeması
-- Supabase → SQL Editor'da çalıştır.
-- =========================================================

-- Katılımcılar
create table if not exists public.katilimcilar (
    id          uuid primary key default gen_random_uuid(),
    ad_soyad    text not null,
    kategori    text not null default 'Bireysel'
                check (kategori in ('Bireysel', 'Kurumsal', 'Anket')),
    created_at  timestamptz not null default now()
);

-- Aynı ismin iki kez eklenmesini engelle (case-insensitive)
create unique index if not exists katilimcilar_ad_soyad_unique
    on public.katilimcilar (lower(ad_soyad));


-- Tahminler
create table if not exists public.beklentiler_takip (
    id                    uuid primary key default gen_random_uuid(),
    kullanici_adi         text not null,
    kategori              text not null,
    anket_donemi          text,
    hedef_donemi          text not null,
    tahmin_tarihi         date not null,

    -- Faiz tahminleri
    tahmin_ppk_faiz       numeric,
    min_ppk_faiz          numeric,
    max_ppk_faiz          numeric,
    tahmin_yilsonu_faiz   numeric,
    min_yilsonu_faiz      numeric,
    max_yilsonu_faiz      numeric,

    -- Enflasyon tahminleri
    tahmin_aylik_enf      numeric,
    min_aylik_enf         numeric,
    max_aylik_enf         numeric,
    tahmin_yilsonu_enf    numeric,
    min_yilsonu_enf       numeric,
    max_yilsonu_enf       numeric,

    -- Meta
    katilimci_sayisi      integer,
    kaynak_link           text,
    created_at            timestamptz not null default now(),

    -- Aynı kullanıcı aynı gün aynı hedef dönem için tek satır
    constraint beklentiler_unique unique (kullanici_adi, hedef_donemi, tahmin_tarihi)
);

-- Filtreleme indeksleri
create index if not exists beklentiler_hedef_idx    on public.beklentiler_takip (hedef_donemi);
create index if not exists beklentiler_user_idx     on public.beklentiler_takip (kullanici_adi);
create index if not exists beklentiler_tarih_idx    on public.beklentiler_takip (tahmin_tarihi desc);
create index if not exists beklentiler_kategori_idx on public.beklentiler_takip (kategori);

-- =========================================================
-- Eğer eski şemandan geçiyorsan (migration):
-- =========================================================
-- alter table public.beklentiler_takip drop column if exists versiyon;
-- alter table public.beklentiler_takip drop constraint if exists beklentiler_unique;
-- alter table public.beklentiler_takip
--     add constraint beklentiler_unique unique (kullanici_adi, hedef_donemi, tahmin_tarihi);

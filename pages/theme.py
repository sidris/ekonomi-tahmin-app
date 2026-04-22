"""
theme.py — Tüm sayfalarda ortak görsel kimlik.
Sayfa başında:  from theme import apply_theme; apply_theme()
"""
import streamlit as st


def apply_theme():
    st.markdown(
        """
        <style>
          /* Global tipografi */
          html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif;
          }

          /* Başlıklar */
          h1, h2, h3 { letter-spacing: -0.02em; }

          /* Blok konteyner biraz daha ferah */
          .main .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1400px;
          }

          /* Metrik kartları */
          [data-testid="stMetric"] {
            background: linear-gradient(135deg, rgba(30,41,59,0.5) 0%, rgba(15,23,42,0.4) 100%);
            padding: 16px 20px;
            border-radius: 12px;
            border: 1px solid rgba(148,163,184,0.15);
          }
          [data-testid="stMetricLabel"] {
            color: #94A3B8 !important;
            font-size: 13px !important;
            font-weight: 500;
          }
          [data-testid="stMetricValue"] {
            font-size: 28px !important;
            font-weight: 700;
          }

          /* Özel renk değişkenleri */
          :root {
            --accent: #3B82F6;
            --accent-soft: rgba(59,130,246,0.15);
            --success: #10B981;
            --warning: #F59E0B;
            --danger: #EF4444;
            --surface: rgba(15,23,42,0.55);
            --surface-strong: rgba(15,23,42,0.85);
            --border: rgba(148,163,184,0.18);
          }

          /* Kart */
          .soft-card {
            padding: 20px 22px;
            border-radius: 16px;
            border: 1px solid var(--border);
            background: var(--surface);
            box-shadow: 0 4px 16px rgba(0,0,0,0.10);
            margin-bottom: 14px;
          }
          .soft-card h3 {
            margin: 0 0 10px 0;
            font-size: 17px;
            font-weight: 600;
          }
          .soft-card ul { margin: 0; padding-left: 18px; color: rgba(226,232,240,0.88); }
          .soft-card li { margin: 4px 0; }

          /* Leaderboard kartları */
          .leader-card {
            padding: 14px 16px;
            border-radius: 12px;
            background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(16,185,129,0.05));
            border: 1px solid rgba(148,163,184,0.15);
            margin-bottom: 8px;
          }
          .leader-rank {
            font-size: 22px;
            margin-right: 6px;
          }
          .leader-name { font-weight: 600; font-size: 15px; }
          .leader-meta {
            color: #94A3B8;
            font-size: 12px;
            margin-top: 2px;
            font-variant-numeric: tabular-nums;
          }

          /* Başlık bloğu (büyük, merkez) */
          .page-header {
            margin-bottom: 22px;
            padding-bottom: 14px;
            border-bottom: 1px solid var(--border);
          }
          .page-header h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 700;
          }
          .page-header .sub {
            color: #94A3B8;
            font-size: 14px;
            margin-top: 4px;
          }

          /* Kategori rozetleri */
          .badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.02em;
          }
          .badge-anket    { background: rgba(59,130,246,0.18);  color: #93C5FD; }
          .badge-kurumsal { background: rgba(16,185,129,0.18);  color: #6EE7B7; }
          .badge-bireysel { background: rgba(245,158,11,0.18);  color: #FCD34D; }

          /* Gerçekleşen değer vurgusu */
          .actual-box {
            background: linear-gradient(135deg, rgba(239,68,68,0.10), rgba(239,68,68,0.04));
            border-left: 3px solid #EF4444;
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 10px;
            font-variant-numeric: tabular-nums;
          }

          /* Tablolar daha ferah */
          [data-testid="stDataFrame"] {
            border-radius: 10px;
            overflow: hidden;
          }

          /* Butonlar */
          .stButton button {
            border-radius: 10px;
            font-weight: 500;
          }
          .stButton button[kind="primary"] {
            box-shadow: 0 2px 8px rgba(59,130,246,0.25);
          }

          /* Giriş ekranı */
          .app-title {
            text-align: center;
            font-size: 36px;
            font-weight: 700;
            margin: 20px 0 6px;
            background: linear-gradient(90deg, #60A5FA, #A78BFA);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
          }
          .app-subtitle {
            text-align: center;
            color: #94A3B8;
            font-size: 16px;
            margin-bottom: 28px;
          }
          .login-box {
            padding: 24px;
            border-radius: 16px;
            border: 1px solid var(--border);
            background: var(--surface-strong);
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
          }
          .hint {
            color: #94A3B8;
            font-size: 13px;
            text-align: center;
            margin-top: 10px;
          }

          /* Tehlikeli buton (sıfırlama) */
          .danger-zone {
            padding: 16px 18px;
            border-radius: 12px;
            border: 1px dashed rgba(239,68,68,0.4);
            background: rgba(239,68,68,0.05);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = ""):
    """Her sayfanın en üstünde tutarlı bir başlık bloğu."""
    st.markdown(
        f"""
        <div class="page-header">
          <h1>{title}</h1>
          {f'<div class="sub">{subtitle}</div>' if subtitle else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def category_badge(kategori: str) -> str:
    """Kategori için HTML rozet döner."""
    cls_map = {
        "Anket": "badge-anket",
        "Kurumsal": "badge-kurumsal",
        "Bireysel": "badge-bireysel",
    }
    cls = cls_map.get(kategori, "badge-bireysel")
    return f'<span class="badge {cls}">{kategori}</span>'

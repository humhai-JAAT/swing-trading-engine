"""Swing Trading Engine — READ-ONLY viewer dashboard.

Shows exactly ONE variant — whichever the admin app's "Public Viewer" control
currently points db.get_setting("public_variant") at. No controls, no settings,
no force exit. Deploy as its OWN separate Streamlit Cloud app (same repo,
main file path "viewer_app.py").
"""

import os

import streamlit as st

try:
    if "DATABASE_URL" in st.secrets:
        os.environ.setdefault("DATABASE_URL", st.secrets["DATABASE_URL"])
except Exception:
    pass

from engine import config, dashboard_view, db

st.set_page_config(page_title="Swing Trading Engine — Viewer", page_icon="📈", layout="wide")
dashboard_view.inject_custom_css()

db.init_db()
settings = config.load_settings()

st.title("📈 Swing Trading Engine — Viewer")
st.caption("Live view only — no controls here. CNC carry-forward on 1H candles.")

public_variant_id = db.get_setting("public_variant", "") or ""
if not public_variant_id or public_variant_id not in config.all_variant_ids():
    st.info("No variant is currently public. Check back later.")
    st.stop()

universe_bot_key, variant_key = public_variant_id.split("/", 1)
variant_cfg = config.VARIANTS_BY_KEY[variant_key]
st.caption(f"Showing: **{config.UNIVERSE_BOTS_BY_KEY[universe_bot_key]['label']}** · "
           f"{variant_key.replace('_', ' ')}")


@st.fragment(run_every=dashboard_view.get_refresh_interval())
def live_panel():
    dashboard_view.render_warning_banner()
    dashboard_view.render_account_health()
    st.divider()
    dashboard_view.render_variant_panel(universe_bot_key, variant_cfg, settings, show_force_exit=False)


live_panel()

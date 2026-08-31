"""Swing Trading Engine — Streamlit dashboard (admin, full controls).

1 universe-bot (bot_500 — full Nifty500) x 2 variants (trailing_ema /
trailing_atr) = 2 total, all scanning/trading independently in the background.
1H candle evaluation at each hourly close. CNC carry-forward, no square-off.
"""

import os
from datetime import datetime

import pytz
import streamlit as st

try:
    if "DATABASE_URL" in st.secrets:
        os.environ.setdefault("DATABASE_URL", st.secrets["DATABASE_URL"])
    for prefix in ("ANGELONE_1", "ANGELONE_2"):
        for suffix in ("CLIENT_CODE", "PASSWORD", "TOTP_SECRET", "API_KEY"):
            key = f"{prefix}_{suffix}"
            if key in st.secrets:
                os.environ.setdefault(key, st.secrets[key])
    for prefix in ("GROWW_1", "GROWW_2"):
        for suffix in ("API_KEY", "API_SECRET", "TOTP_SECRET"):
            key = f"{prefix}_{suffix}"
            if key in st.secrets:
                os.environ.setdefault(key, st.secrets[key])
except Exception:
    pass

from engine import config, dashboard_view, db, scheduler

st.set_page_config(page_title="Swing Trading Engine", page_icon="📈", layout="wide")
dashboard_view.inject_custom_css()

IST = pytz.timezone("Asia/Kolkata")
db.init_db()
settings = config.load_settings()

st.title("📈 Swing Trading Engine")
st.caption(
    "1 universe-bot (full Nifty500) x 2 variants (EMA9 trailing / ATR trailing exit) = "
    "2 independent paper-trading strategies on 1H candles, CNC carry-forward (no intraday "
    "square-off). Shares one deduplicated ranking + candle-data fetch per cycle."
)

# ---------------- Sidebar: controls ----------------
st.sidebar.title("Controls")

running = scheduler.is_running()
st.sidebar.markdown(f"**Scheduler:** {'Running' if running else 'Stopped'}")

col_a, col_b = st.sidebar.columns(2)
if col_a.button("Start", use_container_width=True, disabled=running):
    scheduler.start_scheduler()
    st.rerun()
if col_b.button("Stop", use_container_width=True, disabled=not running):
    scheduler.stop_scheduler()
    st.rerun()

st.sidebar.caption(
    f"Position management every {settings['position_management_interval_minutes']} min · "
    f"entry scan at 1H-boundary+1 offsets (10:16, 11:16, 12:16, 13:16, 14:16) · "
    f"awake only {settings['wake_time']}–{settings['sleep_time']} IST."
)

col_c, col_d = st.sidebar.columns(2)
if col_c.button("Run Position Mgmt Now", use_container_width=True):
    with st.spinner("Managing open positions..."):
        result = scheduler.run_position_management_cycle(settings)
    st.sidebar.success(f"Done: {result.get('status')}")
if col_d.button("Run Scan Now", use_container_width=True, type="primary"):
    with st.spinner("Running Stage 1 + Stage 2 + entry scan..."):
        result = scheduler.run_full_scan_cycle(settings)
    entered = result.get("entered_variants", [])
    st.sidebar.success(f"Done: {result.get('status')} · entered={len(entered)} variant(s)")
    if result.get("warnings"):
        st.sidebar.warning(f"{len(result['warnings'])} warning(s) — see banner below.")

st.sidebar.divider()
now_ist = datetime.now(IST)
bot_awake = scheduler.is_awake(settings, now_ist)
st.sidebar.markdown(f"**Bot:** {'Awake' if bot_awake else 'Asleep (outside wake/sleep window)'}")
status = scheduler.market_status(now_ist)
status_label = {"open": "Market Open", "closed_hours": "Market Closed (outside hours)",
                "closed_weekend": "Market Closed (weekend)"}.get(status, status)
st.sidebar.markdown(f"**{status_label}**")
st.sidebar.caption(f"IST time: {now_ist.strftime('%Y-%m-%d %H:%M:%S')}")

st.sidebar.divider()
st.sidebar.markdown("### Viewing")
variant_key = st.sidebar.radio(
    "Variant", options=[v["key"] for v in config.VARIANTS],
    format_func=lambda k: k.replace("_", " "),
)
variant_cfg = config.VARIANTS_BY_KEY[variant_key]
universe_bot_key = config.UNIVERSE_BOTS[0]["key"]
st.sidebar.caption("Both variants keep scanning/trading independently regardless of which one you're viewing.")

st.sidebar.divider()
st.sidebar.markdown("### Public Viewer")
_public_options = [""] + config.all_variant_ids()
_public_current = db.get_setting("public_variant", "") or ""
public_variant = st.sidebar.selectbox(
    "Variant shown on the Viewer app",
    options=_public_options,
    index=_public_options.index(_public_current) if _public_current in _public_options else 0,
    format_func=lambda v: "— none (viewer shows nothing) —" if v == "" else v.replace("/", " · ").replace("_", " "),
)
if public_variant != _public_current:
    db.set_setting("public_variant", public_variant)
    st.sidebar.success("Viewer app updated.")
    st.rerun()
st.sidebar.caption("Controls what the separate read-only Viewer app shows.")

st.sidebar.divider()
st.sidebar.markdown("### Stock Pool Size")
pool_size = st.sidebar.number_input(
    "Top-N gainers for scanning", min_value=5, max_value=100, step=5,
    value=int(settings["gainers_pool_size"]),
    help="How many top %-gainers Stage 1 hands to the bot for entry scanning. "
         "Lower = fewer Stage 2 candle fetches (faster scan cadence) but a narrower candidate set.",
)
if pool_size != settings["gainers_pool_size"]:
    config.save_settings({**settings, "gainers_pool_size": pool_size})
    st.sidebar.success(f"Pool size updated to {pool_size}. Applies from the next entry-scan cycle.")
    st.rerun()

st.sidebar.divider()
with st.sidebar.expander("Strategy Settings", expanded=False):
    capital = st.number_input("Capital per Variant (Rs)", min_value=1000, step=1000,
                               value=int(settings["starting_capital"]))
    target_pct = st.number_input("Fixed Target % (trailing-activation trigger)", min_value=0.5, max_value=50.0,
                                  step=0.5, value=float(settings["profit_target_pct"]))
    sl_pct = st.number_input("Fixed Stop-Loss %", min_value=0.5, max_value=50.0, step=0.5,
                              value=float(settings["stop_loss_pct"]))
    atr_period = st.number_input("ATR Period", min_value=5, max_value=50, step=1,
                                  value=int(settings["atr_period"]))
    atr_multiplier = st.number_input("ATR Multiplier", min_value=0.5, max_value=5.0, step=0.1,
                                      value=float(settings["atr_multiplier"]))
    wake_time = st.text_input("Bot Wake Time (HH:MM)", value=settings["wake_time"])
    sleep_time = st.text_input("Bot Sleep Time (HH:MM)", value=settings["sleep_time"])

    if st.button("Save Settings", use_container_width=True):
        new_settings = {
            **settings, "starting_capital": capital,
            "profit_target_pct": target_pct, "stop_loss_pct": sl_pct,
            "atr_period": atr_period, "atr_multiplier": atr_multiplier,
            "wake_time": wake_time, "sleep_time": sleep_time,
        }
        config.save_settings(new_settings)
        st.success("Saved. Restart the scheduler for interval changes to take effect.")
        st.rerun()

st.sidebar.divider()
with st.sidebar.expander("Danger Zone", expanded=False):
    st.caption("Permanently deletes ALL trades and cycle logs for both variants. Cannot be undone.")
    confirm_reset = st.checkbox("I understand this deletes everything", key="confirm_reset")
    if st.button("Reset All Data", type="secondary", disabled=not confirm_reset, use_container_width=True):
        db.reset_all_data()
        st.success("All data reset.")
        st.rerun()

st.sidebar.caption(
    "CNC delivery charges (brokerage + STT + stamp duty + exchange + SEBI + IPFT + GST) "
    "are simulated on every paper trade. Broker data is used for forward-testing only — "
    "treat as paper trading, not a live-execution signal."
)


@st.fragment(run_every=dashboard_view.get_refresh_interval())
def live_panel():
    dashboard_view.render_warning_banner()
    dashboard_view.render_account_health()
    st.divider()
    dashboard_view.render_variant_panel(universe_bot_key, variant_cfg, settings, show_force_exit=True)


live_panel()

st.divider()
st.subheader("Variant Scoreboard")
st.caption("Both variants compared side by side.")


@st.fragment(run_every=dashboard_view.get_refresh_interval())
def scoreboard_panel():
    dashboard_view.render_variant_scoreboard(settings)


scoreboard_panel()

st.divider()
st.subheader("Latest Cycle Log")
logs = db.get_cycle_logs(limit=20)
if logs.empty:
    st.info("No cycles run yet — click **Run Scan Now** or start the scheduler.")
else:
    st.dataframe(logs, use_container_width=True, hide_index=True)

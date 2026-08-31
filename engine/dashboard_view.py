"""Dashboard sections shared between app.py (admin) and viewer_app.py (read-only).

render_warning_banner() — Stage 1/2 fallback usage or partial-fetch failures
visible here, not just logged.

render_account_health() — shows which broker accounts are configured.

render_variant_panel() — ONE variant's full panel (metrics/open-position/equity/
trade-log). With only 2 variants, the calling script uses a simple radio selector.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st

from common.helpers import format_currency, format_pct
from engine import config, db, metrics
from engine.broker_accounts import get_configured_accounts

IST = pytz.timezone("Asia/Kolkata")
REFRESH_SECONDS = 15

TOKENS = {
    "bg_page": "#0B0F14",
    "bg_surface": "#141A21",
    "bg_surface_raised": "#1B232C",
    "border": "#232B34",
    "text_primary": "#E8EDF2",
    "text_secondary": "#8A96A3",
    "accent": "#3B82F6",
    "success": "#22C55E",
    "danger": "#EF4444",
    "warning": "#F59E0B",
    "radius": "10px",
}


def inject_custom_css() -> None:
    t = TOKENS
    st.markdown(f"""
    <style>
    div[data-testid="stMetric"] {{
        background: {t["bg_surface_raised"]};
        border: 1px solid {t["border"]};
        border-radius: {t["radius"]};
        padding: 14px 18px;
    }}
    div[data-testid="stMetricLabel"] {{
        color: {t["text_secondary"]};
        font-size: 0.72rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}
    div[data-testid="stMetricValue"] {{
        color: {t["text_primary"]};
    }}
    div[data-testid="stAlert"] {{
        border-radius: {t["radius"]};
        border-width: 1px;
        border-style: solid;
    }}
    .ste-position-card {{
        background: {t["bg_surface_raised"]};
        border: 1px solid {t["accent"]};
        border-radius: {t["radius"]};
        padding: 18px 20px;
        margin-bottom: 8px;
    }}
    .ste-position-header {{
        color: {t["text_primary"]};
        font-weight: 700;
        font-size: 1.05rem;
        margin-bottom: 12px;
    }}
    .ste-position-row {{
        display: flex; gap: 32px; flex-wrap: wrap;
    }}
    .ste-position-field-label {{
        color: {t["text_secondary"]};
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-bottom: 2px;
    }}
    .ste-position-field-value {{
        color: {t["text_primary"]};
        font-size: 0.92rem;
        font-weight: 600;
    }}
    .ste-chip-row {{
        display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 4px;
    }}
    .ste-chip {{
        display: flex; align-items: center; gap: 6px;
        background: {t["bg_surface_raised"]};
        border: 1px solid {t["border"]};
        border-radius: {t["radius"]};
        padding: 8px 12px;
        font-size: 0.8rem;
        font-weight: 600;
        color: {t["text_primary"]};
    }}
    .ste-chip-dot {{
        width: 8px; height: 8px; border-radius: 50%;
        background: {t["text_secondary"]};
        flex-shrink: 0;
    }}
    .ste-chip-dot.ste-chip-ok {{ background: {t["success"]}; }}
    </style>
    """, unsafe_allow_html=True)


def render_warning_banner() -> None:
    logs = db.get_cycle_logs(limit=30)
    scan_logs = logs[logs["stage"] == "entry_scan"] if not logs.empty and "stage" in logs.columns else logs
    if scan_logs.empty:
        st.info("No entry-scan cycle has run yet — waiting for the first hourly-boundary scan.")
    else:
        latest = scan_logs.iloc[0]
        warnings_text = str(latest.get("warnings") or "").strip()
        if warnings_text:
            st.warning(
                f"Last scan cycle ({latest['cycle_time']}) had incomplete data: {warnings_text}",
                icon="⚠️",
            )
        else:
            st.success(f"Last scan cycle ({latest['cycle_time']}) fetched full data, no fallback needed.", icon="✅")

    pos_logs = logs[logs["stage"] == "position_management"] if not logs.empty and "stage" in logs.columns else logs
    if not pos_logs.empty:
        latest_pos = pos_logs.iloc[0]
        pos_warnings_text = str(latest_pos.get("warnings") or "").strip()
        if pos_warnings_text:
            st.warning(
                f"Last position-management cycle ({latest_pos['cycle_time']}) "
                f"couldn't fully monitor open positions: {pos_warnings_text}",
                icon="⚠️",
            )


def render_account_health() -> None:
    accounts = get_configured_accounts()
    labels = [
        ("Angel One #1", accounts["angelone"], 0), ("Angel One #2", accounts["angelone"], 1),
        ("Groww #1", accounts["groww"], 0), ("Groww #2", accounts["groww"], 1),
    ]
    chips = "".join(
        f'<div class="ste-chip">'
        f'<span class="ste-chip-dot {"ste-chip-ok" if idx < len(pool) else ""}"></span>'
        f'{label}</div>'
        for label, pool, idx in labels
    )
    st.markdown(f'<div class="ste-chip-row">{chips}</div>', unsafe_allow_html=True)


def render_variant_scoreboard(settings: dict) -> None:
    df = metrics.get_variant_rankings(settings)
    if df["total_trades"].sum() == 0:
        st.info("No closed trades yet for any variant — the scoreboard fills in once trades start closing.")
        return

    display = df.copy()
    display["profit_factor"] = display["profit_factor"].apply(lambda x: "∞" if x == float("inf") else f"{x:.2f}")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "variant_id": st.column_config.TextColumn("Variant"),
            "universe_bot": None,
            "variant": None,
            "total_trades": st.column_config.NumberColumn("Trades"),
            "win_rate_pct": st.column_config.NumberColumn("Win Rate %", format="%.1f"),
            "wilson_win_rate_pct": st.column_config.NumberColumn("Win Rate % (Wilson LB)", format="%.1f"),
            "profit_factor": st.column_config.TextColumn("Profit Factor"),
            "sqn": st.column_config.NumberColumn("SQN", format="%.2f"),
            "expectancy": st.column_config.NumberColumn("Expectancy (Rs)", format="%.0f"),
            "total_pnl": st.column_config.NumberColumn("Total P&L (Rs)", format="%.0f"),
            "total_pnl_pct": st.column_config.NumberColumn("Total P&L %", format="%.1f"),
            "max_drawdown": st.column_config.NumberColumn("Max Drawdown (Rs)", format="%.0f"),
        },
    )
    st.caption(
        "Ranked by SQN (System Quality Number — rewards a consistent edge over raw trade count). "
        "Wilson LB win rate is a conservative estimate that discounts small samples."
    )


def render_variant_panel(universe_bot_key: str, variant_cfg: dict, settings: dict,
                          show_force_exit: bool = False) -> None:
    variant_id = f"{universe_bot_key}/{variant_cfg['key']}"
    universe_label = config.UNIVERSE_BOTS_BY_KEY[universe_bot_key]["label"]
    exit_label = "EMA9 trailing" if variant_cfg["exit_style"] == "ema" else "ATR trailing"

    summary = metrics.get_summary(variant_id, settings["starting_capital"])

    st.markdown(f"### {universe_label} — {exit_label}")
    st.caption(
        f"**{exit_label}** exit (activates once price crosses the "
        f"{settings['profit_target_pct']:.1f}% fixed target — stop-loss is fixed at "
        f"{settings['stop_loss_pct']:.1f}% throughout) · CNC carry-forward, no intraday square-off"
    )

    m1, m2 = st.columns(2)
    m1.metric("Current Capital", format_currency(summary["current_capital"]))
    m2.metric("Total P&L", format_currency(summary["total_pnl"]), format_pct(summary["total_pnl_pct"]))
    m3, m4 = st.columns(2)
    m3.metric("Total Trades", summary["total_trades"])
    m4.metric("Win Rate", f"{summary['win_rate']:.1f}%")
    m5, m6 = st.columns(2)
    pf = summary["profit_factor"]
    m5.metric("Profit Factor", f"{pf:.2f}" if pf != float("inf") else "∞")
    m6.metric("Max Drawdown", format_currency(summary["max_drawdown"]))
    st.caption(f"Open: {summary['open_positions']} / 1 · Charges paid: {format_currency(summary['total_charges'])}")

    st.divider()

    trade = db.get_open_trade(variant_id)
    if not trade:
        st.info("No open position — scanning for a fresh entry signal at the next 1H candle close.")
    else:
        current_price = trade["entry_price"]
        accounts = get_configured_accounts()
        pool = accounts["groww"] or accounts["angelone"]
        if pool:
            try:
                quotes = pool[0].fetch_quotes_batch([trade["symbol"]])
                if quotes:
                    current_price = quotes[0].last_price
            except Exception:
                pass

        unrealized_pnl = (current_price - trade["entry_price"]) * trade["quantity"]
        unrealized_pct = unrealized_pnl / trade["capital_used"] * 100 if trade["capital_used"] else 0.0

        target_hit = bool(trade.get("target_hit"))
        mode_label = "Trailing (target hit)" if target_hit else "Fixed SL / target"
        fields = [
            ("Symbol", trade["symbol"]), ("Entry", format_currency(trade["entry_price"])),
            ("Current", format_currency(current_price)),
            ("Unrealized P&L", f"{format_currency(unrealized_pnl)} ({format_pct(unrealized_pct)})"),
            ("Mode", mode_label), ("Qty", trade["quantity"]),
            ("Peak", format_currency(trade["peak_price"])), ("Trough", format_currency(trade["trough_price"])),
            ("Capital Used", format_currency(trade["capital_used"])), ("Entered", trade["entry_time"]),
        ]
        fields_html = "".join(
            f'<div><div class="ste-position-field-label">{label}</div>'
            f'<div class="ste-position-field-value">{value}</div></div>'
            for label, value in fields
        )
        st.markdown(
            f'<div class="ste-position-card">'
            f'<div class="ste-position-header">Open Position — {trade["symbol"]}</div>'
            f'<div class="ste-position-row">{fields_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if show_force_exit:
            if st.button(f"Force Exit {trade['symbol']}", key=f"force_exit_{variant_id}"):
                from engine import broker
                result = broker.exit_position(variant_id, trade["id"], trade["quantity"],
                                                trade["entry_price"], "MANUAL_EXIT")
                st.warning(f"Force exited {trade['symbol']}")
                st.rerun()

    with st.expander("Equity Curve", expanded=False):
        equity = metrics.get_equity_curve(variant_id)
        if equity.empty:
            st.info("No closed trades yet.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=equity["exit_time"], y=equity["cum_pnl"], mode="lines+markers",
                name="Cumulative P&L", line=dict(color="#00D46A", width=2),
            ))
            fig.update_layout(template="plotly_dark", height=300, margin=dict(l=20, r=20, t=20, b=20),
                               yaxis_title="Cumulative P&L (Rs)")
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("Trade Log", expanded=False):
        all_trades = db.get_all_trades(variant_id)
        if all_trades.empty:
            st.info("No trades yet.")
        else:
            display_cols = [
                "symbol", "status", "entry_time", "entry_price", "quantity", "capital_used",
                "target_hit", "exit_time", "exit_price", "exit_reason",
                "gross_pnl", "total_charges", "net_pnl", "net_pnl_pct",
            ]
            st.dataframe(all_trades[display_cols], use_container_width=True, hide_index=True)

    now_str = datetime.now(IST).strftime("%H:%M:%S")
    st.caption(f"Last updated {now_str}")


def get_refresh_interval():
    for universe_bot in config.UNIVERSE_BOTS:
        for variant_cfg in config.VARIANTS:
            variant_id = f"{universe_bot['key']}/{variant_cfg['key']}"
            if db.get_open_trade(variant_id):
                return REFRESH_SECONDS
    return None

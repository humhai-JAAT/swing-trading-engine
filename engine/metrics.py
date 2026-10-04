"""Portfolio metrics per variant_id — each of the 2 variants has its own
independent capital pool, so metrics are always computed one variant at a time.
"""

import pandas as pd

from common.metrics import compute_portfolio_metrics
from engine import config, db


def get_summary(variant_id: str, starting_capital: float) -> dict:
    closed = db.get_closed_trades(variant_id)
    metrics = compute_portfolio_metrics(closed.rename(columns={"net_pnl": "pnl"}) if not closed.empty else closed)

    open_trade = db.get_open_trade(variant_id)
    metrics["open_positions"] = 1 if open_trade else 0
    metrics["current_capital"] = starting_capital + metrics["total_pnl"]
    metrics["total_pnl_pct"] = (metrics["total_pnl"] / starting_capital * 100) if starting_capital else 0.0
    metrics["total_charges"] = (
        (closed["entry_charges"].sum() + closed["exit_charges"].sum()) if not closed.empty else 0.0
    )
    return metrics


def get_variant_rankings(settings: dict) -> pd.DataFrame:
    rows = []
    for variant_id in config.all_variant_ids():
        universe_bot_key, variant_key = variant_id.split("/", 1)
        summary = get_summary(variant_id, settings["starting_capital"])
        rows.append({
            "variant_id": variant_id,
            "universe_bot": universe_bot_key,
            "variant": variant_key,
            "total_trades": summary["total_trades"],
            "win_rate_pct": summary["win_rate"],
            "wilson_win_rate_pct": summary["wilson_win_rate"],
            "profit_factor": summary["profit_factor"],
            "sqn": summary["sqn"],
            "expectancy": summary["expectancy"],
            "total_pnl": summary["total_pnl"],
            "total_pnl_pct": summary["total_pnl_pct"],
            "max_drawdown": summary["max_drawdown"],
        })
    df = pd.DataFrame(rows)
    return df.sort_values("sqn", ascending=False).reset_index(drop=True)


def get_equity_curve(variant_id: str) -> pd.DataFrame:
    closed = db.get_closed_trades(variant_id)
    if closed.empty:
        return pd.DataFrame(columns=["exit_time", "symbol", "net_pnl", "cum_pnl"])
    closed = closed.sort_values("exit_time")
    closed["cum_pnl"] = closed["net_pnl"].cumsum()
    return closed[["exit_time", "symbol", "net_pnl", "cum_pnl"]]

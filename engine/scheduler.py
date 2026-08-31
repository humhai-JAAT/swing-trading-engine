"""APScheduler wiring — TWO separate jobs:

  1. Position management (fast, every position_management_interval_minutes,
     default 2) — manages any of the 2 variants' open positions.
  2. Entry scanning (Stage 1 + Stage 2 + both variants' scan_for_entry),
     aligned to 1H candle boundaries with a 1-min safety offset — fires at
     10:16, 11:16, 12:16, 13:16, 14:16 (1 min after each hourly candle close
     at X:15, market opens at 09:15).

No subh30 checkpoint concept. CNC carry-forward — no intraday square-off.
"""

from datetime import datetime, time as dtime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from common.helpers import get_logger
from engine import config, db, live_feed, nse_universe, stage1_ranking, stage2_candles, strategy, variant_engine
from engine.broker_accounts import get_configured_accounts

logger = get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_scheduler: BackgroundScheduler | None = None
POSITION_JOB_ID = "ste_position_management"
SCAN_JOB_ID = "ste_entry_scan"

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


def _parse_time(hhmm: str) -> dtime:
    h, m = map(int, hhmm.split(":"))
    return dtime(h, m)


def _now_ist() -> datetime:
    return datetime.now(IST)


def market_status(now: datetime | None = None) -> str:
    now = now or _now_ist()
    if now.weekday() >= 5:
        return "closed_weekend"
    if now.time() < MARKET_OPEN or now.time() >= MARKET_CLOSE:
        return "closed_hours"
    return "open"


def is_awake(settings: dict, now: datetime) -> bool:
    wake = _parse_time(settings.get("wake_time", "09:00"))
    sleep = _parse_time(settings.get("sleep_time", "16:00"))
    return wake <= now.time() < sleep


def run_position_management_cycle(settings: dict | None = None) -> dict:
    settings = settings or config.load_settings()
    db.init_db()
    now = _now_ist()

    if market_status(now) != "open":
        return {"status": market_status(now)}

    try:
        results = {}
        for universe_bot in config.UNIVERSE_BOTS:
            for variant_cfg in config.VARIANTS:
                variant_id = f"{universe_bot['key']}/{variant_cfg['key']}"
                trade = db.get_open_trade(variant_id)
                if not trade:
                    continue
                try:
                    results[variant_id] = variant_engine.manage_open_position(
                        variant_id, variant_cfg, trade, settings, now
                    )
                except Exception as e:
                    logger.error(f"Position management for {variant_id} crashed: {e}")
                    results[variant_id] = {"action": "hold", "reason": f"error: {e}", "symbol": trade["symbol"]}

        managed = [r for r in results.values() if r.get("action") != "hold"]
        data_warnings = [
            f"{variant_id}: {r['reason']}" for variant_id, r in results.items()
            if r.get("action") == "hold" and r.get("reason")
        ]
        db.log_cycle(status="OK", stage="position_management",
                      message=f"managed={len(managed)}",
                      warnings="; ".join(data_warnings) if data_warnings else "")
        return {"status": "open", "managed": results}
    except Exception as e:
        logger.error(f"Position management cycle crashed mid-execution: {e}")
        db.log_cycle(status="ERROR", stage="position_management", error=str(e))
        raise


def run_full_scan_cycle(settings: dict | None = None) -> dict:
    settings = settings or config.load_settings()
    db.init_db()
    db.prune_cycle_logs(retention_days=7)
    now = _now_ist()

    status = market_status(now)
    if status != "open":
        db.log_cycle(status="MARKET_CLOSED", stage="entry_scan", message=f"market_status={status}")
        return {"status": status}

    with db.try_acquire_scan_lock() as acquired:
        if not acquired:
            logger.warning("Entry scan cycle skipped — another cycle is already in progress")
            db.log_cycle(status="SKIPPED", stage="entry_scan",
                          message="another entry-scan cycle was already in progress")
            return {"status": "skipped", "reason": "scan_already_in_progress"}

        try:
            all_symbols = list(nse_universe.get_universe_symbols("nifty500"))
            stage1_result = stage1_ranking.fetch_ranking_data(all_symbols)
            if stage1_result.warnings:
                logger.warning(f"Stage 1 warnings: {stage1_result.warnings}")

            top_lists: dict[str, "pd.DataFrame"] = {}
            subset_warnings: list[str] = []
            for universe_bot in config.UNIVERSE_BOTS:
                top_df, missing = nse_universe.filter_to_universe(
                    stage1_result.rank_list, universe_bot["universe"], settings["gainers_pool_size"]
                )
                top_lists[universe_bot["key"]] = top_df
                if missing:
                    subset_warnings.append(
                        f"{universe_bot['key']}: {len(missing)} constituent symbol(s) missing from "
                        f"Stage 1's rank list: {missing[:10]}"
                    )
            if subset_warnings:
                logger.warning(f"Subset-safety warnings: {subset_warnings}")

            unique_symbols = stage2_candles.merge_unique_symbols(top_lists)
            candle_interval = config.DEFAULTS.get("candle_interval", "1h")
            candle_days = config.DEFAULTS.get("candle_fetch_calendar_days", stage2_candles.CALENDAR_FETCH_DAYS)
            stage2_result = stage2_candles.fetch_candle_history(
                unique_symbols, interval=candle_interval, period_days=candle_days
            )
            if stage2_result.warnings:
                logger.warning(f"Stage 2 warnings: {stage2_result.warnings}")

            indicator_cache = strategy.build_indicator_cache(stage2_result.candles_by_symbol)

            scan_results = {}
            for universe_bot in config.UNIVERSE_BOTS:
                for variant_cfg in config.VARIANTS:
                    variant_id = f"{universe_bot['key']}/{variant_cfg['key']}"
                    was_flat = db.get_open_trade(variant_id) is None
                    scan_results[variant_id] = variant_engine.scan_for_entry(
                        universe_bot["key"], variant_cfg, settings, now,
                        top_lists[universe_bot["key"]], stage2_result.candles_by_symbol, was_flat,
                        indicator_cache=indicator_cache,
                    )

            strategy_warnings = [
                f"{variant_id}/{c['symbol']}: {c['reason']}"
                for variant_id, result in scan_results.items()
                for c in result.get("candidates", [])
                if isinstance(c.get("reason"), str) and c["reason"].startswith("error:")
            ]
            all_warnings = stage1_result.warnings + subset_warnings + stage2_result.warnings + strategy_warnings
            entered = [v for v, r in scan_results.items() if r.get("action") == "enter"]
            db.log_cycle(
                status="OK", stage="entry_scan",
                symbols_scanned=stage2_result.symbols_fetched,
                message=f"entered={entered}",
                warnings="; ".join(all_warnings) if all_warnings else "",
            )
            return {
                "status": "open", "stage1_chunks_total": stage1_result.chunks_total,
                "stage1_chunks_fallback_used": stage1_result.chunks_fallback_used,
                "stage1_chunks_failed": stage1_result.chunks_failed,
                "stage2_symbols_requested": stage2_result.symbols_requested,
                "stage2_symbols_fetched": stage2_result.symbols_fetched,
                "warnings": all_warnings, "scan": scan_results, "entered_variants": entered,
            }
        except Exception as e:
            logger.error(f"Entry scan cycle crashed mid-execution: {e}")
            db.log_cycle(status="ERROR", stage="entry_scan", error=str(e))
            raise


def _position_job():
    settings = config.load_settings()
    now = _now_ist()
    if not is_awake(settings, now):
        return
    try:
        run_position_management_cycle(settings)
    except Exception as e:
        logger.error(f"Position management cycle failed: {e}")


def _scan_job():
    settings = config.load_settings()
    now = _now_ist()
    if not is_awake(settings, now):
        return
    try:
        result = run_full_scan_cycle(settings)
        logger.info(f"Entry scan cycle: {result.get('status')}, entered={result.get('entered_variants')}")
    except Exception as e:
        logger.error(f"Entry scan cycle failed: {e}")


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    return _scheduler


def start_scheduler() -> None:
    settings = config.load_settings()
    scheduler = get_scheduler()

    for job_id in (POSITION_JOB_ID, SCAN_JOB_ID):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    position_minutes = settings["position_management_interval_minutes"]
    scheduler.add_job(
        _position_job,
        trigger=IntervalTrigger(minutes=position_minutes, timezone="Asia/Kolkata"),
        id=POSITION_JOB_ID, replace_existing=True,
        next_run_time=datetime.now(IST),
    )

    # 1H candle boundary aligned: fires at :16 past hours 10-14 (1 min after
    # each 1H candle close at X:15, market opens at 09:15).
    scheduler.add_job(
        _scan_job,
        trigger=CronTrigger(hour="10,11,12,13,14", minute="16", timezone="Asia/Kolkata"),
        id=SCAN_JOB_ID, replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()

    live_feed_started = live_feed.start()

    logger.info(f"Scheduler started: position management every {position_minutes} min, "
                f"entry scan at 1H-boundary+1 offsets (10:16-14:16), "
                f"live-feed tick-driven exits {'ON' if live_feed_started else 'OFF (no Groww account)'}")


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
    live_feed.stop()
    logger.info("Scheduler stopped")


def is_running() -> bool:
    return get_scheduler().running

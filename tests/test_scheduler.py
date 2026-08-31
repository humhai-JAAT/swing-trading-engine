"""Tests for engine/scheduler.py — hourly scan timing, market status."""

from datetime import datetime

import pytz
import pytest

from engine.scheduler import market_status, is_awake

IST = pytz.timezone("Asia/Kolkata")


class TestMarketStatus:
    def test_open_during_hours(self):
        dt = IST.localize(datetime(2026, 9, 1, 10, 30))  # Monday 10:30
        assert market_status(dt) == "open"

    def test_closed_before_open(self):
        dt = IST.localize(datetime(2026, 9, 1, 9, 0))  # Monday 09:00
        assert market_status(dt) == "closed_hours"

    def test_closed_after_close(self):
        dt = IST.localize(datetime(2026, 9, 1, 15, 35))  # Monday 15:35
        assert market_status(dt) == "closed_hours"

    def test_closed_weekend_saturday(self):
        dt = IST.localize(datetime(2026, 8, 29, 10, 30))  # Saturday
        assert market_status(dt) == "closed_weekend"

    def test_closed_weekend_sunday(self):
        dt = IST.localize(datetime(2026, 8, 30, 10, 30))  # Sunday
        assert market_status(dt) == "closed_weekend"

    def test_open_at_market_open(self):
        dt = IST.localize(datetime(2026, 9, 1, 9, 15))  # Monday 09:15
        assert market_status(dt) == "open"

    def test_closed_at_market_close(self):
        dt = IST.localize(datetime(2026, 9, 1, 15, 30))  # Monday 15:30
        assert market_status(dt) == "closed_hours"


class TestIsAwake:
    def test_awake_in_window(self):
        settings = {"wake_time": "09:00", "sleep_time": "16:00"}
        dt = IST.localize(datetime(2026, 9, 1, 10, 0))
        assert is_awake(settings, dt) is True

    def test_asleep_before_wake(self):
        settings = {"wake_time": "09:00", "sleep_time": "16:00"}
        dt = IST.localize(datetime(2026, 9, 1, 8, 30))
        assert is_awake(settings, dt) is False

    def test_asleep_after_sleep(self):
        settings = {"wake_time": "09:00", "sleep_time": "16:00"}
        dt = IST.localize(datetime(2026, 9, 1, 16, 30))
        assert is_awake(settings, dt) is False

    def test_awake_at_exact_wake(self):
        settings = {"wake_time": "09:00", "sleep_time": "16:00"}
        dt = IST.localize(datetime(2026, 9, 1, 9, 0))
        assert is_awake(settings, dt) is True

    def test_asleep_at_exact_sleep(self):
        settings = {"wake_time": "09:00", "sleep_time": "16:00"}
        dt = IST.localize(datetime(2026, 9, 1, 16, 0))
        assert is_awake(settings, dt) is False


class TestScanScheduleTiming:
    """Verify the CronTrigger fires at the right times for 1H candles."""

    def test_scan_job_hours(self):
        from apscheduler.triggers.cron import CronTrigger
        trigger = CronTrigger(hour="10,11,12,13,14", minute="16", timezone="Asia/Kolkata")
        # Fire times should be at :16 past hours 10-14
        base = IST.localize(datetime(2026, 9, 1, 9, 0))
        fire = trigger.get_next_fire_time(None, base)
        assert fire.hour == 10
        assert fire.minute == 16

        fire2 = trigger.get_next_fire_time(fire, fire)
        assert fire2.hour == 11
        assert fire2.minute == 16

        fire3 = trigger.get_next_fire_time(fire2, fire2)
        assert fire3.hour == 12
        assert fire3.minute == 16

    def test_five_scans_per_day(self):
        from apscheduler.triggers.cron import CronTrigger
        trigger = CronTrigger(hour="10,11,12,13,14", minute="16", timezone="Asia/Kolkata")
        base = IST.localize(datetime(2026, 9, 1, 9, 0))
        fires = []
        current = base
        for _ in range(10):
            fire = trigger.get_next_fire_time(current if not fires else fires[-1], current if not fires else fires[-1])
            if fire is None:
                break
            fires.append(fire)
            current = fire

        day1_fires = [f for f in fires if f.date() == base.date()]
        assert len(day1_fires) == 5

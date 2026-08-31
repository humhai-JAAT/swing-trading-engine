"""Tests for engine/config.py — variant IDs, defaults, settings I/O."""

import os
import tempfile

import pytest
import yaml

from engine import config


class TestVariantStructure:
    def test_universe_bots_count(self):
        assert len(config.UNIVERSE_BOTS) == 1

    def test_universe_bot_key(self):
        assert config.UNIVERSE_BOTS[0]["key"] == "bot_500"
        assert config.UNIVERSE_BOTS[0]["universe"] == "nifty500"

    def test_variants_count(self):
        assert len(config.VARIANTS) == 2

    def test_variant_keys(self):
        keys = [v["key"] for v in config.VARIANTS]
        assert "trailing_ema" in keys
        assert "trailing_atr" in keys

    def test_variant_exit_styles(self):
        for v in config.VARIANTS:
            assert v["exit_style"] in ("ema", "atr")

    def test_no_entry_timing_field(self):
        for v in config.VARIANTS:
            assert "entry_timing" not in v

    def test_all_variant_ids(self):
        ids = config.all_variant_ids()
        assert len(ids) == 2
        assert "bot_500/trailing_ema" in ids
        assert "bot_500/trailing_atr" in ids

    def test_variants_by_key(self):
        assert "trailing_ema" in config.VARIANTS_BY_KEY
        assert "trailing_atr" in config.VARIANTS_BY_KEY
        assert config.VARIANTS_BY_KEY["trailing_ema"]["exit_style"] == "ema"

    def test_universe_bots_by_key(self):
        assert "bot_500" in config.UNIVERSE_BOTS_BY_KEY
        assert config.UNIVERSE_BOTS_BY_KEY["bot_500"]["universe"] == "nifty500"


class TestDefaults:
    def test_no_square_off_time(self):
        assert "square_off_time" not in config.DEFAULTS

    def test_candle_interval_1h(self):
        assert config.DEFAULTS["candle_interval"] == "1h"

    def test_candle_fetch_calendar_days(self):
        assert config.DEFAULTS["candle_fetch_calendar_days"] == 30

    def test_candle_lookback_trading_days(self):
        assert config.DEFAULTS["candle_lookback_trading_days"] == 15

    def test_starting_capital(self):
        assert config.DEFAULTS["starting_capital"] == 10000

    def test_profit_target(self):
        assert config.DEFAULTS["profit_target_pct"] == 3.0

    def test_stop_loss(self):
        assert config.DEFAULTS["stop_loss_pct"] == 1.5

    def test_position_management_interval(self):
        assert config.DEFAULTS["position_management_interval_minutes"] == 2


class TestSettingsIO:
    def test_load_defaults_when_no_file(self):
        settings = config.load_settings()
        assert settings["starting_capital"] == 10000
        assert settings["candle_interval"] == "1h"

    def test_save_and_load(self, tmp_path, monkeypatch):
        settings_path = tmp_path / "settings.yaml"
        monkeypatch.setattr(config, "SETTINGS_PATH", settings_path)

        custom = {**config.DEFAULTS, "starting_capital": 50000}
        config.save_settings(custom)
        assert settings_path.exists()

        loaded = config.load_settings()
        assert loaded["starting_capital"] == 50000
        assert loaded["candle_interval"] == "1h"

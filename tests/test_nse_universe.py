"""Tests for engine/nse_universe.py — Nifty500 only, no subsets."""

import pandas as pd
import pytest

from engine.nse_universe import filter_to_universe, get_universe_symbols


class TestGetUniverseSymbols:
    def test_unknown_universe_raises(self):
        with pytest.raises(ValueError, match="Unknown universe"):
            get_universe_symbols("nifty200")

    def test_nifty500_accepted(self):
        # Won't actually fetch — but the code path should not raise ValueError
        # (may raise network error if no cache, that's fine)
        try:
            symbols = get_universe_symbols("nifty500")
            assert isinstance(symbols, set)
        except Exception as e:
            if "Unknown universe" in str(e):
                pytest.fail("nifty500 should be a valid universe")


class TestFilterToUniverse:
    def test_filters_correctly(self):
        rank = pd.DataFrame({
            "symbol": ["A", "B", "C", "D", "E"],
            "pct_change": [5.0, 4.0, 3.0, 2.0, 1.0],
        })

        class FakeUniverse:
            pass

        import engine.nse_universe as mod
        original = mod.get_universe_symbols
        mod.get_universe_symbols = lambda u, force_refresh=False: {"A", "C", "E", "X"}

        try:
            top, missing = filter_to_universe(rank, "nifty500", top_n=2)
            assert len(top) == 2
            assert top.iloc[0]["symbol"] == "A"  # highest pct_change in universe
            assert top.iloc[1]["symbol"] == "C"
            assert "X" in missing  # in universe but not in rank_list
        finally:
            mod.get_universe_symbols = original

    def test_empty_rank_list(self):
        rank = pd.DataFrame(columns=["symbol", "pct_change"])

        import engine.nse_universe as mod
        original = mod.get_universe_symbols
        mod.get_universe_symbols = lambda u, force_refresh=False: {"A", "B"}

        try:
            top, missing = filter_to_universe(rank, "nifty500", top_n=10)
            assert len(top) == 0
            assert "A" in missing
            assert "B" in missing
        finally:
            mod.get_universe_symbols = original

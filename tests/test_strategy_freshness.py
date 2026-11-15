"""Freshness gate: an entry fires only on the candle where entry_signal turned on.

Run:  python -m pytest tests/test_strategy_freshness.py
  or: python tests/test_strategy_freshness.py   (no pytest needed)
"""

from datetime import datetime, timedelta

import pandas as pd
import pytz

from engine import strategy

IST = pytz.timezone("Asia/Kolkata")
N = strategy.MIN_BARS_REQUIRED + 6


def _index(n: int) -> pd.DatetimeIndex:
    start = IST.localize(datetime(2026, 11, 2, 9, 15))
    return pd.DatetimeIndex([start + timedelta(hours=i) for i in range(n)])


def _frame(signal_tail: list, arm_cycle_id: str = "2026-11-02 09:15:00+05:30") -> pd.DataFrame:
    """Enriched-shaped frame; `signal_tail` sets entry_signal on the LAST len(tail) bars."""
    idx = _index(N)
    sig = [False] * (N - len(signal_tail)) + list(signal_tail)
    df = pd.DataFrame({"Close": [100.0] * N, "entry_signal": sig,
                       "arm_cycle_id": [arm_cycle_id] * N}, index=idx)
    df["signal_onset_id"] = strategy.signal_onset_ids(df["entry_signal"])
    return df


def test_onset_ids_continuous_run_stamps_once():
    df = _frame([True, True, True])            # onset at -3, then continuation
    onset = df["signal_onset_id"]
    assert onset.iloc[-3] == df.index[-3]
    assert onset.iloc[-2] == df.index[-3]      # carried, not re-stamped
    assert onset.iloc[-1] == df.index[-3]
    assert pd.isna(onset.iloc[-4])             # NaT while the signal is off


def test_onset_ids_dip_and_return_is_new_onset():
    df = _frame([True, True, False, True])
    onset = df["signal_onset_id"]
    assert onset.iloc[-4] == df.index[-4]
    assert pd.isna(onset.iloc[-2])
    assert onset.iloc[-1] == df.index[-1]      # fresh again after the dip


def test_entry_on_onset_bar():
    check = strategy.decide_entry(_frame([False, True]))
    assert check.signal is True and check.reason == "entry"


def test_continuation_bar_blocked():
    check = strategy.decide_entry(_frame([True, True]))
    assert check.signal is False and check.reason == "signal_not_fresh"


def test_long_stretch_still_blocked():
    """Busy at onset, flat 3 bars later: the stretch must not count as a signal."""
    check = strategy.decide_entry(_frame([True, True, True, True]))
    assert check.reason == "signal_not_fresh"


def test_dip_and_return_enters():
    check = strategy.decide_entry(_frame([True, True, False, True]))
    assert check.signal is True and check.reason == "entry"


def test_arm_cycle_already_used_still_wins():
    check = strategy.decide_entry(_frame([False, True], arm_cycle_id="used"), used_arm_cycles={"used"})
    assert check.reason == "arm_cycle_already_used"


def test_no_signal():
    check = strategy.decide_entry(_frame([True, False]))
    assert check.reason == "no_signal"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")

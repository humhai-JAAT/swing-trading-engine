"""Tests for engine/costs.py — CNC delivery charges (NOT intraday MIS)."""

import pytest

from engine.costs import calc_charges


class TestCNCCharges:
    def test_buy_stt_both_sides(self):
        result = calc_charges(100000, "buy")
        assert result.stt == pytest.approx(100.0, abs=0.01)

    def test_sell_stt_both_sides(self):
        result = calc_charges(100000, "sell")
        assert result.stt == pytest.approx(100.0, abs=0.01)

    def test_buy_stamp_duty(self):
        result = calc_charges(100000, "buy")
        assert result.stamp_duty == pytest.approx(15.0, abs=0.01)

    def test_sell_stamp_duty_zero(self):
        result = calc_charges(100000, "sell")
        assert result.stamp_duty == pytest.approx(0.0, abs=0.01)

    def test_exchange_charges(self):
        result = calc_charges(100000, "buy")
        assert result.exchange_charge == pytest.approx(2.97, abs=0.01)

    def test_sebi_charges(self):
        result = calc_charges(100000, "buy")
        assert result.sebi_charge == pytest.approx(0.10, abs=0.01)

    def test_ipft_charges(self):
        result = calc_charges(100000, "buy")
        assert result.ipft_charge == pytest.approx(0.10, abs=0.01)

    def test_gst_on_brokerage_exchange_sebi_ipft(self):
        result = calc_charges(100000, "buy")
        taxable = result.brokerage + result.exchange_charge + result.sebi_charge + result.ipft_charge
        assert result.gst == pytest.approx(taxable * 0.18, abs=0.01)

    def test_total_charges_buy(self):
        result = calc_charges(100000, "buy")
        expected = (result.brokerage + result.stt + result.stamp_duty +
                    result.exchange_charge + result.sebi_charge + result.ipft_charge + result.gst)
        assert result.total == pytest.approx(expected, abs=0.01)

    def test_total_charges_sell(self):
        result = calc_charges(100000, "sell")
        expected = (result.brokerage + result.stt + result.stamp_duty +
                    result.exchange_charge + result.sebi_charge + result.ipft_charge + result.gst)
        assert result.total == pytest.approx(expected, abs=0.01)

    def test_buy_more_expensive_than_sell(self):
        buy = calc_charges(100000, "buy")
        sell = calc_charges(100000, "sell")
        assert buy.total > sell.total

    def test_cnc_stt_much_higher_than_zero(self):
        result = calc_charges(100000, "buy")
        assert result.stt > 50

    def test_zero_order_value(self):
        result = calc_charges(0, "buy")
        assert result.total == 0.0

    def test_small_order(self):
        result = calc_charges(100, "buy")
        assert result.total > 0
        assert result.stt == pytest.approx(0.10, abs=0.01)

"""Groww CNC/delivery equity charges simulation.
Rates per Groww's published delivery pricing (groww.in/pricing) and standard
NSE/SEBI statutory rates for delivery equity:
  Brokerage:  Rs 20 or 0.1% of order value, whichever is lower, per executed
              order; floored at min(Rs 5, 2.5% of order value).
  STT:        0.1% on both buy and sell (delivery).
  Stamp Duty: 0.015% on buy, 0% on sell.
  Exchange transaction charge (NSE): 0.00297% on both legs.
  SEBI turnover charge:              0.0001% on both legs.
  IPFT (NSE):                        0.0001% on both legs.
  GST:                               18% on (brokerage + exchange + SEBI + IPFT).
"""

from dataclasses import dataclass

BROKERAGE_CAP = 20.0
BROKERAGE_PCT = 0.001
BROKERAGE_MIN = 5.0
BROKERAGE_MIN_PCT = 0.025

STT_PCT = 0.001
STAMP_BUY_PCT = 0.00015
EXCHANGE_PCT = 0.0000297
SEBI_PCT = 0.000001
IPFT_PCT = 0.000001
GST_RATE = 0.18


@dataclass
class ChargeBreakdown:
    order_value: float
    brokerage: float
    stt: float
    stamp_duty: float
    exchange_charge: float
    sebi_charge: float
    ipft_charge: float
    gst: float
    total: float


def calc_charges(order_value: float, side: str) -> ChargeBreakdown:
    if order_value <= 0:
        return ChargeBreakdown(order_value, 0, 0, 0, 0, 0, 0, 0, 0)

    brokerage = min(BROKERAGE_CAP, order_value * BROKERAGE_PCT)
    if brokerage < BROKERAGE_MIN:
        brokerage = min(BROKERAGE_MIN, order_value * BROKERAGE_MIN_PCT)

    stt = order_value * STT_PCT
    stamp_duty = order_value * STAMP_BUY_PCT if side == "buy" else 0.0
    exchange_charge = order_value * EXCHANGE_PCT
    sebi_charge = order_value * SEBI_PCT
    ipft_charge = order_value * IPFT_PCT
    gst = GST_RATE * (brokerage + exchange_charge + sebi_charge + ipft_charge)

    total = brokerage + stt + stamp_duty + exchange_charge + sebi_charge + ipft_charge + gst

    return ChargeBreakdown(
        order_value=order_value, brokerage=brokerage, stt=stt, stamp_duty=stamp_duty,
        exchange_charge=exchange_charge, sebi_charge=sebi_charge, ipft_charge=ipft_charge,
        gst=gst, total=total,
    )


def round_trip_charges(entry_value: float, exit_value: float) -> tuple[float, float]:
    entry = calc_charges(entry_value, "buy")
    exit_ = calc_charges(exit_value, "sell")
    return entry.total, exit_.total

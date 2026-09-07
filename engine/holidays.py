"""NSE trading holidays for 2026 (and a small 2027 buffer).
Update this list annually from NSE's published calendar."""

from datetime import date

NSE_HOLIDAYS_2026 = frozenset([
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 17),   # Mahashivratri (tentative)
    date(2026, 3, 10),   # Holi
    date(2026, 3, 30),   # Id-Ul-Fitr (Ramadan)
    date(2026, 4, 2),    # Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 25),   # Buddha Purnima (tentative)
    date(2026, 6, 6),    # Bakri Id (tentative)
    date(2026, 7, 6),    # Muharram (tentative)
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 16),   # Parsi New Year (tentative)
    date(2026, 9, 4),    # Milad-un-Nabi (tentative)
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 9),   # Diwali (Laxmi Pujan)
    date(2026, 11, 10),  # Diwali (Balipratipada)
    date(2026, 11, 19),  # Guru Nanak Jayanti (tentative)
    date(2026, 12, 25),  # Christmas
])

NSE_HOLIDAYS_2027 = frozenset([
    date(2027, 1, 26),   # Republic Day
])

ALL_HOLIDAYS = NSE_HOLIDAYS_2026 | NSE_HOLIDAYS_2027


def is_nse_holiday(d: date) -> bool:
    return d in ALL_HOLIDAYS

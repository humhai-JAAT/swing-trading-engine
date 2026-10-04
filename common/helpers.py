import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def format_currency(value: float) -> str:
    return f"₹{value:,.2f}"


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

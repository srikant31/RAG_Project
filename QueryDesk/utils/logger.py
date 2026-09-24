"""
QueryDesk — Centralized Logger
Uses loguru for structured, colourful, enterprise-grade logging.
"""
import sys
from loguru import logger

# Remove default handler
logger.remove()

# Console handler — colourful, human-readable
logger.add(
    sys.stdout,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO",
    colorize=True,
)

# File handler — JSON-structured for production log aggregators
logger.add(
    "logs/QueryDesk.log",
    format="{time} | {level} | {name}:{function}:{line} | {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="14 days",
    compression="zip",
    serialize=False,
)

__all__ = ["logger"]

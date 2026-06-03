"""News Agent — track topics, detect signals, generate daily briefings."""

from .agent import NewsAgent
from .fetcher import RssFetcher

__all__ = ["NewsAgent", "RssFetcher"]

"""
RssFetcher — parse RSS/Atom feeds with feedparser, deduplicate by URL,
and rank by recency.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import feedparser


class RssFetcher:
    """
    Fetch one or more RSS/Atom feeds, normalise items into a common schema,
    deduplicate by URL, and sort newest-first.
    """

    # Seconds to wait between requests (simple politeness)
    REQUEST_DELAY: float = 0.3

    def __init__(self) -> None:
        self._seen_urls: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str) -> list[dict[str, Any]]:
        """
        Fetch a single feed URL and return a list of normalised item dicts,
        sorted newest-first. Deduplicates against items fetched in earlier
        calls on this fetcher instance.
        """
        try:
            feed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            return [{"error": str(exc), "feed_url": url}]

        items = []
        for entry in feed.entries:
            item = self._normalise(entry, url)
            url_key = item.get("url", "")
            if not url_key:
                url_key = self._content_hash(item.get("title", ""))
            if url_key in self._seen_urls:
                continue
            self._seen_urls.add(url_key)
            items.append(item)

        # Sort newest-first
        items.sort(key=lambda x: x.get("published_ts", 0), reverse=True)

        time.sleep(self.REQUEST_DELAY)
        return items

    def fetch_many(self, urls: list[str]) -> list[dict[str, Any]]:
        """
        Fetch multiple feed URLs, deduplicate across all, return newest-first.
        """
        all_items: list[dict[str, Any]] = []
        for url in urls:
            all_items.extend(self.fetch(url))
        all_items.sort(key=lambda x: x.get("published_ts", 0), reverse=True)
        return all_items

    def reset_dedup(self) -> None:
        """Clear the seen-URL set so future calls start fresh."""
        self._seen_urls.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(entry: Any, feed_url: str) -> dict[str, Any]:
        """Convert a feedparser entry into a plain dict with consistent keys."""
        # URL
        url = getattr(entry, "link", "") or ""

        # Title
        title = getattr(entry, "title", "") or "(no title)"

        # Summary / description — strip HTML if present
        summary_raw = (
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
        summary = _strip_html(summary_raw)[:500]  # truncate for token budget

        # Published timestamp
        published_ts = 0
        published_str = ""
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            val = getattr(entry, attr, None)
            if val:
                try:
                    dt = datetime(*val[:6], tzinfo=timezone.utc)
                    published_ts = int(dt.timestamp())
                    published_str = dt.strftime("%Y-%m-%d %H:%M UTC")
                    break
                except (TypeError, ValueError):
                    pass

        # Author
        author = getattr(entry, "author", "") or ""

        # Tags / categories
        tags = []
        for tag in getattr(entry, "tags", []):
            label = getattr(tag, "term", "") or getattr(tag, "label", "")
            if label:
                tags.append(label)

        return {
            "title": title,
            "url": url,
            "summary": summary,
            "author": author,
            "published": published_str,
            "published_ts": published_ts,
            "tags": tags,
            "feed_url": feed_url,
        }

    @staticmethod
    def _content_hash(text: str) -> str:
        return "hash:" + hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Very lightweight HTML tag stripper — avoids a BeautifulSoup dependency."""
    import re
    # Remove tags
    clean = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

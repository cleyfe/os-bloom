"""News: merge configured sources, dedupe by normalized headline, newest first.

RSS is the only source. NewsSource is the seam for adding another — implement
the protocol, append to the sources list in main.py.
"""
from __future__ import annotations

import html
import logging
import re
from calendar import timegm
from datetime import datetime, timezone
from typing import Protocol

import feedparser

from collector.config import FeedCfg
from collector.http import GetText
from collector.store import Store

log = logging.getLogger(__name__)

_TAG = re.compile(r"<[^>]+>")
SUMMARY_CHARS = 300  # at most this much of the feed's own blurb; never a stored article


def _summary(entry) -> str:
    """The feed's description as plain text: tags stripped, entities unescaped,
    whitespace collapsed, capped. Empty when the feed has none."""
    raw = str(entry.get("summary") or entry.get("description") or "")
    text = " ".join(html.unescape(_TAG.sub(" ", raw)).split())
    return text[:SUMMARY_CHARS]


class NewsSource(Protocol):
    async def headlines(self) -> list[dict]: ...


def dedupe_key(headline: str) -> str:
    # full normalized headline — truncating collides "Live updates: ..."-style
    # headlines that differ only in the tail, silently dropping real stories
    return re.sub(r"[^a-z0-9 ]", "", headline.lower()).strip()


def _entry_time(entry) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).isoformat().replace("+00:00", "Z")


async def fetch_news(feeds: list[FeedCfg], store: Store, get_text: GetText, max_items: int) -> str:
    items: list[dict] = []
    for feed in feeds:
        try:
            parsed = feedparser.parse(await get_text(feed.url))
        except Exception as exc:  # noqa: BLE001 — spec: drop dead feeds silently
            log.warning("news feed %s dead, skipping: %s", feed.name, exc)
            continue
        for entry in parsed.entries:
            if not entry.get("title") or not entry.get("link"):
                continue
            items.append({
                "headline": entry["title"],
                "url": entry["link"],
                "feed": feed.name,
                "summary": _summary(entry),
                "published_at": _entry_time(entry),
                "source": "rss",
            })
    if not items:
        raise RuntimeError("all news feeds failed")
    seen: set[str] = set()
    unique = []
    for item in sorted(items, key=lambda i: i["published_at"], reverse=True):
        key = dedupe_key(item["headline"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    store.put_doc("news", {"items": unique[:max_items]}, source="rss")
    return "rss"

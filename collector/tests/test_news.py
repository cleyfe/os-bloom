from pathlib import Path

from collector.config import FeedCfg
from collector.fetchers.news import dedupe_key, fetch_news
from collector.store import Store

RSS_XML = (Path(__file__).parent / "fixtures" / "rss_ft.xml").read_text()


def test_dedupe_key_normalizes():
    a = dedupe_key("ECB Signals Pause on Rate Cuts!")
    b = dedupe_key("ecb signals pause on rate cuts")
    assert a == b


async def test_fetch_news_merges_dedupes_sorts_caps(tmp_path):
    store = Store(tmp_path / "t.db")
    feeds = [FeedCfg(name="FT", url="http://a"), FeedCfg(name="FT2", url="http://b"),
             FeedCfg(name="Dead", url="http://dead")]

    async def fake_get(url, params=None):
        if url == "http://dead":
            raise RuntimeError("connection refused")
        return RSS_XML  # both live feeds return the same items -> dedupe

    label = await fetch_news(feeds, store, fake_get, max_items=1)
    assert label == "rss"
    items = store.doc("news").payload["items"]
    assert len(items) == 1  # deduped (2 unique) then capped to 1
    assert items[0]["headline"] == "ECB signals pause on rate cuts"  # newest first
    assert items[0]["feed"] == "FT"
    assert items[0]["url"].startswith("https://www.ft.com/")
    assert items[0]["published_at"]  # parsed pubDate present


async def test_all_feeds_dead_raises(tmp_path):
    store = Store(tmp_path / "t.db")

    async def fake_get(url, params=None):
        raise RuntimeError("nope")

    try:
        await fetch_news([FeedCfg(name="FT", url="http://a")], store, fake_get, max_items=5)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


async def test_fetch_news_keeps_feed_summary_as_plain_text(tmp_path):
    store = Store(tmp_path / "t.db")

    async def fake_get(url, params=None):
        return RSS_XML

    await fetch_news([FeedCfg(name="FT", url="http://a")], store, fake_get, max_items=5)
    items = store.doc("news").payload["items"]
    by_headline = {i["headline"]: i for i in items}
    # tags stripped, entities unescaped, whitespace collapsed
    assert by_headline["ECB signals pause on rate cuts"]["summary"] == "The ECB held rates & signalled a pause."
    # a feed item without a description gets an empty summary, never a missing key
    assert by_headline["Global equities rally on soft inflation print"]["summary"] == ""

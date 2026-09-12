import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from collector.config import load_config
from collector.fetchers.comment import (
    COMMENT_SCHEMA, SYSTEM, TRIAGE_SCHEMA, TRIAGE_THRESHOLD, _news_items, _parse_response,
    _web_fetch_tool, build_snapshot, fetch_comment, select_articles,
)
from collector.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

FAKE_COMMENT = {
    "headline": "Vol bid, credit calm",
    "regime_read": "Risk appetite is holding up.",
    "drivers": ["VIX +2 on the week", "HY OAS 3.1%, unchanged"],
    "rotation_note": "Defensives outperforming.",
}
NEWS = [
    {"headline": "Fed holds rates", "url": "https://www.cnbc.com/fed", "feed": "CNBC",
     "published_at": "2026-09-11T20:00:00Z", "source": "rss", "summary": "Rates unchanged at 3.75%."},
    {"headline": "Ten hikes for autumn", "url": "https://www.ft.com/hikes", "feed": "FT",
     "published_at": "2026-09-11T19:00:00Z", "source": "rss", "summary": ""},
    {"headline": "Bund yields jump", "url": "https://www.ft.com/bunds", "feed": "FT",
     "published_at": "2026-09-11T18:00:00Z", "source": "rss", "summary": "10Y at 3.40%."},
    {"headline": "No link", "url": "", "feed": "ECB", "published_at": "2026-09-11T17:00:00Z",
     "source": "rss", "summary": "s"},
]


def seeded_store(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("equity_quotes", {"SPX": {
        "last": 6100.0, "source": "yahoo", "delayed": True, "ts": "2026-09-12T07:00:00Z",
    }}, source="yahoo")
    store.upsert_points("idx:SPX", [(date(2026, 9, 11), 6050.0)])
    store.put_doc("news", {"items": NEWS}, source="rss")
    store.upsert_points("cycle:vix", [(date(2026, 9, 11), 16.0)])
    return store


async def no_triage(model, system, user_text, schema, fetch_urls):
    return {"scores": []}, model, []


def triage_scoring(scores: dict[int, int]):
    async def call(model, system, user_text, schema, fetch_urls):
        assert schema is TRIAGE_SCHEMA and fetch_urls == []
        return {"scores": [{"id": i, "score": s, "reason": "r"} for i, s in scores.items()]}, model, []
    return call


def test_schemas_have_exactly_the_expected_fields():
    props = COMMENT_SCHEMA["schema"]["properties"]
    assert set(props) == {"headline", "regime_read", "drivers", "rotation_note"}
    assert COMMENT_SCHEMA["schema"]["required"] == list(props)
    assert COMMENT_SCHEMA["schema"]["additionalProperties"] is False
    assert "watchlist" not in SYSTEM and "risks" not in SYSTEM
    item = TRIAGE_SCHEMA["schema"]["properties"]["scores"]["items"]
    assert set(item["properties"]) == {"id", "score", "reason"}


def test_build_snapshot_trims_to_analyst_fields(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    snap = build_snapshot(seeded_store(tmp_path), cfg, now=NOW)
    assert set(snap) == {"as_of", "equity", "bonds", "cycle", "news", "macro_past", "macro_upcoming"}
    eq = snap["equity"][0]
    assert eq["symbol"] == "SPX" and eq["last"] == 6100.0
    assert "source" not in eq and "delayed" not in eq and "updated_at" not in eq
    assert snap["news"][0] == {"feed": "CNBC", "headline": "Fed holds rates",
                               "summary": "Rates unchanged at 3.75%."}
    assert all("url" not in n for n in snap["news"])  # urls only reach the prompt via selection
    vix_rows = [r for r in snap["cycle"] if r["name"] == "VIX"]
    assert vix_rows and vix_rows[0]["value"] == 16.0 and "overlay" not in vix_rows[0]


def test_build_snapshot_on_empty_store(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    snap = build_snapshot(Store(tmp_path / "t.db"), cfg, now=NOW)
    assert snap["equity"] == [] and snap["bonds"] == [] and snap["news"] == []
    assert snap["macro_past"] == [] and snap["macro_upcoming"] == []
    assert snap["cycle"] and all(r.get("value") is None for r in snap["cycle"])


async def test_select_articles_threshold_order_cap_and_url(tmp_path):
    store = seeded_store(tmp_path)
    items = _news_items(store)
    assert [i["id"] for i in items] == [0, 1, 2, 3]
    # id 3 has no url so it is never offered to triage; ids 0 and 2 score in, 1 is below threshold
    chosen = await select_articles(items, triage_scoring({0: 8, 1: TRIAGE_THRESHOLD - 1, 2: 9}),
                                   "claude-haiku-4-5", max_articles=4)
    assert [a["url"] for a in chosen] == ["https://www.ft.com/bunds", "https://www.cnbc.com/fed"]
    assert chosen[0]["score"] == 9 and chosen[0]["reason"] == "r"
    capped = await select_articles(items, triage_scoring({0: 8, 2: 9}), "m", max_articles=1)
    assert [a["url"] for a in capped] == ["https://www.ft.com/bunds"]
    assert await select_articles(items, triage_scoring({}), "m", max_articles=4) == []
    assert await select_articles([], triage_scoring({0: 10}), "m", max_articles=4) == []


async def test_select_articles_tolerates_triage_failure(tmp_path):
    async def boom(*_a):
        raise RuntimeError("triage down")

    assert await select_articles(_news_items(seeded_store(tmp_path)), boom, "m", 4) == []


async def test_fetch_comment_reads_selected_articles_and_records_sources(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    seen = {}

    async def fake_call(model, system, user_text, schema, fetch_urls):
        seen.update(model=model, system=system, user_text=user_text, schema=schema, urls=fetch_urls)
        # the FT fetch failed (paywall), the CNBC one worked
        return FAKE_COMMENT, "claude-opus-4-8", [
            {"url": "https://www.ft.com/bunds", "fetched": False},
            {"url": "https://www.cnbc.com/fed", "fetched": True},
        ]

    label = await fetch_comment(cfg, store, fake_call, triage_scoring({0: 8, 2: 9}), now=NOW)
    assert label == "claude-opus-4-8"
    assert seen["model"] == "claude-opus-5" and seen["system"] is SYSTEM and seen["schema"] is COMMENT_SCHEMA
    assert seen["urls"] == ["https://www.ft.com/bunds", "https://www.cnbc.com/fed"]
    assert "Selected articles" in seen["user_text"]
    assert "1. Bund yields jump (FT) https://www.ft.com/bunds" in seen["user_text"]
    assert '"SPX"' in seen["user_text"] and "Previous comment" not in seen["user_text"]
    doc = store.doc("market_comment")
    assert doc.payload["comment"]["headline"] == "Vol bid, credit calm"
    assert doc.payload["model"] == "claude-opus-4-8" and doc.source == "claude-opus-4-8"
    assert doc.payload["snapshot_as_of"] == NOW.isoformat().replace("+00:00", "Z")
    assert doc.payload["sources"] == [
        {"url": "https://www.ft.com/bunds", "headline": "Bund yields jump", "feed": "FT",
         "score": 9, "fetched": False},
        {"url": "https://www.cnbc.com/fed", "headline": "Fed holds rates", "feed": "CNBC",
         "score": 8, "fetched": True},
    ]


async def test_fetch_comment_without_articles_offers_no_urls(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    seen = {}

    async def fake_call(model, system, user_text, schema, fetch_urls):
        seen.update(user_text=user_text, urls=fetch_urls)
        return FAKE_COMMENT, model, []

    await fetch_comment(cfg, store, fake_call, no_triage, now=NOW)
    assert seen["urls"] == [] and "Selected articles" not in seen["user_text"]
    assert store.doc("market_comment").payload["sources"] == []


async def test_fetch_comment_passes_previous_comment(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    store.put_doc("market_comment", {
        "comment": {**FAKE_COMMENT, "headline": "YESTERDAY-HEADLINE"},
        "snapshot_as_of": "2026-09-11T08:00:00Z", "model": "claude-opus-5",
    }, source="claude-opus-5")
    seen = {}

    async def fake_call(model, system, user_text, schema, fetch_urls):
        seen["user_text"] = user_text
        return FAKE_COMMENT, model, []

    await fetch_comment(cfg, store, fake_call, no_triage, now=NOW)
    assert "Previous comment" in seen["user_text"] and "YESTERDAY-HEADLINE" in seen["user_text"]


async def test_fetch_comment_recovers_from_malformed_previous_doc(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    store.put_doc("market_comment", ["not", "a", "dict"], source="m")

    async def fake_call(model, system, user_text, schema, fetch_urls):
        assert "Previous comment" not in user_text
        return FAKE_COMMENT, model, []

    await fetch_comment(cfg, store, fake_call, no_triage, now=NOW)
    assert store.doc("market_comment").payload["comment"]["headline"] == "Vol bid, credit calm"


async def test_fetch_comment_failure_keeps_previous_doc(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    store.put_doc("market_comment", {
        "comment": FAKE_COMMENT, "snapshot_as_of": "old", "model": "claude-opus-5",
    }, source="claude-opus-5")

    async def fake_call(model, system, user_text, schema, fetch_urls):
        raise RuntimeError("comment model stopped early: stop_reason=refusal")

    with pytest.raises(RuntimeError, match="refusal"):
        await fetch_comment(cfg, store, fake_call, no_triage, now=NOW)
    assert store.doc("market_comment").payload["snapshot_as_of"] == "old"


@pytest.mark.parametrize("bad, match", [
    ({"headline": "only a headline"}, "rotation_note"),
    ({**FAKE_COMMENT, "drivers": "VIX +2 on the week"}, "drivers is not a list"),
    (["not", "an", "object"], "not an object"),
])
async def test_fetch_comment_rejects_wrong_shape(tmp_path, bad, match):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)

    async def fake_call(model, system, user_text, schema, fetch_urls):
        return bad, model, []

    with pytest.raises(ValueError, match=match):
        await fetch_comment(cfg, store, fake_call, no_triage, now=NOW)
    assert store.doc("market_comment") is None


def _resp(stop_reason="end_turn", content=None, model="claude-opus-5", stop_details=None):
    return NS(stop_reason=stop_reason, content=content or [], model=model, stop_details=stop_details)


def _text(obj):
    return NS(type="text", text=json.dumps(obj))


def test_parse_response_skips_fallback_block_and_reports_served_model():
    resp = _resp(content=[NS(type="fallback"), _text(FAKE_COMMENT)], model="claude-opus-4-8")
    assert _parse_response(resp) == (FAKE_COMMENT, "claude-opus-4-8", [])


def test_parse_response_pairs_fetch_results_and_takes_the_last_text_block():
    ok = NS(type="web_fetch_tool_result", tool_use_id="a",
            content=NS(type="web_fetch_result", url="https://www.cnbc.com/fed"))
    err = NS(type="web_fetch_tool_result", tool_use_id="b",
             content=NS(type="web_fetch_tool_result_error", error_code="url_not_accessible"))
    resp = _resp(content=[
        NS(type="text", text="I'll read both articles first."),
        NS(type="server_tool_use", id="a", name="web_fetch", input={"url": "https://www.cnbc.com/fed"}),
        ok,
        NS(type="server_tool_use", id="b", name="web_fetch", input={"url": "https://www.ft.com/bunds"}),
        err,
        _text(FAKE_COMMENT),
    ])
    comment, model, fetches = _parse_response(resp)
    assert comment == FAKE_COMMENT and model == "claude-opus-5"
    assert fetches == [{"url": "https://www.cnbc.com/fed", "fetched": True},
                       {"url": "https://www.ft.com/bunds", "fetched": False}]


def test_parse_response_raises_on_refusal_with_category():
    resp = _resp(stop_reason="refusal", stop_details=NS(category="cyber"))
    with pytest.raises(RuntimeError, match="refusal.*category=cyber"):
        _parse_response(resp)


def test_parse_response_raises_on_max_tokens():
    with pytest.raises(RuntimeError, match="max_tokens"):
        _parse_response(_resp(stop_reason="max_tokens"))


def test_parse_response_raises_without_text_block():
    with pytest.raises(RuntimeError, match="no text block"):
        _parse_response(_resp(content=[NS(type="fallback")]))


def test_web_fetch_tool_is_bounded_to_the_selected_hosts():
    tool = _web_fetch_tool(["https://www.cnbc.com/fed", "https://www.ft.com/bunds", "https://ft.com/x"])
    assert tool["type"] == "web_fetch_20250910" and tool["name"] == "web_fetch"
    assert tool["max_uses"] == 3
    assert tool["allowed_domains"] == ["cnbc.com", "ft.com"]
    assert tool["max_content_tokens"] == 4000


@pytest.mark.parametrize("payload", [{"items": None}, {"items": 7}, {"items": [1, "x"]}, ["nope"], {}])
def test_news_items_tolerates_a_malformed_doc(tmp_path, payload):
    store = Store(tmp_path / "t.db")
    store.put_doc("news", payload, source="rss")
    assert _news_items(store) == []


async def test_select_articles_ignores_duplicate_and_unknown_ids_and_omits_urls(tmp_path):
    items = _news_items(seeded_store(tmp_path))
    seen = {}

    async def triage(model, system, user_text, schema, fetch_urls):
        seen["user_text"] = user_text
        return {"scores": [{"id": 0, "score": 2, "reason": "first"}, {"id": 0, "score": 8, "reason": None},
                           {"id": 42, "score": 10, "reason": "ghost"}]}, model, []

    chosen = await select_articles(items, triage, "m", max_articles=4)
    assert [a["id"] for a in chosen] == [0]      # last score for a repeated id wins; unknown ids dropped
    assert chosen[0]["reason"] == ""             # a null reason is stored as empty, not "None"
    assert "https://" not in seen["user_text"]   # triage sees headlines and summaries, never URLs


async def test_fetched_flag_tolerates_url_normalisation(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)

    async def fake_call(model, system, user_text, schema, fetch_urls):
        return FAKE_COMMENT, model, [{"url": "https://WWW.cnbc.com/fed/", "fetched": True}]

    await fetch_comment(cfg, store, fake_call, triage_scoring({0: 9}), now=NOW)
    assert store.doc("market_comment").payload["sources"][0]["fetched"] is True

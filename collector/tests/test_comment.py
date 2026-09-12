import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from collector.config import load_config
from collector.fetchers.comment import (COMMENT_SCHEMA, SYSTEM, _parse_response, build_snapshot,
                                        fetch_comment)
from collector.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

FAKE_COMMENT = {
    "headline": "Vol bid, credit calm",
    "regime_read": "Risk appetite is holding up.",
    "drivers": ["VIX +2 on the week", "HY OAS 3.1%, unchanged"],
    "rotation_note": "Defensives outperforming.",
}


def seeded_store(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("equity_quotes", {"SPX": {
        "last": 6100.0, "source": "yahoo", "delayed": True, "ts": "2026-09-12T07:00:00Z",
    }}, source="yahoo")
    store.upsert_points("idx:SPX", [(date(2026, 9, 11), 6050.0)])
    store.put_doc("news", {"items": [{
        "headline": "Fed holds rates", "url": "http://x", "feed": "FT",
        "published_at": "2026-09-11T20:00:00Z", "source": "rss",
    }]}, source="rss")
    store.upsert_points("cycle:vix", [(date(2026, 9, 11), 16.0)])
    return store


def test_schema_has_exactly_the_four_band_fields():
    props = COMMENT_SCHEMA["schema"]["properties"]
    assert set(props) == {"headline", "regime_read", "drivers", "rotation_note"}
    assert COMMENT_SCHEMA["schema"]["required"] == list(props)
    assert COMMENT_SCHEMA["schema"]["additionalProperties"] is False
    assert "watchlist" not in SYSTEM and "risks" not in SYSTEM


def test_build_snapshot_trims_to_analyst_fields(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    snap = build_snapshot(seeded_store(tmp_path), cfg, now=NOW)
    assert set(snap) == {"as_of", "equity", "bonds", "cycle", "news", "macro_past", "macro_upcoming"}
    eq = snap["equity"][0]
    assert eq["symbol"] == "SPX" and eq["last"] == 6100.0
    assert "source" not in eq and "delayed" not in eq and "updated_at" not in eq
    assert snap["news"] == [{"feed": "FT", "headline": "Fed holds rates"}]
    vix_rows = [r for r in snap["cycle"] if r["name"] == "VIX"]
    assert vix_rows and vix_rows[0]["value"] == 16.0 and "overlay" not in vix_rows[0]


async def test_fetch_comment_stores_doc_with_served_model(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    seen = {}

    async def fake_call(model, system, user_text, schema):
        seen.update(model=model, system=system, user_text=user_text, schema=schema)
        return FAKE_COMMENT, "claude-opus-4-8"  # a fallback model answered

    label = await fetch_comment(cfg, store, fake_call, now=NOW)
    assert label == "claude-opus-4-8"
    doc = store.doc("market_comment")
    assert doc.payload["comment"]["headline"] == "Vol bid, credit calm"
    assert doc.payload["model"] == "claude-opus-4-8"
    assert doc.source == "claude-opus-4-8"
    assert doc.payload["snapshot_as_of"] == NOW.isoformat().replace("+00:00", "Z")
    assert seen["model"] == "claude-opus-5"  # requested model comes from config
    assert seen["system"] is SYSTEM
    assert seen["schema"] is COMMENT_SCHEMA
    assert '"SPX"' in seen["user_text"]  # snapshot serialized into the prompt
    assert "Previous comment" not in seen["user_text"]


async def test_fetch_comment_passes_previous_comment(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    store.put_doc("market_comment", {
        "comment": {**FAKE_COMMENT, "headline": "YESTERDAY-HEADLINE"},
        "snapshot_as_of": "2026-09-11T08:00:00Z", "model": "claude-opus-5",
    }, source="claude-opus-5")
    seen = {}

    async def fake_call(model, system, user_text, schema):
        seen["user_text"] = user_text
        return FAKE_COMMENT, model

    await fetch_comment(cfg, store, fake_call, now=NOW)
    assert "Previous comment" in seen["user_text"]
    assert "YESTERDAY-HEADLINE" in seen["user_text"]


async def test_fetch_comment_failure_keeps_previous_doc(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    store.put_doc("market_comment", {
        "comment": FAKE_COMMENT, "snapshot_as_of": "old", "model": "claude-opus-5",
    }, source="claude-opus-5")

    async def fake_call(model, system, user_text, schema):
        raise RuntimeError("comment model stopped early: stop_reason=refusal")

    with pytest.raises(RuntimeError, match="refusal"):
        await fetch_comment(cfg, store, fake_call, now=NOW)
    assert store.doc("market_comment").payload["snapshot_as_of"] == "old"


async def test_fetch_comment_rejects_wrong_shape(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)

    async def fake_call(model, system, user_text, schema):
        return {"headline": "only a headline"}, model

    with pytest.raises(ValueError, match="rotation_note"):
        await fetch_comment(cfg, store, fake_call, now=NOW)
    assert store.doc("market_comment") is None


def test_build_snapshot_on_empty_store(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    snap = build_snapshot(Store(tmp_path / "t.db"), cfg, now=NOW)
    assert snap["equity"] == [] and snap["bonds"] == [] and snap["news"] == []
    assert snap["macro_past"] == [] and snap["macro_upcoming"] == []
    assert snap["cycle"] and all(r.get("value") is None for r in snap["cycle"])


async def test_fetch_comment_recovers_from_malformed_previous_doc(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)
    store.put_doc("market_comment", ["not", "a", "dict"], source="m")

    async def fake_call(model, system, user_text, schema):
        assert "Previous comment" not in user_text
        return FAKE_COMMENT, model

    await fetch_comment(cfg, store, fake_call, now=NOW)
    assert store.doc("market_comment").payload["comment"]["headline"] == "Vol bid, credit calm"


async def test_fetch_comment_rejects_drivers_not_a_list(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)

    async def fake_call(model, system, user_text, schema):
        return {**FAKE_COMMENT, "drivers": "VIX +2 on the week"}, model

    with pytest.raises(ValueError, match="drivers is not a list"):
        await fetch_comment(cfg, store, fake_call, now=NOW)
    assert store.doc("market_comment") is None


async def test_fetch_comment_rejects_non_object(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = seeded_store(tmp_path)

    async def fake_call(model, system, user_text, schema):
        return ["not", "an", "object"], model

    with pytest.raises(ValueError, match="not an object"):
        await fetch_comment(cfg, store, fake_call, now=NOW)
    assert store.doc("market_comment") is None


def _resp(stop_reason="end_turn", content=None, model="claude-opus-5", stop_details=None):
    return NS(stop_reason=stop_reason, content=content or [], model=model, stop_details=stop_details)


def test_parse_response_skips_fallback_block_and_reports_served_model():
    resp = _resp(content=[NS(type="fallback"), NS(type="text", text=json.dumps(FAKE_COMMENT))],
                 model="claude-opus-4-8")
    assert _parse_response(resp) == (FAKE_COMMENT, "claude-opus-4-8")


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

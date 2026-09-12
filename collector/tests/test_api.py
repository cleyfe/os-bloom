from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from collector.api import create_app
from collector.config import load_config
from collector.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_client(tmp_path, refresh=None):
    store = Store(tmp_path / "t.db")
    cfg = load_config(REPO_ROOT / "config.yaml")
    return TestClient(create_app(store, cfg, comment_refresh=refresh)), store


def test_dashboard_shape_on_empty_store(tmp_path):
    client, _ = make_client(tmp_path)
    body = client.get("/api/dashboard").json()
    assert set(body["panels"].keys()) == {
        "macro", "equity", "bonds", "news", "defi", "midnight", "morpho", "refs", "cycle",
        "comment",
    }
    assert [t["id"] for t in body["panels"]["cycle"]["tabs"]] == [
        "risk", "econ", "credit", "profit", "pos",
    ]


def test_series_endpoint_applies_transform_and_range(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("macro:us-cpi-yoy", [
        (date(2010, 6, 1), 80.0),
        (date(2025, 6, 1), 100.0),
        (date(2026, 6, 1), 103.0),
    ])
    body = client.get("/api/series/us-cpi-yoy?range=5y").json()
    assert body["id"] == "us-cpi-yoy"
    assert body["unit"] == "%"
    assert body["points"] == [["2026-06-01", 3.0]]  # yoy transform, 5y window
    body_max = client.get("/api/series/us-cpi-yoy?range=max").json()
    assert len(body_max["points"]) == 1  # yoy needs a prior-year point; 2010 has none


def test_series_unknown_id_404(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/series/nope").status_code == 404


def test_series_endpoint_serves_configured_ref_id(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("ref:aave-base-usdc-supply", [
        (date(2026, 7, 1), 2.60), (date(2026, 7, 8), 2.71),
    ])
    body = client.get("/api/series/aave-base-usdc-supply?range=max").json()
    assert body["id"] == "aave-base-usdc-supply"
    assert body["name"] == "AAVE USDC BASE SUP"
    assert body["unit"] == "%"
    assert body["points"] == [["2026-07-01", 2.60], ["2026-07-08", 2.71]]  # raw, no transform
    # non-base markets resolve too (ids derived from the config list)
    store.upsert_points("ref:aave-arb-usdt-borrow", [(date(2026, 7, 8), 3.68)])
    arb = client.get("/api/series/aave-arb-usdt-borrow?range=max").json()
    assert arb["name"] == "AAVE USDT ARB BOR"
    assert arb["points"] == [["2026-07-08", 3.68]]


def test_series_endpoint_unknown_ref_id_still_404(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/series/pendle-pt-cbbtc-usdc-typo").status_code == 404


def test_series_endpoint_serves_index_symbol(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("idx:SPX", [
        (date(2026, 7, 1), 6150.0), (date(2026, 7, 8), 6234.5),
    ])
    body = client.get("/api/series/SPX?range=max").json()
    assert body["name"] == "S&P 500" and body["unit"] == "px"
    assert body["points"] == [["2026-07-01", 6150.0], ["2026-07-08", 6234.5]]


def test_series_endpoint_serves_bond_and_cb_ids(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("yield:US3M", [(date(2026, 7, 8), 3.89)])
    store.upsert_points("cb:US", [(date(2026, 7, 8), 3.75)])
    y3m = client.get("/api/series/US3M?range=max").json()
    assert y3m["unit"] == "%" and y3m["points"] == [["2026-07-08", 3.89]]
    cb = client.get("/api/series/USCB?range=max").json()
    assert cb["name"] == "FED" and cb["points"] == [["2026-07-08", 3.75]]
    assert client.get("/api/series/JP10Y").status_code == 404  # not in config


def test_series_bad_range_422(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/series/us-cpi-yoy?range=2w").status_code == 422


def test_healthz_reports_fetchers(tmp_path):
    client, store = make_client(tmp_path)
    store.record_success("equity", "yahoo")
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["fetchers"][0]["name"] == "equity"


def test_cors_header_present(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.get("/api/dashboard", headers={"Origin": "http://elsewhere"})
    assert resp.headers["access-control-allow-origin"] == "*"


def test_healthz_not_ok_when_fetcher_failing(tmp_path):
    client, store = make_client(tmp_path)
    store.record_success("equity", "yahoo")
    store.record_error("news", "all feeds dead")   # error, never succeeded
    body = client.get("/healthz").json()
    assert body["ok"] is False


def test_corrupted_doc_does_not_500_dashboard(tmp_path):
    client, store = make_client(tmp_path)
    store.conn.execute(
        "INSERT INTO docs(key, payload, updated_at, source) VALUES(?,?,?,?)",
        ("news", "{not json", "2026-07-08T00:00:00Z", "rss"),
    )
    store.conn.commit()
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    assert resp.json()["panels"]["news"]["items"] == []


def test_cycle_series_endpoint_applies_transform(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("cycle:m2-yoy", [
        (date(2025, 6, 1), 100.0),
        (date(2026, 6, 1), 106.0),
    ])
    body = client.get("/api/series/m2-yoy?range=5y").json()
    assert body["name"] == "M2 YoY"
    assert body["unit"] == "%"
    assert body["points"] == [["2026-06-01", 6.0]]


def test_recessions_endpoint(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("cycle:usrec", [
        (date(2020, 1, 1), 0.0), (date(2020, 3, 1), 1.0),
        (date(2020, 4, 1), 1.0), (date(2020, 5, 1), 0.0),
    ])
    body = client.get("/api/recessions").json()
    assert body == {"bands": [["2020-03-01", "2020-05-01"]]}


def test_recessions_empty_store(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/recessions").json() == {"bands": []}


def test_refresh_unconfigured_is_503(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.post("/api/comment/refresh")
    assert r.status_code == 503


def test_refresh_refused_while_comment_is_current(tmp_path):
    calls = []

    async def refresh():
        calls.append(1)

    client, store = make_client(tmp_path, refresh)
    store.put_doc("market_comment", {"comment": {"headline": "H"}}, source="m")
    r = client.post("/api/comment/refresh")
    assert r.status_code == 429 and "current" in r.json()["detail"]
    assert calls == []


def test_refresh_runs_when_outdated_then_cools_down(tmp_path):
    calls = []
    holder = {}

    async def refresh():
        calls.append(1)
        holder["store"].record_success("comment", "m")  # what run_fetcher does on success

    client, store = make_client(tmp_path, refresh)
    holder["store"] = store
    store.put_doc("market_comment", {"comment": {"headline": "old"}}, source="m")
    store.conn.execute("UPDATE docs SET updated_at=? WHERE key='market_comment'",
                       ("2020-01-01T00:00:00Z",))
    store.conn.commit()
    r = client.post("/api/comment/refresh")
    assert r.status_code == 202 and calls == [1]
    r = client.post("/api/comment/refresh")  # the attempt was just recorded
    assert r.status_code == 429 and "try again" in r.json()["detail"]
    assert calls == [1]


def test_refresh_allowed_with_no_comment_yet(tmp_path):
    calls = []

    async def refresh():
        calls.append(1)

    client, _ = make_client(tmp_path, refresh)
    assert client.post("/api/comment/refresh").status_code == 202
    assert calls == [1]


def test_refresh_cools_down_after_a_failure_too(tmp_path):
    async def refresh():
        raise AssertionError("must not run")

    client, store = make_client(tmp_path, refresh)
    store.record_error("comment", "BadRequestError: credit balance too low")
    assert client.post("/api/comment/refresh").status_code == 429


def test_cooldown_remaining():
    from datetime import datetime, timedelta, timezone

    from collector.api import REFRESH_COOLDOWN, _cooldown_remaining

    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    assert _cooldown_remaining(None, now) == 0
    assert _cooldown_remaining({"last_success": None, "last_error_at": None}, now) == 0
    recent = (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
    left = _cooldown_remaining({"last_success": None, "last_error_at": recent}, now)
    assert left == int((REFRESH_COOLDOWN - timedelta(minutes=3)).total_seconds())
    old = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert _cooldown_remaining({"last_success": old, "last_error_at": None}, now) == 0

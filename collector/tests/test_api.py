from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from collector.api import create_app
from collector.config import load_config
from collector.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_client(tmp_path):
    store = Store(tmp_path / "t.db")
    cfg = load_config(REPO_ROOT / "config.yaml")
    return TestClient(create_app(store, cfg)), store


def test_dashboard_shape_on_empty_store(tmp_path):
    client, _ = make_client(tmp_path)
    body = client.get("/api/dashboard").json()
    assert set(body["panels"].keys()) == {
        "macro", "equity", "bonds", "news", "defi", "midnight", "morpho", "refs", "cycle",
        "fx", "sectors",
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


def test_series_endpoint_serves_fx_symbol(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("fx:EURUSD", [
        (date(2026, 7, 1), 1.0800), (date(2026, 7, 8), 1.0850),
    ])
    body = client.get("/api/series/EURUSD?range=max").json()
    assert body["name"] == "EUR/USD" and body["unit"] == "px"
    assert body["points"] == [["2026-07-01", 1.0800], ["2026-07-08", 1.0850]]


def test_series_endpoint_serves_sector_symbol(tmp_path):
    client, store = make_client(tmp_path)
    store.upsert_points("sec:XLK", [
        (date(2026, 7, 1), 240.0), (date(2026, 7, 8), 242.0),
    ])
    body = client.get("/api/series/XLK?range=max").json()
    assert body["name"] == "Technology" and body["unit"] == "px"
    assert body["points"] == [["2026-07-01", 240.0], ["2026-07-08", 242.0]]


def test_series_endpoint_unknown_fx_sector_id_still_404(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/series/NOTAFXPAIR").status_code == 404


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

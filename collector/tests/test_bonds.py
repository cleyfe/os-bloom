from datetime import date
from pathlib import Path

import pytest

from collector.config import BondCfg, CbRateCfg
from collector.fetchers.bonds import fetch_bonds
from collector.store import Store

FIX = Path(__file__).parent / "fixtures"
BUNDESBANK_CSV = (FIX / "bundesbank_10y.csv").read_text()
FRED_JSON = (FIX / "fred_dgs10.json").read_text()
ECB_CSV = (FIX / "ecb_3m.csv").read_text()
BOE_ZIP = (FIX / "boe_latest_yield_curve_data.zip").read_bytes()


async def fake_get(url, params=None, headers=None):
    if "stlouisfed" in url:
        return FRED_JSON
    if "bundesbank" in url:
        return BUNDESBANK_CSV
    if "data-api.ecb" in url:
        return ECB_CSV
    raise RuntimeError(f"unexpected url: {url}")


async def fake_get_bytes(url, params=None, headers=None):
    if "bankofengland" in url:
        return BOE_ZIP
    raise RuntimeError(f"unexpected url: {url}")


def make_cfg(**kw):
    base = dict(
        country="DE", tenor="10Y", fred=None,
        bundesbank="D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A",
        ecb=None,
    )
    return BondCfg(**{**base, **kw})


def make_gb_10y(**kw):
    return BondCfg(country="GB", tenor="10Y", boe="10", **kw)


def make_gb_3m(**kw):
    return BondCfg(country="GB", tenor="3M", boe="0.5", tenor_label="6M", **kw)


async def run(bonds, store, cb_rates=(), get=fake_get, get_bytes=fake_get_bytes):
    return await fetch_bonds(list(bonds), list(cb_rates), store, get, fred_api_key="k",
                             get_bytes=get_bytes)


async def test_fred_bond(tmp_path):
    store = Store(tmp_path / "t.db")
    cfg = make_cfg(country="US", fred="DGS10", bundesbank=None)
    label = await run([cfg], store)
    assert label == "fred"
    q = store.doc("bond_quotes").payload["US10Y"]
    assert q["yield_pct"] == 4.12 and q["source"] == "fred"
    assert q["country"] == "US" and q["tenor"] == "10Y"
    assert store.points("yield:US10Y")[date(2026, 7, 8)] == 4.12


async def test_bundesbank_bond(tmp_path):
    store = Store(tmp_path / "t.db")
    label = await run([make_cfg()], store)
    assert label == "bundesbank"
    q = store.doc("bond_quotes").payload["DE10Y"]
    assert q["yield_pct"] == 3.17 and q["source"] == "bundesbank"
    assert store.points("yield:DE10Y")[date(2026, 7, 8)] == 3.17


async def test_ecb_bond(tmp_path):
    store = Store(tmp_path / "t.db")
    cfg = make_cfg(tenor="3M", bundesbank=None, ecb="YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M")
    label = await run([cfg], store)
    assert label == "ecb"
    q = store.doc("bond_quotes").payload["DE3M"]
    assert q["yield_pct"] == 2.3337121399 and q["source"] == "ecb"
    assert store.points("yield:DE3M")[date(2026, 7, 20)] == 2.3299925919


async def test_boe_bonds(tmp_path):
    store = Store(tmp_path / "t.db")
    label = await run([make_gb_10y(), make_gb_3m()], store)
    assert label == "boe"
    quotes = store.doc("bond_quotes").payload
    gb10 = quotes["GB10Y"]
    assert gb10["source"] == "boe" and gb10["tenor"] == "10Y" and "tenor_label" not in gb10
    assert gb10["yield_pct"] == pytest.approx(5.361281731875085)
    gb3m = quotes["GB3M"]
    assert gb3m["source"] == "boe" and gb3m["tenor"] == "3M" and gb3m["tenor_label"] == "6M"
    assert gb3m["yield_pct"] == pytest.approx(4.193813518536796)
    assert store.points("yield:GB10Y")[date(2026, 9, 24)] == pytest.approx(5.361281731875085)


async def test_boe_zip_fetched_once_for_both_rows(tmp_path):
    store = Store(tmp_path / "t.db")
    calls = []

    async def counting_get_bytes(url, params=None, headers=None):
        calls.append(url)
        return BOE_ZIP

    await run([make_gb_10y(), make_gb_3m()], store, get_bytes=counting_get_bytes)
    assert len(calls) == 1


async def test_boe_zip_failure_degrades_both_boe_rows_only(tmp_path):
    store = Store(tmp_path / "t.db")

    async def failing_get_bytes(url, params=None, headers=None):
        raise RuntimeError("boe down")

    bonds = [make_cfg(country="US", fred="DGS10", bundesbank=None), make_gb_10y()]
    label = await run(bonds, store, get_bytes=failing_get_bytes)
    assert label == "fred"
    quotes = store.doc("bond_quotes").payload
    assert "US10Y" in quotes and "GB10Y" not in quotes


async def test_cb_rates_written_alongside_bonds(tmp_path):
    store = Store(tmp_path / "t.db")
    cbs = [CbRateCfg(country="US", label="FED", fred="DFEDTARU")]
    label = await run([make_cfg()], store, cb_rates=cbs)
    assert label == "bundesbank+fred"
    quotes = store.doc("bond_quotes").payload
    fed = quotes["USCB"]
    assert fed["label"] == "FED" and fed["country"] == "US"
    assert fed["yield_pct"] == 4.12 and "tenor" not in fed  # fred_dgs10 fixture value
    assert store.points("cb:US")[date(2026, 7, 8)] == 4.12


async def test_failed_instrument_keeps_last_known_but_removed_dropped(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("bond_quotes", {
        "DE10Y": {"country": "DE", "tenor": "10Y", "yield_pct": 2.50,
                  "ts": "2026-07-01T00:00:00Z", "source": "bundesbank"},
        "IT10Y": {"country": "IT", "tenor": "10Y", "yield_pct": 3.90,
                  "ts": "2026-07-01T00:00:00Z", "source": "yahoo"},
        "DE": {"tenor": "10Y", "yield_pct": 4.60,  # pre-matrix key: must be dropped
               "ts": "2026-07-01T00:00:00Z", "source": "bundesbank"},
    }, source="bundesbank")

    async def de_fails(url, params=None, headers=None):
        if "stlouisfed" in url:
            return FRED_JSON
        raise RuntimeError("bundesbank down")

    # config now has US (works via fred) and DE (fails); IT no longer configured
    bonds = [make_cfg(country="US", fred="DGS10", bundesbank=None), make_cfg()]
    label = await run(bonds, store, get=de_fails)
    assert label == "fred"
    quotes = store.doc("bond_quotes").payload
    assert quotes["DE10Y"]["yield_pct"] == 2.50   # carried forward, visibly stale via old ts
    assert quotes["US10Y"]["yield_pct"] == 4.12   # fresh
    assert "IT10Y" not in quotes                  # removed from config -> dropped
    assert "DE" not in quotes                     # old-shape key -> dropped


async def test_all_failed_raises(tmp_path):
    store = Store(tmp_path / "t.db")

    async def failing_get(url, params=None, headers=None):
        raise RuntimeError("down")

    try:
        await run([make_cfg()], store, get=failing_get)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "all bonds failed" in str(exc)

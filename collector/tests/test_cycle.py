from datetime import date
from pathlib import Path

import pytest

from collector.config import CycleSeriesCfg
from collector.fetchers.cycle import fetch_cycle
from collector.store import Store

FIX = Path(__file__).parent / "fixtures"
FRED = (FIX / "fred_dgs10.json").read_text()
DBNOMICS = (FIX / "dbnomics_ism.json").read_text()
OECD = (FIX / "oecd_cli.csv").read_text()
CFTC = (FIX / "cftc_vix.json").read_text()
CBOE = (FIX / "cboe_daily.json").read_text()
YAHOO = (FIX / "yahoo_spx.json").read_text()
AAII = (FIX / "aaii_sentiment.xls").read_bytes()
EUROSTAT = (FIX / "eurostat_hicp_total.json").read_text()


def fake_io(urls):
    async def get_text(url, params=None, headers=None):
        urls.append(url)
        if "stlouisfed" in url:
            return FRED
        if "db.nomics" in url:
            return DBNOMICS
        if "sdmx.oecd" in url:
            return OECD
        if "cftc.gov" in url:
            return CFTC
        if "cboe.com" in url:
            return CBOE
        if "yahoo.com" in url:
            return YAHOO
        if "eurostat" in url:
            return EUROSTAT
        raise AssertionError(f"unexpected url {url}")

    async def get_bytes(url, params=None, headers=None):
        urls.append(url)
        return AAII

    return get_text, get_bytes


ALL_SOURCES = [
    CycleSeriesCfg(id="vix", name="VIX", unit="idx", fred="VIXCLS"),
    CycleSeriesCfg(id="ism", name="ISM", unit="idx", dbnomics="ISM/pmi/pm"),
    CycleSeriesCfg(id="cli", name="CLI", unit="idx", oecd="F/USA.M.LI...AA...H"),
    CycleSeriesCfg(id="esi", name="ESI", unit="idx", eurostat="ei_bssi_m_r2?geo=EA21"),
    CycleSeriesCfg(id="cot", name="COT", unit="contracts", cftc="1170E1"),
    CycleSeriesCfg(id="pc", name="PC", unit="ratio", cboe="TOTAL PUT/CALL RATIO"),
    CycleSeriesCfg(id="aaii", name="AAII", unit="pts", aaii="bull_bear_spread"),
    CycleSeriesCfg(id="ratio", name="R", unit="ratio", yahoo_ratio=["RSP", "SPY"]),
]


async def test_fetch_cycle_dispatches_every_source(tmp_path):
    store = Store(tmp_path / "t.db")
    urls = []
    get_text, get_bytes = fake_io(urls)
    label = await fetch_cycle(ALL_SOURCES, store, "test-key", get_text, get_bytes,
                              today=date(2026, 8, 24))
    assert label == "cycle"
    for cfg in ALL_SOURCES:
        assert store.points(f"cycle:{cfg.id}") != {}, cfg.id
    assert sum("yahoo.com" in u for u in urls) == 2  # numerator + denominator


async def test_fetch_cycle_eurostat_branch(tmp_path):
    store = Store(tmp_path / "t.db")
    seen = {}

    async def get_text(url, params=None, headers=None):
        seen["url"] = url
        return EUROSTAT

    async def get_bytes(url, params=None, headers=None):
        raise AssertionError("unused")

    series = [CycleSeriesCfg(id="ea-esi", name="ESI", unit="idx",
                             eurostat="ei_bssi_m_r2?geo=EA21&s_adj=SA&indic=BS-ESI-I")]
    await fetch_cycle(series, store, "k", get_text, get_bytes)
    assert "ei_bssi_m_r2" in seen["url"] and "sinceTimePeriod=" in seen["url"]
    assert store.points("cycle:ea-esi") != {}


async def test_fetch_cycle_isolates_failures(tmp_path):
    store = Store(tmp_path / "t.db")
    series = [
        CycleSeriesCfg(id="bad", name="Bad", unit="idx", dbnomics="NOPE/x/y"),
        CycleSeriesCfg(id="vix", name="VIX", unit="idx", fred="VIXCLS"),
    ]

    async def get_text(url, params=None, headers=None):
        if "db.nomics" in url:
            raise RuntimeError("HTTP 404")
        return FRED

    async def get_bytes(url, params=None, headers=None):
        raise AssertionError("unused")

    with pytest.raises(RuntimeError, match="1/2 cycle series failed.*bad"):
        await fetch_cycle(series, store, "k", get_text, get_bytes)
    assert store.points("cycle:vix") != {}  # good series still stored


async def test_fetch_cycle_unconfigured_source_reports_error(tmp_path):
    store = Store(tmp_path / "t.db")
    series = [CycleSeriesCfg(id="empty", name="E", unit="idx")]

    async def get_text(url, params=None, headers=None):
        raise AssertionError("unused")

    with pytest.raises(RuntimeError, match="empty"):
        await fetch_cycle(series, store, "k", get_text, get_text)


async def test_fetch_cycle_valid_range_drops_corrupt_points(tmp_path):
    store = Store(tmp_path / "t.db")
    series = [CycleSeriesCfg(id="ism", name="ISM", unit="idx", dbnomics="ISM/pmi/pm",
                             valid_range=[20, 80])]
    urls = []
    get_text, get_bytes = fake_io(urls)
    await fetch_cycle(series, store, "k", get_text, get_bytes)
    # dbnomics fixture holds 49.5 and 48.7 — inject nothing out of range here;
    # the range logic is exercised directly below via a synthetic fetch
    assert set(store.points("cycle:ism").values()) == {49.5, 48.7}

    corrupt = [CycleSeriesCfg(id="vixr", name="V", unit="idx", fred="VIXCLS",
                              valid_range=[4.0, 4.2])]
    await fetch_cycle(corrupt, store, "k", get_text, get_bytes)
    # fred fixture holds 4.15 and 4.12 -> only both in [4.0, 4.2]; then narrow:
    narrow = [CycleSeriesCfg(id="vixn", name="V", unit="idx", fred="VIXCLS",
                             valid_range=[4.13, 4.2])]
    await fetch_cycle(narrow, store, "k", get_text, get_bytes)
    assert list(store.points("cycle:vixn").values()) == [4.15]  # 4.12 dropped

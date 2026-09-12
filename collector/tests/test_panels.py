from datetime import date, datetime, timedelta, timezone

from collector.config import IndexCfg
from collector.panels import build_dashboard
from collector.store import Store

NOW = datetime(2026, 7, 8, 14, 30, tzinfo=timezone.utc)
INDEXES = [IndexCfg(symbol="SPX", name="S&P 500", yahoo="^GSPC")]

# rate_refs rows have no per-row 'ts' (unlike bond/equity quotes); the panel
# anchors asof to the doc's own updated_at, which store.put_doc always stamps
# with the real wall-clock time -- so ref series fixtures must be seeded
# relative to today, not a fixed calendar date, for the bp-change math below
# to land on non-trivial, reproducible values.
TODAY = datetime.now(timezone.utc).date()


def seeded_store(tmp_path) -> Store:
    store = Store(tmp_path / "t.db")
    store.upsert_points("idx:SPX", [
        (date(2025, 12, 31), 5800.0),
        (date(2026, 6, 30), 6100.0),
        (date(2026, 7, 1), 6150.0),
        (date(2026, 7, 7), 6200.0),
        (date(2026, 7, 8), 6234.5),
    ])
    store.put_doc("equity_quotes", {"SPX": {
        "last": 6234.5, "ts": "2026-07-08T14:00:00Z", "source": "yahoo", "delayed": True,
    }}, source="yahoo")
    store.upsert_points("yield:US10Y", [
        (date(2026, 7, 1), 4.20), (date(2026, 7, 7), 4.15), (date(2026, 7, 8), 4.12),
    ])
    store.put_doc("bond_quotes", {
        "US10Y": {"country": "US", "tenor": "10Y", "yield_pct": 4.12,
                  "ts": "2026-07-08T00:00:00Z", "source": "fred"},
        "US3M": {"country": "US", "tenor": "3M", "yield_pct": 3.89,
                 "ts": "2026-07-08T00:00:00Z", "source": "fred"},
        "USCB": {"country": "US", "label": "FED", "yield_pct": 3.75,
                 "ts": "2026-07-08T00:00:00Z", "source": "fred"},
        "JP10Y": {"country": "JP", "tenor": "10Y", "yield_pct": 4.60,  # no 3M/CB: null cells
                  "ts": "2026-07-08T00:00:00Z", "source": "bundesbank"},
    }, source="bundesbank+fred")
    store.put_doc("macro_calendar", {"releases": [
        {"name": "CPI y/y", "country": "USD", "time": "2026-07-10T12:30:00-04:00",
         "impact": "High", "previous": "2.4%", "consensus": "2.3%", "actual": None,
         "series_id": "us-cpi-yoy"},
        {"name": "Retail Sales m/m", "country": "USD", "time": "2026-07-08T08:30:00-04:00",
         "impact": "High", "previous": "0.2%", "consensus": "0.3%", "actual": "0.4%",
         "series_id": "us-retail"},  # released before NOW -> past section only
    ]}, source="forexfactory")
    store.put_doc("macro_history", {"releases": [
        {"name": "Old GDP q/q", "country": "USD", "time": "2026-06-20T08:30:00-04:00",
         "impact": "High", "actual": "2.1%", "series_id": "us-gdp"},  # outside 7d window
        {"name": "Non-Farm Payrolls", "country": "USD", "time": "2026-07-03T08:30:00-04:00",
         "impact": "High", "actual": "185k", "series_id": "us-nfp"},
        {"name": "Retail Sales m/m", "country": "USD", "time": "2026-07-08T08:30:00-04:00",
         "impact": "High", "previous": "0.2%", "consensus": "0.3%", "actual": "0.4%",
         "series_id": "us-retail"},
    ]}, source="forexfactory")
    store.put_doc("news", {"items": [
        {"headline": "h", "url": "u", "feed": "FT", "published_at": "2026-07-08T13:00:00Z",
         "source": "rss"},
    ]}, source="rss")
    store.put_doc("defi_pools", {"rows": [
        {"tier": "Conservative", "chain": "Base", "chain_id": 8453,
         "pool_address": "0x91c0", "protocol": "Morpho", "pool": "Clearstar",
         "apy": 7.98, "apy_7d": 6.54, "apy_30d": 7.03, "tvl_usd": 10732971.3,
         "url": "https://app.morpho.org/x"},
    ]}, source="zyfai")
    store.put_doc("midnight_curve", {"rows": [
        {"chain": "Base", "market_id": "0x0595", "maturity": "2026-08-28",
         "days": 37.6, "lend_apy": 4.09, "borrow_apy": 4.53,
         "ask_depth_usd": 100699.3, "bid_depth_usd": 318.8, "collateral": "cbBTC"},
    ]}, source="morpho")
    store.put_doc("morpho_markets", {"rows": [
        {"chain": "Base", "chain_id": 8453, "market_id": "0x9103", "collateral": "cbBTC",
         "lltv_pct": 86.0, "supply_apy": 4.90, "borrow_apy": 5.43,
         "utilization_pct": 90.41, "tvl_usd": 1413119205.8},
    ]}, source="morpho-blue")
    store.upsert_points("ref:aave-base-usdc-supply", [
        (TODAY - timedelta(days=7), 2.60),
        (TODAY - timedelta(days=1), 2.69),
        (TODAY, 2.71),
    ])
    store.put_doc("rate_refs", {"rows": [
        {"id": "aave-base-usdc-supply", "label": "AAVE SUPPLY", "value_pct": 2.71,
         "extra": None},
        {"id": "aave-base-usdc-borrow", "label": "AAVE BORROW", "value_pct": 3.88,
         "extra": None},  # no ref: series seeded -- exercises the "no history yet" case
    ]}, source="refs")
    return store


def test_build_dashboard_full_shape(tmp_path):
    dash = build_dashboard(seeded_store(tmp_path), INDEXES, now=NOW)
    assert dash["as_of"] == "2026-07-08T14:30:00Z"

    row = dash["panels"]["equity"]["rows"][0]
    assert row["symbol"] == "SPX" and row["name"] == "S&P 500"
    assert row["last"] == 6234.5 and row["delayed"] is True and row["source"] == "yahoo"
    assert row["chg_1d"] == 0.56          # vs 6200.0 (Jul 7)
    assert row["chg_1w"] == 1.37          # vs 6150.0 (Jul 1, on-or-before rule)
    assert row["chg_ytd"] == 7.49         # vs 5800.0 (Dec 31 2025)
    assert row["chg_1y"] is None          # no history that far back
    assert dash["panels"]["equity"]["updated_at"]  # doc timestamp surfaced

    us, jp = dash["panels"]["bonds"]["rows"]     # doc insertion order preserved
    assert us["country"] == "US" and us["y10_pct"] == 4.12
    assert us["y3m_pct"] == 3.89
    assert us["cb_pct"] == 3.75 and us["cb_label"] == "FED"
    assert us["chg_1d_bp"] == -3          # 10Y: 4.12 vs 4.15
    assert us["chg_1w_bp"] == -8          # 10Y: 4.12 vs 4.20 (Jul 1)
    assert jp["country"] == "JP" and jp["y10_pct"] == 4.60
    assert jp["y3m_pct"] is None and jp["cb_pct"] is None   # unsourced cells stay null
    assert jp["chg_1d_bp"] is None        # no yield:JP10Y history seeded
    assert dash["panels"]["bonds"]["source"] == "bundesbank+fred"

    macro = dash["panels"]["macro"]
    assert [r["name"] for r in macro["releases"]] == ["CPI y/y"]  # released events filtered out
    assert macro["releases"][0]["series_id"] == "us-cpi-yoy"
    assert [r["name"] for r in macro["past"]] == [
        "Non-Farm Payrolls", "Retail Sales m/m",  # chronological, 7-day window
    ]
    assert macro["past"][1]["actual"] == "0.4%"
    assert dash["panels"]["news"]["items"][0]["feed"] == "FT"

    defi = dash["panels"]["defi"]
    assert defi["rows"][0]["pool"] == "Clearstar" and defi["source"] == "zyfai"
    assert defi["updated_at"]
    mid = dash["panels"]["midnight"]
    assert mid["rows"][0]["maturity"] == "2026-08-28" and mid["source"] == "morpho"

    morpho = dash["panels"]["morpho"]
    assert morpho["rows"][0]["collateral"] == "cbBTC" and morpho["source"] == "morpho-blue"
    assert morpho["rows"][0]["lltv_pct"] == 86.0
    assert morpho["updated_at"]

    refs = dash["panels"]["refs"]
    assert refs["source"] == "refs" and refs["updated_at"]
    supply, borrow = refs["rows"]
    assert supply["id"] == "aave-base-usdc-supply" and supply["label"] == "AAVE SUPPLY"
    assert supply["value_pct"] == 2.71
    assert supply["chg_1d_bp"] == 2         # 2.71 vs 2.69 (yesterday)
    assert supply["chg_1w_bp"] == 11        # 2.71 vs 2.60 (a week ago)
    assert borrow["id"] == "aave-base-usdc-borrow"
    assert borrow["chg_1d_bp"] is None      # no history yet for this ref
    assert borrow["chg_1w_bp"] is None


def test_build_dashboard_empty_store(tmp_path):
    dash = build_dashboard(Store(tmp_path / "t.db"), INDEXES, now=NOW)
    assert dash["panels"]["equity"]["rows"] == []
    assert dash["panels"]["bonds"]["rows"] == []
    assert dash["panels"]["macro"]["releases"] == []
    assert dash["panels"]["macro"]["past"] == []
    assert dash["panels"]["news"]["items"] == []
    assert dash["panels"]["defi"]["rows"] == []
    assert dash["panels"]["midnight"]["rows"] == []
    assert dash["panels"]["morpho"]["rows"] == []
    assert dash["panels"]["refs"] == {"rows": [], "updated_at": None, "source": None}


def test_malformed_equity_quote_skipped_not_500(tmp_path):
    store = seeded_store(tmp_path)
    store.put_doc("equity_quotes", {
        "SPX": {"last": 6234.5, "ts": "not-a-timestamp", "source": "yahoo", "delayed": True},
    }, source="yahoo")
    dash = build_dashboard(store, INDEXES, now=NOW)
    assert dash["panels"]["equity"]["rows"] == []      # bad row skipped
    assert dash["panels"]["bonds"]["rows"]             # other panels unaffected


def test_malformed_bond_quote_skipped_not_500(tmp_path):
    store = seeded_store(tmp_path)
    store.put_doc("bond_quotes", {
        # yield_pct missing on the only US entry -> all-null row -> dropped
        "US10Y": {"country": "US", "tenor": "10Y", "ts": "2026-07-08T00:00:00Z", "source": "fred"},
        # pre-matrix key shape (no country) -> degraded, not a 500
        "JP": {"tenor": "10Y", "yield_pct": 4.60, "ts": "2026-07-08T00:00:00Z", "source": "bundesbank"},
    }, source="fred")
    dash = build_dashboard(store, INDEXES, now=NOW)
    assert dash["panels"]["bonds"]["rows"] == []
    assert dash["panels"]["equity"]["rows"]            # equity unaffected


def test_malformed_ref_row_skipped_not_500(tmp_path):
    store = seeded_store(tmp_path)
    store.put_doc("rate_refs", {"rows": [
        {"id": "aave-base-usdc-supply", "label": "AAVE SUPPLY"},  # value_pct missing
        {"id": "aave-base-usdc-borrow", "label": "AAVE BORROW", "value_pct": 3.88, "extra": None},
    ]}, source="refs")
    dash = build_dashboard(store, INDEXES, now=NOW)
    refs_rows = dash["panels"]["refs"]["rows"]
    assert [r["id"] for r in refs_rows] == ["aave-base-usdc-borrow"]  # bad row skipped
    assert dash["panels"]["equity"]["rows"]            # other panels unaffected


def test_cycle_panel_rows_values_and_changes(tmp_path):
    from collector.config import CyclePanelCfg, CycleRowCfg, CycleSeriesCfg, CycleTabCfg

    store = Store(tmp_path / "t.db")
    store.upsert_points("cycle:vix", [
        (date(2025, 8, 20), 30.0), (date(2026, 7, 20), 20.0), (date(2026, 8, 20), 16.5),
    ])
    series = [
        CycleSeriesCfg(id="vix", name="VIX", unit="idx", fred="VIXCLS"),
        CycleSeriesCfg(id="empty", name="Empty", unit="idx", fred="NONE"),
        CycleSeriesCfg(id="usrec", name="Rec", unit="idx", fred="USREC", hidden=True),
    ]
    tabs = [CycleTabCfg(id="risk", label="RISK", panels=[
        CyclePanelCfg(title="VOL", rows=[
            CycleRowCfg(series="vix", overlay="usrec"),
            CycleRowCfg(series="empty"),
        ]),
    ])]
    dash = build_dashboard(store, INDEXES, now=NOW, cycle_series=series, cycle_tabs=tabs)
    cycle = dash["panels"]["cycle"]
    tab = cycle["tabs"][0]
    assert (tab["id"], tab["label"]) == ("risk", "RISK")
    row = tab["panels"][0]["rows"][0]
    assert row["id"] == "vix" and row["name"] == "VIX" and row["unit"] == "idx"
    assert row["value"] == 16.5
    assert row["chg_1m"] == -3.5   # vs 2026-07-20
    assert row["chg_1y"] == -13.5  # vs 2025-08-20
    assert row["overlay"] == "usrec"
    empty_row = tab["panels"][0]["rows"][1]
    assert empty_row["value"] is None and empty_row["chg_1m"] is None


def test_cycle_panel_applies_transform(tmp_path):
    from collector.config import CyclePanelCfg, CycleRowCfg, CycleSeriesCfg, CycleTabCfg

    store = Store(tmp_path / "t.db")
    store.upsert_points("cycle:m2", [(date(2025, 8, 1), 100.0), (date(2026, 8, 1), 110.0)])
    series = [CycleSeriesCfg(id="m2", name="M2 YoY", unit="%", transform="yoy", fred="M2SL")]
    tabs = [CycleTabCfg(id="econ", label="ECON", panels=[
        CyclePanelCfg(title="MONEY", rows=[CycleRowCfg(series="m2")]),
    ])]
    dash = build_dashboard(store, INDEXES, now=NOW, cycle_series=series, cycle_tabs=tabs)
    assert dash["panels"]["cycle"]["tabs"][0]["panels"][0]["rows"][0]["value"] == 10.0


def test_comment_panel_empty_and_populated(tmp_path):
    store = Store(tmp_path / "t.db")
    dash = build_dashboard(store, INDEXES, now=NOW)
    assert dash["panels"]["comment"] == {"comment": None, "updated_at": None, "source": None, "stale": False}
    store.put_doc("market_comment", {
        "comment": {"headline": "H"}, "snapshot_as_of": "x", "model": "claude-opus-5",
    }, source="claude-opus-5")
    dash = build_dashboard(store, INDEXES, now=NOW)
    panel = dash["panels"]["comment"]
    assert panel["comment"]["headline"] == "H"
    assert panel["source"] == "claude-opus-5"
    assert panel["updated_at"] is not None


def test_comment_panel_degrades_on_bad_payload(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("market_comment", {"snapshot_as_of": "x"}, source="m")
    panel = build_dashboard(store, INDEXES, now=NOW)["panels"]["comment"]
    assert set(panel) == {"comment", "updated_at", "source", "stale"}
    assert panel["comment"] is None and panel["source"] == "m" and panel["updated_at"]
    store.put_doc("market_comment", ["not", "a", "dict"], source="m")
    panel = build_dashboard(store, INDEXES, now=NOW)["panels"]["comment"]
    assert panel["comment"] is None


def test_news_panel_strips_summaries(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("news", {"items": [{
        "headline": "H", "url": "http://x", "feed": "FT", "published_at": "2026-09-12T00:00:00Z",
        "source": "rss", "summary": "never served to the browser",
    }]}, source="rss")
    items = build_dashboard(store, INDEXES, now=NOW)["panels"]["news"]["items"]
    assert items == [{"headline": "H", "url": "http://x", "feed": "FT",
                      "published_at": "2026-09-12T00:00:00Z", "source": "rss"}]


def test_comment_panel_stale_flag_from_stale_hours(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("market_comment", {"comment": {"headline": "H"}}, source="m")
    written = datetime.now(timezone.utc)
    fresh = build_dashboard(store, INDEXES, now=written)["panels"]["comment"]
    assert fresh["stale"] is False
    old = build_dashboard(store, INDEXES, now=written + timedelta(hours=25))["panels"]["comment"]
    assert old["stale"] is True
    wide = build_dashboard(store, INDEXES, now=written + timedelta(hours=25),
                           comment_stale_hours=48)["panels"]["comment"]
    assert wide["stale"] is False

from pathlib import Path

from collector.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_real_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert len(cfg.indexes) == 10
    spx = cfg.indexes[0]
    assert (spx.symbol, spx.yahoo) == ("SPX", "^GSPC")
    assert spx.yahoo == "^GSPC"
    assert {b.country for b in cfg.bonds} == {"US", "DE", "GB"}
    us = next(b for b in cfg.bonds if b.country == "US")
    assert us.fred == "DGS10"
    de = next(b for b in cfg.bonds if b.country == "DE")
    assert de.bundesbank == "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A"
    gb = [b for b in cfg.bonds if b.country == "GB"]
    assert {b.tenor for b in gb} == {"10Y", "3M"}
    gb_10y = next(b for b in gb if b.tenor == "10Y")
    assert gb_10y.boe == "10" and gb_10y.tenor_label is None
    gb_3m = next(b for b in gb if b.tenor == "3M")
    assert gb_3m.boe == "0.5" and gb_3m.tenor_label == "6M"  # BoE curve has no 3M point
    assert not any(c.country == "GB" for c in cfg.cb_rates)  # no clean UK Bank Rate source
    assert cfg.cadences["equity"] == 300
    assert cfg.max_news == 15
    ids = [s.id for s in cfg.series]
    assert "us-cpi-yoy" in ids and "ez-hicp-yoy" in ids
    assert cfg.calendar_map[0].match == "Core CPI"  # order preserved
    assert cfg.feeds[0].name == "FT"


def test_env_overrides_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", "/data/bloom.db")
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.db_path == "/data/bloom.db"


def test_defi_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.zyfai_base == "https://defiapi.zyf.ai/api/v2/opportunities"
    assert cfg.midnight_base == "https://api.morpho.org/v0/midnight"
    assert cfg.cadences["defi"] == 900 and cfg.cadences["midnight"] == 900
    assert cfg.defi.asset == "USDC"
    # strategy order is the dedupe priority: most conservative first
    assert [(s.id, s.label) for s in cfg.defi.strategies] == [
        ("safe", "Conservative"), ("degen", "Moderate"), ("async", "Dynamic"),
    ]
    assert [(c.id, c.name) for c in cfg.defi.chains] == [
        (8453, "Base"), (1, "Ethereum"), (42161, "Arbitrum"),
    ]
    base = cfg.defi.chains[0]
    # addresses are normalized to lowercase at load so fetchers compare directly
    assert base.usdc == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert cfg.defi.midnight_chains == [8453]
    assert cfg.defi.token_symbols["0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"] == "cbBTC"
    assert cfg.defi.morpho_graphql == "https://blue-api.morpho.org/graphql"
    assert cfg.defi.morpho_first == 25
    assert cfg.cadences["morpho"] == 900


def test_refs_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.cadences["refs"] == 900 and cfg.cadences["refs_history"] == 86400

    aave = cfg.refs.aave
    assert [(a.chain, a.symbol) for a in aave] == [
        ("BASE", "USDC"), ("ETH", "USDC"), ("ETH", "USDT"), ("ARB", "USDC"), ("ARB", "USDT"),
    ]  # Base USDT deliberately absent: not listed on Aave v3 Base
    base = aave[0]
    assert base.rpc == "https://mainnet.base.org"
    # addresses are normalized to lowercase at load so fetchers compare directly
    assert base.pool == "0xa238dd80c259a72e81d7e4664a9801593f98d1c5"
    assert base.asset == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert (base.supply_id, base.supply_label) == ("aave-base-usdc-supply", "AAVE USDC BASE SUP")
    assert (base.borrow_id, base.borrow_label) == ("aave-base-usdc-borrow", "AAVE USDC BASE BOR")
    assert aave[1].pool == aave[2].pool  # ETH markets share the v3 core pool

    # every aave market has a supply-side llama backfill entry
    assert [c.series for c in cfg.refs.llama_chart] == [a.supply_id for a in aave]
    assert cfg.refs.llama_chart[0].pool == "7e0661bf-8cf3-45e6-9424-31916d4c7b84"

    assert len(cfg.refs.pendle) == 1
    pendle = cfg.refs.pendle[0]
    assert pendle.chain_id == 8453
    assert pendle.address == "0xa97bb0de338b23c088dba9bf8c948da726e49033"
    assert (pendle.implied_id, pendle.implied_label) == ("pendle-pt-cbbtc-usdc", "PENDLE PT")
    assert (pendle.underlying_id, pendle.underlying_label) == (
        "pendle-underlying-cbbtc-usdc", "PENDLE UNDERLY",
    )

    assert len(cfg.refs.funding) == 1
    funding = cfg.refs.funding[0]
    assert (funding.symbol, funding.id, funding.label) == ("BTCUSDT", "funding-binance-btc", "BTC FUND ANN")


def test_cycle_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.cadences["cycle"] == 86400
    by_id = {s.id: s for s in cfg.cycle_series}
    assert by_id["vix"].fred == "VIXCLS"
    assert by_id["usrec"].hidden is True
    assert by_id["ism-pmi"].dbnomics == "ISM/pmi/pm"
    assert by_id["oecd-cli-us"].oecd.endswith("/USA.M.LI...AA...H")
    assert by_id["cot-vix"].cftc == "1170E1"
    assert by_id["pc-total"].cboe == "TOTAL PUT/CALL RATIO"
    assert by_id["aaii-spread"].aaii == "bull_bear_spread"
    assert by_id["spw-spx"].yahoo_ratio == ["RSP", "SPY"]
    assert by_id["m2-yoy"].transform == "yoy"
    assert by_id["vix"].transform == "none"  # default
    assert by_id["ea-esi"].eurostat == "ei_bssi_m_r2?geo=EA21&s_adj=SA&indic=BS-ESI-I"
    assert by_id["uk-gdp-yoy"].dbnomics == "ONS/MGDP/ECY2.M" and by_id["uk-gdp-yoy"].transform == "yoy"
    assert by_id["uk-unemployment"].dbnomics == "ONS/LMS/MGSX.M"
    # every source entry has exactly one source key
    for s in cfg.cycle_series:
        sources = [s.fred, s.dbnomics, s.oecd, s.eurostat, s.cftc, s.cboe, s.aaii, s.yahoo_ratio]
        assert sum(x is not None for x in sources) == 1, s.id
    # every tab row references an existing series; overlays too
    tabs = {t.id: t for t in cfg.cycle_tabs}
    assert list(tabs) == ["risk", "econ", "credit", "profit", "pos"]
    for t in cfg.cycle_tabs:
        assert t.label == t.id.upper()
        for p in t.panels:
            for r in p.rows:
                assert r.series in by_id, r.series
                assert r.overlay is None or r.overlay in by_id, r.overlay
                assert not by_id[r.series].hidden
    econ_panels = {p.title for p in tabs["econ"].panels}
    assert {"EURO AREA", "UK"} <= econ_panels


def test_actuals_rules():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.cadences["actuals"] == 600
    rules = cfg.actuals
    assert len(rules) == 18
    for r in rules:
        assert (r.fred is None) != (r.eurostat is None), r.match
        assert r.calc in ("level", "pct_prev", "pct_yoy", "diff_k")
        assert r.fmt in ("pct1", "pct2", "k") and r.freq in ("m", "q", "d")
    # first match wins, so the core rules must precede the headline ones
    names = [(r.country, r.match) for r in rules]
    assert names.index(("USD", "Core CPI m/m")) < names.index(("USD", "CPI m/m"))
    assert names.index(("EUR", "Core CPI Flash Estimate y/y")) < names.index(("EUR", "CPI Flash Estimate y/y"))
    assert names.index(("USD", "Core Retail Sales m/m")) < names.index(("USD", "Retail Sales m/m"))
    nfp = next(r for r in rules if r.match == "Non-Farm Employment Change")
    assert nfp.exclude == ["ADP"]
    assert next(r for r in rules if r.match == "CPI y/y").fred == "CPIAUCNS"   # y/y is printed NSA
    assert next(r for r in rules if r.match == "CPI m/m").fred == "CPIAUCSL"   # m/m is printed SA
    eu_gdp = next(r for r in rules if r.country == "EUR" and r.match == "GDP q/q")
    assert "German" in eu_gdp.exclude and eu_gdp.freq == "q"
    nfp = next(r for r in rules if r.match == "Non-Farm Employment Change")
    assert nfp.calc == "diff_k" and nfp.fmt == "k"
    eu_unemp = next(r for r in rules if r.country == "EUR" and r.match == "Unemployment Rate")
    assert eu_unemp.lag == 2 and eu_unemp.eurostat.startswith("une_rt_m?")
    fed = next(r for r in rules if r.match == "Federal Funds Rate")
    assert fed.freq == "d" and fed.fmt == "pct2" and fed.lag == 1


def test_fx_and_sectors_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert len(cfg.fx) == 11
    dxy = cfg.fx[0]
    assert (dxy.symbol, dxy.name, dxy.yahoo) == ("DXY", "US Dollar Index", "DX-Y.NYB")
    eurusd = next(f for f in cfg.fx if f.symbol == "EURUSD")
    assert eurusd.yahoo == "EURUSD=X"
    assert cfg.cadences["fx"] == 300

    assert len(cfg.sectors) == 2
    us, eu = cfg.sectors
    assert us.title == "US SECTORS" and len(us.rows) == 11
    assert us.rows[0].symbol == "XLK" and us.rows[0].yahoo == "XLK"
    assert eu.title == "EUROPE SECTORS" and len(eu.rows) == 19
    assert eu.rows[0].symbol == "EXV3" and eu.rows[0].yahoo == "EXV3.DE"
    assert cfg.cadences["sectors"] == 900


def test_config_without_fx_sectors_keys_defaults_empty(tmp_path):
    import yaml

    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    raw.pop("fx", None)
    raw.pop("sectors", None)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw))
    cfg = load_config(p)
    assert cfg.fx == []
    assert cfg.sectors == []


def test_duplicate_symbol_across_indexes_and_fx_raises(tmp_path):
    import yaml

    import pytest

    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    raw["fx"].append({"symbol": "SPX", "name": "dup", "yahoo": "SPX=X"})
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError):
        load_config(p)


def test_duplicate_symbol_across_fx_and_sectors_raises(tmp_path):
    import yaml

    import pytest

    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    raw["sectors"][0]["rows"].append({"symbol": "EURUSD", "name": "dup", "yahoo": "EURUSD=X"})
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError):
        load_config(p)


def test_actuals_rule_rejects_ambiguous_source():
    import pytest

    from collector.config import ActualRuleCfg

    with pytest.raises(ValueError):
        ActualRuleCfg(country="USD", match="x", fred="A", eurostat="b?c=d")
    with pytest.raises(ValueError):
        ActualRuleCfg(country="USD", match="x", fred="A", calc="nope")
    with pytest.raises(ValueError):
        ActualRuleCfg(country="USD", match="x", fred="A", fmt="nope")
    with pytest.raises(ValueError):
        ActualRuleCfg(country="USD", match="x", fred="A", freq="w")
    with pytest.raises(ValueError):
        ActualRuleCfg(country="GBP", match="x", fred="A")
    with pytest.raises(ValueError):
        ActualRuleCfg(country="USD", match="x", fred="A", lag=-1)
    with pytest.raises(ValueError):
        ActualRuleCfg(country="USD", match="x", fred="A", exclude=[""])

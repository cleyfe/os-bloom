from pathlib import Path

from collector.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_real_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert len(cfg.indexes) == 10
    spx = cfg.indexes[0]
    assert (spx.symbol, spx.yahoo) == ("SPX", "^GSPC")
    assert spx.yahoo == "^GSPC"
    assert {b.country for b in cfg.bonds} == {"US", "DE"}
    us = next(b for b in cfg.bonds if b.country == "US")
    assert us.fred == "DGS10"
    de = next(b for b in cfg.bonds if b.country == "DE")
    assert de.bundesbank == "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A"
    assert not any(b.country == "UK" for b in cfg.bonds)  # no keyless gilt source
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
    # every source entry has exactly one source key
    for s in cfg.cycle_series:
        sources = [s.fred, s.dbnomics, s.oecd, s.cftc, s.cboe, s.aaii, s.yahoo_ratio]
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


def test_comment_config():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.cadences["comment"] == 43200
    assert cfg.comment.model == "claude-opus-5"
    assert cfg.comment.triage_model == "claude-haiku-4-5"
    assert cfg.comment.max_articles == 4
    assert cfg.comment.stale_hours == 24

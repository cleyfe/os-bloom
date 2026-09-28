<div align="center">

# os-bloom

**A self-hosted macro and markets terminal that runs entirely on free data
sources — built AI-first.**

No Bloomberg seat, no paid vendors, no brokerage account —
one free FRED API key is the only credential you need.

Written largely by AI agents, directed and reviewed by a human. That is the
point rather than a disclaimer: os-bloom is both a working terminal and an
experiment in how far AI-assisted development carries a real system — one with
live upstreams, awkward data, and decisions that have to be defended.

[![License](https://img.shields.io/badge/license-MIT-f5a623?style=flat-square)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12+-5f9ea0?style=flat-square)
![Tests](https://img.shields.io/badge/tests-224%20passing-4c9a2a?style=flat-square)
![Paid data sources](https://img.shields.io/badge/paid%20data%20sources-0-f5a623?style=flat-square)
![Built AI-first](https://img.shields.io/badge/built-AI--first-8a63d2?style=flat-square)

<img src="docs/screenshot-mkt.png" alt="os-bloom MKT tab: equity indexes, world bonds, macro calendar and headlines" width="900">

</div>

---

It collects ~60 series on a schedule into a local SQLite file and serves them
as a dense, keyboard-driven terminal UI: macro calendar, world equity indexes,
government bond yields and policy rates, headlines, DeFi yields, and a
five-tab market-cycle chart pack.

## Tabs

Press `1`–`8`, or use `#/mkt`-style URL fragments.

| Tab | Contents |
| --- | --- |
| **MKT** | Macro release calendar (this week's prints and what is still to come, actuals from FRED and Eurostat within the hour), 10 world equity indexes, a CURRENCIES panel (dollar index plus 10 FX pairs), a bond matrix (10Y / 3M / central bank rate, for the US and Germany), and top headlines. Every row opens a click-through chart. |
| **SECTORS** | US sector performance (11 SPDR select sector funds) and Europe sector performance (19 iShares STOXX Europe 600 sector ETFs on Xetra), same last/1D/1W/YTD/1Y columns as MKT. Every row opens a click-through chart. |
| **DEFI** | Zyfai decentralized-finance USDC yield tiers, Morpho Midnight fixed-term structure with a hover-readout curve, Morpho markets, and a RATE REFS panel (Aave, Pendle implied APY, BTC perp funding) with history charts. |
| **RISK** | Volatility and hedging (VIX, VXN, put/call), sentiment and rotation (AAII spread, cyclicals/defensives, small/large, gold/silver). |
| **ECON** | ISM PMIs, OECD leading indicators, jobless claims, JOLTS, heavy truck sales, UMich sentiment, M2, breakevens, real rates, dollar index. |
| **CREDIT** | Yield curves (10Y-3M, 10Y-2Y), IG/HY/BBB/CCC option-adjusted spreads, the Chicago Fed NFCI, and bank lending growth. |
| **PROFIT** | Corporate profits growth. |
| **POS** | CFTC Commitments of Traders net non-commercial positioning (VIX, crude, USD index, GBP). |

The 39 market-cycle series across RISK/ECON/CREDIT/PROFIT/POS refresh daily.

## Every row opens a chart

Click any series and it opens over the dashboard with ten years of history,
NBER recession shading, and an optional second series on a right-hand axis
(marked `⇄` in the tables).

<div align="center">
<img src="docs/screenshot-chart.png" alt="Click-through chart: VIX against the US 10Y-2Y curve, with NBER recession shading" width="900">
</div>

## Quickstart

You need Docker and a free [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html)
(instant, email only).

```bash
git clone https://github.com/cleyfe/os-bloom.git && cd os-bloom
cp .env.example .env        # then set FRED_API_KEY
docker compose up --build
```

Open <http://localhost:8080>. Panels fill in as the scheduler's first fetches
land — most within a minute, the daily cycle job on its first tick.

Port 8080 already taken? Set `UI_PORT`:

```bash
UI_PORT=9090 docker compose up --build
```

`GET /healthz` reports, per fetcher, its last run, the source actually used,
and any error.

<details>
<summary><b>Running without Docker</b></summary>

```bash
cd collector
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cd .. && set -a && . ./.env && set +a
cd collector && SERVE_UI=1 CONFIG_PATH=../config.yaml .venv/bin/python -m collector.main
```

Serves UI and API together on <http://localhost:8000>.

</details>

## Data sources

Everything below is free. Only FRED requires registration; everything else is
keyless.

| Source | Provides | Key |
| --- | --- | :---: |
| [FRED](https://fred.stlouisfed.org/) | US/EZ macro series, Treasury yields, credit spreads, NFCI, recession bands and US release prints | free key |
| [DBnomics](https://db.nomics.world/) | ISM manufacturing + services PMI | — |
| [OECD SDMX](https://sdmx.oecd.org/) | Composite leading indicators (US, G4E) | — |
| [CFTC](https://publicreporting.cftc.gov/) | Commitments of Traders positioning | — |
| [CBOE](https://www.cboe.com/) | Daily total + equity put/call ratios | — |
| [AAII](https://www.aaii.com/sentimentsurvey) | Bull-bear sentiment spread (legacy `.xls`) | — |
| [Yahoo Finance](https://finance.yahoo.com/) | Equity index closes and ratio series | — |
| [ECB Data Portal](https://data.ecb.europa.eu/) | Euro-area AAA yield curve (3M) | — |
| [Bundesbank](https://www.bundesbank.de/) | German 10Y benchmark | — |
| ForexFactory mirror | Macro release calendar (times, consensus, previous) | — |
| [Eurostat](https://ec.europa.eu/eurostat) | Euro-area HICP, unemployment and GDP prints | — |
| FT, CNBC, MarketWatch, ECB, Fed | Headlines, via public RSS | — |
| [Morpho](https://morpho.org/) | Morpho Blue markets, Midnight fixed-term book | — |
| [Pendle](https://www.pendle.finance/) | Implied APY and expiry | — |
| [Binance](https://www.binance.com/) | BTC perpetual funding rate | — |
| [DefiLlama](https://defillama.com/) | APY history backfill | — |
| [Zyfai](https://zyf.ai/) | USDC opportunity tiers | — |
| Public RPCs (Base, Ethereum, Arbitrum) | Aave reserve data, read-only `eth_call` | — |

### Data sources and polite use

"Free" here means *free of charge and free of API keys*. It does **not** mean
*licensed for redistribution or commercial use*. The rules os-bloom holds
itself to:

- **Never impersonate a browser.** Every request goes out as
  `os-bloom/0.1 (+https://github.com/cleyfe/os-bloom)` — honest, and
  contactable if an operator wants to reach us. No fetcher sends a fake
  Chrome User-Agent, and none should.
- **Never defeat a bot check.** If a source puts its data behind a CAPTCHA or
  a proof-of-work challenge, that is a clear "no" and the source is dropped,
  not worked around. Stooq was removed for exactly this reason.
- **Never fetch a path `robots.txt` disallows.** This is why there is no UK row
  in the bond matrix: the only keyless daily gilt source is the Bank of England
  IADB CSV export, whose path BoE disallows. A row we cannot source politely is
  a row we do without.
- **Every source keeps its own terms.** FRED, OECD, CFTC, ECB, Bundesbank and
  DefiLlama publish open-data terms. Yahoo Finance does not offer a documented
  free API — os-bloom reads the same public endpoint a browser does, at low
  volume, identifying itself. That is tolerated; it is not a licence.
- **Don't turn this into a public service.** Cadences in `config.yaml` are
  tuned for one instance. Pointing many users at these upstreams through a
  hosted deployment is exactly the abuse the terms exist to prevent.
- **Headlines are titles and links only**, straight from public RSS. No article
  text is stored or served.

## Configuration

Everything is declarative in [`config.yaml`](config.yaml) — no code changes to
add or drop a series:

- `cadences` — seconds between runs, per fetcher
- `indexes`, `bonds`, `cb_rates` — instruments and their source IDs
- `series`, `cycle_series` — chart series; exactly one source key each, with an
  optional `transform` (`yoy`, `diff`, `pct_prev`) and `valid_range` guard
- `cycle_tabs` — pure layout; rows reference `cycle_series` ids
- `feeds` — RSS bundle; a dead feed is skipped silently

## Development

```bash
make test    # unit suite, no network (28 test files, 188 tests, HTTP fully faked)
make run     # docker compose up --build
make smoke   # live end-to-end check against a running stack
```

The unit suite never touches the network — fetchers take an injected
`get_text`/`get_bytes`, and tests feed them recorded fixtures from
`collector/tests/fixtures/`. `make smoke` is the only thing that hits real
upstreams, and it is not part of the suite.

## Architecture

```
collector/                 FastAPI + APScheduler, Python 3.12
  src/collector/
    main.py                wiring: config -> store -> jobs -> app
    scheduler.py           per-fetcher cadences
    fetchers/              one module per upstream, pure + injected HTTP
    store.py               SQLite: time series + JSON docs
    panels.py              store -> dashboard JSON
    api.py                 /api/dashboard, /api/series, /healthz
ui/                        static, no build step: ES modules + uPlot, nginx
config.yaml                every instrument, series, tab and cadence
```

Design notes:

- **Fetchers are pure.** HTTP arrives as an injected callable, which is why the
  suite runs offline.
- **Stale beats gone.** A source that fails this run keeps its last-known
  value, with an old timestamp marking it stale, rather than blanking the panel.
- **Fallback chains are per-instrument.** One dead symbol never kills a run.
- **No frontend build.** Plain ES modules and a vendored copy of
  [uPlot](https://github.com/leeoniya/uPlot); edit and reload.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Adding a data
source is usually one fetcher module, one test with a recorded fixture, and a
few lines of `config.yaml`.

## License

[MIT](LICENSE).

**Not investment advice.** This is a personal-scale data viewer built for
learning and monitoring. Data arrives from third-party sources on a best-effort
basis, may be delayed, revised, wrong, or missing, and is not validated against
any official record. Do not trade on it.

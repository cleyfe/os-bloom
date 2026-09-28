"""Typed loading of config.yaml. Secrets come from env, never from YAML."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class IndexCfg:
    symbol: str
    name: str
    yahoo: str | None = None


@dataclass(frozen=True)
class SectorGroupCfg:
    title: str
    rows: list[IndexCfg]
    note: str = ""


@dataclass(frozen=True)
class BondCfg:
    country: str
    tenor: str
    fred: str | None = None
    bundesbank: str | None = None
    ecb: str | None = None


@dataclass(frozen=True)
class CbRateCfg:
    country: str  # must match a bonds country so the matrix row lines up
    label: str
    fred: str | None = None


@dataclass(frozen=True)
class SeriesCfg:
    id: str
    name: str
    fred: str
    unit: str
    transform: str


@dataclass(frozen=True)
class CycleSeriesCfg:
    """One market-cycle series; exactly one source field is set per entry."""
    id: str
    name: str
    unit: str
    transform: str = "none"
    hidden: bool = False           # fetched + chartable but never a panel row (usrec)
    valid_range: list[float] | None = None  # drop points outside [min, max] (corrupt feeds)
    fred: str | None = None
    dbnomics: str | None = None    # "PROVIDER/dataset/series"
    oecd: str | None = None        # "{flow}/{key}" under the OECD rest/data base
    cftc: str | None = None        # CFTC contract market code
    cboe: str | None = None        # exact ratio name in the CBOE daily JSON
    aaii: str | None = None        # "bull_bear_spread"
    yahoo_ratio: list[str] | None = None  # [numerator, denominator] yahoo symbols


@dataclass(frozen=True)
class CycleRowCfg:
    series: str
    overlay: str | None = None     # right-axis series on the click-through chart


@dataclass(frozen=True)
class CyclePanelCfg:
    title: str
    rows: list[CycleRowCfg]


@dataclass(frozen=True)
class CycleTabCfg:
    id: str
    label: str
    panels: list[CyclePanelCfg]


@dataclass(frozen=True)
class CalendarMapEntry:
    country: str
    match: str
    series: str


@dataclass(frozen=True)
class ActualRuleCfg:
    """How a released calendar row's printed number is reproduced from a free series."""
    country: str
    match: str                   # case-insensitive substring of the FF title; list order breaks ties
    fred: str | None = None
    eurostat: str | None = None  # "dataset?dim=code&..." selecting exactly one series
    calc: str = "level"          # level | pct_prev | pct_yoy | diff_k
    fmt: str = "pct1"            # pct1 | pct2 | k
    freq: str = "m"              # m | q | d
    lag: int = 1                 # reference periods back (m, q) or days after the decision (d)
    exclude: list[str] | None = None  # titles containing any of these are not this release ("ADP")

    def __post_init__(self) -> None:
        where = f"actuals rule {self.country} {self.match!r}"
        if (self.fred is None) == (self.eurostat is None):
            raise ValueError(f"{where}: exactly one of fred / eurostat")
        if self.country not in ("USD", "EUR"):
            raise ValueError(f"{where}: country must be USD or EUR")
        if self.lag < 0:
            raise ValueError(f"{where}: lag must be >= 0")
        if self.exclude is not None and not all(isinstance(x, str) and x for x in self.exclude):
            raise ValueError(f"{where}: exclude must be a list of non-empty strings")
        if self.calc not in ("level", "pct_prev", "pct_yoy", "diff_k"):
            raise ValueError(f"{where}: unknown calc {self.calc!r}")
        if self.fmt not in ("pct1", "pct2", "k"):
            raise ValueError(f"{where}: unknown fmt {self.fmt!r}")
        if self.freq not in ("m", "q", "d"):
            raise ValueError(f"{where}: unknown freq {self.freq!r}")


@dataclass(frozen=True)
class FeedCfg:
    name: str
    url: str


@dataclass(frozen=True)
class StrategyCfg:
    id: str
    label: str


@dataclass(frozen=True)
class ChainCfg:
    id: int
    name: str
    usdc: str  # USDC token address on this chain, lowercase


@dataclass(frozen=True)
class DefiCfg:
    asset: str
    strategies: list[StrategyCfg]  # config order == dedupe priority (most conservative first)
    chains: list[ChainCfg]
    midnight_chains: list[int]     # subset of chains ids that have Midnight deployments
    token_symbols: dict[str, str]  # lowercase collateral address -> display symbol
    morpho_graphql: str = "https://blue-api.morpho.org/graphql"
    morpho_first: int = 25


@dataclass(frozen=True)
class AaveRefCfg:
    chain: str   # display abbr (BASE/ETH/ARB); also the id token, so keep it stable
    rpc: str
    pool: str    # lowercase
    asset: str   # lowercase
    symbol: str  # asset display symbol (USDC/USDT); also the id token

    # Derived, not configured: the BASE/USDC ids resolve to the original
    # aave-base-usdc-* series, preserving their accumulated history.
    @property
    def supply_id(self) -> str:
        return f"aave-{self.chain.lower()}-{self.symbol.lower()}-supply"

    @property
    def borrow_id(self) -> str:
        return f"aave-{self.chain.lower()}-{self.symbol.lower()}-borrow"

    @property
    def supply_label(self) -> str:
        return f"AAVE {self.symbol} {self.chain} SUP"

    @property
    def borrow_label(self) -> str:
        return f"AAVE {self.symbol} {self.chain} BOR"


@dataclass(frozen=True)
class LlamaChartCfg:
    pool: str
    series: str


@dataclass(frozen=True)
class PendleRefCfg:
    chain_id: int
    address: str  # lowercase
    implied_id: str
    implied_label: str
    underlying_id: str
    underlying_label: str


@dataclass(frozen=True)
class FundingRefCfg:
    symbol: str
    id: str
    label: str


@dataclass(frozen=True)
class RefsCfg:
    aave: list[AaveRefCfg]
    llama_chart: list[LlamaChartCfg]
    pendle: list[PendleRefCfg]
    funding: list[FundingRefCfg]


@dataclass(frozen=True)
class Config:
    db_path: str
    calendar_url: str
    max_news: int
    cadences: dict[str, int]
    indexes: list[IndexCfg]
    fx: list[IndexCfg]
    sectors: list[SectorGroupCfg]
    bonds: list[BondCfg]
    cb_rates: list[CbRateCfg]
    series: list[SeriesCfg]
    cycle_series: list[CycleSeriesCfg]
    cycle_tabs: list[CycleTabCfg]
    calendar_map: list[CalendarMapEntry]
    actuals: list[ActualRuleCfg]
    feeds: list[FeedCfg]
    zyfai_base: str
    midnight_base: str
    defi: DefiCfg
    refs: RefsCfg


def _duplicate_symbol(symbols: list[str]) -> str | None:
    seen: set[str] = set()
    for s in symbols:
        if s in seen:
            return s
        seen.add(s)
    return None


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    indexes = [IndexCfg(**i) for i in raw["indexes"]]
    fx = [IndexCfg(**i) for i in raw.get("fx") or []]
    sectors = [
        SectorGroupCfg(
            title=g["title"], note=g.get("note", ""),
            rows=[IndexCfg(**r) for r in g["rows"]],
        )
        for g in raw.get("sectors") or []
    ]
    all_symbols = (
        [i.symbol for i in indexes]
        + [i.symbol for i in fx]
        + [r.symbol for g in sectors for r in g.rows]
    )
    dup = _duplicate_symbol(all_symbols)
    if dup is not None:
        raise ValueError(f"duplicate symbol across indexes/fx/sectors: {dup!r}")
    return Config(
        db_path=os.environ.get("DB_PATH", raw["db_path"]),
        calendar_url=raw["calendar_url"],
        max_news=raw["max_news"],
        cadences=dict(raw["cadences"]),
        indexes=indexes,
        fx=fx,
        sectors=sectors,
        bonds=[BondCfg(**b) for b in raw["bonds"]],
        cb_rates=[CbRateCfg(**c) for c in raw["cb_rates"]],
        series=[SeriesCfg(**s) for s in raw["series"]],
        cycle_series=[CycleSeriesCfg(**s) for s in raw["cycle_series"]],
        cycle_tabs=[
            CycleTabCfg(
                id=t["id"], label=t["label"],
                panels=[
                    CyclePanelCfg(
                        title=p["title"],
                        rows=[CycleRowCfg(**r) for r in p["rows"]],
                    )
                    for p in t["panels"]
                ],
            )
            for t in raw["cycle_tabs"]
        ],
        calendar_map=[CalendarMapEntry(**m) for m in raw["calendar_map"]],
        actuals=[ActualRuleCfg(**a) for a in raw["actuals"]],
        feeds=[FeedCfg(**f) for f in raw["feeds"]],
        zyfai_base=raw["zyfai_base"],
        midnight_base=raw["midnight_base"],
        defi=DefiCfg(
            asset=raw["defi"]["asset"],
            strategies=[StrategyCfg(**s) for s in raw["defi"]["strategies"]],
            chains=[
                ChainCfg(id=c["id"], name=c["name"], usdc=c["usdc"].lower())
                for c in raw["defi"]["chains"]
            ],
            midnight_chains=list(raw["defi"]["midnight_chains"]),
            token_symbols={
                k.lower(): v
                for k, v in (raw["defi"].get("token_symbols") or {}).items()
            },
            morpho_graphql=raw["defi"]["morpho_graphql"],
            morpho_first=raw["defi"]["morpho_first"],
        ),
        refs=RefsCfg(
            aave=[
                AaveRefCfg(
                    chain=a["chain"], rpc=a["rpc"], pool=a["pool"].lower(),
                    asset=a["asset"].lower(), symbol=a["symbol"],
                )
                for a in raw["refs"]["aave"]
            ],
            llama_chart=[
                LlamaChartCfg(pool=c["pool"], series=c["series"])
                for c in raw["refs"]["llama_chart"]
            ],
            pendle=[
                PendleRefCfg(
                    chain_id=p["chain_id"],
                    address=p["address"].lower(),
                    implied_id=p["implied_id"],
                    implied_label=p["implied_label"],
                    underlying_id=p["underlying_id"],
                    underlying_label=p["underlying_label"],
                )
                for p in raw["refs"]["pendle"]
            ],
            funding=[
                FundingRefCfg(symbol=f["symbol"], id=f["id"], label=f["label"])
                for f in raw["refs"]["funding"]
            ],
        ),
    )

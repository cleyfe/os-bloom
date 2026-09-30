"""Daily market-cycle job: one series list, eight source kinds, per-series
isolation (a bad id or a dead file URL degrades that series only — the
summary error raises at the end so /healthz surfaces it)."""
from __future__ import annotations

from datetime import date

from collector.config import CycleSeriesCfg
from collector.fetchers import aaii, cboe, cftc, dbnomics, eurostat, fred, oecd, yahoo
from collector.http import GetBytes, GetText
from collector.store import Store

# eurostat requires a `since`; cycle series want everything available, so
# this predates every dataset we point at (the API clips to its own start).
EUROSTAT_SINCE = date(2000, 1, 1)


async def _fetch_one(
    cfg: CycleSeriesCfg,
    fred_api_key: str,
    get_text: GetText,
    get_bytes: GetBytes,
    today: date | None,
) -> list[tuple[date, float]]:
    if cfg.fred:
        return await fred.fetch_series(cfg.fred, fred_api_key, get_text)
    if cfg.dbnomics:
        return await dbnomics.fetch_series(cfg.dbnomics, get_text)
    if cfg.oecd:
        return await oecd.fetch_series(cfg.oecd, get_text)
    if cfg.eurostat:
        return await eurostat.fetch_eurostat(cfg.eurostat, get_text, since=EUROSTAT_SINCE, freq="m")
    if cfg.cftc:
        return await cftc.fetch_net_noncommercial(cfg.cftc, get_text)
    if cfg.cboe:
        return await cboe.fetch_ratio_history(cfg.cboe, get_text, today=today)
    if cfg.aaii:
        return await aaii.fetch_spread(get_bytes)
    if cfg.yahoo_ratio:
        num, den = cfg.yahoo_ratio
        a = await yahoo.fetch_chart(num, get_text, range_="10y")
        b = await yahoo.fetch_chart(den, get_text, range_="10y")
        return yahoo.ratio_points(a.closes, b.closes)
    raise ValueError("no source configured")


async def fetch_cycle(
    series: list[CycleSeriesCfg],
    store: Store,
    fred_api_key: str,
    get_text: GetText,
    get_bytes: GetBytes,
    today: date | None = None,
) -> str:
    errors: list[str] = []
    for cfg in series:
        try:
            pts = await _fetch_one(cfg, fred_api_key, get_text, get_bytes, today)
            if cfg.valid_range:
                lo, hi = cfg.valid_range
                pts = [(d, v) for d, v in pts if lo <= v <= hi]
                store.prune_outside_range(f"cycle:{cfg.id}", lo, hi)
            store.upsert_points(f"cycle:{cfg.id}", pts)
        except Exception as exc:  # noqa: BLE001 — per-series isolation
            errors.append(f"{cfg.id}: {exc}")
    if errors:
        raise RuntimeError(f"{len(errors)}/{len(series)} cycle series failed: {'; '.join(errors)}")
    return "cycle"

"""Government yields (10Y + 3M) and central bank policy rates.

Chain per bond: FRED (US) -> Bundesbank (DE 10Y) -> ECB (euro-area 3M curve)
-> BoE (GB, from the "latest yield curve data" zip). CB rates use the FRED
fetcher; there is no clean keyless daily/weekly UK Bank Rate source (FRED's
UK policy-rate series stopped updating in 2017), so the GB CB cell is left
empty rather than shipped with a stale or mismatched proxy.

The BoE zip is downloaded once per run (not once per `boe:` row) and its
tenors handed to each `boe:` instrument.

Writes history to 'yield:{country}{tenor}' / 'cb:{country}' and latest to the
'bond_quotes' doc keyed '{country}{tenor}' ('US10Y', 'US3M', 'USCB'):
{country, tenor|label, yield_pct, ts, source}. Instruments that fail this run
keep their last-known quote (stale beats gone) — but only instruments still
in config, because the panels layer iterates the doc's keys. Pre-matrix docs
were keyed by bare country; those keys fall out of `wanted` and are dropped.
"""
from __future__ import annotations

import logging

from collector.config import BondCfg, CbRateCfg
from collector.fetchers import boe, bundesbank, ecb, fred
from collector.http import GetBytes, GetText
from collector.store import Store

log = logging.getLogger(__name__)


async def _daily_series(
    cfg: BondCfg | CbRateCfg, get_text: GetText, fred_api_key: str,
    boe_data: dict[str, list] | None, boe_error: str | None,
) -> tuple[list, str] | None:
    """(closes, source) via the keyless-source chain, or None if unconfigured."""
    if cfg.fred:
        return await fred.fetch_series(cfg.fred, fred_api_key, get_text), "fred"
    if getattr(cfg, "bundesbank", None):
        return await bundesbank.fetch_series(cfg.bundesbank, get_text), "bundesbank"
    if getattr(cfg, "ecb", None):
        return await ecb.fetch_series(cfg.ecb, get_text), "ecb"
    if getattr(cfg, "boe", None):
        if boe_data is None:
            raise RuntimeError(boe_error or "boe zip fetch failed")
        return boe_data[cfg.boe], "boe"
    return None


async def fetch_bonds(
    bonds: list[BondCfg],
    cb_rates: list[CbRateCfg],
    store: Store,
    get_text: GetText,
    fred_api_key: str,
    get_bytes: GetBytes | None = None,
) -> str:
    instruments = [(f"{b.country}{b.tenor}", f"yield:{b.country}{b.tenor}", b) for b in bonds]
    instruments += [(f"{c.country}CB", f"cb:{c.country}", c) for c in cb_rates]
    wanted = {key for key, _, _ in instruments}
    prev = store.doc("bond_quotes")
    quotes: dict[str, dict] = (
        {k: q for k, q in prev.payload.items() if k in wanted} if prev else {}
    )
    sources_used: set[str] = set()
    errors: list[str] = []
    fetched = 0

    boe_tenors = sorted({b.boe for b in bonds if b.boe})
    boe_data: dict[str, list] | None = None
    boe_error: str | None = None
    if boe_tenors:
        try:
            boe_data = await boe.fetch_spot_curve(boe_tenors, get_bytes)
        except Exception as exc:  # noqa: BLE001 — degrades every boe: instrument, not the run
            boe_error = str(exc)
            log.warning("boe zip fetch failed: %s", exc)

    for key, series_id, cfg in instruments:
        try:
            is_bond = isinstance(cfg, BondCfg)
            result = await _daily_series(cfg, get_text, fred_api_key, boe_data, boe_error)
            if result is None:
                errors.append(f"{key}: no source configured")
                continue
            closes, source = result
            last_d, last_v = closes[-1]
            latest = (f"{last_d.isoformat()}T00:00:00Z", last_v)
        except Exception as exc:  # noqa: BLE001 — one instrument must not kill the run
            log.warning("bond fetch failed for %s: %s", key, exc)
            errors.append(f"{key}: {exc}")
            continue
        store.upsert_points(series_id, closes)
        ts, value = latest
        quotes[key] = {"country": cfg.country, "yield_pct": value, "ts": ts, "source": source}
        if is_bond:
            quotes[key]["tenor"] = cfg.tenor
            if cfg.tenor_label:
                quotes[key]["tenor_label"] = cfg.tenor_label
        else:
            quotes[key]["label"] = cfg.label
        sources_used.add(source)
        fetched += 1

    if fetched == 0:
        raise RuntimeError(f"all bonds failed: {'; '.join(errors)}")
    store.put_doc("bond_quotes", quotes, source="+".join(sorted(sources_used)))
    return "+".join(sorted(sources_used))

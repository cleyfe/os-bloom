"""Quote instruments (equity indexes, FX pairs, sector ETFs), from Yahoo's
keyless chart API.

(Stooq was a fallback until it put its CSV endpoint behind a JavaScript
proof-of-work wall; it returned HTTP 200 with an HTML challenge body rather
than an error, so it failed at parse time and never served a quote. Removed
2026-09-06 along with an optional IBKR path that returned data flagged just as
delayed as Yahoo's, for no gain.)

fetch_quotes is the shared body: it writes daily closes to series
'{prefix}{symbol}' and the latest quotes to the '{doc_key}' doc:
{symbol: {last, ts, source, delayed}}. fetch_equity is the equity-indexes
wrapper ('idx:', 'equity_quotes'); fx and sectors call fetch_quotes directly
with their own prefix/doc_key from the scheduler.
"""
from __future__ import annotations

import logging

from collector.config import IndexCfg
from collector.fetchers import yahoo
from collector.http import GetText
from collector.store import Store

log = logging.getLogger(__name__)


async def fetch_quotes(
    instruments: list[IndexCfg], store: Store, get_text: GetText, prefix: str, doc_key: str,
) -> str:
    sources_used: set[str] = set()
    # Stale beats gone: seed with the previous doc so a symbol that fails every
    # source this run keeps its last-known quote (its old ts marks it stale).
    # Symbols removed from config are dropped, not carried forward forever.
    wanted = {i.symbol for i in instruments}
    prev = store.doc(doc_key)
    quotes: dict[str, dict] = (
        {s: q for s, q in prev.payload.items() if s in wanted} if prev else {}
    )
    fetched = 0
    errors: list[str] = []

    for idx in instruments:
        if idx.yahoo:
            try:
                chart = await yahoo.fetch_chart(idx.yahoo, get_text)
                store.upsert_points(f"{prefix}{idx.symbol}", chart.closes)
                last_d, last_v = chart.closes[-1]
                quotes[idx.symbol] = {
                    "last": chart.last if chart.last is not None else last_v,
                    "ts": chart.last_ts or f"{last_d.isoformat()}T00:00:00Z",
                    "source": "yahoo", "delayed": True,
                }
                sources_used.add("yahoo")
                fetched += 1
                continue
            except Exception as exc:  # noqa: BLE001 — one dead symbol must not kill the run
                errors.append(f"{idx.symbol}: {exc}")
        else:
            errors.append(f"{idx.symbol}: no source configured")

    if fetched == 0:
        label = doc_key.removesuffix("_quotes")  # "equity_quotes" -> "equity", "fx_quotes" -> "fx"
        raise RuntimeError(f"all {label} symbols failed: {'; '.join(errors)}")
    store.put_doc(doc_key, quotes, source="+".join(sorted(sources_used)))
    return "+".join(sorted(sources_used))


async def fetch_equity(indexes: list[IndexCfg], store: Store, get_text: GetText) -> str:
    return await fetch_quotes(indexes, store, get_text, "idx:", "equity_quotes")

"""AI market comment: one Claude call over the terminal's own data.

Closed-book by design: the model comments ONLY on the snapshot we hand it, so
every comment is auditable against its stored input. The Anthropic call lives
behind an injectable `call_model` coroutine; tests never touch the SDK.

The comment is rendered as a band at the top of the MKT tab, so it is short:
headline, regime read, drivers, rotation note. Nothing that would not fit.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from collector.config import Config
from collector.panels import build_dashboard
from collector.store import Store

log = logging.getLogger(__name__)

# (model, system, user_text, schema) -> (parsed comment, model that actually answered).
# The served model can differ from the requested one when the server-side
# refusal fallback kicks in; the band shows whichever wrote the text.
CallModel = Callable[[str, str, str, dict], Awaitable[tuple[dict, str]]]

FIELDS = ("headline", "regime_read", "drivers", "rotation_note")

COMMENT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string",
                         "description": "One-line market read, about 10 words"},
            "regime_read": {"type": "string",
                            "description": "2-4 sentences on the overall regime"},
            # The API caps minItems at 1 in output schemas; the 3-5 target
            # lives in the description and the SYSTEM rules instead.
            "drivers": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                        "description": "3-5 data points doing the work, each citing a number "
                                       "from the snapshot; one short phrase each"},
            "rotation_note": {"type": "string",
                              "description": "1-2 sentences on rotation and positioning"},
        },
        "required": list(FIELDS),
        "additionalProperties": False,
    },
}

# Stable across runs -> prompt-cached; anything volatile goes in the user turn.
SYSTEM = """You are the in-house market strategist for a self-hosted market terminal.
Twice a day you write a short, data-grounded market comment that sits in a
band at the top of the terminal's main tab.

You will receive a JSON snapshot with:
- equity: index levels with % changes over 1d/1w/ytd/1y
- bonds: per-country central-bank rate, 3M and 10Y yields, 10Y bp changes
- cycle: market-cycle indicators grouped by tab (risk / econ / credit / profit / pos):
  volatility, put/call, sentiment spreads, rotation ratios (value>1 rising means the
  first leg outperforms), PMIs, OECD CLIs, claims, money supply, inflation expectations,
  curve slopes, credit OAS by quality, CFTC net non-commercial positioning.
  chg_1m / chg_1y are absolute changes in the series' own unit.
- news: recent headlines (titles only)
- macro_past / macro_upcoming: high-impact releases, actual vs consensus

Rules:
- Comment ONLY on the data provided. No outside knowledge of current markets,
  no price targets, no investment advice, no asset recommendations.
- Cite concrete numbers from the snapshot for every claim.
- A stale or missing value is a data caveat: say so in the regime read rather
  than treating it as fresh.
- If a previous comment is provided, lead with what CHANGED since it.
- Plain professional tone; no hedging boilerplate, no exclamation marks.
- Keep it tight: the headline is about 10 words, the regime read 2-4 sentences,
  3-5 drivers of one short phrase each, the rotation note 1-2 sentences."""


def _snap_equity(rows: list[dict]) -> list[dict]:
    keep = ("symbol", "name", "last", "chg_1d", "chg_1w", "chg_ytd", "chg_1y")
    return [{k: r[k] for k in keep if k in r} for r in rows]


def _snap_bonds(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "updated_at"} for r in rows]


def _snap_cycle(cycle: dict) -> list[dict]:
    """Flatten tabs -> one row list; drop UI-only fields (id, overlay)."""
    keep = ("name", "unit", "value", "chg_1m", "chg_1y")
    out = []
    for tab in cycle.get("tabs", []):
        for panel in tab.get("panels", []):
            for row in panel.get("rows", []):
                out.append({"tab": tab["id"], **{k: row[k] for k in keep if k in row}})
    return out


def _snap_macro(releases: list[dict]) -> list[dict]:
    keep = ("country", "name", "time", "actual", "consensus", "previous")
    return [{k: r[k] for k in keep if r.get(k) is not None} for r in releases]


def build_snapshot(store: Store, cfg: Config, now: datetime) -> dict:
    dash = build_dashboard(store, cfg.indexes, now=now,
                           cycle_series=cfg.cycle_series, cycle_tabs=cfg.cycle_tabs)
    p = dash["panels"]
    return {
        "as_of": dash["as_of"],
        "equity": _snap_equity(p["equity"]["rows"]),
        "bonds": _snap_bonds(p["bonds"]["rows"]),
        "cycle": _snap_cycle(p["cycle"]),
        "news": [{"feed": n.get("feed"), "headline": n.get("headline")}
                 for n in p["news"]["items"]],
        "macro_past": _snap_macro(p["macro"].get("past", [])),
        "macro_upcoming": _snap_macro(p["macro"].get("releases", [])),
    }


def _user_text(snapshot: dict, previous: dict | None) -> str:
    parts = []
    if previous:
        parts.append("Previous comment (for continuity: lead with what changed):\n"
                     + json.dumps(previous, separators=(",", ":")))
    parts.append("Data snapshot:\n" + json.dumps(snapshot, separators=(",", ":")))
    parts.append("Write the market comment now.")
    return "\n\n".join(parts)


def _validate(comment: dict) -> dict:
    """The schema is enforced server-side, but the call layer is injectable:
    check the shape here so a bad fake or a changed API never stores junk."""
    missing = [f for f in FIELDS if not comment.get(f)]
    if missing or not isinstance(comment["drivers"], list):
        raise ValueError(f"comment missing fields: {', '.join(missing) or 'drivers not a list'}")
    return {f: comment[f] for f in FIELDS}


async def fetch_comment(cfg: Config, store: Store, call_model: CallModel,
                        now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    snapshot = build_snapshot(store, cfg, now)
    prev_doc = store.doc("market_comment")
    previous = prev_doc.payload.get("comment") if prev_doc else None
    raw, served_model = await call_model(cfg.comment.model, SYSTEM,
                                         _user_text(snapshot, previous), COMMENT_SCHEMA)
    comment = _validate(raw)
    store.put_doc("market_comment", {
        "comment": comment,
        "snapshot_as_of": snapshot["as_of"],
        "model": served_model,
    }, source=served_model)
    return served_model


async def call_claude(model: str, system: str, user_text: str, schema: dict) -> tuple[dict, str]:
    """Production call layer: the only function that touches the SDK.

    Lazy import so the collector runs (and tests pass) without the anthropic
    package when the comment job isn't registered.

    - Structured output via output_config.format: the first text block is
      valid JSON matching the schema.
    - The system prompt is cache-marked, so the second run of the day is
      mostly cache reads.
    - fallbacks="default": if a safety classifier declines this benign market
      note, the API re-runs it on another model inside the same call, and
      response.model names whichever answered. That is what the band shows.
    """
    import anthropic

    client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env
    try:
        response = await client.beta.messages.create(
            model=model,
            max_tokens=4096,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
            output_config={"format": schema},
        )
    finally:
        await client.close()
    if response.stop_reason != "end_turn":
        # refusal (whole chain declined) / max_tokens: fail the run, the stored
        # comment keeps serving
        raise RuntimeError(f"comment model stopped early: stop_reason={response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response.model

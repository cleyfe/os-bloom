import { fmtAge, isStale } from "../fmt.js";
import { renderQuoteTable } from "./quotes.js";

// Labels come from collector config, not a third-party API, but escape
// before innerHTML anyway — cheap insurance against a bad config value.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STALE_MINUTES = 40; // ~2.7x the 900s sector cadence

export function renderSectors(panel) {
  const root = document.getElementById("sectors-grid");
  if (!root) return;
  const groups = panel.groups ?? [];
  if (!groups.some((g) => g.rows.length)) {
    root.innerHTML = `<section class="panel"><div class="panel-body"><div class="empty-state">NO DATA</div></div></section>`;
    return;
  }
  const stale = isStale(panel.updated_at, STALE_MINUTES);
  const foot = `<div class="panel-foot muted${stale ? " stale" : ""}">DATA: ${esc((panel.source ?? "—").toUpperCase())} · ${fmtAge(panel.updated_at)}</div>`;
  root.innerHTML = groups.map((g, gi) => `
    <section class="panel" id="sector-panel-${gi}">
      <div class="panel-title"><span>${esc(g.title)}</span>${g.note ? `<span class="muted">${esc(g.note)}</span>` : ""}</div>
      <div class="panel-body"></div>
      ${foot}
    </section>`).join("");
  groups.forEach((g, gi) => {
    const body = document.querySelector(`#sector-panel-${gi} .panel-body`);
    renderQuoteTable(body, g.rows, { label: "Sector", showName: true });
  });
}

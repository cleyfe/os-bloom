import { getDashboard } from "./api.js";
import { fmtAge, fmtClock, isStale } from "./fmt.js";
import { defiFootData, initDefiViewToggle, renderDefi, renderMidnight } from "./panels/defi.js";
import { renderBonds, renderEquity } from "./panels/equity.js";
import { renderMacro } from "./panels/macro.js";
import { renderNews } from "./panels/news.js";
import { renderComment } from "./panels/comment.js";
import { renderCycle } from "./panels/cycle.js";
import { renderRefs } from "./panels/refs.js";
import { initTabs } from "./tabs.js";

const POLL_MS = 60_000;
const STALE_MINUTES = { equity: 20, bonds: 130, macro: 390, news: 40, defi: 35, midnight: 35, refs: 35, comment: 1500 };  // ~2x cadence

const EMPTY = { rows: [], updated_at: null, source: null };

let lastDash = null; // last successful payload, for the view-toggle re-render (no re-fetch)

function foot(panelId, name, data) {
  const el = document.querySelector(`#panel-${panelId} .panel-foot`);
  const src = (data.source ?? "—").toUpperCase();
  el.textContent = `DATA: ${src} · ${fmtAge(data.updated_at)}`;
  el.classList.toggle("stale", isStale(data.updated_at, STALE_MINUTES[name]));
}

function renderDefiPanel(p) {
  const defi = p.defi ?? EMPTY;      // ?? EMPTY: tolerate an old collector during rollout
  const morpho = p.morpho ?? EMPTY;
  renderDefi(defi, morpho);
  foot("defi", "defi", defiFootData(defi, morpho));
}

async function tick() {
  const banner = document.getElementById("banner");
  try {
    const dash = await getDashboard();
    lastDash = dash;
    const p = dash.panels;
    renderEquity(p.equity);
    renderBonds(p.bonds);
    renderMacro(p.macro);
    renderNews(p.news);
    renderDefiPanel(p);
    renderMidnight(p.midnight ?? EMPTY);
    renderRefs(p.refs ?? EMPTY);
    renderCycle(p.cycle ?? { tabs: [], updated_at: null });
    renderComment(p.comment, STALE_MINUTES.comment);  // undefined from an old collector -> band stays hidden
    foot("equity", "equity", { ...p.equity, source: p.equity.rows[0]?.source });
    foot("bonds", "bonds", p.bonds);
    foot("macro", "macro", p.macro);
    foot("news", "news", p.news);
    foot("midnight", "midnight", p.midnight ?? EMPTY);
    foot("refs", "refs", p.refs ?? EMPTY);
    document.getElementById("clock").textContent = `as of ${fmtClock(dash.as_of)} UTC`;
    banner.classList.add("hidden");
  } catch (err) {
    banner.textContent = `COLLECTOR UNREACHABLE — ${err.message}`;
    banner.classList.remove("hidden");
  }
}

initTabs();
initDefiViewToggle(() => {
  if (lastDash) renderDefiPanel(lastDash.panels);
});
// A chart drawn while its tab is hidden sees clientWidth 0 and falls back to
// 300px; redraw on tab switch so it sizes to the now-visible panel.
window.addEventListener("hashchange", () => {
  if (lastDash) renderMidnight(lastDash.panels.midnight ?? EMPTY);
});
tick();
setInterval(tick, POLL_MS);

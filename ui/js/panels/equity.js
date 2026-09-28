import { openChart } from "../chart.js";
import { fmtBp } from "../fmt.js";
import { renderQuoteTable } from "./quotes.js";

export function renderEquity(panel) {
  const body = document.querySelector("#panel-equity .panel-body");
  renderQuoteTable(body, panel.rows, { label: "Index" });
}

// Matrix: one row per country, CB / 3M / 10Y cells each click through to
// their own history series (USCB / US3M / US10Y — api applies store prefixes).
export function renderBonds(panel) {
  const body = document.querySelector("#panel-bonds .panel-body");
  const chg = (bp) => { const { text, cls } = fmtBp(bp); return `<td class="${cls}">${text}</td>`; };
  const yld = (r, pct, sid, title) => pct == null
    ? `<td>—</td>`
    : `<td class="clickable" data-sid="${r.country}${sid}" data-title="${title}">${pct.toFixed(2)}</td>`;
  body.innerHTML = `<table>
    <tr><th>Ctry</th><th>CB</th><th>3M</th><th>10Y</th><th>1D</th><th>1W</th></tr>
    ${panel.rows.map((r) =>
      `<tr><td class="sym">${r.country}</td>` +
      yld(r, r.cb_pct, "CB", `${r.cb_label ?? r.country} RATE`) +
      yld(r, r.y3m_pct, "3M", `${r.country} 3M YIELD`) +
      yld(r, r.y10_pct, "10Y", `${r.country} 10Y YIELD`) +
      `${chg(r.chg_1d_bp)}${chg(r.chg_1w_bp)}</tr>`
    ).join("")}
  </table>`;
  body.querySelectorAll("td.clickable").forEach((td) => {
    td.addEventListener("click", () => openChart(td.dataset.sid, td.dataset.title));
  });
}

import { openChart } from "../chart.js";
import { fmtNum, fmtPct } from "../fmt.js";

const HORIZONS = ["1d", "1w", "ytd", "1y"];

// Labels come from collector config, not a third-party API, but escape
// before innerHTML anyway — cheap insurance against a bad config value.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Shared table for any list of quoted instruments (equity indexes, FX pairs,
// sector ETFs): label, Last, 1D, 1W, YTD, 1Y, each row opening its chart.
// showName puts the name first with the symbol in the tooltip (sectors);
// otherwise the symbol leads with the name in the tooltip (FX, EQTY).
export function renderQuoteTable(body, rows, { label = "", showName = false, digits = fmtNum } = {}) {
  const cells = (row) => HORIZONS.map((h) => {
    const { text, cls } = fmtPct(row[`chg_${h}`]);
    const optCls = h === "1w" || h === "1y" ? " c-opt" : "";
    return `<td class="${cls}${optCls}">${text}</td>`;
  }).join("");
  const firstCell = (r) => showName
    ? `<td class="sym" title="${esc(r.symbol)}">${esc(r.name)}</td>`
    : `<td class="sym" title="${esc(r.name)}">${esc(r.symbol)}</td>`;
  body.innerHTML = `<table>
    <tr><th>${esc(label)}</th><th>Last</th><th>1D</th><th class="c-opt">1W</th><th>YTD</th><th class="c-opt">1Y</th></tr>
    ${rows.map((r, i) =>
      `<tr class="clickable" data-i="${i}">${firstCell(r)}` +
      `<td>${digits(r.last)}</td>${cells(r)}</tr>`
    ).join("")}
  </table>`;
  body.querySelectorAll("tr.clickable").forEach((tr) => {
    tr.addEventListener("click", () => {
      const r = rows[Number(tr.dataset.i)];
      openChart(r.symbol, r.name);
    });
  });
}

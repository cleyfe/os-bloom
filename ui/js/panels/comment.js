import { fmtAge, isStale } from "../fmt.js";

// Drivers go through innerHTML, so escape them: the text is LLM-generated
// and is treated like any other untrusted feed. Everything else uses
// textContent and needs no escaping.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STALE_MINUTES = 1500; // ~2x the 12h cadence

// Hidden entirely when there is no comment (no key, or no run yet), so an
// install without ANTHROPIC_API_KEY looks exactly as it did before.
export function renderComment(panel) {
  const el = document.getElementById("panel-comment");
  const c = panel?.comment ?? null;
  el.classList.toggle("hidden", !c);
  el.closest(".grid").classList.toggle("has-comment", !!c);
  if (!c) return;
  el.querySelector(".comment-headline").textContent = c.headline ?? "";
  el.querySelector(".comment-read").textContent = c.regime_read ?? "";
  el.querySelector(".comment-drivers").innerHTML =
    (c.drivers ?? []).map((d) => `<span class="comment-driver">${esc(d)}</span>`).join("");
  el.querySelector(".comment-rotation").textContent = c.rotation_note ?? "";
  const meta = el.querySelector(".comment-meta");
  meta.textContent =
    `${(panel.source ?? "—").toUpperCase()} · ${fmtAge(panel.updated_at)} · AI-GENERATED, NOT INVESTMENT ADVICE`;
  meta.classList.toggle("stale", isStale(panel.updated_at, STALE_MINUTES));
}

import { getDashboard, refreshComment } from "../api.js";
import { fmtAge } from "../fmt.js";

// Drivers go through innerHTML, so escape them: the text is LLM-generated
// and is treated like any other untrusted feed. Everything else uses
// textContent and needs no escaping.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const POLL_MS = 5_000;
const POLL_TRIES = 36;  // 3 minutes: an Opus call plus a few article fetches

// Set while a refresh is in flight or has just failed, so the 60s tick does
// not overwrite the status line the user is looking at.
let holdStatus = false;

// Three states. Hidden entirely when there is no comment (no key, or no run
// yet), so an install without ANTHROPIC_API_KEY looks exactly as it did
// before. Outdated (the server's verdict): title row, one status line and a
// REFRESH control, no comment text. Fresh: the comment.
export function renderComment(panel) {
  const el = document.getElementById("panel-comment");
  if (!el) return;  // stale index.html with new JS during a deploy: skip, don't kill the tick
  const c = panel?.comment ?? null;
  el.classList.toggle("hidden", !c);
  el.closest(".grid")?.classList.toggle("has-comment", !!c);
  if (!c) return;
  const body = el.querySelector(".comment-body");
  const outdated = el.querySelector(".comment-outdated");
  if (!body || !outdated) return;  // same deploy-skew guard, one markup generation later
  const stale = !!panel.stale;
  el.dataset.updatedAt = panel.updated_at ?? "";
  body.classList.toggle("hidden", stale);
  outdated.classList.toggle("hidden", !stale);
  const meta = el.querySelector(".comment-meta");
  meta.textContent =
    `${(panel.source ?? "—").toUpperCase()} · ${fmtAge(panel.updated_at)} · AI-GENERATED, NOT INVESTMENT ADVICE`;
  meta.classList.toggle("stale", stale);
  if (stale) {
    if (!holdStatus) {
      el.querySelector(".comment-outdated-text").textContent =
        `COMMENT OUTDATED · last written ${fmtAge(panel.updated_at)}`;
    }
    return;
  }
  holdStatus = false;  // a fresh comment retires any refresh failure message
  el.querySelector(".comment-headline").textContent = c.headline ?? "";
  el.querySelector(".comment-read").textContent = c.regime_read ?? "";
  el.querySelector(".comment-drivers").innerHTML =
    (c.drivers ?? []).map((d) => `<span class="comment-driver">${esc(d)}</span>`).join("");
  el.querySelector(".comment-rotation").textContent = c.rotation_note ?? "";
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// POST the refresh, then poll until the comment's timestamp moves. The server
// decides whether a refresh is allowed at all; a refusal comes back as its
// detail text.
export function initCommentRefresh() {
  const el = document.getElementById("panel-comment");
  if (!el) return;
  const btn = el.querySelector(".comment-refresh");
  const status = el.querySelector(".comment-outdated-text");
  if (!btn || !status) return;  // old index.html without the control: nothing to bind
  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    holdStatus = true;
    status.textContent = "REFRESHING…";
    const before = el.dataset.updatedAt;
    try {
      const resp = await refreshComment();
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      for (let i = 0; i < POLL_TRIES; i++) {
        await sleep(POLL_MS);
        let p;
        try {
          p = (await getDashboard()).panels.comment;
        } catch {
          continue;  // one blip on the dashboard is not a failed refresh
        }
        if (p?.updated_at && p.updated_at !== before) {
          holdStatus = false;
          renderComment(p);
          return;
        }
      }
      throw new Error("timed out");
    } catch (err) {
      status.textContent = `REFRESH FAILED · ${err.message} · see /healthz`;
    } finally {
      btn.disabled = false;
    }
  });
}

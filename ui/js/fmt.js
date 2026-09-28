export const fmtNum = (x) =>
  x == null ? "—" : x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// FX pairs read more precisely below parity (e.g. EURUSD) than above it (e.g. USDJPY).
export const fmtFx = (x) => {
  if (x == null) return "—";
  const digits = Math.abs(x) < 10 ? 4 : 2;
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

const signed = (x, suffix, digits) => ({
  text: x == null ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(digits)}${suffix}`,
  cls: x == null || x === 0 ? "flat" : x > 0 ? "up" : "down",
});
export const fmtPct = (x) => signed(x, "%", 2);
export const fmtBp = (x) => (x == null ? { text: "—", cls: "flat" } : {
  text: `${x > 0 ? "+" : ""}${x}bp`, cls: x === 0 ? "flat" : x > 0 ? "up" : "down",
});

export const fmtClock = (iso) => (iso ? iso.slice(11, 19) : "—");
export const fmtAge = (iso) => {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - Date.parse(iso)) / 60000);
  return mins < 1 ? "now" : mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`;
};
export const isStale = (iso, maxMinutes) =>
  !iso || (Date.now() - Date.parse(iso)) / 60000 > maxMinutes;

export const fmtUsd = (x) => {
  if (x == null) return "—";
  const abs = Math.abs(x);
  if (abs >= 1e9) return `${(x / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(x / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(x / 1e3).toFixed(1)}K`;
  return x.toFixed(0);
};

const TABS = ["mkt", "sectors", "defi", "risk", "econ", "credit", "profit", "pos"];

const currentTab = () => {
  const t = location.hash.replace("#/", "");
  return TABS.includes(t) ? t : "mkt";
};

export function initTabs() {
  const apply = () => {
    const active = currentTab();
    document.querySelectorAll("main[data-tab]").forEach((m) =>
      m.classList.toggle("hidden", m.dataset.tab !== active));
    document.querySelectorAll("[data-tab-link]").forEach((a) =>
      a.classList.toggle("active", a.dataset.tabLink === active));
  };
  window.addEventListener("hashchange", apply);
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const i = Number(e.key) - 1;
    if (i >= 0 && i < TABS.length) location.hash = `#/${TABS[i]}`;
  });
  apply();
}

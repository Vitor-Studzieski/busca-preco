(() => {
  const storageKey = "busca-preco:recent-searches:v1";
  const currentUrl = new URL(window.location.href);
  const query = currentUrl.searchParams.get("q")?.trim();
  let recent = [];

  try {
    const saved = JSON.parse(window.localStorage.getItem(storageKey) || "[]");
    if (Array.isArray(saved)) recent = saved.filter((item) => typeof item === "string").slice(0, 5);
  } catch {
    recent = [];
  }

  if (query && currentUrl.pathname === "/") {
    recent = [query, ...recent.filter((item) => item.toLocaleLowerCase() !== query.toLocaleLowerCase())].slice(0, 5);
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(recent));
    } catch {
      // A pesquisa continua funcionando quando o armazenamento do navegador está indisponível.
    }
  }

  const section = document.querySelector("[data-recent-searches]");
  const list = section?.querySelector("[data-recent-list]");
  if (section && list && recent.length) {
    for (const item of recent) {
      const link = document.createElement("a");
      link.href = `/?${new URLSearchParams({ q: item }).toString()}`;
      link.textContent = item;
      const row = document.createElement("li");
      row.append(link);
      list.append(row);
    }
    section.hidden = false;
  }

  document.addEventListener("keydown", (event) => {
    const input = document.querySelector('.market-search input[name="q"]');
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey
        && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      event.preventDefault();
      input?.focus();
    }
  });
})();

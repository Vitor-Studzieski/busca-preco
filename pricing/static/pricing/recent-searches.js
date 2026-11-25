(() => {
  const storageKey = "busca-preco:recent-searches:v1";
  const url = new URL(window.location.href);
  const query = url.searchParams.get("q")?.trim();
  let recent = [];

  try {
    const saved = JSON.parse(window.localStorage.getItem(storageKey) || "[]");
    if (Array.isArray(saved)) recent = saved.filter((item) => typeof item === "string").slice(0, 5);
  } catch {
    recent = [];
  }

  if (query && ["/comparar/", "/promocoes/"].includes(url.pathname)) {
    recent = [query, ...recent.filter((item) => item.toLocaleLowerCase() !== query.toLocaleLowerCase())].slice(0, 5);
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(recent));
    } catch {
      // The search still works when browser storage is unavailable.
    }
  }

  const section = document.querySelector("[data-recent-searches]");
  const list = section?.querySelector("[data-recent-list]");
  if (!section || !list || recent.length === 0) return;

  const city = url.searchParams.get("cidade") || "todas";
  for (const item of recent) {
    const params = new URLSearchParams({ q: item, cidade: city });
    const link = document.createElement("a");
    link.href = `/comparar/?${params.toString()}`;
    link.textContent = item;
    const row = document.createElement("li");
    row.append(link);
    list.append(row);
  }
  section.hidden = false;
})();

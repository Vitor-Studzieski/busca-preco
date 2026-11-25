(() => {
  "use strict";

  const storageKey = "busca-preco:recent-searches:v2";
  const form = document.querySelector("[data-search-form]");
  const input = document.querySelector("#product-query");
  const resultsSection = document.querySelector("[data-results]");
  const productsNode = document.querySelector("[data-products]");
  const unitCards = [...document.querySelectorAll("[data-store-card]")];
  const overallStatus = document.querySelector("[data-overall-status]");
  const headerStatus = document.querySelector(".market-header-status");
  const resultMeta = document.querySelector("[data-result-meta]");
  const queryTitle = document.querySelector("[data-query-title]");
  const progressNode = document.querySelector("[data-progress]");
  const progressText = document.querySelector("[data-progress-text]");
  const progressBar = document.querySelector("[data-progress-bar]");
  const emptyState = document.querySelector("[data-empty-state]");
  const partialMessage = document.querySelector("[data-partial-message]");
  const retryAllButton = document.querySelector("[data-retry-all]");
  const allUnitsCheckbox = document.querySelector("[data-all-units]");
  const sortSelect = document.querySelector("[data-sort]");
  const clearButton = document.querySelector("[data-clear-query]");
  const barcodeBadge = document.querySelector("[data-barcode-badge]");
  const submitButton = document.querySelector("[data-submit-search]");
  const buttonSpinner = document.querySelector(".market-button-spinner");
  const lastUpdate = document.querySelector("[data-last-update]");
  const recentSection = document.querySelector("[data-recent-searches]");
  const recentList = document.querySelector("[data-recent-list]");
  const examplesSection = document.querySelector("[data-search-examples]");
  const suggestions = document.querySelector("[data-search-suggestions]");
  const unitBySlug = new Map();
  const unitState = new Map();
  const activeControllers = new Map();
  const responseCache = new Map();
  const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const percent = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const clock = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });

  let recent = loadRecent();
  let currentQuery = "";
  let currentView = "cards";
  let currentFilter = "all";
  let searchVersion = 0;
  let searchStartedAt = 0;
  let progressTimer = 0;
  let suggestionTimer = 0;
  let currentProducts = [];
  let hasServerResults = false;

  for (const card of unitCards) {
    const slug = card.dataset.storeSlug;
    const logo = card.querySelector(".market-store-mark img");
    const copy = card.querySelector(".market-unit-copy");
    const meta = {
      slug,
      retailer: card.dataset.storeRetailer,
      location: card.dataset.storeLocation,
      name: copy?.querySelector("strong")?.textContent.trim() || "Mercado",
      is_reference: card.dataset.reference === "true",
      logo: logo?.getAttribute("src") || "",
    };
    unitBySlug.set(slug, meta);
    unitState.set(slug, { ...meta, status: "idle", issue: "", offers: [] });
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function loadRecent() {
    try {
      const current = window.localStorage.getItem(storageKey);
      const legacy = current === null ? window.localStorage.getItem("busca-preco:recent-searches:v1") : null;
      const saved = JSON.parse(current || legacy || "[]");
      if (!Array.isArray(saved)) return [];
      const items = saved.filter((item) => typeof item === "string" && item.trim()).slice(0, 8);
      if (current === null && legacy !== null) {
        try { window.localStorage.setItem(storageKey, JSON.stringify(items)); } catch { /* Keep the migrated items in memory. */ }
      }
      return items;
    } catch {
      return [];
    }
  }

  function saveRecent() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(recent.slice(0, 8)));
    } catch {
      // A busca segue funcionando quando o navegador bloqueia o armazenamento local.
    }
  }

  function rememberQuery(query) {
    recent = [query, ...recent.filter((item) => item.toLocaleLowerCase() !== query.toLocaleLowerCase())].slice(0, 8);
    saveRecent();
    renderRecent();
  }

  function renderRecent() {
    if (!recentSection || !recentList) return;
    recentList.replaceChildren();
    for (const query of recent) {
      const row = node("li", "market-recent-item");
      const link = node("a", "", query);
      link.href = `/?${new URLSearchParams({ q: query }).toString()}`;
      link.dataset.recentQuery = query;
      const remove = node("button", "market-remove-recent", "×");
      remove.type = "button";
      remove.dataset.removeRecent = query;
      remove.setAttribute("aria-label", `Remover ${query} das buscas recentes`);
      row.append(link, remove);
      recentList.append(row);
    }
    recentSection.hidden = recent.length === 0;
    if (examplesSection) examplesSection.hidden = recent.length > 0;
    renderSuggestions();
  }

  function renderSuggestions() {
    if (!suggestions) return;
    const typed = normalizeText(input?.value || "");
    const cachedProducts = [...responseCache.values()].flatMap((entry) =>
      entry.units.flatMap((unit) => unit.offers.map((offer) => offer.name))
    );
    const candidates = [...recent, ...currentProducts.map((product) => product.name), ...cachedProducts];
    const seen = new Set();
    suggestions.replaceChildren();
    for (const query of candidates) {
      const normalized = normalizeText(query);
      if (seen.has(normalized) || (typed && !normalized.includes(typed))) continue;
      seen.add(normalized);
      const option = node("option");
      option.value = query;
      suggestions.append(option);
      if (seen.size >= 8) break;
    }
  }

  function updateInputControls() {
    const value = input?.value || "";
    if (clearButton) clearButton.hidden = value.length === 0;
    if (barcodeBadge) barcodeBadge.hidden = !/^(?:\d{8}|\d{12}|\d{13}|\d{14})$/.test(value.trim());
    window.clearTimeout(suggestionTimer);
    suggestionTimer = window.setTimeout(renderSuggestions, 250);
  }

  function normalizeText(value) {
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase("pt-BR").replace(/[^a-z0-9]+/g, " ").trim();
  }

  function cacheKey(query) {
    return normalizeText(query);
  }

  function doneCount() {
    return [...unitState.values()].filter((unit) => ["success", "partial", "error"].includes(unit.status)).length;
  }

  function failedUnits() {
    return [...unitState.values()].filter((unit) => unit.status === "error" || unit.status === "partial");
  }

  function statusLabel(unit) {
    if (unit.status === "loading") return "Consultando…";
    if (unit.status === "success") return unit.offers.length ? "Preço recebido" : "Sem resultados";
    if (unit.status === "partial") return "Resposta parcial";
    if (unit.status === "error") return "Falha ao consultar";
    return "Pronta para consulta";
  }

  function setUnitState(data) {
    const existing = unitState.get(data.slug);
    if (!existing) return;
    const next = {
      ...existing,
      status: data.status || "success",
      issue: String(data.issue || ""),
      offers: Array.isArray(data.offers) ? data.offers : [],
      observed_at: data.observed_at || "",
    };
    unitState.set(data.slug, next);
    const card = unitCards.find((item) => item.dataset.storeSlug === data.slug);
    if (card) {
      card.dataset.status = next.status;
      delete card.dataset.waitState;
      const status = card.querySelector("[data-unit-status]");
      if (status) status.textContent = statusLabel(next);
      const retry = card.querySelector("[data-retry-store]");
      if (retry) retry.hidden = next.status !== "error" && next.status !== "partial";
    }
  }

  function setGroupPending(group) {
    for (const slug of group.slugs) {
      const unit = unitState.get(slug);
      if (!unit) continue;
      setUnitState({ ...unit, status: "loading", issue: "", offers: [] });
    }
    updateVisualState();
  }

  function apiGroups() {
    const leaders = [...unitState.values()].filter((unit) => unit.retailer === "lider");
    const groups = [];
    if (leaders.length) groups.push({ key: "lider", slug: leaders[0].slug, slugs: leaders.map((unit) => unit.slug) });
    for (const unit of unitState.values()) {
      if (unit.retailer !== "lider") groups.push({ key: unit.slug, slug: unit.slug, slugs: [unit.slug] });
    }
    return groups;
  }

  function groupForSlug(slug) {
    return apiGroups().find((group) => group.slugs.includes(slug));
  }

  function updateLocation(query, method = "pushState") {
    const url = new URL(window.location.href);
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    window.history[method]({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function cancelActiveSearches() {
    for (const controller of activeControllers.values()) controller.abort();
    activeControllers.clear();
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = 0;
  }

  function resetUnits(status) {
    for (const unit of unitState.values()) {
      setUnitState({ ...unit, status, issue: "", offers: [] });
    }
  }

  function applyUnits(units) {
    for (const data of units) setUnitState(data);
  }

  function setSearchBusy(busy) {
    if (buttonSpinner) buttonSpinner.hidden = !busy;
    if (submitButton) submitButton.setAttribute("aria-busy", String(busy));
    const label = submitButton?.querySelector(".market-button-label");
    if (label) label.textContent = "Buscar";
  }

  function formatElapsed(milliseconds) {
    const seconds = Math.max(0, milliseconds / 1000);
    return `${seconds.toFixed(1).replace(".", ",")} s`;
  }

  function updateProgress() {
    const total = unitState.size;
    const done = doneCount();
    const pending = total - done;
    const elapsed = formatElapsed(performance.now() - searchStartedAt);
    const slow = pending > 0 && performance.now() - searchStartedAt >= 6000;
    for (const unit of unitState.values()) {
      if (unit.status !== "loading") continue;
      const card = unitCards.find((item) => item.dataset.storeSlug === unit.slug);
      if (!card) continue;
      card.dataset.waitState = slow ? "slow" : "normal";
      const status = card.querySelector("[data-unit-status]");
      if (status) status.textContent = slow ? "Demorando mais que o normal…" : "Consultando…";
    }
    if (progressNode) progressNode.hidden = pending === 0;
    if (progressText && pending > 0) progressText.textContent = `Consultando ${done} de ${total} unidades · ${elapsed}`;
    if (progressBar) progressBar.style.width = `${total ? (done / total) * 100 : 0}%`;
    const onlineCount = [...unitState.values()].filter((unit) => unit.status === "success").length;
    if (overallStatus) overallStatus.textContent = pending > 0 ? `${done}/${total} consultadas` : `${onlineCount}/${total} online`;
    if (headerStatus) {
      const errors = failedUnits().length;
      headerStatus.dataset.state = pending > 0 ? "loading" : errors === total ? "error" : errors ? "partial" : "success";
    }
    const anyBusy = pending > 0;
    setSearchBusy(anyBusy);
    if (anyBusy && resultMeta) {
      const productCount = buildProducts().length;
      resultMeta.textContent = productCount
        ? `${productCount} ${productCount === 1 ? "produto" : "produtos"} encontrados até agora`
        : "Consultando preços nas unidades…";
    }
    if (!anyBusy && currentQuery) {
      const errors = failedUnits().length;
      const productCount = buildProducts().length;
      const statusText = errors
        ? `${total - errors} de ${total} unidades responderam`
        : `${total} unidades consultadas`;
      if (resultMeta) resultMeta.textContent = `${productCount} ${productCount === 1 ? "produto" : "produtos"} · ${statusText} · ${elapsed}`;
      const observedTimes = [...unitState.values()]
        .map((unit) => Date.parse(unit.observed_at || ""))
        .filter((value) => Number.isFinite(value));
      const updatedAt = observedTimes.length ? new Date(Math.max(...observedTimes)) : new Date();
      if (lastUpdate) {
        lastUpdate.hidden = false;
        lastUpdate.textContent = `Última atualização às ${clock.format(updatedAt)}`;
      }
    }
  }

  function updateVisualState() {
    updateProgress();
    renderProducts();
  }

  async function fetchGroup(group, version) {
    const existingController = activeControllers.get(group.key);
    existingController?.abort();
    const controller = new AbortController();
    activeControllers.set(group.key, controller);
    try {
      const params = new URLSearchParams({ q: currentQuery, store: group.slug });
      const response = await fetch(`/api/search/?${params.toString()}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
        credentials: "same-origin",
      });
      let payload = {};
      try { payload = await response.json(); } catch { payload = {}; }
      if (!response.ok) throw new Error(payload.error || "Não foi possível consultar esta unidade.");
      if (version !== searchVersion || controller.signal.aborted) return;
      if (!Array.isArray(payload.units)) throw new Error("A loja retornou uma resposta incompleta.");
      applyUnits(payload.units);
      for (const slug of group.slugs) {
        const unit = unitState.get(slug);
        if (unit?.status === "loading") {
          setUnitState({ ...unit, status: "error", issue: "A unidade não apareceu na resposta." });
        }
      }
    } catch (error) {
      if (error.name === "AbortError" || version !== searchVersion) return;
      for (const slug of group.slugs) {
        const unit = unitState.get(slug);
        if (unit) setUnitState({ ...unit, status: "error", offers: [], issue: error.message || "Verifique a conexão e tente de novo." });
      }
    } finally {
      if (activeControllers.get(group.key) === controller) activeControllers.delete(group.key);
      if (version === searchVersion) updateVisualState();
    }
  }

  function restoreCache(query) {
    const cached = responseCache.get(cacheKey(query));
    if (!cached || Date.now() - cached.savedAt > 120000) return false;
    resetUnits("idle");
    applyUnits(cached.units);
    searchStartedAt = performance.now() - cached.elapsed;
    updateVisualState();
    return true;
  }

  function saveCache(query) {
    if (responseCache.size > 20) responseCache.delete(responseCache.keys().next().value);
    responseCache.set(cacheKey(query), {
      savedAt: Date.now(),
      elapsed: performance.now() - searchStartedAt,
      units: [...unitState.values()].map((unit) => ({
        slug: unit.slug,
        status: unit.status,
        issue: unit.issue,
        observed_at: unit.observed_at || "",
        offers: unit.offers.map((offer) => ({ ...offer })),
      })),
    });
  }

  async function startSearch(value, options = {}) {
    const query = String(value || "").trim().slice(0, 255);
    if (!query) {
      input?.focus();
      return;
    }
    if (query === currentQuery && [...unitState.values()].some((unit) => unit.status === "loading")) return;
    cancelActiveSearches();
    const version = ++searchVersion;
    hasServerResults = false;
    currentQuery = query;
    if (input) input.value = query;
    updateInputControls();
    if (queryTitle) queryTitle.textContent = `Resultados para ${query}`;
    if (resultsSection) resultsSection.hidden = false;
    if (options.updateHistory !== false) updateLocation(query);
    if (options.remember !== false) rememberQuery(query);
    searchStartedAt = performance.now();
    if (lastUpdate) lastUpdate.hidden = true;
    partialMessage.hidden = true;
    emptyState.hidden = true;
    retryAllButton.hidden = true;

    if (restoreCache(query)) return;

    resetUnits("loading");
    progressNode.hidden = false;
    progressBar.style.width = "0%";
    updateVisualState();
    progressTimer = window.setInterval(updateProgress, 200);
    const groups = apiGroups();
    await Promise.allSettled(groups.map((group) => fetchGroup(group, version)));
    if (version !== searchVersion) return;
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = 0;
    updateVisualState();
    saveCache(query);
  }

  function retryGroup(group) {
    if (!group || !currentQuery) return;
    for (const slug of group.slugs) {
      const unit = unitState.get(slug);
      if (unit) setUnitState({ ...unit, status: "loading", issue: "", offers: [] });
    }
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = window.setInterval(updateProgress, 200);
    updateVisualState();
    const version = searchVersion;
    fetchGroup(group, version).then(() => {
      if (version !== searchVersion) return;
      if (doneCount() === unitState.size) {
        if (progressTimer) window.clearInterval(progressTimer);
        progressTimer = 0;
        updateVisualState();
        saveCache(currentQuery);
      }
    });
  }

  function buildProducts() {
    const products = new Map();
    for (const unit of unitState.values()) {
      for (const offer of unit.offers || []) {
        const gtin = String(offer.gtin || "").replace(/\D/g, "");
        const key = gtin ? `gtin:${gtin}` : `name:${normalizeText(offer.name)}:${offer.unit || ""}`;
        let product = products.get(key);
        if (!product) {
          product = { key, name: offer.name, gtin, unit: offer.unit || "", offers: new Map() };
          products.set(key, product);
        }
        const previous = product.offers.get(unit.slug);
        if (!previous || Number(offer.price) < Number(previous.price)) product.offers.set(unit.slug, offer);
        if (unit.is_reference) product.name = offer.name;
      }
    }
    const rows = [...products.values()].map((product) => {
      const offers = [...product.offers.entries()].map(([slug, offer]) => ({ slug, offer }));
      const ownEntry = offers.find(({ slug }) => unitState.get(slug)?.is_reference);
      const ownPrice = ownEntry ? Number(ownEntry.offer.price) : null;
      const validPrices = offers
        .filter(({ offer }) => !offer.is_multibuy && Number.isFinite(Number(offer.price)))
        .map(({ slug, offer }) => ({ slug, price: Number(offer.price), offer }));
      const minimum = validPrices.length > 1 ? Math.min(...validPrices.map((item) => item.price)) : null;
      const competitorPrices = validPrices.filter((item) => !unitState.get(item.slug)?.is_reference);
      const maxDifference = ownPrice === null || !competitorPrices.length
        ? null
        : Math.max(...competitorPrices.map((item) => Math.abs(item.price - ownPrice)));
      return { ...product, ownEntry, ownPrice, validPrices, minimum, maxDifference };
    });

    if (sortSelect?.value === "name") {
      rows.sort((left, right) => left.name.localeCompare(right.name, "pt-BR"));
    } else if (sortSelect?.value === "savings") {
      rows.sort((left, right) => (right.maxDifference ?? -1) - (left.maxDifference ?? -1));
    } else {
      rows.sort((left, right) => {
        const leftMin = left.validPrices.length ? Math.min(...left.validPrices.map((item) => item.price)) : Infinity;
        const rightMin = right.validPrices.length ? Math.min(...right.validPrices.map((item) => item.price)) : Infinity;
        return leftMin - rightMin || left.name.localeCompare(right.name, "pt-BR");
      });
    }

    const onlyAll = allUnitsCheckbox?.checked && doneCount() === unitState.size;
    const filtered = onlyAll ? rows.filter((product) => product.offers.size === unitState.size) : rows;
    return filtered;
  }

  function visibleUnits() {
    return [...unitState.values()].filter((unit) => {
      if (currentFilter === "marilia") return unit.location.toLocaleLowerCase("pt-BR").includes("marília");
      if (currentFilter === "competitors") return !unit.is_reference;
      return true;
    });
  }

  function productMeta(product) {
    const parts = [];
    if (product.gtin) parts.push(`EAN ${product.gtin}`);
    if (product.unit) parts.push(`Preço por ${product.unit}`);
    return parts.join(" · ") || "Código de barras não informado";
  }

  function lowestOffer(product) {
    if (product.minimum === null) return null;
    return product.validPrices.find((item) => Math.abs(item.price - product.minimum) < 0.005) || null;
  }

  function differenceLabel(offer, ownPrice) {
    if (ownPrice === null || !Number.isFinite(ownPrice)) return { text: "Referência indisponível", className: "" };
    const delta = Number((Number(offer.price) - ownPrice).toFixed(2));
    if (Math.abs(delta) < 0.005) return { text: "＝ Mesmo preço da sua loja", className: "is-same" };
    const amount = currency.format(Math.abs(delta));
    const ratio = percent.format(Math.abs(delta / ownPrice) * 100);
    if (delta < 0) return { text: `↓ ${amount} · ${ratio}% mais barato`, className: "is-cheaper" };
    return { text: `↑ ${amount} · ${ratio}% mais caro`, className: "is-costlier" };
  }

  function storeMark(unit) {
    const mark = node("span", "market-store-mark");
    if (unit.logo) {
      const image = node("img");
      image.src = unit.logo;
      image.alt = `Logo ${unit.name}`;
      image.width = 40;
      image.height = 40;
      image.loading = "lazy";
      mark.append(image);
    } else {
      mark.append(node("span", "", unit.name.slice(0, 1)));
    }
    return mark;
  }

  function appendDifference(row, offer, unit, product) {
    if (unit.is_reference) {
      row.append(node("span", "comparison-difference is-same", "Sua loja · referência"));
      return;
    }
    const result = differenceLabel(offer, product.ownPrice);
    const difference = node("span", `comparison-difference ${result.className}`, result.text);
    difference.setAttribute("aria-label", `${result.text} em relação ao Super Pompeia`);
    row.append(difference);
  }

  function retryButton(slug, label = "Tentar novamente") {
    const button = node("button", "", label);
    button.type = "button";
    button.dataset.retryStore = slug;
    return button;
  }

  function createComparisonRow(unit, product, lowest) {
    const row = node("div", `comparison-row${unit.is_reference ? " is-own" : ""}`);
    row.setAttribute("role", "listitem");
    const offer = product.offers.get(unit.slug);
    const store = node("div", "comparison-store");
    store.append(storeMark(unit));
    const storeCopy = node("div", "comparison-store-copy");
    storeCopy.append(node("strong", "", unit.name), node("span", "", unit.location));
    if (unit.is_reference) storeCopy.append(node("span", "market-tag market-tag-blue", "Sua loja"));
    store.append(storeCopy);
    row.append(store);

    if (offer) {
      const price = node("div", "comparison-price");
      const priceStrong = node("strong", "", currency.format(Number(offer.price)));
      if (lowest && lowest.slug === unit.slug) priceStrong.append(" ", node("span", "product-lowest-tag", "Menor preço"));
      price.append(priceStrong);
      if (offer.unit) price.append(node("small", "", `por ${offer.unit}`));
      if (offer.club_price) price.append(node("span", "comparison-price-extra", `No clube ${currency.format(Number(offer.club_price))}`));
      if (offer.condition_detail) price.append(node("small", "comparison-price-extra", offer.condition_detail));
      row.append(price);
      appendDifference(row, offer, unit, product);
      const link = node("a", "comparison-link", "Ver na loja ↗");
      link.href = offer.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Ver ${offer.name} no ${unit.name}, ${unit.location}`);
      row.append(link);
      row.append(node("span", "comparison-status", offer.availability));
      return row;
    }

    if (unit.status === "loading" || unit.status === "idle") {
      row.append(node("span", "comparison-pending", "Consultando esta unidade…"));
    } else if (unit.status === "error" || unit.status === "partial") {
      row.append(node("span", "comparison-error", unit.issue || "Não foi possível consultar."));
      row.append(retryButton(unit.slug));
    } else {
      row.append(node("span", "comparison-no-result", "Produto não localizado"));
    }
    return row;
  }

  function createProductCard(product, index) {
    const card = node("article", "product-card");
    const header = node("header", "product-card-head");
    const title = node("div", "product-card-title");
    title.append(node("h3", "", product.name), node("p", "", productMeta(product)));
    header.append(title);
    const tools = node("div", "product-card-tools");
    const lowest = lowestOffer(product);
    if (lowest) tools.append(node("span", "product-lowest-tag", "Menor preço"));
    const copy = node("button", "market-copy-button", "Copiar resumo");
    copy.type = "button";
    copy.dataset.copyProduct = String(index);
    tools.append(copy);
    header.append(tools);
    card.append(header);
    const list = node("div", "product-offer-list");
    list.setAttribute("role", "list");
    for (const unit of visibleUnits()) list.append(createComparisonRow(unit, product, lowest));
    card.append(list);
    return card;
  }

  function appendTablePrice(cell, unit, product, lowest) {
    const offer = product.offers.get(unit.slug);
    if (offer) {
      const isLowest = lowest?.slug === unit.slug;
      cell.append(node("strong", "", currency.format(Number(offer.price))));
      if (offer.unit) cell.append(node("small", "", `por ${offer.unit}`));
      if (isLowest) cell.append(node("small", "product-lowest-tag", "Menor preço"));
      if (unit.is_reference) cell.append(node("small", "", "Sua loja · referência"));
      else if (product.ownPrice !== null) cell.append(node("small", "", differenceLabel(offer, product.ownPrice).text));
      if (offer.club_price) cell.append(node("small", "", `No clube ${currency.format(Number(offer.club_price))}`));
      return;
    }
    const status = unitState.get(unit.slug);
    if (status.status === "loading" || status.status === "idle") cell.append(node("small", "", "Consultando…"));
    else if (status.status === "error" || status.status === "partial") cell.append(node("small", "comparison-error", "Falha na consulta"));
    else cell.append(node("small", "", "Não localizado"));
  }

  function renderTable(products) {
    const visible = visibleUnits();
    const wrapper = node("div", "table-scroll");
    const table = node("table", "comparison-table");
    const head = node("thead");
    const headerRow = node("tr");
    headerRow.append(node("th", "", "Produto"));
    for (const unit of visible) headerRow.append(node("th", unit.is_reference ? "table-own" : "", `${unit.name} · ${unit.location}`));
    head.append(headerRow);
    const body = node("tbody");
    products.forEach((product) => {
      const row = node("tr");
      const productCell = node("th");
      productCell.append(node("strong", "", product.name), node("small", "", productMeta(product)));
      row.append(productCell);
      const lowest = lowestOffer(product);
      for (const unit of visible) {
        const cell = node("td", unit.is_reference ? "table-own" : "");
        appendTablePrice(cell, unit, product, lowest);
        row.append(cell);
      }
      body.append(row);
    });
    table.append(head, body);
    wrapper.append(table);
    return wrapper;
  }

  function renderSkeletons() {
    for (let index = 0; index < 3; index += 1) productsNode.append(node("div", "market-skeleton"));
  }

  function renderEmptyState(products, done) {
    emptyState.replaceChildren();
    const errors = failedUnits();
    if (done < unitState.size) {
      emptyState.hidden = true;
      return;
    }
    if (errors.length === unitState.size) {
      emptyState.append(node("strong", "", "Nenhuma unidade respondeu."));
      emptyState.append(document.createTextNode("Confira sua conexão e tente consultar novamente."));
      const retry = node("button", "", "Tentar novamente");
      retry.type = "button";
      retry.dataset.retryAllEmpty = "true";
      emptyState.append(retry);
      emptyState.hidden = false;
      return;
    }
    if (!products.length) {
      emptyState.append(node("strong", "", "Nenhum produto encontrado."));
      emptyState.append(document.createTextNode("Tente remover palavras ou buscar pelo código de barras."));
      emptyState.hidden = false;
      return;
    }
    emptyState.hidden = true;
  }

  function renderProducts() {
    if (!productsNode || !currentQuery) return;
    productsNode.replaceChildren();
    const done = doneCount();
    currentProducts = buildProducts();
    renderEmptyState(currentProducts, done);
    const errors = failedUnits();
    if (partialMessage) {
      partialMessage.hidden = errors.length === 0 || done !== unitState.size;
      partialMessage.textContent = errors.length
        ? "Algumas unidades não responderam. Os preços recebidos continuam disponíveis; você pode tentar de novo em cada unidade."
        : "";
    }
    if (retryAllButton) retryAllButton.hidden = errors.length === 0 || done !== unitState.size;
    if (!currentProducts.length) {
      if (done < unitState.size) renderSkeletons();
      return;
    }
    if (currentView === "table") {
      productsNode.append(renderTable(currentProducts));
      return;
    }
    currentProducts.forEach((product, index) => productsNode.append(createProductCard(product, index)));
  }

  function setFilter(filter) {
    currentFilter = filter;
    for (const button of document.querySelectorAll("[data-market-filter]")) {
      const selected = button.dataset.marketFilter === filter;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    }
    renderProducts();
  }

  function resetSearch(updateUrl = true) {
    cancelActiveSearches();
    searchVersion += 1;
    hasServerResults = false;
    currentQuery = "";
    if (input) input.value = "";
    if (updateUrl) updateLocation("", "replaceState");
    updateInputControls();
    resetUnits("idle");
    if (resultsSection) resultsSection.hidden = true;
    if (overallStatus) overallStatus.textContent = `${unitState.size} unidades`;
    if (headerStatus) delete headerStatus.dataset.state;
    if (lastUpdate) lastUpdate.hidden = true;
    setSearchBusy(false);
  }

  async function copyProduct(index, button) {
    const product = currentProducts[index];
    if (!product) return;
    const lines = [`${product.name}${product.gtin ? ` (EAN ${product.gtin})` : ""}`];
    for (const unit of unitState.values()) {
      const offer = product.offers.get(unit.slug);
      if (offer) lines.push(`${unit.name} · ${unit.location}: ${currency.format(Number(offer.price))}${offer.unit ? ` / ${offer.unit}` : ""}`);
    }
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      button.textContent = "Copiado";
      window.setTimeout(() => { if (button.isConnected) button.textContent = "Copiar resumo"; }, 1600);
    } catch {
      const textArea = node("textarea", "market-sr-only");
      textArea.value = lines.join("\n");
      document.body.append(textArea);
      textArea.select();
      document.execCommand("copy");
      textArea.remove();
      button.textContent = "Copiado";
      window.setTimeout(() => { if (button.isConnected) button.textContent = "Copiar resumo"; }, 1600);
    }
  }

  function initializeFromServer() {
    const script = document.querySelector("#initial-results");
    if (!script) return;
    let initial = [];
    try { initial = JSON.parse(script.textContent || "[]"); } catch { initial = []; }
    if (!Array.isArray(initial) || !initial.length) return;
    applyUnits(initial);
    currentQuery = input?.value.trim() || new URL(window.location.href).searchParams.get("q") || "";
    if (!currentQuery) return;
    hasServerResults = true;
    const serverElapsed = Number(resultsSection?.dataset.initialElapsed || 0);
    searchStartedAt = performance.now() - (Number.isFinite(serverElapsed) ? serverElapsed * 1000 : 0);
    if (queryTitle) queryTitle.textContent = `Resultados para ${currentQuery}`;
    if (resultsSection) resultsSection.hidden = false;
    if (resultMeta) resultMeta.textContent = `${buildProducts().length} produtos · Consulta carregada`;
    updateVisualState();
    rememberQuery(currentQuery);
    if (lastUpdate) {
      lastUpdate.hidden = false;
      lastUpdate.textContent = `Última atualização às ${clock.format(new Date())}`;
    }
  }

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    startSearch(input?.value || "");
  });

  input?.addEventListener("input", updateInputControls);
  clearButton?.addEventListener("click", () => {
    resetSearch();
    input?.focus();
  });

  recentList?.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove-recent]");
    if (remove) {
      event.preventDefault();
      recent = recent.filter((item) => item !== remove.dataset.removeRecent);
      saveRecent();
      renderRecent();
      return;
    }
    const link = event.target.closest("[data-recent-query]");
    if (link) {
      event.preventDefault();
      startSearch(link.dataset.recentQuery);
    }
  });

  document.querySelector("[data-clear-recent]")?.addEventListener("click", () => {
    recent = [];
    saveRecent();
    renderRecent();
  });

  examplesSection?.addEventListener("click", (event) => {
    const link = event.target.closest("[data-search-example]");
    if (!link) return;
    event.preventDefault();
    startSearch(new URL(link.href).searchParams.get("q") || link.textContent);
  });

  unitCards.forEach((card) => {
    card.querySelector("[data-retry-store]")?.addEventListener("click", () => retryGroup(groupForSlug(card.dataset.storeSlug)));
  });

  productsNode?.addEventListener("click", (event) => {
    const retry = event.target.closest("[data-retry-store]");
    if (retry) {
      retryGroup(groupForSlug(retry.dataset.retryStore));
      return;
    }
    const copy = event.target.closest("[data-copy-product]");
    if (copy) copyProduct(Number(copy.dataset.copyProduct), copy);
  });

  retryAllButton?.addEventListener("click", () => {
    const badSlugs = new Set(failedUnits().map((unit) => unit.slug));
    const failedGroups = apiGroups().filter((group) => group.slugs.some((slug) => badSlugs.has(slug)));
    for (const group of failedGroups) retryGroup(group);
  });

  emptyState?.addEventListener("click", (event) => {
    if (event.target.closest("[data-retry-all-empty]")) retryAllButton?.click();
  });

  document.querySelectorAll("[data-market-filter]").forEach((button) => {
    button.addEventListener("click", () => setFilter(button.dataset.marketFilter));
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      currentView = button.dataset.view;
      for (const toggle of document.querySelectorAll("[data-view]")) {
        toggle.setAttribute("aria-pressed", String(toggle === button));
      }
      productsNode.dataset.view = currentView;
      renderProducts();
    });
  });

  sortSelect?.addEventListener("change", renderProducts);
  allUnitsCheckbox?.addEventListener("change", renderProducts);

  document.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    const isEditing = active?.matches("input, textarea, select, [contenteditable='true']");
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !isEditing) {
      event.preventDefault();
      input?.focus();
    }
    if (event.key === "Escape" && active === input) {
      event.preventDefault();
      resetSearch();
      input?.blur();
    }
  });

  window.addEventListener("popstate", () => {
    const query = new URL(window.location.href).searchParams.get("q") || "";
    if (input) input.value = query;
    updateInputControls();
    if (query) startSearch(query, { updateHistory: false, remember: false });
    else resetSearch(false);
  });

  renderRecent();
  updateInputControls();
  initializeFromServer();
  if (currentQuery && !hasServerResults) {
    startSearch(currentQuery, { updateHistory: false, remember: false });
  } else {
    window.setTimeout(() => input?.focus({ preventScroll: true }), 0);
  }
})();

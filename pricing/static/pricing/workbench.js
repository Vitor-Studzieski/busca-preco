const searchInput = document.getElementById('product-query');
if (searchInput) {
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target.closest('input, textarea, select, [contenteditable]')) return;
    event.preventDefault();
    searchInput.focus();
  });

  const suggestions = document.getElementById('product-suggestions');
  let suggestionTimer;
  let pending;
  searchInput.addEventListener('input', () => {
    clearTimeout(suggestionTimer);
    if (pending) pending.abort();
    suggestions.replaceChildren();
    const query = searchInput.value.trim();
    if (query.length < 2) return;
    suggestionTimer = setTimeout(async () => {
      pending = new AbortController();
      const url = new URL(searchInput.dataset.suggestions, location.origin);
      url.searchParams.set('q', query);
      try {
        const response = await fetch(url, {signal: pending.signal});
        if (!response.ok) return;
        const data = await response.json();
        if (searchInput.value.trim() !== query) return;
        for (const item of data.items) {
          const option = document.createElement('option');
          option.value = item.value;
          option.label = item.label;
          suggestions.append(option);
        }
      } catch {
        // A busca pelo campo principal continua disponível.
      }
    }, 220);
  });
}

const liveForm = document.querySelector('[data-live-search]');
if (liveForm) {
  const general = document.querySelector('[data-update-status]');
  const cards = new Map(Array.from(document.querySelectorAll('[data-store]'), (el) => [Number(el.dataset.store), el]));
  const busy = new Set();
  const currency = new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'});
  const clock = new Intl.DateTimeFormat('pt-BR', {dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo'});

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function link(offer) {
    const anchor = element('a', offer.name);
    const target = new URL(offer.url);
    if (target.protocol !== 'https:') return element('span', offer.name);
    anchor.href = target.href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    return anchor;
  }

  function show(row) {
    const card = cards.get(row.store);
    if (!card) return;
    const status = card.querySelector('[data-store-state]');
    const parts = [row.label];
    if (row.observed_at) parts.push(clock.format(new Date(row.observed_at)));
    if (row.reason) parts.push(row.reason);
    status.textContent = parts.join(' · ');
    status.dataset.state = row.state;
    const list = card.querySelector('[data-offers]');
    if (!row.offers?.length && !row.unpriced?.length) {
      if (!['pending', 'running'].includes(row.state) && list.children.length) {
        status.textContent += ' · Exibindo a última coleta confirmada';
      }
      return;
    }
    list.replaceChildren();
    for (const offer of row.offers || []) {
      const item = element('li', '', 'market-offer');
      const info = element('div');
      info.append(link(offer), element('small', [offer.condition, offer.availability].join(' · ')));
      const price = element('div', '', 'market-price');
      price.append(element('strong', currency.format(Number(offer.price)) + (offer.unit ? '/' + offer.unit : ''), 'money'));
      if (offer.club) price.append(element('small', 'Clube · ' + currency.format(Number(offer.club))));
      item.append(info, price);
      list.append(item);
    }
    for (const offer of row.unpriced || []) {
      const item = element('li');
      item.append(link(offer), element('small', 'Sem preço confirmado'));
      list.append(item);
    }
  }

  async function update(store) {
    const targets = store ? [store] : [...cards.keys()];
    if (targets.some((id) => busy.has(id))) return;
    for (const id of targets) {
      busy.add(id);
      show({store: id, label: 'Aguardando atualização', state: 'pending'});
      cards.get(id).querySelector('[data-retry]').disabled = true;
    }
    liveForm.querySelector('button').disabled = true;
    const form = new FormData(liveForm);
    if (store) form.set('store', store);
    general.textContent = '';
    try {
      const response = await fetch(liveForm.action, {method: 'POST', body: form});
      if (response.redirected) {
        location.assign(response.url);
        return;
      }
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.message);
      }
      const job = await response.json();
      const progress = new URL(liveForm.dataset.progress, location.origin);
      progress.searchParams.set('token', job.token);
      for (let i = 0; i < 60; i += 1) {
        const result = await fetch(progress);
        if (result.redirected) {
          location.assign(result.url);
          return;
        }
        if (!result.ok) throw new Error('O acompanhamento da coleta ficou indisponível.');
        const current = await result.json();
        current.rows.forEach(show);
        if (current.complete) return;
        await new Promise((resolve) => setTimeout(resolve, 1250));
      }
      general.textContent = 'A coleta continua na fila. Reabra a busca para ver os resultados disponíveis.';
    } catch (error) {
      general.textContent = error.message || 'Não foi possível agendar a coleta.';
      for (const id of targets) show({store: id, label: 'Atualização indisponível', state: 'error'});
    } finally {
      for (const id of targets) {
        busy.delete(id);
        cards.get(id).querySelector('[data-retry]').disabled = false;
      }
      liveForm.querySelector('button').disabled = busy.size > 0;
    }
  }

  liveForm.addEventListener('submit', (event) => {
    event.preventDefault();
    update(null);
  });
  document.querySelectorAll('[data-retry]').forEach((button) => {
    button.addEventListener('click', () => update(Number(button.dataset.retry)));
  });
  if ([...cards.values()].some((card) => card.dataset.cached !== '1')) update(null);
}

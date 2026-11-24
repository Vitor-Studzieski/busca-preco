document.querySelectorAll('img[data-store-logo]').forEach((image) => {
  const fallback = image.nextElementSibling;
  const showFallback = () => {
    image.hidden = true;
    if (fallback?.classList.contains('store-mark')) fallback.hidden = false;
  };
  if (image.complete && !image.naturalWidth) showFallback();
  else image.addEventListener('error', showFallback, {once: true});
});

const searchInput = document.getElementById('product-query');
if (searchInput) {
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target.closest('input, textarea, select, [contenteditable]')) return;
    event.preventDefault();
    searchInput.focus();
  });

  if (!searchInput.value && matchMedia("(min-width: 771px)").matches) searchInput.focus({preventScroll: true});
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
    let target;
    try { target = new URL(offer.url); }
    catch { return element('span', offer.name); }
    if (target.protocol !== 'https:') return element('span', offer.name);
    anchor.href = target.href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    return anchor;
  }

  const filter = document.querySelector('[data-promotion-filter]');

  function applyFilter(card) {
    const list = card.querySelector('[data-offers]');
    const offers = [...list.children];
    for (const offer of offers) offer.hidden = filter.checked && !offer.hasAttribute('data-promotional');
    card.querySelector('[data-filter-empty]').hidden = !filter.checked || !offers.length || offers.some((offer) => !offer.hidden);
  }

  function show(row) {
    const card = cards.get(row.store);
    if (!card) return;
    const status = card.querySelector('[data-store-state]');
    const detail = card.querySelector('[data-store-detail]');
    const date = card.querySelector('[data-store-time]');
    const list = card.querySelector('[data-offers]');
    const empty = card.querySelector('[data-empty]');
    const inProgress = ['pending', 'running'].includes(row.state);
    status.textContent = row.label;
    status.dataset.state = row.state;
    card.setAttribute('aria-busy', String(inProgress));
    if (row.observed_at) date.textContent = clock.format(new Date(row.observed_at));
    detail.textContent = row.reason || '';
    if (row.offers?.length) {
      list.replaceChildren();
      for (const offer of row.offers) {
        const item = element('li', '', 'offer-row');
        if (offer.club || ['Promoção', 'Clube'].includes(offer.condition)) item.setAttribute('data-promotional', '');
        const info = element('div', '', 'offer-copy');
        info.append(link(offer), element('small', [offer.condition, offer.availability].join(' · ')));
        const price = element('div', '', 'offer-price');
        price.append(element('strong', currency.format(Number(offer.price)) + (offer.unit ? '/' + offer.unit : ''), 'money'));
        if (offer.club) price.append(element('small', 'Clube · ' + currency.format(Number(offer.club))));
        item.append(info, price);
        list.append(item);
      }
    } else if (!inProgress && list.children.length) {
      const note = 'Exibindo a última coleta confirmada.';
      detail.textContent = detail.textContent ? detail.textContent + ' ' + note : note;
    }
    if (row.unpriced?.length && !list.children.length) {
      list.replaceChildren();
      for (const offer of row.unpriced) {
        const item = element('li', '', 'offer-row');
        item.append(link(offer), element('small', 'Sem preço confirmado'));
        list.append(item);
      }
    }
    empty.hidden = Boolean(list.children.length);
    empty.textContent = inProgress ? 'Consultando esta unidade…' :
      row.state === 'missing' ? 'Tente buscar pela marca e pela embalagem.' : 'Nenhum preço confirmado nesta atualização.';
    applyFilter(card);
  }

  filter.addEventListener('change', () => cards.forEach(applyFilter));

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
      for (let i = 0; i < 60; i += 1) {
        const result = await fetch(progress, {headers: {'X-Collection-Ticket': job.token}});
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

const proposal = document.querySelector('[data-price-proposal]');
if (proposal) {
  const amountField = proposal.querySelector('#proposal-amount');
  const output = proposal.querySelector('[data-proposal-preview]');
  const sources = JSON.parse(document.getElementById('proposal-sources').textContent);
  const money = new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'});
  amountField.addEventListener('input', () => {
    const entered = amountField.value.trim();
    const amount = Number(entered.includes(',') ? entered.replaceAll('.', '').replace(',', '.') : entered);
    output.hidden = !(amount > 0 && sources.length);
    if (!output.hidden) {
      output.textContent = sources.map((item) => {
        const difference = Number(item.amount) - amount;
        const percentage = (100 * difference / amount).toLocaleString('pt-BR', {maximumFractionDigits: 1});
        return item.label + ' · ' + money.format(difference) + ' (' + percentage + '%)';
      }).join('\n');
    }
  });
}
const chart = document.querySelector('[data-price-chart]');
if (chart) {
  const series = JSON.parse(document.getElementById('price-history-data').textContent);
  const colors = ['#123d77', '#156a4b', '#913890', '#996319', '#ac3943'];
  const points = series.flatMap((line) => line.points);
  const times = points.map((point) => point[0]);
  const amounts = points.map((point) => Number(point[1]));
  const start = Math.min(...times), end = Math.max(...times);
  const low = Math.min(...amounts), high = Math.max(...amounts);
  const legend = document.createElement('ul');
  legend.className = 'chart-legend';
  series.forEach((line, index) => {
    const item = document.createElement('li');
    item.textContent = line.label;
    item.dataset.series = index;
    legend.append(item);
  });
  chart.after(legend);
  const currency = new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'});
  function draw() {
    const width = chart.offsetWidth, height = chart.offsetHeight;
    if (!width || !height) return;
    chart.width = width * devicePixelRatio;
    chart.height = height * devicePixelRatio;
    const ctx = chart.getContext('2d');
    ctx.scale(devicePixelRatio, devicePixelRatio);
    ctx.font = '11px system-ui';
    const bar = 79, right = 21, top = 19, bottom = 25;
    ctx.strokeStyle = '#dde5ef';
    ctx.fillStyle = '#52647a';
    for (const [y, value] of [[top, high], [height-bottom, low]]) {
      ctx.fillText(currency.format(value), 12, y+4);
      ctx.beginPath();
      ctx.moveTo(bar, y);
      ctx.lineTo(width-right, y);
      ctx.stroke();
    }
    series.forEach((line, index) => {
      ctx.strokeStyle = ctx.fillStyle = colors[index % colors.length];
      ctx.lineWidth = 2;
      const positions = line.points.map(([time, amount]) => [
        start === end ? width / 2 : bar + (time - start) * (width - right - bar) / (end - start),
        low === high ? height / 2 : height - bottom - (amount - low) * (height - top - bottom) / (high - low),
      ]);
      ctx.beginPath();
      positions.forEach(([x, y], i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y));
      ctx.stroke();
      positions.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x,y,3,0,Math.PI*2);
        ctx.fill();
      });
    });
  }
  new ResizeObserver(draw).observe(chart);
}

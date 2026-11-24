const searchForm = document.querySelector('[data-market-search]');
if (searchForm) {
  const status = searchForm.querySelector('.search-status');
  const submit = searchForm.querySelector('button[type="submit"]');

  searchForm.addEventListener('submit', () => {
    status.textContent = 'Consultando os sites dos supermercados…';
    submit.disabled = true;
  });

  window.addEventListener('pageshow', () => {
    status.textContent = '';
    submit.disabled = false;
  });
}

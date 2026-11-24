from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

from .confianca import confianca_search_entries
from .extract import ProductPage, clean_text
from .http import (
    CollectionError,
    fetch_html,
    split_storefront_url,
    storefront_config,
    validate_product_url,
    validate_store_url,
)

SEARCH_PATHS = {
    "lider": ("/busca", "q", "page"),
    "tauste": ("/catalogsearch/result/", "q", "p"),
    "confianca": ("/search", "Ntt", "page"),
}


@dataclass(frozen=True)
class SearchPage:
    entries: tuple[tuple[str, str], ...]
    has_next: bool = False


def search_catalog(retailer, store_url, term, *, page_number=1):
    """Return the product links and pagination visible in one public search page."""
    store_url = validate_store_url(retailer, store_url)
    store = urlsplit(store_url)
    store_path = store.path.rstrip("/")
    suffix, field, page_field = SEARCH_PATHS[retailer]
    search_path = store_path + suffix
    parameters = {field: term}
    if retailer == "confianca":
        parameters["Nrpp"] = "16"
    if page_number > 1:
        parameters[page_field] = str(page_number)
    search_url = urlunsplit((store.scheme, store.netloc, search_path, urlencode(parameters), ""))
    hosts, _, _ = storefront_config(retailer)

    def validate_url(url):
        parts = split_storefront_url(url, hosts)
        path = parts.path.rstrip("/")
        query = parse_qs(parts.query)
        # Tauste may return the city's homepage when no results are available.
        if retailer == "tauste" and path == store_path and not query:
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if (path != search_path.rstrip("/") or query.get(field) != [term]
                or query.get(page_field, ["1"]) != [str(page_number)]):
            raise CollectionError("O site não confirmou a busca na unidade selecionada.")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(parameters), ""))

    html, final_url = fetch_html(search_url, validate_url)
    if urlsplit(final_url).path.rstrip("/") == store_path:
        return SearchPage(())

    if retailer == "confianca":
        entries, has_next = confianca_search_entries(html, final_url)
    else:
        page = ProductPage(html)
        expected_title = "resultados para" if retailer == "lider" else "resultados da busca"
        if expected_title not in clean_text(" ".join(page.title)).casefold():
            raise CollectionError("O site não apresentou sua página de resultados.")
        links = page.product_links if retailer == "tauste" else page.links
        entries = [(link, page.link_names.get(link, "")) for link in links]
        has_next = False
        for link in page.links:
            try:
                parsed = urlsplit(urljoin(final_url, link))
                params = parse_qs(parsed.query)
            except ValueError:
                continue
            if (parsed.netloc.lower() in hosts and parsed.path.rstrip("/") == search_path.rstrip("/")
                    and params.get(field) == [term] and params.get(page_field) == [str(page_number + 1)]):
                has_next = True
                break

    results = []
    seen = set()
    for link, name in entries:
        try:
            url = validate_product_url(retailer, store_url, urljoin(final_url, link))
        except ValueError:
            continue
        path = urlsplit(url).path.rstrip("/")
        if path in seen:
            continue
        seen.add(path)
        slug = unquote(path.rsplit("/", 1)[-1]).removesuffix(".html")
        results.append((url, clean_text(name)[:300] or slug))
    return SearchPage(tuple(results), has_next)

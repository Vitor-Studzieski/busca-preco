from functools import partial
import re
from urllib.parse import urljoin, urlsplit

from .confianca import confianca_product_routes
from .extract import ProductPage
from .http import CollectionError, fetch_html, validate_product_url, validate_store_url


MAX_DISCOVERY_LINKS = 100
TAUSTE_PRODUCT_SLUG = re.compile(r"[0-9]+-[a-zA-Z0-9_-]+\.html")


def discover_product_urls(retailer: str, store_url: str, limit: int) -> list[str]:
    """Find product links shown on the unit's public home page."""
    if type(limit) is not int or not 1 <= limit <= MAX_DISCOVERY_LINKS:
        raise CollectionError(f"O limite deve ser entre 1 e {MAX_DISCOVERY_LINKS} produtos.")
    store_url = validate_store_url(retailer, store_url)
    store_path = urlsplit(store_url).path.removesuffix("/")
    html, final_url = fetch_html(
        store_url, partial(validate_store_url, retailer, store_path=store_path)
    )
    if retailer == "confianca":
        links = confianca_product_routes(html, final_url)
    else:
        links = ProductPage(html).links

    products = []
    seen_paths = set()
    for link in links:
        if not isinstance(link, str) or not link.strip() or link.startswith(("#", "?")):
            continue
        try:
            url = validate_product_url(retailer, store_url, urljoin(final_url, link))
        except ValueError:
            continue
        path = urlsplit(url).path.removesuffix("/")
        if retailer == "tauste" and not TAUSTE_PRODUCT_SLUG.fullmatch(path.rsplit("/", 1)[-1]):
            continue
        if path in seen_paths:
            continue
        seen_paths.add(path)
        products.append(url)
        if len(products) == limit:
            break
    return products

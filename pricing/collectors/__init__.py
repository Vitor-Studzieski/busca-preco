from functools import partial

from .discovery import MAX_DISCOVERY_LINKS, discover_product_urls
from .extract import CollectedOffer, parse_offer
from .http import CollectionError, fetch_html, validate_product_url

__all__ = [
    "MAX_DISCOVERY_LINKS",
    "CollectedOffer",
    "CollectionError",
    "collect_offer",
    "discover_product_urls",
    "validate_product_url",
]


def collect_offer(retailer: str, store_url: str, product_url: str) -> CollectedOffer:
    """Read an already identified product page from a public storefront."""
    validator = partial(validate_product_url, retailer, store_url)
    html, final_url = fetch_html(product_url, validator)
    return parse_offer(retailer, html, final_url)

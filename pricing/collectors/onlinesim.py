import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit, urlunsplit

from .extract import CollectedOffer, clean_text
from .http import CollectionError, fetch_json, split_storefront_url, validate_product_url, validate_store_url

STORE_HOSTS = {"onlinesim.com.br", "www.onlinesim.com.br"}
STORE_ID = re.compile(r"[0-9]{1,12}")


def search_pompeia_catalog(store_url: str, external_id: str, term: str):
    """Search the public online catalog for the configured Pompéia unit."""
    store_url = validate_store_url("pompeia", store_url)
    if not STORE_ID.fullmatch(str(external_id or "")):
        raise CollectionError("A unidade da Pompéia não está configurada corretamente.")
    term = clean_text(term)[:255]
    if not term:
        return ()

    store = urlsplit(store_url)
    endpoint = urlunsplit((store.scheme, store.netloc,
                           f"{store.path.rstrip('/')}/api/user/v1.04/findProduct", "", ""))

    def validate_api_url(url):
        parts = split_storefront_url(url, STORE_HOSTS)
        if (parts.path != urlsplit(endpoint).path or parts.query or parts.fragment):
            raise CollectionError("A busca precisa permanecer na API pública da Pompéia.")
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))

    response = fetch_json(
        endpoint,
        validate_api_url,
        body={"name": term},
        headers={
            "store": str(external_id),
            "isu": "0",
            "platform": "1",
            "version": "v2.7.2",
            "Origin": "https://onlinesim.com.br",
            "Referer": store_url.rstrip("/") + "/",
        },
    )
    if response.get("cod") != 100 or not isinstance(response.get("return"), dict):
        raise CollectionError("A Pompéia não conseguiu concluir esta busca.")

    result = response["return"]
    products = []
    for key in ("products", "offers_elf"):
        rows = result.get(key, [])
        if isinstance(rows, list):
            products.extend(row for row in rows if isinstance(row, dict))

    offers = []
    seen = set()
    for product in products:
        offer = _parse_product(product, store_url, term)
        if offer is None or offer.external_code in seen:
            continue
        seen.add(offer.external_code)
        offers.append(offer)
    return tuple(offers)


def _price(value):
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return price if price.is_finite() and price > 0 else None


def _parse_product(product, store_url, term):
    name = clean_text(product.get("name"))[:300]
    sku = clean_text(product.get("sku"))[:100]
    barcode = clean_text(product.get("barcode"))[:32]
    price = _price(product.get("price"))
    if not name or not sku or price is None:
        return None

    condition = "regular"
    club_price = None
    condition_details = []
    current_offer = product.get("offer")
    if isinstance(current_offer, dict):
        offer_price = _price(current_offer.get("offer_price"))
        connect_price = _price(current_offer.get("offer_connect"))
        is_club = current_offer.get("is_offer_club") == 1
        if connect_price and (current_offer.get("is_offer_unlimited") == 1
                              or _price(current_offer.get("amount_connect"))):
            offer_price = connect_price
            condition_details.append("Oferta por quantidade")
        if offer_price and offer_price < price:
            if is_club:
                condition = "club"
                club_price = offer_price
            else:
                condition = "promotion"
                price = offer_price
                if not condition_details:
                    condition_details.append("Ative e pague")

    # The catalog still lists prices for products sold only at the physical store.
    # It does not expose stock counts, so availability remains unknown.
    if product.get("is_sale") == 0:
        condition_details.append("Exclusivo da loja física")

    path = f"details/{barcode}" if barcode.isdigit() else f"search/{quote(term, safe='')}"
    product_url = f"{store_url.rstrip('/')}/{path}"
    try:
        product_url = validate_product_url("pompeia", store_url, product_url)
    except CollectionError:
        return None

    return CollectedOffer(
        external_code=sku,
        name=name,
        price=price,
        condition=condition,
        availability="unknown",
        gtin=barcode if barcode.isdigit() else "",
        url=product_url,
        club_price=club_price,
        price_unit="kg" if product.get("is_kg") == 1 else "",
        condition_detail=" · ".join(condition_details),
    )

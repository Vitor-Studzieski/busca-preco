import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlsplit

from .extract import CollectedOffer, clean_text, extract_code, extract_gtin, extract_price
from .http import CONFIANCA_PRODUCT_PATH, CollectionError

STATE_PREFIX = re.compile(r"\bwindow\.state\s*=\s*JSON\.parse\(\s*decodeURI\(\s*")
PUBLIC_LIST = "DefaultPriceListEsmeralda"
CLUB_LIST = "ClubPriceListEsmeralda"


def read_page_state(html: str, url: str) -> tuple[dict, dict]:
    match = STATE_PREFIX.search(html)
    if match is None:
        raise CollectionError("A página do Confiança não apresentou o catálogo esperado.")
    try:
        encoded, end = json.JSONDecoder().raw_decode(html, match.end())
        if not isinstance(encoded, str) or not re.match(r"\s*\)\s*\)", html[end : end + 32]):
            raise ValueError
        state = json.loads(unquote(encoded, errors="strict"), parse_float=Decimal)
    except (ValueError, RecursionError) as error:
        raise CollectionError("O catálogo do Confiança está em um formato inesperado.") from error

    client = state.get("clientRepository") if isinstance(state, dict) else None
    context = client.get("context") if isinstance(client, dict) else None
    global_context = context.get("global") if isinstance(context, dict) else None
    expected_context = {
        "site": "ConfiancaEsmeralda",
        "priceListGroup": PUBLIC_LIST,
        "currencyCode": "BRL",
        "path": urlsplit(url).path.rstrip("/"),
    }
    if not isinstance(global_context, dict) or any(
        global_context.get(key) != value for key, value in expected_context.items()
    ):
        raise CollectionError("A página não confirmou a praça e a lista de preços do Confiança Esmeralda.")
    return state, context


def read_catalog(html: str, url: str, *, product_id: str = "") -> dict:
    state, context = read_page_state(html, url)
    if product_id:
        request_context = context.get("request")
        if not isinstance(request_context, dict) or request_context.get("productId") != product_id:
            raise CollectionError("O catálogo não confirmou o produto solicitado no Confiança.")

    catalog = state.get("catalogRepository") if isinstance(state, dict) else None
    if not isinstance(catalog, dict) or not all(
        isinstance(catalog.get(section), dict) for section in ("products", "skus")
    ):
        raise CollectionError("O catálogo do Confiança não apresentou produtos e SKUs.")
    return catalog


def confianca_product_routes(html: str, url: str) -> list[str]:
    catalog = read_catalog(html, url)
    routes = []
    for product_id, product in catalog["products"].items():
        if not isinstance(product, dict) or product.get("id") != product_id:
            continue
        route = product.get("route")
        match = CONFIANCA_PRODUCT_PATH.fullmatch(route) if isinstance(route, str) else None
        if match is None or match[2] != product_id:
            continue
        routes.append(f"/marilia/{route}")
    return routes


def confianca_search_entries(html: str, url: str) -> tuple[list[tuple[str, str]], bool]:
    state, context = read_page_state(html, url)
    request = context.get("request", {})
    search_path = request.get("search") if isinstance(request, dict) else None
    repository = state.get("searchRepository")
    pages = repository.get("pages") if isinstance(repository, dict) else None
    if not isinstance(pages, dict) or not isinstance(search_path, str):
        raise CollectionError("A página não apresentou resultados de busca do Confiança.")
    if parse_qs(urlsplit(search_path).query).get("Ntt") != parse_qs(urlsplit(url).query).get("Ntt"):
        raise CollectionError("O site do Confiança não confirmou o termo pesquisado.")
    page = pages.get(search_path)
    results = page.get("results") if isinstance(page, dict) else None
    records = results.get("records") if isinstance(results, dict) else None
    if not isinstance(records, list):
        raise CollectionError("Os resultados do Confiança estão em um formato inesperado.")

    entries = []
    for record in records:
        attributes = record.get("attributes") if isinstance(record, dict) else None
        if not isinstance(attributes, dict):
            continue
        routes = attributes.get("product.route")
        names = attributes.get("product.displayName")
        if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], str):
            continue
        if not CONFIANCA_PRODUCT_PATH.fullmatch(routes[0].removeprefix("/")):
            continue
        name = names[0] if isinstance(names, list) and names and isinstance(names[0], str) else ""
        entries.append((f"/marilia/{routes[0].lstrip('/')}", name))
    total = results.get("totalNumRecs")
    last = results.get("lastRecNum")
    has_next = type(total) is int and type(last) is int and 0 < last < total
    return entries, has_next


def promotion_is_current(sku: dict) -> bool:
    now = datetime.now(timezone.utc)
    for key in ("salePriceStartDate", "salePriceEndDate"):
        value = sku.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return False
        try:
            date = datetime.fromisoformat(value)
        except ValueError:
            return False
        if date.tzinfo is None:
            return False
        if (key == "salePriceStartDate" and date > now) or (key == "salePriceEndDate" and date <= now):
            return False
    return True


def price_in_list(sku: dict, field: str, price_list: str) -> Decimal | None:
    prices = sku.get(field)
    return extract_price(prices.get(price_list)) if isinstance(prices, dict) else None


def parse_confianca_offer(html: str, url: str) -> CollectedOffer:
    path = urlsplit(url).path.rstrip("/")
    route = path.removeprefix("/marilia/")
    product_id = route.rsplit("/", 1)[-1]
    catalog = read_catalog(html, url, product_id=product_id)
    product = catalog["products"].get(product_id)
    if not isinstance(product, dict) or product.get("id") != product_id or product.get("route") != route:
        raise CollectionError("A página não confirmou a identidade do produto do Confiança.")

    child_skus = product.get("childSKUs")
    if not isinstance(child_skus, list) or len(child_skus) != 1 or not isinstance(child_skus[0], str):
        raise CollectionError("O produto do Confiança não tem um SKU único confirmado.")
    external_code = extract_code(child_skus[0])
    sku = catalog["skus"].get(external_code)
    if not external_code or not isinstance(sku, dict) or sku.get("repositoryId") != external_code:
        raise CollectionError("A página não confirmou o código do SKU do Confiança.")
    if sku.get("soldAsPackage") is not True:
        raise CollectionError("A página não confirmou um preço por embalagem do Confiança.")

    name = clean_text(product.get("displayName"))
    regular = price_in_list(sku, "listPrices", PUBLIC_LIST)
    club_regular = price_in_list(sku, "listPrices", CLUB_LIST)
    promotion_current = promotion_is_current(sku)
    sale = price_in_list(sku, "salePrices", PUBLIC_LIST) if promotion_current else None
    club_sale = price_in_list(sku, "salePrices", CLUB_LIST) if promotion_current else None
    if sale is not None and regular is not None and sale > regular:
        raise CollectionError("A página apresentou preços públicos conflitantes no Confiança.")
    price = sale if sale is not None else regular
    if not name or len(name) > 300 or price is None:
        raise CollectionError("A página não confirmou o nome e o preço público da unidade Esmeralda.")
    club_price = club_sale if club_sale is not None else club_regular

    availability = "unknown"
    if (
        product.get("active") is False
        or sku.get("x_activeConfiancaEsmeralda") is False
        or sku.get("active") is False
    ):
        availability = "unavailable"

    return CollectedOffer(
        external_code=external_code,
        name=name,
        price=price,
        condition="promotion" if sale is not None and sale != regular else "regular",
        availability=availability,
        gtin=extract_gtin({"gtin": sku.get("barcode")}),
        url=url,
        club_price=club_price if club_price is not None and club_price < price else None,
    )

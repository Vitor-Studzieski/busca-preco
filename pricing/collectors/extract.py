from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from .http import CollectionError


@dataclass(frozen=True)
class CollectedOffer:
    external_code: str
    name: str
    price: Decimal
    condition: str
    availability: str
    gtin: str
    url: str
    club_price: Decimal | None = None
    price_unit: str = ""


class ProductPage(HTMLParser):
    """Collect visible detail text and the page's structured product metadata."""

    def __init__(self, html: str):
        super().__init__()
        self.text = []
        self.title = []
        self.heading = []
        self.scripts = []
        self.links = []
        self.product_links = []
        self.link_names = {}
        self.anchor = ""
        self.product_anchor_text = None
        self.active = None
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        if self.active in {"script", "ld+json", "style"}:
            return
        if tag == "script":
            mime_type = dict(attrs).get("type")
            self.active = "ld+json" if mime_type == "application/ld+json" else "script"
        elif tag in {"style", "title", "h1"}:
            self.active = tag
        elif tag == "a":
            attributes = dict(attrs)
            href = attributes.get("href")
            self.anchor = href or ""
            self.product_anchor_text = None
            if href:
                self.links.append(href)
                if attributes.get("title"):
                    self.link_names[href] = attributes["title"]
                if "product-item-link" in (attributes.get("class") or "").split():
                    self.product_links.append(href)
                    self.product_anchor_text = []

        elif tag == "img" and self.anchor:
            alt = dict(attrs).get("alt")
            if alt and not alt.strip().isdecimal():
                self.link_names.setdefault(self.anchor, alt)

    def handle_endtag(self, tag):
        if tag == "a":
            if self.product_anchor_text and self.anchor:
                label = clean_text(" ".join(self.product_anchor_text))
                if label and not label.isdecimal():
                    self.link_names[self.anchor] = label
            self.anchor = ""
            self.product_anchor_text = None
        if (tag == "script" and self.active == "ld+json") or tag == self.active:
            self.active = None

    def handle_data(self, data):
        if self.active == "ld+json":
            self.scripts.append(data)
        elif self.active == "title":
            self.title.append(data)
        elif self.active in {None, "h1"}:
            if self.product_anchor_text is not None:
                self.product_anchor_text.append(data)
            self.text.append(data)
            if self.active == "h1":
                self.heading.append(data)


def clean_text(value) -> str:
    return " ".join(str(value or "").split())


PRODUCT_CODES = {
    "lider": re.compile(r"\bC[ÓO]DIGO\s*:\s*#\s*([\w.-]+)", re.IGNORECASE),
    "tauste": re.compile(r"\bCOD\.\s*:?\s*([\w.-]+)", re.IGNORECASE),
}
DETAIL_END = re.compile(
    r"\b(?:informaç(?:ões|ão)\s+(?:gerais|adicionais)|produtos similares"
    r"|aproveite as nossas promoções|formas de pagamento)\b|\b(?:subtotal|quantidade)\s*:",
    re.IGNORECASE,
)
MONEY = re.compile(
    r"R\$\s*(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})(?![\d.,])",
    re.IGNORECASE,
)
RATE = re.compile(
    r"\s*/\s*(?:(\d+(?:[.,]\d+)?)\s*)?(kg|g|ml|l|un(?:idade)?)\b",
    re.IGNORECASE,
)
CLUB = re.compile(r"\b(?:clube|exclusiv\w*\s+(?:do|para)\s+club)\b", re.IGNORECASE)
CONDITIONAL = re.compile(r"\b(?:cupom|leve\s+\d+|a partir de\s+\d+\s+unidades)\b", re.IGNORECASE)


def extract_price(value) -> Decimal | None:
    value = clean_text(value)
    if not re.fullmatch(r"\d{1,7}(?:\.\d{1,2})?", value):
        return None
    price = Decimal(value)
    return price if price > 0 else None


def extract_code(value) -> str:
    code = clean_text(value)
    return code if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", code) else ""


def extract_gtin(product: dict) -> str:
    for field in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin"):
        number = clean_text(product.get(field))
        if len(number) not in {8, 12, 13, 14} or not re.fullmatch(r"[0-9]+", number):
            continue
        checksum = sum(
            int(digit) * (3 if index % 2 else 1)
            for index, digit in enumerate(reversed(number))
        )
        if checksum % 10 == 0 and int(number) > 0:
            return number
    return ""


def schema_has_type(item: dict, expected: str) -> bool:
    item_type = item.get("@type")
    if isinstance(item_type, str):
        item_type = [item_type]
    return isinstance(item_type, list) and any(
        value.rstrip("/").rsplit("/", 1)[-1] == expected
        for value in item_type
        if isinstance(value, str)
    )


def structured_products(page: ProductPage):
    for script in page.scripts:
        try:
            data = json.loads(script, parse_float=Decimal)
        except (RecursionError, ValueError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            candidates = graph if isinstance(graph, list) else [node]
            for item in candidates:
                if isinstance(item, dict) and schema_has_type(item, "Product"):
                    yield item


def same_page(identifier, url: str) -> bool:
    if not isinstance(identifier, str) or not identifier.strip() or identifier.startswith("#"):
        return False
    try:
        candidate = urlsplit(urljoin(url, identifier))
        source = urlsplit(url)
    except ValueError:
        return False
    return (
        candidate.scheme == "https"
        and candidate.netloc.lower() == source.netloc.lower()
        and candidate.path.rstrip("/") == source.path.rstrip("/")
    )


def main_product(page: ProductPage, name: str, url: str):
    products = list(structured_products(page))
    by_url = [
        product
        for product in products
        if any(same_page(product.get(field), url) for field in ("url", "@id"))
        and (not name or clean_text(product.get("name")).casefold() == name.casefold())
    ]
    if len(by_url) == 1:
        return by_url[0]
    if by_url or not name:
        return {}
    by_name = [
        product
        for product in products
        if clean_text(product.get("name")).casefold() == name.casefold()
        and not product.get("url")
        and (
            not product.get("@id")
            or (isinstance(product["@id"], str) and product["@id"].startswith("#"))
        )
    ]
    return by_name[0] if len(by_name) == 1 else {}


def structured_offer(product: dict, url: str) -> tuple[Decimal | None, str]:
    raw_offers = product.get("offers")
    offers = raw_offers if isinstance(raw_offers, list) else [raw_offers]
    if len(offers) != 1 or not isinstance(offers[0], dict):
        return None, "unknown"
    offer = offers[0]
    if not schema_has_type(offer, "Offer") or offer.get("priceCurrency") != "BRL":
        return None, "unknown"
    if offer.get("url") and not same_page(offer["url"], url):
        return None, "unknown"
    if offer.get("priceSpecification") or offer.get("eligibleQuantity"):
        return None, "unknown"
    availability = clean_text(offer.get("availability")).rsplit("/", 1)[-1]
    status = {
        "InStock": "available",
        "OutOfStock": "unavailable",
        "SoldOut": "unavailable",
    }.get(availability, "unknown")
    return extract_price(offer.get("price")), status


def detail_text(page: ProductPage, name: str, code_pattern: re.Pattern):
    visible = clean_text(" ".join(page.text))
    for heading in re.finditer(re.escape(name), visible, re.IGNORECASE):
        detail = DETAIL_END.split(visible[heading.end() : heading.end() + 1000], maxsplit=1)[0]
        if code_pattern.search(detail):
            return detail
    return ""


def visible_offer(detail: str, *, lider=False) -> tuple[Decimal | None, str, str, str]:
    availability = "unknown"
    if re.search(r"\b(?:indisponível|fora de estoque|sem estoque|esgotado)\b", detail, re.IGNORECASE):
        availability = "unavailable"
    elif re.search(r"\bem estoque\b", detail, re.IGNORECASE):
        availability = "available"

    candidates = []
    for match in MONEY.finditer(detail):
        suffix = RATE.match(detail, match.end())
        if suffix is not None and (suffix[1] is not None or suffix[2].lower() in {"g", "ml"}):
            # The per-100g or per-100ml amount is a reference beside the actual selling price.
            continue
        unit = suffix[2].lower() if suffix is not None and suffix[2].lower() in {"kg", "l"} else ""
        candidates.append((match, unit, suffix.end() if suffix else match.end()))
    if not candidates:
        return None, "unknown", availability, ""

    # "De ... Por ..." and the Líder discount badge identify the current price.
    promotional = [
        entry for entry in candidates
        if re.search(r"\bpor\s*:?\s*$", detail[:entry[0].start()], re.IGNORECASE)
        and re.search(r"\bde\s*:?\s*R\$", detail[:entry[0].start()], re.IGNORECASE)
    ]
    if lider and not promotional and len(candidates) == 2:
        first, second = candidates
        discount_label = detail[first[2]:second[0].start()]
        first_price = extract_price(first[0][1].replace(".", "").replace(",", "."))
        old_price = extract_price(second[0][1].replace(".", "").replace(",", "."))
        if re.fullmatch(r"\s*-\s*[1-9]\d?\s*%\s*", discount_label) and (
            first_price is not None and old_price is not None and first_price < old_price
        ):
            promotional = [first]
    if len(promotional) == 1:
        selected, unit, _ = promotional[0]
        if not unit and any(entry[1] for entry in candidates):
            return None, "unknown", availability, ""
    elif len({(match[1], unit) for match, unit, _ in candidates}) == 1:
        selected, unit, _ = candidates[0]
    else:
        return None, "unknown", availability, ""

    condition = "unknown"
    if CLUB.search(detail):
        condition = "club"
    elif not CONDITIONAL.search(detail):
        if promotional or re.search(r"\bem promoção\b", detail, re.IGNORECASE):
            condition = "promotion"
        elif re.search(r"\bpreço regular\b", detail, re.IGNORECASE):
            condition = "regular"
    price = extract_price(selected[1].replace(".", "").replace(",", "."))
    return price, condition, availability, unit


def parse_offer(retailer: str, html: str, url: str) -> CollectedOffer:
    if retailer == "confianca":
        from .confianca import parse_confianca_offer

        return parse_confianca_offer(html, url)
    page = ProductPage(html)
    name = clean_text(" ".join(page.heading))
    if retailer == "lider":
        title = clean_text(" ".join(page.title))
        if re.search(r"\s+-\s+Super L[íi]der", title, re.IGNORECASE):
            name = re.split(r"\s+-\s+Super L[íi]der", title, maxsplit=1, flags=re.IGNORECASE)[0]
    product = main_product(page, name, url)
    name = name or clean_text(product.get("name"))
    if not name or len(name) > 300:
        raise CollectionError("A página não confirmou o nome do produto.")

    external_code = extract_code(product.get("sku"))
    price, availability = structured_offer(product, url)
    condition = "unknown"
    price_unit = ""
    if retailer in PRODUCT_CODES:
        code_pattern = PRODUCT_CODES[retailer]
        detail = detail_text(page, name, code_pattern)
        code_match = code_pattern.search(detail)
        if code_match:
            external_code = extract_code(code_match[1])
            # When local details show prices, do not fall back to different
            # metadata if the displayed amount is ambiguous or sold by weight.
            displayed_price, condition, displayed_availability, price_unit = visible_offer(
                detail, lider=retailer == "lider",
            )
            if MONEY.search(detail):
                price = displayed_price
            if displayed_availability != "unknown":
                availability = displayed_availability
    if not external_code or price is None:
        raise CollectionError("A página não confirmou um código externo e um preço comparável.")
    return CollectedOffer(
        external_code=external_code,
        name=name,
        price=price,
        condition=condition,
        availability=availability,
        gtin=extract_gtin(product),
        url=url,
        price_unit=price_unit,
    )

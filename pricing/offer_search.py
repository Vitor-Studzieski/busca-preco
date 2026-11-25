import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from .collectors import CollectedOffer, CollectionError, collect_offer
from .collectors.http import storefront_deadline
from .collectors.search import search_catalog
from .identifiers import normalize_gtin, search_text
from .models import Store

CONDITION_LABELS = {
    "regular": "Regular",
    "promotion": "Promoção",
    "club": "Clube",
    "unknown": "Condição não identificada",
}
AVAILABILITY_LABELS = {
    "available": "Disponível",
    "unavailable": "Indisponível",
    "unknown": "Estoque não informado",
}

MEASURE = re.compile(
    r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*-?\s*"
    r"(mililitros?|litros?|ml|lts?|l|quilogramas?|quilos?|kgs?|gramas?|grs?|g|rolos?|unidades?|uns?)\b"
)
MULTIPACK = re.compile(r"\b(\d+)\s*[x×]\s*(?=\d)")
WORDS = re.compile(r"[a-z0-9]+")
CONNECTORS = {"de", "da", "do", "das", "dos", "e", "para", "com"}
ALIASES = {
    "coca": ("coca", "cola"), "cocacola": ("coca", "cola"), "contrafile": ("contra", "file"),
    "lv": ("longa", "vida"), "uht": ("longa", "vida"), "cerv": ("cerveja",),
    "refrig": ("refrigerante",), "detg": ("detergente",), "liq": ("liquido",),
    "gfa": ("garrafa",), "bov": ("bovina",), "bovino": ("bovina",),
}
BUNDLE = {"pack", "kit", "combo", "fardo"}
VARIANTS = {"zero", "semacucar", "diet", "light", "retornavel", "capa", "bisteca", "temperado"}
LIMITED_ACCESS = {401, 403, 429}
MAX_OFFERS = 3
MAX_DETAILS = 6
MAX_SEARCH_PAGES = 4
MAX_ACTIVE_SEARCHES = 8
TIMEOUT_ISSUE = "A loja não respondeu no tempo disponível."
logger = logging.getLogger(__name__)
workers = ThreadPoolExecutor(max_workers=MAX_ACTIVE_SEARCHES, thread_name_prefix="consulta-loja")
pending_searches = {}
pending_lock = Lock()


def product_terms(value, aliases=None):
    normalized = search_text(value)
    normalized = re.sub(r"\b(?:zero|sem)\s+(acucar|alcool|lactose|gluten)\b", r"sem\1", normalized)
    measures = [("un", Decimal(count)) for count in MULTIPACK.findall(normalized)]
    normalized = MULTIPACK.sub(" ", normalized)
    for number, unit in MEASURE.findall(normalized):
        amount = Decimal(number.replace(",", "."))
        if unit.startswith(("kg", "quilo")):
            measures.append(("g", amount * 1000))
        elif unit.startswith("l"):
            measures.append(("ml", amount * 1000))
        elif unit.startswith("m"):
            measures.append(("ml", amount))
        elif unit.startswith("rolo"):
            measures.append(("rolo", amount))
        elif unit.startswith("un"):
            measures.append(("un", amount))
        else:
            measures.append(("g", amount))

    raw = [word for word in WORDS.findall(MEASURE.sub(" ", normalized)) if word not in CONNECTORS]
    aliases = ALIASES if aliases is None else ALIASES | aliases
    terms = [alias for word in raw for alias in (
        (word,) if word == "coca" and "cola" in raw else aliases.get(word, (word,))
    )]
    if "coca" in terms and "zero" in terms:
        terms = ["semacucar" if word == "zero" else word for word in terms]
    return tuple(dict.fromkeys(terms)), tuple(dict.fromkeys(measures))


def term_set(terms):
    return set(terms) | {left + right for left, right in zip(terms, terms[1:])}


def size_terms(measures):
    for unit, quantity in measures:
        if unit == "ml" and quantity >= 1000:
            unit, quantity = "l", quantity / 1000
        elif unit == "g" and quantity >= 1000:
            unit, quantity = "kg", quantity / 1000
        if unit == "rolo":
            yield f"{quantity.normalize():f} rolos"
        else:
            yield f"{quantity.normalize():f}{unit}"


@dataclass(frozen=True)
class SearchQuery:
    terms: tuple[str, ...]
    measures: tuple[tuple[str, Decimal], ...]
    code: str

    @classmethod
    def from_text(cls, query, aliases=None):
        terms, measures = product_terms(query, aliases)
        return cls(terms, measures, query if query.isascii() and query.isdigit() else "")

    def candidate(self, name, *, detail=False):
        if self.code:
            return True
        terms, measures = product_terms(name)
        available = term_set(terms)
        for left, right in zip(self.terms, self.terms[1:]):
            if left + right in available:
                available.update((left, right))
        if not set(self.terms).issubset(available):
            return False
        if self.measures and (detail or measures) and not set(self.measures).issubset(measures):
            return False
        if len(self.measures) <= 1 and not BUNDLE.intersection(self.terms):
            if (BUNDLE.intersection(terms) or ("+" in name and len(MEASURE.findall(search_text(name))) > 1)
                    or (self.measures and any(unit == "un" and quantity > 1 for unit, quantity in measures))):
                return False
        return True

    def rank(self, name):
        terms, measures = product_terms(name)
        extras = VARIANTS.intersection(terms) - set(self.terms)
        return (bool(self.measures and not measures), len(extras), len(measures) > 1)

    def vendor_terms(self, retailer):
        if self.code:
            return (self.code,)
        native = tuple(word.replace("semacucar", "zero" if "coca" in self.terms else "sem acucar")
                       .replace("semalcool", "sem alcool").replace("semlactose", "sem lactose")
                       .replace("semgluten", "sem gluten") for word in self.terms)
        words = " ".join(native)
        descriptive = words.replace("zero", "sem acucar") if "semacucar" in self.terms else words
        sizes = tuple(size_terms(self.measures))
        with_size = " ".join(filter(None, (words, *sizes)))
        alternate = " ".join(filter(None, (descriptive, *sizes)))
        spaced_size = re.sub(r"(?<=\d)(?=[a-z])", " ", with_size)
        compact = words.replace("contra file", "contrafile").replace("longa vida", "uht")
        broad = " ".join(word for word in native if word not in ("longa", "vida", "garrafa", "liquido"))
        if retailer == "tauste" and len(native) > 1:
            choices = ("-".join(native) if native == ("coca", "cola") else with_size,
                       alternate, words, compact, broad, spaced_size)
        else:
            choices = (with_size, alternate, spaced_size, words, compact, broad)
        return tuple(dict.fromkeys(filter(None, choices)))

    def confirms(self, offer):
        if not self.code:
            return self.candidate(offer.name, detail=True)
        gtin = normalize_gtin(self.code)
        return self.code == offer.external_code or bool(gtin and gtin == normalize_gtin(offer.gtin))


@dataclass(frozen=True)
class SearchOffer:
    collected: CollectedOffer

    @property
    def condition(self):
        return CONDITION_LABELS.get(self.collected.condition, CONDITION_LABELS["unknown"])

    @property
    def availability(self):
        return AVAILABILITY_LABELS.get(self.collected.availability, AVAILABILITY_LABELS["unknown"])


@dataclass(frozen=True)
class UnpricedProduct:
    url: str
    name: str


@dataclass(frozen=True)
class StoreSearch:
    store: Store
    offers: tuple[SearchOffer, ...]
    observed_at: datetime | None = None
    issue: str = ""
    unpriced: tuple[UnpricedProduct, ...] = ()
    shared_checked: bool = False


def search_unit(store, query, *, deadline=None):
    offers = []
    unpriced = []
    codes = set()
    tried_urls = set()
    issue = ""
    pages = 0
    deadline = monotonic() + 16 if deadline is None else deadline

    for term in query.vendor_terms(store.retailer):
        if offers or len(tried_urls) >= MAX_DETAILS:
            break
        for page_number in (1, 2):
            if pages >= MAX_SEARCH_PAGES or monotonic() >= deadline or len(tried_urls) >= MAX_DETAILS:
                break
            pages += 1
            try:
                page = search_catalog(store.retailer, store.url, term, page_number=page_number)
            except CollectionError as error:
                issue = str(error)
                if error.status in LIMITED_ACCESS:
                    return StoreSearch(store, (), issue=issue, unpriced=tuple(unpriced[:MAX_OFFERS]))
                break
            candidates = sorted(
                ((url, name) for url, name in page.entries if query.candidate(name)),
                key=lambda item: query.rank(item[1]),
            )
            for url, name in candidates:
                if len(offers) >= MAX_OFFERS or len(tried_urls) >= MAX_DETAILS or monotonic() >= deadline:
                    break
                if url in tried_urls:
                    continue
                tried_urls.add(url)
                try:
                    offer = collect_offer(store.retailer, store.url, url)
                except CollectionError as error:
                    if error.temporary:
                        issue = str(error)
                    if not query.code and query.candidate(name, detail=True):
                        unpriced.append(UnpricedProduct(url, name))
                    if error.status in LIMITED_ACCESS:
                        issue = str(error)
                        return StoreSearch(store, tuple(offers), timezone.now() if offers else None,
                                           issue, tuple(unpriced[:MAX_OFFERS]))
                    continue
                if offer.external_code not in codes and query.confirms(offer):
                    offers.append(SearchOffer(offer))
                    codes.add(offer.external_code)
            if offers or not page.has_next:
                break
    if monotonic() >= deadline and not offers and not unpriced:
        issue = TIMEOUT_ISSUE
    offers.sort(key=lambda offer: query.rank(offer.collected.name))
    return StoreSearch(store, tuple(offers), timezone.now() if offers else None,
                       issue, tuple(unpriced[:MAX_OFFERS]))


def search_cache_key(store, query):
    # Keep the retailer's ID exact and normalize only equivalent quantities.
    measures = tuple((unit, str(quantity.normalize())) for unit, quantity in query.measures)
    identity = (store.slug, store.retailer, store.url, query.terms, measures, query.code)
    return "market-search:v1:" + sha256(repr(identity).encode()).hexdigest()


def schedule_search(key, lookup):
    with pending_lock:
        previous = pending_searches.get(key)
        if previous is not None:
            if not previous.done():
                return previous
            del pending_searches[key]
        if len(pending_searches) >= MAX_ACTIVE_SEARCHES:
            return None
        future = workers.submit(lookup)
        pending_searches[key] = future

    def release(done):
        with pending_lock:
            if pending_searches.get(key) is done:
                del pending_searches[key]

    future.add_done_callback(release)
    return future


def refresh_search(key, store, lookup, deadline, *, shared=False):
    cache = caches["pricing_search"]
    existing = cache.get(key)
    if existing is not None and (not shared or existing.offers or existing.shared_checked):
        return replace(existing, store=store)
    if deadline <= monotonic():
        return StoreSearch(store, (), issue=TIMEOUT_ISSUE)
    with storefront_deadline(deadline):
        result = lookup()
    if shared:
        result = replace(result, shared_checked=True)
    if result.issue or (result.unpriced and not result.offers):
        ttl = settings.PRICING_SEARCH_FAILURE_TTL
    elif result.offers:
        ttl = settings.PRICING_SEARCH_TTL
    else:
        ttl = settings.PRICING_SEARCH_EMPTY_TTL
    cache.set(key, result, timeout=ttl)
    return result


def take_results(results, jobs, deadline):
    if not jobs:
        return
    finished, _ = wait(jobs.values(), timeout=max(0, deadline - monotonic()))
    for index, future in jobs.items():
        store = results[index].store
        if future not in finished:
            results[index] = replace(results[index], issue=TIMEOUT_ISSUE)
            continue
        try:
            results[index] = future.result()
        except Exception:
            logger.exception("Falha inesperada na consulta da unidade %s", store.slug)
            results[index] = replace(results[index], issue="Não foi possível consultar esta loja.")


def search_stores(stores, text):
    query = SearchQuery.from_text(text)
    results = [StoreSearch(store, ()) for store in stores]
    if not query.terms and not query.measures:
        return results

    timeout = settings.PRICING_SEARCH_TIMEOUT
    deadline = monotonic() + timeout
    primary_deadline = deadline - min(3, timeout / 4)
    cache = caches["pricing_search"]
    keys = [search_cache_key(row.store, query) for row in results]
    jobs = {}
    for index, key in enumerate(keys):
        store = results[index].store
        existing = cache.get(key)
        if existing is not None:
            results[index] = replace(existing, store=store)
            continue
        future = schedule_search(key, lambda key=key, store=store: refresh_search(
            key, store, lambda: search_unit(store, query, deadline=primary_deadline), primary_deadline,
        ))
        if future is None:
            results[index] = StoreSearch(store, (), issue="Consultas em andamento. Tente novamente.")
        else:
            jobs[index] = future
    lider_jobs = {index: job for index, job in jobs.items() if results[index].store.retailer == "lider"}
    remaining_jobs = {index: job for index, job in jobs.items() if index not in lider_jobs}
    take_results(results, lider_jobs, primary_deadline)

    paths = tuple(dict.fromkeys(
        path for result in results if result.store.retailer == "lider"
        for offer in result.offers
        if (path := urlsplit(offer.collected.url).path.partition("/produto/m/")[2])
    ))[:MAX_OFFERS]
    jobs = {}
    for index, result in enumerate(results):
        if (not paths or result.store.retailer != "lider" or result.shared_checked
                or result.offers or result.unpriced or result.issue):
            continue
        key = keys[index]
        future = schedule_search(key + ":shared", lambda key=key, result=result: refresh_search(
            key, result.store, lambda: search_lider_shared_catalog(result, query, paths),
            deadline, shared=True,
        ))
        if future is not None:
            jobs[index] = future
        else:
            results[index] = replace(result, issue="Consultas em andamento. Tente novamente.")
    take_results(results, remaining_jobs, primary_deadline)
    take_results(results, jobs, deadline)
    return results


def search_lider_shared_catalog(result, query, product_paths):
    """A shared product path can exist in a Líder unit even if its search omits it."""
    store = result.store
    offers = []
    issue = ""
    for product_path in product_paths:
        if not product_path:
            continue
        url = f"{store.url.rstrip('/')}/produto/m/{product_path}"
        try:
            offer = collect_offer(store.retailer, store.url, url)
        except CollectionError as error:
            if error.temporary:
                issue = str(error)
            if error.status in LIMITED_ACCESS:
                issue = str(error)
                break
            continue
        if query.confirms(offer):
            offers.append(SearchOffer(offer))
    return StoreSearch(store, tuple(offers), timezone.now() if offers else None, issue)

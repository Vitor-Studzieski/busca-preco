from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET

from .collectors import CollectionError
from .collectors.http import validate_product_url
from .identifiers import normalize_gtin
from .models import Store
from .offer_search import SearchQuery, search_stores
from .request_limits import search_retry_after

MARKET_LIMIT = 4
PROMOTION = "Promoção"
CLUB = "Clube"
MULTIBUY = "Leve 2, Pague 1"
PROMOTION_TYPES = {"promocao": PROMOTION, "clube": CLUB}
CONDITION_PROMOTIONS = {PROMOTION, CLUB, MULTIBUY}
CONDITION_LABELS = {"promotion": PROMOTION, "club": CLUB, "multibuy": MULTIBUY}
AVAILABILITY_LABELS = {
    "available": "Disponível",
    "unavailable": "Indisponível",
    "unknown": "Estoque não informado",
}


@dataclass(frozen=True)
class MarketOffer:
    store: Store
    name: str
    price: Decimal
    unit: str
    condition: str
    availability: str
    url: str
    observed_at: datetime
    gtin: str
    club_price: Decimal | None

    @property
    def is_multibuy(self):
        return self.condition == MULTIBUY

    @property
    def is_promotion(self):
        return self.condition == PROMOTION

    @property
    def is_club(self):
        return self.condition == CLUB


def region_context(request, *, query="", kind=""):
    all_stores = list(Store.objects.filter(active=True).order_by("display_order", "pk"))
    cities = defaultdict(list)
    for store in all_stores:
        cities[slugify(store.unit) or store.slug].append(store)

    location_key = request.GET.get("cidade", "todas")
    if location_key not in cities and location_key != "todas":
        location_key = "todas"
    available = all_stores if location_key == "todas" else cities[location_key]

    requested_ids = set(request.GET.getlist("loja")[:MARKET_LIMIT])
    selected = [store for store in available if str(store.pk) in requested_ids] if requested_ids else available
    selected = selected or available

    extra = {}
    if query:
        extra["q"] = query
    if kind:
        extra["tipo"] = kind
    city_query = urlencode({"cidade": location_key})
    scope_pairs = [("cidade", location_key)]
    scope_pairs.extend(("loja", store.pk) for store in selected)
    scope_query = urlencode(scope_pairs)
    city_rows = [{
        "name": "Marília e região",
        "key": "todas",
        "url": "?" + urlencode({"cidade": "todas", **extra}),
    }]
    city_rows.extend({
        "name": stores[0].unit,
        "key": key,
        "url": "?" + urlencode({"cidade": key, **extra}),
    } for key, stores in sorted(cities.items()))

    location = "Marília e região" if location_key == "todas" else available[0].unit
    return {
        "cities": city_rows,
        "location": location,
        "city_key": location_key,
        "city_query": city_query,
        "scope_query": scope_query,
        "stores": selected,
        "all_stores": all_stores,
        "store_options": available if len(available) > 1 else (),
        "selected_ids": {store.pk for store in selected},
        "market_limit": MARKET_LIMIT,
        "search_action": (
            "pricing:storefront_promotions"
            if request.resolver_match.url_name == "storefront_promotions"
            else "pricing:storefront_compare"
        ),
    }


def to_market_offer(result_offer, store, observed_at):
    collected = result_offer.collected
    try:
        url = validate_product_url(store.retailer, store.url, collected.url)
    except CollectionError:
        return None
    return MarketOffer(
        store=store,
        name=collected.name.strip()[:255],
        price=collected.price,
        unit=collected.price_unit,
        condition=CONDITION_LABELS.get(collected.condition, "Condição não identificada"),
        availability=AVAILABILITY_LABELS.get(collected.availability, "Estoque não informado"),
        url=url,
        observed_at=observed_at,
        gtin=normalize_gtin(collected.gtin) if collected.gtin else "",
        club_price=collected.club_price,
    )


def compare_offers(stores, query):
    results = search_stores(stores, query)
    groups = []
    now = timezone.now()
    parsed_query = SearchQuery.from_text(query)
    for result in results:
        observed_at = result.observed_at or now
        offers = [
            offer for item in result.offers
            if (offer := to_market_offer(item, result.store, observed_at)) is not None
            and parsed_query.confirms(item.collected)
        ]
        groups.append({
            "store": result.store,
            "offers": offers[:3],
            "issue": result.issue,
        })
    matching = [group for group in groups if group["offers"]]
    exact_offers = [group["offers"][0] for group in groups if len(group["offers"]) == 1]
    lowest_price = None
    if (len(exact_offers) > 1 and len(exact_offers) == len(matching)
            and exact_offers[0].gtin
            and all(
                offer.gtin == exact_offers[0].gtin
                and offer.unit == exact_offers[0].unit
                and not offer.is_club
                and not offer.is_multibuy
                for offer in exact_offers
            )):
        lowest_price = min(offer.price for offer in exact_offers)
    return groups, len(matching), lowest_price


@require_GET
def home(request):
    query = request.GET.get("q", "").strip()[:255]
    if query:
        return redirect(f"/comparar/?{urlencode({'q': query, 'cidade': request.GET.get('cidade', 'todas')})}")
    context = region_context(request)
    return render(request, "pricing/storefront/home.html", context)


@require_GET
def compare(request):
    query = request.GET.get("q", "").strip()[:255]
    if query and (retry_after := search_retry_after(request)):
        return HttpResponse(
            "Muitas buscas em sequência. Aguarde um pouco e tente novamente.",
            status=429,
            headers={"Retry-After": str(retry_after)},
            content_type="text/plain; charset=utf-8",
        )
    context = region_context(request, query=query)
    groups, matching_stores, lowest_price = compare_offers(context["stores"], query) if query else ([], 0, None)
    context.update(
        query=query,
        groups=groups,
        matching_stores=matching_stores,
        lowest_price=lowest_price,
    )
    return render(request, "pricing/storefront/compare.html", context)


@require_GET
def promotions(request):
    query = request.GET.get("q", "").strip()[:255]
    if query and (retry_after := search_retry_after(request)):
        return HttpResponse(
            "Muitas buscas em sequência. Aguarde um pouco e tente novamente.",
            status=429,
            headers={"Retry-After": str(retry_after)},
            content_type="text/plain; charset=utf-8",
        )
    kind = request.GET.get("tipo", "")
    kind = kind if kind in PROMOTION_TYPES else ""
    context = region_context(request, query=query, kind=kind)
    groups, _, _ = compare_offers(context["stores"], query) if query else ([], 0, None)
    allowed = {PROMOTION_TYPES[kind]} if kind else CONDITION_PROMOTIONS
    offers = [offer for group in groups for offer in group["offers"] if offer.condition in allowed]
    context.update(query=query, kind=kind, groups=groups, offers=offers)
    return render(request, "pricing/storefront/promotions.html", context)

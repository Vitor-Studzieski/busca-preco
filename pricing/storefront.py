from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .collectors import CollectionError
from .collectors.http import validate_product_url
from .identifiers import normalize_gtin
from .models import Store
from .offer_search import SearchQuery, search_stores
from .request_limits import search_retry_after

PROMOTION = "Promoção"
CLUB = "Clube"
MULTIBUY = "Leve 2, Pague 1"
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
    condition_detail: str

    @property
    def is_multibuy(self):
        return self.condition == MULTIBUY

    @property
    def is_promotion(self):
        return self.condition == PROMOTION

    @property
    def is_club(self):
        return self.condition == CLUB


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
        condition_detail=collected.condition_detail,
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
    if query and (retry_after := search_retry_after(request)):
        return HttpResponse(
            "Muitas buscas em sequência. Aguarde um pouco e tente novamente.",
            status=429,
            headers={"Retry-After": str(retry_after)},
            content_type="text/plain; charset=utf-8",
        )

    stores = list(Store.objects.filter(active=True).order_by("display_order", "pk"))
    groups, matching_stores, lowest_price = compare_offers(stores, query) if query else ([], 0, None)
    return render(request, "pricing/storefront/home.html", {
        "query": query,
        "stores": stores,
        "groups": groups,
        "matching_stores": matching_stores,
        "lowest_price": lowest_price,
    })

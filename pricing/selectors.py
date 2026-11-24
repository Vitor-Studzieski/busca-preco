from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone

from .identifiers import normalize_gtin, search_text
from .models import Listing, Observation, Product, Store
from .price_workflow import current_prices


def find_products(query, limit=50):
    if not query:
        return []
    filtered = Q(sku__iexact=query)
    normalized, gtin = search_text(query), normalize_gtin(query)
    if normalized:
        filtered |= Q(search_name__contains=normalized)
    if gtin:
        filtered |= Q(gtin=gtin)
    return list(Product.objects.filter(filtered, active=True)[:limit])


def comparison(product, now=None, *, own_amount_override=None):
    now = now or timezone.now()
    enabled = list(Store.objects.filter(active=True).order_by("display_order", "pk"))
    configured_price = current_prices(product, now).order_by(
        F("kind").desc(), "-starts_at"
    ).first()
    own_amount = own_amount_override if own_amount_override is not None else (
        configured_price.amount if configured_price else product.current_price
    )
    latest_id = Observation.objects.filter(listing_id=OuterRef("pk")).order_by("-observed_at", "-pk")
    listings = list(product.listings.filter(active=True).annotate(
        latest_id=Subquery(latest_id.values("pk")[:1])
    ))
    observations = Observation.objects.in_bulk([row.latest_id for row in listings if row.latest_id])
    by_store = {row.store_id: row for row in listings}
    local_day = timezone.localtime(now).date()
    rows = []
    for store in enabled:
        listing = by_store.get(store.pk)
        observation = observations.get(listing.latest_id) if listing else None
        if listing and listing.gtin and product.gtin and listing.gtin != product.gtin:
            observation = None
        fresh = bool(observation and timezone.localtime(observation.observed_at).date() == local_day)
        confirmed = bool(listing and listing.match_method and listing.status == Listing.Status.OK)
        # The legacy own catalog does not store unit price bases. Only package prices can be compared.
        comparable = bool(own_amount and observation and fresh and confirmed and not observation.price_unit
                          and observation.availability != Observation.Availability.UNAVAILABLE)
        difference = observation.price - own_amount if comparable else None
        rows.append({"store": store, "listing": listing, "observation": observation, "fresh": fresh,
                     "comparable": comparable, "diff": difference,
                     "percent": difference * 100 / own_amount if comparable else None})
    minimum = min((row["observation"].price for row in rows if row["comparable"]), default=None)
    for row in rows:
        row["lowest"] = row["comparable"] and row["observation"].price == minimum
    return configured_price, own_amount, rows

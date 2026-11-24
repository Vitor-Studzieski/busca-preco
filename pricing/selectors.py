from collections import defaultdict
from datetime import timedelta

from django.db.models import Case, F, IntegerField, OuterRef, Q, Subquery, Value, When
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
    order = [When(sku__iexact=query, then=Value(1))]
    if gtin:
        order.insert(0, When(gtin=gtin, then=Value(0)))
    return list(Product.objects.filter(filtered, active=True).annotate(
        search_rank=Case(*order, default=Value(2), output_field=IntegerField())
    ).order_by("search_rank", "name", "package", "sku")[:limit])


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
        if not observation:
            issue = "Sem preço confirmado"
        elif not confirmed or listing.confirmed_at and observation.observed_at < listing.confirmed_at:
            issue = "Vínculo ou coleta pendente"
        elif not fresh:
            issue = "Coleta desatualizada"
        elif observation.price_unit:
            issue = "Base de preço diferente"
        elif observation.availability == Observation.Availability.UNAVAILABLE:
            issue = "Produto indisponível"
        else:
            issue = ""
        comparable = bool(own_amount and not issue)
        difference = observation.price - own_amount if comparable else None
        rows.append({"store": store, "listing": listing, "observation": observation, "fresh": fresh,
                     "eligible": not issue, "comparable": comparable, "diff": difference,
                     "comparison_issue": issue or "Sem preço do Pompeia para comparar",
                     "percent": difference * 100 / own_amount if comparable else None})
    minimum = min((row["observation"].price for row in rows if row["comparable"]), default=None)
    for row in rows:
        row["lowest"] = row["comparable"] and row["observation"].price == minimum
    return configured_price, own_amount, rows


def product_history(product):
    since = timezone.now() - timedelta(days=30)
    series = defaultdict(list)
    points = []
    own = product.own_prices.filter(starts_at__gte=since, starts_at__lte=timezone.now(),
                                    cancelled_at__isnull=True).order_by("starts_at")[:120]
    for price in own:
        points.append({"name": "Pompeia", "date": price.starts_at, "amount": price.amount, "unit": ""})
    observed = Observation.objects.filter(
        listing__product=product, observed_at__gte=since, listing__active=True,
    ).filter(
        Q(listing__confirmed_at__isnull=True) | Q(observed_at__gte=F("listing__confirmed_at"))
    ).select_related("listing__store").order_by("-observed_at", "-pk")[:120]
    for item in observed:
        points.append({"name": str(item.listing.store), "date": item.observed_at,
                       "amount": item.price, "unit": item.price_unit})
    for point in sorted(points, key=lambda p: p["date"]):
        if not point["unit"]:
            series[point["name"]].append([int(point["date"].timestamp() * 1000), str(point["amount"])])
    return (
        sorted(points, key=lambda p: p["date"], reverse=True),
        [{"label": label, "points": values} for label, values in series.items()],
    )

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .collectors import CollectionError, collect_offer
from .identifiers import normalize_gtin
from .models import Listing, Observation, Product, Store


def collect_listing(listing, *, collection_run_id=None):
    if collection_run_id and Observation.objects.filter(
        listing=listing, collection_run_id=collection_run_id
    ).exists():
        return Listing.Status.OK, "Observação já registrada nesta execução.", None
    started_at = timezone.now()
    try:
        offer = collect_offer(listing.store.retailer, listing.store.url, listing.url)
    except CollectionError as error:
        status, message = record_collection_error(listing.pk, started_at, str(error))
        return status, message, error.status
    collected_at = timezone.now()
    gtin = normalize_gtin(offer.gtin)

    with transaction.atomic():
        # Serialize identity decisions for a unit, keeping network I/O outside the lock.
        Store.objects.select_for_update().get(pk=listing.store_id)
        listing = Listing.objects.select_for_update().get(pk=listing.pk)
        if listing.checked_at and listing.checked_at >= started_at:
            return listing.status, "Uma tentativa mais recente já foi registrada.", None
        other_listings = Listing.objects.filter(store=listing.store).exclude(pk=listing.pk)
        conflict = ""
        if listing.external_code and listing.external_code != offer.external_code:
            conflict = "O código publicado na URL mudou. Revise a identidade do anúncio."
        elif other_listings.filter(external_code=offer.external_code).exists():
            conflict = "Outro anúncio desta unidade já usa esse código externo."
        elif gtin and any(known and known != gtin for known in (
            listing.gtin, listing.product.gtin if listing.product_id else "",
        )):
            conflict = "O EAN/GTIN observado diverge do cadastro. Revise o vínculo."

        listing.checked_at = started_at
        listing.status = Listing.Status.CONFLICT if conflict else Listing.Status.OK
        listing.error = conflict
        if conflict:
            listing.save(update_fields=["checked_at", "status", "error"])
            return listing.status, conflict, None

        listing.name = offer.name[:255]
        listing.external_code = offer.external_code
        listing.gtin = gtin or listing.gtin
        if listing.gtin and not listing.product_id:
            matches = list(Product.objects.filter(gtin=listing.gtin).order_by("pk")[:2])
            if len(matches) == 1 and not other_listings.filter(product=matches[0]).exists():
                listing.product = matches[0]
                listing.match_method = Listing.Match.GTIN
        listing.save()
        Observation.objects.create(
            listing=listing, collection_run_id=collection_run_id,
            price=offer.price, condition=offer.condition,
            club_price=offer.club_price, price_unit=offer.price_unit,
            availability=offer.availability, source_url=offer.url, observed_at=collected_at,
        )
        return listing.status, f"{offer.external_code} · R$ {offer.price:.2f}", None


def record_collection_error(listing_id, started_at, message):
    with transaction.atomic():
        listing = Listing.objects.select_for_update().get(pk=listing_id)
        if listing.checked_at and listing.checked_at >= started_at:
            return listing.status, "Uma tentativa mais recente já foi registrada."
        listing.checked_at = started_at
        listing.status = Listing.Status.ERROR
        listing.error = message[:300]
        listing.save(update_fields=["checked_at", "status", "error"])
    return listing.status, message


def comparison_rows(product, now):
    listings = {listing.store_id: listing for listing in product.listings.filter(active=True)}
    oldest_valid = now - timedelta(hours=settings.OFFER_MAX_AGE_HOURS)
    for store in Store.objects.filter(active=True).order_by("display_order", "pk"):
        listing = listings.get(store.pk)
        observation = listing.observations.first() if listing else None
        stale = bool(observation and observation.observed_at < oldest_valid)
        historical = stale
        status = "Sem anúncio vinculado"
        if listing:
            if listing.gtin and product.gtin and listing.gtin != product.gtin:
                status = "EAN divergente do catálogo Pompeia"
                observation = None
                historical = False
            elif listing.status != Listing.Status.OK:
                status = listing.get_status_display()
                historical = bool(observation)
            elif observation and observation.availability == Observation.Availability.UNAVAILABLE:
                status = "Produto indisponível"
            elif stale:
                status = "Preço desatualizado"
            elif observation:
                status = observation.get_availability_display()
        yield {"store": store, "listing": listing, "observation": observation,
               "stale": stale, "historical": historical, "status": status}

import logging
import random
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from time import monotonic

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from .collectors import CollectionError
from .collectors.http import storefront_deadline
from .identifiers import normalize_gtin
from .models import Listing, Observation, Product, Store
from .offer_search import SearchQuery, search_unit
from .services import collect_listing
from .workflow_models import (
    Alert,
    CollectionJob,
    CollectionRun,
    DayItem,
    MonitoredQuery,
    NetworkHealth,
    OwnPrice,
    RateWindow,
    SearchAlias,
)

logger = logging.getLogger(__name__)
Status = CollectionJob.Status
OPEN = (Status.PENDING, Status.RUNNING)
LEASE = timedelta(minutes=2)
BLOCK_CODES = (401, 403, 429)


def configured_query(query):
    aliases = {
        item.abbreviation.casefold(): tuple(item.expansion.casefold().split())
        for item in SearchAlias.objects.filter(active=True)
    }
    return SearchQuery.from_text(query, aliases)


def normalized_lookup(query, parsed=None):
    terms = parsed or configured_query(query)
    return job_key("lookup", terms.terms, tuple((unit, str(amount.normalize())) for unit, amount in terms.measures), terms.code)


def job_key(*parts):
    return sha256(repr(parts).encode()).hexdigest()


@transaction.atomic
def enqueue_search(query, *, store_id=None, product=None, force=False):
    normalized = configured_query(query)
    if not (normalized.terms or normalized.measures):
        return []
    stores = Store.objects.filter(active=True).order_by("display_order", "pk")
    if store_id is not None:
        stores = stores.filter(pk=store_id)
    now = timezone.now()
    slots = 30 if force else 90
    lookup = normalized_lookup(query, normalized)
    tasks = []
    for store in stores:
        Store.objects.select_for_update().get(pk=store.pk)
        active = CollectionJob.objects.filter(store=store, lookup_key=lookup, product=product,
                                              status__in=OPEN, available_at__lte=now).first()
        if active and not force:
            tasks.append(active)
            continue
        job, _ = CollectionJob.objects.get_or_create(
            key=job_key("search", store.pk, product.pk if product else None, lookup, int(now.timestamp()) // slots),
            defaults={"store": store, "query": query, "product": product, "lookup_key": lookup},
        )
        tasks.append(job)
    return tasks


@transaction.atomic
def enqueue_product_collection(product, trigger, key, available_at=None):
    run, _ = CollectionRun.objects.get_or_create(key=key, defaults={"trigger": trigger})
    available_at = available_at or timezone.now()
    listings = {row.store_id: row for row in product.listings.filter(active=True)}
    for store in Store.objects.filter(active=True):
        listing = listings.get(store.pk)
        CollectionJob.objects.get_or_create(
            key=job_key(run.pk, product.pk, store.pk),
            defaults={"run": run, "store": store, "listing": listing,
                      "query": product.gtin or f"{product.name} {product.package}" if not listing else "",
                      "available_at": available_at, "product": product},
        )
    return run


@transaction.atomic
def enqueue_daily(day, hour=4):
    run, created = CollectionRun.objects.get_or_create(key=f"daily:{day}:{hour:02d}", defaults={"trigger": "daily"})
    if not created:
        return run
    day_products = DayItem.objects.filter(day=day).values("product_id")
    listings = Listing.objects.filter(active=True, store__active=True).select_related("store")
    product_ids = set()
    for listing in listings.iterator():
        CollectionJob.objects.create(run=run, store=listing.store, listing=listing,
                                     key=job_key(run.pk, listing.store_id, listing.pk))
        if listing.product_id:
            product_ids.add((listing.product_id, listing.store_id))
    stores = list(Store.objects.filter(active=True))
    for product in Product.objects.filter(pk__in=day_products, active=True).iterator():
        for store in stores:
            if (product.pk, store.pk) not in product_ids:
                CollectionJob.objects.create(
                    run=run, store=store, key=job_key(run.pk, product.pk, store.pk, "search"),
                    query=product.gtin or f"{product.name} {product.package}", product=product,
                )
    for item in MonitoredQuery.objects.order_by("-last_used_at").iterator():
        for store in stores:
            CollectionJob.objects.create(
                run=run, store=store, key=job_key(run.pk, item.key, store.pk),
                query=item.query, lookup_key=item.key,
            )
    if not run.jobs.exists():
        run.started_at = run.finished_at = timezone.now()
        run.stats = {"total": 0, "processed": 0, "failed": 0, "by_network": {}}
        run.save(update_fields=["started_at", "finished_at", "stats"])
    return run


def schedule_due(now=None):
    now = now or timezone.now()
    local = timezone.localtime(now)
    reached = [hour for hour in settings.PRICING_COLLECTION_HOURS if hour <= local.hour]
    if reached:
        enqueue_daily(local.date(), max(reached))
    from .price_workflow import sync_promotion_alert

    active = OwnPrice.objects.filter(kind=OwnPrice.Kind.PROMOTION, starts_at__lte=now,
                                     ends_at__gt=now, cancelled_at__isnull=True)
    open_prices = Alert.objects.filter(kind="promotion", resolved_at__isnull=True).values("own_price_id")
    for price in OwnPrice.objects.filter(Q(pk__in=active.values("pk")) | Q(pk__in=open_prices)):
        sync_promotion_alert(price, now)
    RateWindow.objects.filter(expires_at__lt=now).delete()


@transaction.atomic
def claim_job():
    now = timezone.now()
    CollectionJob.objects.filter(status=Status.RUNNING, started_at__lt=now - LEASE).update(
        status=Status.PENDING, available_at=now, started_at=None
    )
    candidates = CollectionJob.objects.filter(status=Status.PENDING, available_at__lte=now).order_by(
        F("run_id").asc(nulls_first=True), "available_at", "pk"
    )
    lock_options = {"skip_locked": True, "of": ("self",)} if connection.vendor == "postgresql" else {}
    network_order = list(Store.objects.filter(active=True).order_by("retailer").values_list("retailer", flat=True).distinct())
    for retailer in dict.fromkeys(network_order):
        network, _ = NetworkHealth.objects.select_for_update().get_or_create(retailer=retailer)
        if CollectionJob.objects.filter(status=Status.RUNNING, store__retailer=retailer).exists():
            continue
        job = candidates.filter(store__retailer=retailer).select_for_update(**lock_options).first()
        if job is None:
            continue
        job.status = Status.RUNNING
        job.started_at = now
        job.attempts += 1
        job.save(update_fields=["status", "started_at", "attempts"])
        if job.run_id:
            CollectionRun.objects.filter(pk=job.run_id, started_at__isnull=True).update(started_at=now)
        return job, network.next_attempt_at and network.next_attempt_at > now
    return None, False


def public_offer(item):
    offer = item.collected
    return {
        "name": offer.name, "url": offer.url, "price": str(offer.price), "unit": offer.price_unit,
        "club": str(offer.club_price) if offer.club_price is not None else None,
        "condition": item.condition, "availability": item.availability,
    }


def live_result(job):
    started = monotonic()
    with storefront_deadline(started + 8):
        result = search_unit(job.store, configured_query(job.query), deadline=started + 8)
    reason = result.issue
    if any(f"HTTP {code}" in reason for code in BLOCK_CODES):
        status = Status.BLOCKED
    elif reason and not result.offers:
        status = Status.ERROR
    elif result.offers:
        unavailable = all(i.collected.availability == "unavailable" for i in result.offers)
        status = Status.UNAVAILABLE if unavailable else Status.UPDATED
    else:
        status = Status.NO_PRICE if result.unpriced else Status.MISSING
    if job.product_id and result.offers:
        persist_confirmed_offer(job, result)
    data = {
        "reason": reason, "offers": [public_offer(i) for i in result.offers],
        "unpriced": [{"name": i.name, "url": i.url} for i in result.unpriced],
        "observed_at": result.observed_at.isoformat() if result.observed_at else None,
        "duration_ms": int((monotonic() - started) * 1000),
    }
    return status, data


@transaction.atomic
def persist_confirmed_offer(job, result):
    product = Product.objects.select_for_update().get(pk=job.product_id)
    if not product.gtin or Product.objects.filter(gtin=product.gtin, active=True).count() != 1:
        return
    matches = [item.collected for item in result.offers
               if normalize_gtin(item.collected.gtin) == product.gtin]
    if len(matches) != 1:
        return
    offer = matches[0]
    Store.objects.select_for_update().get(pk=job.store_id)
    if Listing.objects.filter(store=job.store, active=True, product=product).exclude(url=offer.url).exists():
        return
    if Listing.objects.filter(store=job.store, external_code=offer.external_code).exclude(url=offer.url).exists():
        return
    listing, _ = Listing.objects.get_or_create(store=job.store, url=offer.url)
    if (not listing.active or listing.product_id not in (None, product.pk)
            or listing.external_code not in ("", offer.external_code)
            or listing.gtin not in ("", product.gtin)):
        return
    if listing.checked_at and listing.checked_at > job.started_at:
        return
    listing.product = product
    listing.gtin = product.gtin
    listing.match_method = Listing.Match.GTIN
    listing.external_code = offer.external_code
    listing.name = offer.name[:255]
    listing.status = Listing.Status.OK
    listing.checked_at = job.started_at
    listing.error = ""
    listing.save()
    fields = dict(price=offer.price, club_price=offer.club_price, price_unit=offer.price_unit,
                  condition=offer.condition, availability=offer.availability,
                  source_url=offer.url, observed_at=result.observed_at or timezone.now())
    if job.run_id:
        Observation.objects.get_or_create(listing=listing, collection_run_id=job.run_id, defaults=fields)
    else:
        Observation.objects.create(listing=listing, **fields)
    Alert.objects.filter(key=f"listing:{listing.pk}", resolved_at__isnull=True).update(
        resolved_at=timezone.now()
    )


def listing_result(job):
    status, message, code = collect_listing(job.listing, collection_run_id=job.run_id)
    if status == Listing.Status.OK:
        observed = Observation.objects.filter(listing=job.listing, collection_run_id=job.run_id).first()
        state = Status.UNAVAILABLE if observed and observed.availability == "unavailable" else Status.UPDATED
        return state, {"reason": ""}
    if status == Listing.Status.CONFLICT:
        return Status.ERROR, {"reason": message, "conflict": True}
    return (Status.BLOCKED if code in BLOCK_CODES else Status.ERROR), {"reason": message}


def listing_alert(job, status, data, now):
    if job.listing_id is None:
        return
    key = f"listing:{job.listing_id}"
    if status in (Status.UPDATED, Status.UNAVAILABLE):
        Alert.objects.filter(key=key, resolved_at__isnull=True).update(resolved_at=now)
    elif status in (Status.BLOCKED, Status.ERROR):
        Alert.objects.update_or_create(key=key, resolved_at=None, defaults={
            "kind": "match" if data.get("conflict") else "collection",
            "product_id": job.listing.product_id, "listing_id": job.listing_id,
            "detail": (data.get("reason") or job.get_status_display())[:300],
        })


@transaction.atomic
def finish_job(job, status, data, *, paused=False):
    now = timezone.now()
    network = NetworkHealth.objects.select_for_update().get(retailer=job.store.retailer)
    current = CollectionJob.objects.select_for_update().get(pk=job.pk)
    if current.status != Status.RUNNING or current.attempts != job.attempts:
        return
    if not paused:
        network.last_status = status
        if status in (Status.ERROR, Status.BLOCKED):
            network.failures = min(network.failures + 1, 20)
            if status == Status.BLOCKED or network.failures >= 3:
                base = 300 if status == Status.BLOCKED else 30
                delay = min(base * 2 ** min(network.failures - 1, 4), 3600)
                network.next_attempt_at = now + timedelta(seconds=delay + random.randint(0, 10))
        else:
            network.failures = 0
            network.next_attempt_at = None
            network.last_success_at = now
        network.save()
    if job.lookup_key and job.run_id is None and status in (Status.UPDATED, Status.UNAVAILABLE):
        MonitoredQuery.objects.update_or_create(key=job.lookup_key, defaults={
            "query": job.query, "last_used_at": now,
        })
    network_key = f"network:{job.store.retailer}"
    if not paused and network.next_attempt_at and network.next_attempt_at > now:
        Alert.objects.update_or_create(key=network_key, resolved_at=None, defaults={
            "kind": "network", "detail": f"{job.store.get_retailer_display()} em pausa. "
            f"{(data.get('reason') or job.get_status_display())[:240]}",
        })
    elif not paused and status not in (Status.ERROR, Status.BLOCKED):
        Alert.objects.filter(key=network_key, resolved_at__isnull=True).update(resolved_at=now)
    current.status = status
    current.result = data
    current.finished_at = now
    current.save(update_fields=["status", "result", "finished_at"])
    listing_alert(job, status, data, now)
    if job.run_id:
        run = CollectionRun.objects.select_for_update().get(pk=job.run_id)
        rows = list(run.jobs.values_list("store__retailer", "status"))
        if not any(state in OPEN for _, state in rows):
            errors = Counter(network for network, state in rows if state in (Status.ERROR, Status.BLOCKED))
            run.stats = {"total": len(rows), "processed": len(rows), "failed": sum(errors.values()),
                         "by_network": dict(errors)}
            run.finished_at = now
            run.save(update_fields=["finished_at", "stats"])


def work_once():
    job, paused = claim_job()
    if job is None:
        return False
    if paused:
        state, data = Status.BLOCKED, {"reason": "Rede em pausa. Tente novamente depois."}
    else:
        try:
            if job.listing_id:
                with storefront_deadline(monotonic() + 8):
                    state, data = listing_result(job)
            else:
                state, data = live_result(job)
        except CollectionError as error:
            state, data = (Status.BLOCKED if error.status in BLOCK_CODES else Status.ERROR), {"reason": str(error)}
        except Exception:
            logger.exception("Falha interna na coleta", extra={"collection_job": job.pk})
            state, data = Status.ERROR, {"reason": "Falha interna na coleta."}
    finish_job(job, state, data, paused=paused)
    logger.info("Coleta concluída", extra={"collection_job": job.pk, "store": job.store_id,
                                          "status": state, "duration_ms": data.get("duration_ms")})
    return True

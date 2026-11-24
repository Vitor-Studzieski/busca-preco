from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import Listing, Observation
from .price_workflow import current_prices
from .workflow_models import Alert, AlertRule


def valid_rule(rule):
    return (
        rule.direction in ("higher", "lower")
        and (rule.amount is not None or rule.percentage is not None)
        and (rule.amount is None or rule.amount > 0)
        and (rule.percentage is None or rule.percentage > 0)
        and rule.window_minutes is not None and rule.window_minutes > 0
        and rule.severity in ("low", "medium", "high")
    )


def evaluate_for_listing(listing, now=None):
    now = now or timezone.now()
    if not settings.PRICING_ENABLE_OWN_PRICES or listing.product_id is None:
        return
    product = listing.product
    price = current_prices(product, now).order_by("-kind", "-starts_at").first()
    own = price.amount if price else product.current_price
    offer = listing.observations.first()
    eligible = (
        own is not None and offer is not None and listing.active and listing.store.active
        and listing.status == Listing.Status.OK and listing.match_method
        and (not listing.gtin or not product.gtin or listing.gtin == product.gtin)
        and (not listing.confirmed_at or offer.observed_at >= listing.confirmed_at)
        and timezone.localdate(offer.observed_at) == timezone.localdate(now)
        and not offer.price_unit and offer.availability != Observation.Availability.UNAVAILABLE
    )
    active = set()
    for rule in AlertRule.objects.filter(enabled=True):
        if not eligible or not valid_rule(rule) or now - offer.observed_at > timedelta(minutes=rule.window_minutes):
            continue
        difference = offer.price - Decimal(own)
        if rule.direction == "lower":
            difference = -difference
        if difference <= 0 or rule.amount is not None and difference < rule.amount:
            continue
        percentage = difference / Decimal(own) * Decimal("100")
        if rule.percentage is not None and percentage < rule.percentage:
            continue
        key = f"price-rule:{rule.pk}:{listing.pk}"
        active.add(key)
        Alert.objects.update_or_create(key=key, resolved_at=None, defaults={
            "kind": "price", "listing": listing, "product": product,
            "detail": f"{rule.title} · {listing.store} · {dict(LEVELS)[rule.severity]}"[:300],
        })
    Alert.objects.filter(listing=listing, kind="price", resolved_at__isnull=True).exclude(
        key__in=active
    ).update(resolved_at=now)


LEVELS = (("low", "Baixa"), ("medium", "Média"), ("high", "Alta"))

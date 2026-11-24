from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Product
from .workflow_models import Alert, AuditLog, DayItem, OwnPrice


def current_prices(product, now=None):
    now = now or timezone.now()
    return product.own_prices.filter(cancelled_at__isnull=True, starts_at__lte=now).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gt=now)
    )


def price_snapshot(price):
    if price is None:
        return None
    return {"amount": str(price.amount), "kind": price.kind, "starts_at": price.starts_at.isoformat(),
            "ends_at": price.ends_at.isoformat() if price.ends_at else None,
            "cancelled_at": price.cancelled_at.isoformat() if price.cancelled_at else None}


@transaction.atomic
def publish_price(product, buyer, values):
    product = Product.objects.select_for_update().get(pk=product.pk, active=True)
    from .selectors import comparison

    _, _, rows = comparison(product, own_amount_override=values["amount"])
    if not rows or not all(row["comparable"] for row in rows):
        raise ValidationError("A publicação exige um preço comparável coletado hoje em cada unidade ativa. Salve como rascunho até atualizar a comparação.")
    candidate = OwnPrice(product=product, buyer=buyer, **values)
    candidate.full_clean()
    overlaps = product.own_prices.filter(kind=candidate.kind, cancelled_at__isnull=True).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gt=candidate.starts_at)
    )
    if candidate.ends_at is not None:
        overlaps = overlaps.filter(starts_at__lt=candidate.ends_at)
    existing = list(overlaps[:2])
    previous = None
    if existing:
        predecessor = existing[0]
        if (len(existing) != 1 or candidate.kind != OwnPrice.Kind.REGULAR
                or predecessor.ends_at is not None or predecessor.starts_at >= candidate.starts_at):
            raise ValidationError("Já existe um preço deste tipo que se sobrepõe à vigência.")
        previous = price_snapshot(predecessor)
        predecessor.ends_at = candidate.starts_at
        predecessor.save(update_fields=["ends_at"])
    candidate.save()
    AuditLog.objects.create(actor=buyer, action="price.publish", object_key=str(product.pk), data={
        "before": previous, "after": price_snapshot(candidate), "reason": candidate.note,
    })
    if candidate.kind == OwnPrice.Kind.PROMOTION:
        DayItem.objects.update_or_create(product=product, day=timezone.localtime(candidate.starts_at).date(),
                                         defaults={"buyer": buyer, "status": DayItem.Status.PUBLISHED})
    from .jobs import enqueue_product_collection

    enqueue_product_collection(product, "price", f"price:{candidate.pk}:publish")
    if candidate.starts_at > timezone.now():
        enqueue_product_collection(product, "effective", f"price:{candidate.pk}:effective",
                                   available_at=candidate.starts_at)
    sync_promotion_alert(candidate)
    return candidate


@transaction.atomic
def cancel_price(price_id, product, buyer, reason):
    Product.objects.select_for_update().get(pk=product.pk)
    price = OwnPrice.objects.select_for_update().get(pk=price_id, product=product, buyer=buyer)
    if price.cancelled_at:
        return
    previous = price_snapshot(price)
    price.cancelled_at = timezone.now()
    price.save(update_fields=["cancelled_at"])
    AuditLog.objects.create(actor=buyer, action="price.cancel", object_key=str(product.pk), data={
        "before": previous, "after": price_snapshot(price), "reason": reason,
    })
    if price.kind == OwnPrice.Kind.PROMOTION:
        DayItem.objects.filter(product=product, day=timezone.localtime(price.starts_at).date(),
                               status=DayItem.Status.PUBLISHED).update(status=DayItem.Status.REVIEW)
    sync_promotion_alert(price)


def sync_promotion_alert(price, now=None):
    if price.kind != OwnPrice.Kind.PROMOTION:
        return
    now = now or timezone.now()
    key = f"promotion:{price.pk}"
    if price.cancelled_at is None and price.starts_at <= now < price.ends_at:
        Alert.objects.get_or_create(key=key, resolved_at=None, defaults={
            "kind": "promotion", "product": price.product, "own_price": price,
            "detail": "Promoção do Pompeia em vigência.",
        })
    else:
        Alert.objects.filter(key=key, resolved_at__isnull=True).update(resolved_at=now)

from datetime import datetime, timezone
from hashlib import sha256
from ipaddress import ip_address
from time import time

from django.conf import settings
from django.core.cache import caches
from django.db import transaction


def client_ip(request):
    remote = request.META.get("REMOTE_ADDR", "")
    if settings.IS_VERCEL:
        forwarded = request.META.get("HTTP_X_VERCEL_FORWARDED_FOR", "")
    elif settings.DJANGO_TRUST_LOCAL_PROXY:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    else:
        return remote
    candidate = forwarded.split(",", 1)[0].strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return remote


def retry_after(scope, identity, *, limit, window):
    bucket, offset = divmod(int(time()), window)
    digest = sha256(str(identity).encode()).hexdigest()
    key = f"{scope}:{digest}:{bucket}"
    if settings.PRICING_REDIS_URL:
        counters = caches["pricing_limits"]
        if counters.add(key, 1, timeout=window + 1):
            return 0
        try:
            count = counters.incr(key)
        except ValueError:
            if counters.add(key, 1, timeout=window + 1):
                return 0
            count = counters.incr(key)
    else:
        from .workflow_models import RateWindow

        with transaction.atomic():
            row, _ = RateWindow.objects.select_for_update().get_or_create(
                key=key, defaults={"expires_at": datetime.fromtimestamp(
                    (bucket + 1) * window, tz=timezone.utc
                )}
            )
            row.count += 1
            row.save(update_fields=["count"])
            count = row.count
    return window - offset if count > limit else 0


def search_retry_after(user_id):
    return retry_after("search-rate", user_id, limit=settings.PRICING_SEARCH_RATE_LIMIT,
                       window=settings.PRICING_SEARCH_RATE_WINDOW)

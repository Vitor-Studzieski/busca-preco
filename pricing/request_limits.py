from hashlib import sha256
from ipaddress import ip_address
from time import time

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    remote = request.META.get("REMOTE_ADDR", "")
    forwarded = request.META.get("HTTP_X_VERCEL_FORWARDED_FOR", "") if settings.IS_VERCEL else ""
    candidate = forwarded.split(",", 1)[0].strip() or remote
    try:
        return str(ip_address(candidate))
    except ValueError:
        return "unknown"


def search_retry_after(request, *, query=None):
    window = settings.PRICING_SEARCH_RATE_WINDOW
    limit = settings.PRICING_SEARCH_RATE_LIMIT
    bucket, offset = divmod(int(time()), window)
    identity = sha256(client_ip(request).encode()).hexdigest()
    key = f"search-rate:{identity}:{bucket}"
    if query is not None:
        normalized = " ".join(query.casefold().split())[:255]
        fingerprint = sha256(normalized.encode()).hexdigest()
        burst_key = f"search-burst:{identity}:{fingerprint}"
        if not cache.add(burst_key, 1, timeout=3):
            count = cache.get(key, 0)
            return window - offset if count > limit else 0
    if cache.add(key, 1, timeout=window + 1):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=window + 1)
            count = 1
    return window - offset if count > limit else 0

from time import time

from django.conf import settings
from django.core.cache import caches


def search_retry_after(user_id):
    """Return the time until the next search window when this account exceeds its limit."""
    window = settings.PRICING_SEARCH_RATE_WINDOW
    now = int(time())
    bucket, offset = divmod(now, window)
    key = f"search-rate:{user_id}:{bucket}"
    counters = caches["pricing_limits"]
    if counters.add(key, 1, timeout=window + 1):
        return 0
    try:
        count = counters.incr(key)
    except ValueError:
        # Recover if the counter was evicted between the add and increment.
        if counters.add(key, 1, timeout=window + 1):
            return 0
        count = counters.incr(key)
    return window - offset if count > settings.PRICING_SEARCH_RATE_LIMIT else 0

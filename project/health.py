from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def readiness(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        if settings.PRICING_REDIS_URL and not cache.touch("pompeia-health", 15):
            cache.set("pompeia-health", True, 15)
    except (DatabaseError, OSError):
        return JsonResponse({"ready": False}, status=503)
    return JsonResponse({"ready": True})

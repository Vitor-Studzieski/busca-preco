from django.http import JsonResponse


def readiness(request):
    return JsonResponse({"status": "ok"})

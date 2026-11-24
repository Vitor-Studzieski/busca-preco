from django.http import HttpResponse
from django.views.decorators.debug import sensitive_post_parameters
from django_otp.admin import OTPAdminSite

from pricing.request_limits import retry_after


class ProtectedAdminSite(OTPAdminSite):
    @sensitive_post_parameters()
    def login(self, request, extra_context=None):
        if request.method == "POST":
            ip = request.META.get("REMOTE_ADDR", "")
            wait = retry_after("admin-login", ip, limit=20, window=900)
            if wait:
                return HttpResponse(
                    "Limite de tentativas atingido. Aguarde antes de tentar novamente.",
                    status=429,
                    headers={"Retry-After": str(wait), "Cache-Control": "no-store"},
                )
        return super().login(request, extra_context)

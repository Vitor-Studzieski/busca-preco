from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.sessions.models import Session
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .workflow_models import AuditLog, BuyerDevice


def track_session(request):
    if not request.session.session_key:
        request.session.save()
    BuyerDevice.objects.update_or_create(session_id=request.session.session_key, defaults={
        "buyer": request.user,
        "browser": request.headers.get("User-Agent", "")[:180],
        "last_seen_at": timezone.now(),
    })


class PortalSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.session_key:
            BuyerDevice.objects.filter(
                buyer=request.user, session_id=request.session.session_key,
                last_seen_at__lt=timezone.now() - timedelta(minutes=15),
            ).update(last_seen_at=timezone.now())
        response = self.get_response(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


@login_required
@never_cache
@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@require_http_methods(["GET", "POST"])
def devices(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        current = request.session.session_key
        form.save()
        revoke_other_sessions(request.user, current)
        update_session_auth_hash(request, request.user)
        track_session(request)
        AuditLog.objects.create(actor=request.user, action="account.password_change")
        messages.success(request, "Senha atualizada. Os outros dispositivos foram desconectados.")
        return redirect("buyer_devices")
    rows = BuyerDevice.objects.filter(buyer=request.user, session__expire_date__gt=timezone.now()).order_by(
        "-last_seen_at"
    )
    return render(request, "registration/devices.html", {"rows": rows, "form": form})


def revoke_other_sessions(user, current):
    keys = BuyerDevice.objects.filter(buyer=user).exclude(session_id=current).values_list("session_id", flat=True)
    Session.objects.filter(pk__in=list(keys)).delete()


@login_required
@never_cache
@sensitive_post_parameters("password")
@require_POST
def revoke_device(request, pk=None):
    if pk is not None:
        device = get_object_or_404(BuyerDevice, pk=pk, buyer=request.user)
        if device.session_id == request.session.session_key:
            logout(request)
            return redirect("login")
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Confirme sua senha para encerrar outras sessões.")
        return redirect("buyer_devices")
    if pk is None:
        revoke_other_sessions(request.user, request.session.session_key)
        AuditLog.objects.create(actor=request.user, action="session.revoke_others")
    else:
        device.session.delete()
        AuditLog.objects.create(actor=request.user, action="session.revoke")
    return redirect("buyer_devices")

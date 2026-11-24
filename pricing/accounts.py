from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Permission
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .access import track_session
from .models import InitialAccountSetup
from .request_limits import client_ip, retry_after
from .workflow_models import AuditLog

LOCAL_ADDRESSES = {"127.0.0.1", "::1"}


def setup_available():
    return not InitialAccountSetup.objects.exists() and not get_user_model().objects.exists()


def local_development_request(request):
    if not settings.DEBUG or request.META.get("REMOTE_ADDR") not in LOCAL_ADDRESSES:
        return False
    if any(header in request.META for header in (
        "HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_HOST",
    )):
        return False
    return urlsplit(f"//{request.get_host()}").hostname in LOCAL_ADDRESSES | {"localhost"}


class BuyerAuthenticationForm(AuthenticationForm):
    remember = forms.BooleanField(label="Manter conectado neste dispositivo", required=False, initial=True)


class SignInView(LoginView):
    authentication_form = BuyerAuthenticationForm
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        if local_development_request(request) and setup_available():
            return redirect("initial_setup")
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip().casefold()[:150]
        ip = client_ip(request)
        delay = retry_after("signin-ip", ip, limit=60, window=900)
        if username:
            delay = max(delay, retry_after("signin-account", (ip, username), limit=10, window=900))
        if delay:
            response = self.render_to_response(self.get_context_data(form=self.get_form()), status=429)
            response["Retry-After"] = str(delay)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE if form.cleaned_data["remember"] else 0)
        self.request.session["persistent_buyer_session"] = form.cleaned_data["remember"]
        self.request.session.save()
        track_session(self.request)
        AuditLog.objects.create(actor=self.request.user, action="signin.ok")
        return response

    def form_invalid(self, form):
        AuditLog.objects.create(action="signin.failed")
        return super().form_invalid(form)



@sensitive_post_parameters("password1", "password2")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def initial_setup(request):
    if not local_development_request(request) or not setup_available():
        return redirect("login")

    form = UserCreationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                # Insert the singleton first so competing requests cannot both create an administrator.
                InitialAccountSetup.objects.create(pk=1)
                if get_user_model().objects.exists():
                    transaction.set_rollback(True)
                    return redirect("login")
                user = form.save(commit=False)
                user.is_staff = user.is_superuser = True
                user.save()
        except IntegrityError:
            if setup_available():
                raise
            return redirect("login")
        login(request, user)
        messages.success(request, "Conta de administrador criada.")
        return redirect("pricing:search")

    return render(request, "registration/account_form.html", {
        "form": form,
        "heading": "Criar primeira conta",
        "description": "Defina o usuário e a senha do administrador do sistema.",
        "button_label": "Criar conta e entrar",
    })


@login_required
@sensitive_post_parameters("password1", "password2")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def add_buyer(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    form = UserCreationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            buyer = form.save()
            permissions = Permission.objects.filter(content_type__app_label="pricing").filter(
                Q(content_type__model="product", codename="view_product")
                | Q(content_type__model="pricedraft", codename="add_pricedraft")
            )
            buyer.user_permissions.add(*permissions)
        messages.success(request, f"Conta de {buyer.get_username()} criada.")
        return redirect("add_buyer")

    return render(request, "registration/account_form.html", {
        "form": form,
        "heading": "Cadastrar comprador",
        "description": "A conta pode consultar preços e salvar rascunhos.",
        "button_label": "Cadastrar comprador",
    })

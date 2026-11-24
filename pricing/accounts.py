from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
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

from .models import InitialAccountSetup


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


class SignInView(LoginView):
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        if local_development_request(request) and setup_available():
            return redirect("initial_setup")
        return super().get(request, *args, **kwargs)


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

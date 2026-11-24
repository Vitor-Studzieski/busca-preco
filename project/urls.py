from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from pricing.access import devices, revoke_device
from pricing.accounts import SignInView, add_buyer, initial_setup
from project.health import readiness

urlpatterns = [
    path("healthz/", readiness, name="healthz"),
    path(settings.PORTAL_ADMIN_PATH, admin.site.urls),
    path("entrar/", SignInView.as_view(extra_context={
        "heading": "Entrar",
        "description": "Acesse a precificação do Pompeia.",
        "button_label": "Entrar",
    }), name="login"),
    path("dispositivos/", devices, name="buyer_devices"),
    path("dispositivos/<int:pk>/revogar/", revoke_device, name="revoke_device"),
    path("dispositivos/revogar-outros/", revoke_device, name="revoke_other_devices"),
    path("sair/", login_required(LogoutView.as_view()), name="logout"),
    path("", include("pricing.urls")),
]

if settings.ALLOW_DEV_PROVISIONING:
    urlpatterns += [
        path("configurar-acesso/", initial_setup, name="initial_setup"),
        path("compradores/novo/", add_buyer, name="add_buyer"),
    ]

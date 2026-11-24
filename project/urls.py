from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from pricing.accounts import SignInView, add_buyer, initial_setup


urlpatterns = [
    path("admin/", admin.site.urls),
    path("entrar/", SignInView.as_view(extra_context={
        "heading": "Entrar",
        "description": "Acesse a precificação do Pompeia.",
        "button_label": "Entrar",
    }), name="login"),
    path("configurar-acesso/", initial_setup, name="initial_setup"),
    path("compradores/novo/", add_buyer, name="add_buyer"),
    path("sair/", login_required(LogoutView.as_view()), name="logout"),
    path("", include("pricing.urls")),
]

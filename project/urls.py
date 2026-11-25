from django.urls import include, path

from .health import readiness

urlpatterns = [
    path("healthz/", readiness, name="healthz"),
    path("", include("pricing.urls")),
]

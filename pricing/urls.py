from django.urls import path

from . import storefront

app_name = "pricing"
urlpatterns = [
    path("", storefront.home, name="storefront"),
]

from django.urls import path

from . import storefront

app_name = "pricing"
urlpatterns = [
    path("", storefront.home, name="storefront"),
    path("comparar/", storefront.compare, name="storefront_compare"),
    path("promocoes/", storefront.promotions, name="storefront_promotions"),
]

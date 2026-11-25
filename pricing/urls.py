from django.urls import path

from . import storefront

app_name = "pricing"
urlpatterns = [
    path("api/search/", storefront.unit_search, name="unit-search"),
    path("", storefront.home, name="storefront"),
]

from django.urls import path

from . import views

app_name = "pricing"
urlpatterns = [
    path("", views.search, name="search"),
    path("dashboard/", views.dashboard, {"section": "overview"}, name="dashboard"),
    path("dashboard/comparativos/", views.dashboard, {"section": "comparisons"},
         name="dashboard_comparisons"),
    path("dashboard/promocoes/", views.dashboard, {"section": "promotions"},
         name="dashboard_promotions"),
    path("dashboard/mercadologico/", views.dashboard, {"section": "mercadologico"},
         name="dashboard_merchandising"),
    path("dashboard/alertas/", views.dashboard, {"section": "alerts"},
         name="dashboard_alerts"),
    path("produtos/<int:pk>/", views.product_detail, name="product"),
]

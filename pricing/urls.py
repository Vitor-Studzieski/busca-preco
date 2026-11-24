from django.urls import path

from . import portal, views

app_name = "pricing"
urlpatterns = [
    path("", portal.search, name="search"),
    path("pesquisa/sugestoes/", portal.suggestions, name="suggestions"),
    path("pesquisa/atualizar/", portal.refresh, name="refresh"),
    path("pesquisa/progresso/", portal.progress, name="progress"),
    path("fila/", portal.day_queue, name="day_queue"),
    path("fila/<int:pk>/", portal.queue_action, name="queue_action"),
    path("alertas/", portal.alerts, name="alerts"),
    path("alertas/<int:pk>/reconhecer/", portal.acknowledge, name="acknowledge"),
    path("coletas/", portal.collection_health, name="health"),
    path("dashboard/", portal.former_page, name="dashboard"),
    path("dashboard/comparativos/", portal.former_page, name="dashboard_comparisons"),
    path("dashboard/promocoes/", portal.former_page, name="dashboard_promotions"),
    path("dashboard/mercadologico/", portal.former_page, name="dashboard_merchandising"),
    path("dashboard/alertas/", portal.alerts, name="dashboard_alerts"),
    path("produtos/<int:pk>/", views.product_detail, name="product"),
    path("produtos/<int:pk>/publicar/", portal.publish, name="publish"),
    path("produtos/<int:pk>/precos/<int:price_id>/cancelar/", portal.cancel, name="cancel_price"),
]

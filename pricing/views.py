from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods

from .forms import PriceDraftForm
from .identifiers import normalize_gtin, search_text
from .models import Listing, Observation, Product, Store
from .offer_search import search_stores
from .request_limits import search_retry_after
from .services import comparison_rows


def _listing_snapshot_queryset():
    latest = Observation.objects.filter(listing=OuterRef("pk")).order_by("-observed_at", "-pk")
    return Listing.objects.select_related("store", "product").annotate(
        latest_price=Subquery(latest.values("price")[:1]),
        latest_condition=Subquery(latest.values("condition")[:1]),
        latest_observed_at=Subquery(latest.values("observed_at")[:1]),
    )


@login_required
@permission_required("pricing.view_product", raise_exception=True)
@never_cache
@require_GET
def search(request):
    query = request.GET.get("q", "").strip()[:255]
    products, store_results = [], []
    if query:
        retry_after = search_retry_after(request.user.pk)
        if retry_after:
            response = render(request, "pricing/search.html", {
                "query": query, "retry_after": retry_after,
            }, status=429)
            response["Retry-After"] = retry_after
            return response
        criteria = Q(sku__iexact=query)
        normalized = search_text(query)
        if normalized:
            criteria |= Q(search_name__contains=normalized)
        gtin = normalize_gtin(query)
        if gtin:
            criteria |= Q(gtin=gtin)
        products = list(Product.objects.filter(criteria)[:51])
        retailer_query = query
        if len(products) == 1 and (products[0].sku.casefold() == query.casefold() or gtin):
            retailer_query = f"{products[0].name} {products[0].package}"
        store_results = search_stores(list(Store.objects.all()), retailer_query)
    return render(request, "pricing/search.html", {
        "query": query, "products": products[:50], "more_results": len(products) > 50,
        "store_results": store_results,
    })


@login_required
@permission_required("pricing.view_product", raise_exception=True)
@never_cache
@require_GET
def dashboard(request, section):
    now = timezone.now()
    cutoff = now - timedelta(hours=settings.OFFER_MAX_AGE_HOURS)
    snapshots = _listing_snapshot_queryset()
    context = {
        "section": section,
        "refreshed_at": Observation.objects.order_by("-observed_at", "-pk")
                                      .values_list("observed_at", flat=True).first(),
        "offer_max_age_hours": settings.OFFER_MAX_AGE_HOURS,
    }
    issue_filter = (
        Q(status__in=(Listing.Status.PENDING, Listing.Status.ERROR, Listing.Status.CONFLICT))
        | Q(latest_observed_at__isnull=True)
        | Q(latest_observed_at__lt=cutoff)
    )

    if section == "overview":
        recent_promotions = snapshots.filter(
            status=Listing.Status.OK,
            latest_condition__in=(Observation.Condition.PROMOTION, Observation.Condition.CLUB),
            latest_observed_at__gte=cutoff,
        )
        context.update({
            "page_title": "Visão geral",
            "page_description": "Resumo dos registros atuais do banco de preços.",
            "product_count": Product.objects.count(),
            "store_count": Store.objects.count(),
            "observations_today": Observation.objects.filter(
                observed_at__date=timezone.localdate()
            ).count(),
            "promotion_count": recent_promotions.count(),
            "alert_count": snapshots.filter(issue_filter).count(),
            "recent_observations": Observation.objects.select_related(
                "listing__store", "listing__product"
            ).order_by("-observed_at", "-pk")[:12],
        })

    elif section == "comparisons":
        query = request.GET.get("q", "").strip()[:255]
        products, selected_product, rows = [], None, []
        if query:
            criteria = Q(sku__iexact=query)
            normalized = search_text(query)
            if normalized:
                criteria |= Q(search_name__contains=normalized)
            gtin = normalize_gtin(query)
            if gtin:
                criteria |= Q(gtin=gtin)
            products = list(Product.objects.filter(criteria).order_by("name", "package")[:51])
            if len(products) == 1:
                selected_product = products[0]
                rows = list(comparison_rows(selected_product, now))
        context.update({
            "page_title": "Comparativos",
            "page_description": "Compare o preço vigente do Pompeia com as últimas observações por unidade.",
            "query": query, "products": products[:50], "more_results": len(products) > 50,
            "selected_product": selected_product, "comparison_rows": rows,
        })

    elif section == "promotions":
        promotions = snapshots.filter(
            status=Listing.Status.OK,
            latest_condition__in=(Observation.Condition.PROMOTION, Observation.Condition.CLUB),
            latest_observed_at__gte=cutoff,
        ).order_by("-latest_observed_at")
        promotion_rows = list(promotions[:100])
        condition_labels = dict(Observation.Condition.choices)
        for listing in promotion_rows:
            listing.condition_label = condition_labels.get(
                listing.latest_condition, "Condição não identificada"
            )
        context.update({
            "page_title": "Promoções concorrentes",
            "page_description": "Ofertas identificadas nos registros mais recentes dos supermercados.",
            "promotion_count": promotions.count(), "promotion_rows": promotion_rows,
        })

    elif section == "mercadologico":
        context.update({
            "page_title": "Mercadológico",
            "page_description": "Produtos existentes no catálogo do Pompeia e disponibilidade da classificação.",
            "products": Product.objects.order_by("name", "package", "sku")[:100],
            "product_count": Product.objects.count(),
        })

    elif section == "alerts":
        alert_query = snapshots.filter(issue_filter).order_by("store_id", "product__name", "pk")
        alerts = list(alert_query[:200])
        for listing in alerts:
            if listing.status in (Listing.Status.CONFLICT, Listing.Status.ERROR):
                listing.alert_reason = listing.error or listing.get_status_display()
            elif listing.status == Listing.Status.PENDING:
                listing.alert_reason = listing.get_status_display()
            elif listing.latest_observed_at is None:
                listing.alert_reason = "Nenhum preço observado"
            else:
                listing.alert_reason = "Preço fora da janela de atualização"
        context.update({
            "page_title": "Alertas",
            "page_description": "Pendências reais de coleta, divergências e preços desatualizados.",
            "alerts": alerts, "alert_count": alert_query.count(),
            "alert_limit_reached": alert_query.count() > 200,
        })

    return render(request, "pricing/dashboard.html", context)


@login_required
@permission_required("pricing.view_product", raise_exception=True)
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    can_draft = request.user.has_perm("pricing.add_pricedraft")
    if request.method == "POST" and not can_draft:
        return render(request, "403.html", status=403)
    form = PriceDraftForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        draft = form.save(commit=False)
        draft.product = product
        draft.author = request.user
        draft.save()
        messages.success(request, "Rascunho de preço salvo.")
        return redirect("pricing:product", pk=pk)
    return render(request, "pricing/product.html", {
        "product": product, "rows": list(comparison_rows(product, timezone.now())),
        "drafts": product.price_drafts.select_related("author")[:10] if can_draft else [],
        "can_draft": can_draft, "form": form,
    })


from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import OuterRef, Subquery
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import PublishPriceForm
from .jobs import OPEN, enqueue_product_collection, enqueue_search, normalized_lookup
from .models import Product, Store
from .price_workflow import cancel_price, publish_price
from .request_limits import search_retry_after
from .selectors import comparison, find_products
from .workflow_models import (
    Alert,
    AlertAcknowledgment,
    CollectionJob,
    CollectionRun,
    DayItem,
    MonitoredQuery,
    NetworkHealth,
    OwnPrice,
)

portal_access = permission_required("pricing.view_product", raise_exception=True)
price_access = permission_required("pricing.add_pricedraft", raise_exception=True)
TOKEN_SCOPE = "pricing.collection.poll"


def text_query(source):
    return source.get("q", "").strip()[:255]


@login_required
@portal_access
@never_cache
@require_GET
def search(request):
    query = text_query(request.GET)
    product_id = request.GET.get("produto")
    products = find_products(query) if settings.PRICING_ENABLE_OWN_PRICES else []
    if product_id and settings.PRICING_ENABLE_OWN_PRICES:
        if not product_id.isascii() or not product_id.isdigit() or len(product_id) > 18:
            raise Http404
        product = get_object_or_404(Product, pk=int(product_id), active=True)
    else:
        product = products[0] if len(products) == 1 else None
    price, amount, rows = comparison(product) if product else (None, None, [])
    result_query = f"{product.name} {product.package}" if product else query
    cached = {}
    if result_query:
        latest = CollectionJob.objects.filter(
            lookup_key=normalized_lookup(result_query), store__active=True,
            status__in=(CollectionJob.Status.UPDATED, CollectionJob.Status.UNAVAILABLE),
        )
        latest_for_store = latest.filter(store_id=OuterRef("pk")).order_by("-finished_at", "-pk")
        latest_ids = Store.objects.filter(active=True).annotate(
            cache_id=Subquery(latest_for_store.values("pk")[:1])
        ).values_list("cache_id", flat=True)
        for job in CollectionJob.objects.filter(pk__in=latest_ids):
            cached.setdefault(job.store_id, job)
    stores = [row["store"] for row in rows] if product else list(
        Store.objects.filter(active=True).order_by("display_order", "pk")
    ) if query else []
    for job in cached.values():
        job.fresh = bool(job.finished_at and timezone.localtime(job.finished_at).date() == timezone.localdate())
    cached_rows = [(store, cached.get(store.pk)) for store in stores]
    return render(request, "pricing/workbench.html", {
        "query": query, "recent_queries": request.session.get("recent_queries", []), "cached_rows": cached_rows, "own_enabled": settings.PRICING_ENABLE_OWN_PRICES, "products": products, "product": product, "price": price, "amount": amount,
        "rows": rows, "stores": stores,
        "configured": (not settings.PRICING_ENABLE_OWN_PRICES
                       or bool(product or Product.objects.filter(active=True).exists())),
        "publish_ready": bool(rows and all(row["comparable"] for row in rows)),
    })


@login_required
@portal_access
@never_cache
@require_GET
def suggestions(request):
    query = text_query(request.GET)
    items = []
    if len(query) >= 2:
        if settings.PRICING_ENABLE_OWN_PRICES:
            items = [{"value": p.sku, "label": f"{p.name} · {p.package} · {p.sku}"}
                     for p in find_products(query, limit=8)]
        else:
            terms = MonitoredQuery.objects.filter(query__icontains=query).order_by("-last_used_at")[:8]
            items = [{"value": row.query, "label": row.query} for row in terms]
    return JsonResponse({"items": items})


@login_required
@portal_access
@never_cache
@require_POST
def refresh(request):
    query = text_query(request.POST)
    product = None
    raw_product = request.POST.get("product", "")
    store = None
    raw_store = request.POST.get("store", "")
    if raw_product:
        if not settings.PRICING_ENABLE_OWN_PRICES:
            raise Http404
        if not raw_product.isascii() or not raw_product.isdigit() or len(raw_product) > 18:
            raise Http404
        product = get_object_or_404(Product, pk=int(raw_product), active=True)
        query = f"{product.name} {product.package}"
    if raw_store:
        if not raw_store.isascii() or not raw_store.isdigit() or len(raw_store) > 18:
            raise Http404
        store = get_object_or_404(Store, pk=int(raw_store), active=True)
    if not query:
        return JsonResponse({"message": "Informe um produto."}, status=400)
    retry = search_retry_after(request.user.pk)
    if retry:
        return JsonResponse({"message": "Limite de buscas atingido. Tente novamente em alguns instantes."},
                            status=429, headers={"Retry-After": str(retry)})
    jobs = enqueue_search(query, product=product, store_id=store.pk if store else None, force=bool(store))
    if jobs and not store:
        last_queries = request.session.get("recent_queries", [])
        request.session["recent_queries"] = [query] + [item for item in last_queries if item != query][:5]
    token = signing.dumps({"buyer": request.user.pk, "jobs": [job.pk for job in jobs]}, salt=TOKEN_SCOPE)
    return JsonResponse({"token": token, "jobs": [job.store_id for job in jobs]}, status=202)


@login_required
@portal_access
@never_cache
@require_GET
def progress(request):
    try:
        token = signing.loads(request.GET.get("token", ""), salt=TOKEN_SCOPE, max_age=600)
    except signing.BadSignature as error:
        raise Http404 from error
    if token["buyer"] != request.user.pk:
        raise Http404
    jobs = list(CollectionJob.objects.filter(pk__in=token["jobs"]).order_by("store_id"))
    return JsonResponse({"complete": all(job.status not in OPEN for job in jobs),
                         "rows": [{"store": job.store_id, "state": job.status,
                                   "label": job.get_status_display(), **job.result} for job in jobs]})


@login_required
@portal_access
@never_cache
@require_GET
def day_queue(request):
    today = timezone.localdate()
    rows = DayItem.objects.filter(day=today).select_related("product", "buyer").order_by("product__name")
    status = request.GET.get("status", "")
    return render(request, "pricing/queue.html", {
        "rows": rows.filter(status=status) if status in DayItem.Status.values else rows,
        "total": rows.count(), "reviewed": rows.exclude(status=DayItem.Status.PENDING).count(),
        "statuses": DayItem.Status.choices, "status": status, "today": today,
        "own_enabled": settings.PRICING_ENABLE_OWN_PRICES,
        "monitored": MonitoredQuery.objects.order_by("-last_used_at")[:100],
    })


@login_required
@portal_access
@price_access
@never_cache
@require_POST
def queue_action(request, pk):
    product = get_object_or_404(Product, pk=pk, active=True)
    today = timezone.localdate()
    action = request.POST.get("action")
    if action == "add":
        DayItem.objects.get_or_create(day=today, product=product, defaults={"buyer": request.user})
        messages.success(request, "Produto incluído na fila de hoje.")
    elif action == "review":
        DayItem.objects.filter(day=today, product=product, status=DayItem.Status.PENDING).update(
            status=DayItem.Status.REVIEW, buyer=request.user
        )
    elif action == "collect":
        window = int(timezone.now().timestamp()) // 300
        enqueue_product_collection(product, "manual", f"manual:{product.pk}:{window}")
        messages.success(request, "Atualização enfileirada.")
    else:
        raise Http404
    return redirect("pricing:day_queue")


@login_required
@portal_access
@never_cache
@require_GET
def alerts(request):
    rows = Alert.objects.filter(resolved_at__isnull=True).select_related("product", "listing__store")
    return render(request, "pricing/alerts.html", {
        "rows": rows.order_by("-opened_at")[:100],
        "acknowledged": set(AlertAcknowledgment.objects.filter(buyer=request.user).values_list("alert_id", flat=True)),
    })


@login_required
@portal_access
@never_cache
@require_POST
def acknowledge(request, pk):
    alert = get_object_or_404(Alert, pk=pk, resolved_at__isnull=True)
    AlertAcknowledgment.objects.get_or_create(alert=alert, buyer=request.user)
    return redirect("pricing:alerts")


@login_required
@portal_access
@never_cache
@require_GET
def collection_health(request):
    status = {row.retailer: row for row in NetworkHealth.objects.all()}
    runs = CollectionRun.objects.order_by("-created_at")[:20]
    return render(request, "pricing/health.html", {
        "networks": [(label, status.get(code)) for code, label in Store.Retailer.choices], "runs": runs,
    })


@login_required
@portal_access
@price_access
@never_cache
@require_POST
def publish(request, pk):
    if not settings.PRICING_ENABLE_OWN_PRICES:
        raise Http404
    product = get_object_or_404(Product, pk=pk, active=True)
    form = PublishPriceForm(request.POST)
    if form.is_valid():
        try:
            publish_price(product, request.user, form.cleaned_data)
        except (ValidationError, IntegrityError) as error:
            messages.error(request, error.messages[0] if isinstance(error, ValidationError)
                           else "Não foi possível publicar. Revise a vigência.")
        else:
            messages.success(request, "Preço registrado no portal.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("pricing:product", pk=pk)


@login_required
@portal_access
@price_access
@never_cache
@require_POST
def cancel(request, pk, price_id):
    if not settings.PRICING_ENABLE_OWN_PRICES:
        raise Http404
    reason = request.POST.get("reason", "").strip()
    if not reason or len(reason) > 500:
        messages.error(request, "Informe o motivo do cancelamento em até 500 caracteres.")
    else:
        try:
            cancel_price(price_id, get_object_or_404(Product, pk=pk), request.user, reason)
        except OwnPrice.DoesNotExist as error:
            raise Http404 from error
        messages.success(request, "Preço cancelado.")
    return redirect("pricing:product", pk=pk)


@login_required
@portal_access
@never_cache
@require_GET
def former_page(request):
    if request.resolver_match.url_name == "dashboard_comparisons":
        return redirect(reverse("pricing:search") + ("?" + request.GET.urlencode() if request.GET else ""))
    return redirect("pricing:day_queue")

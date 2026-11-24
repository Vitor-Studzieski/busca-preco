from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Subquery
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .jobs import enqueue_product_collection, enqueue_search
from .models import Listing, Observation, Store
from .workflow_models import Alert, CollectionJob, CollectionRun, DayItem, MonitoredQuery

view_access = permission_required("pricing.view_product", raise_exception=True)
SESSION_KEY = "buyer_queue_filters"


def read_filters(data):
    order = data.get("order", "")
    network = data.get("network", "")
    status = data.get("status", "")
    return {
        "order": order if order in ("newest", "name", "status") else "newest",
        "network": network if network in Store.Retailer.values else "",
        "status": status if status in DayItem.Status.values else "",
        "issues": data.get("issues") == "1",
        "missing": data.get("missing") == "1",
        "promotion": data.get("promotion") == "1",
    }


def monitored_rows(filters, today):
    jobs = CollectionJob.objects.filter(lookup_key=OuterRef("key"), store__active=True)
    if filters["network"]:
        jobs = jobs.filter(store__retailer=filters["network"])
    latest = jobs.order_by("-finished_at", "-pk").filter(finished_at__isnull=False)
    newest = CollectionJob.objects.filter(
        lookup_key=OuterRef("lookup_key"), store_id=OuterRef("store_id"), finished_at__isnull=False
    ).order_by("-finished_at", "-pk")
    current = latest.filter(pk=Subquery(newest.values("pk")[:1]))
    listing = MonitoredQuery.objects.annotate(
        collected=Exists(current.filter(status=CollectionJob.Status.UPDATED, finished_at__date=today)),
        has_network=Exists(jobs), with_issue=Exists(current.filter(
            status__in=(CollectionJob.Status.BLOCKED, CollectionJob.Status.ERROR, CollectionJob.Status.NO_PRICE)
        )),
    )
    if filters["issues"]:
        listing = listing.filter(with_issue=True)
    if filters["missing"]:
        listing = listing.filter(collected=False)
    if filters["network"]:
        listing = listing.filter(has_network=True)
    order = "query" if filters["order"] == "name" else "-last_used_at"
    return listing.order_by(order, "pk")


def own_rows(base, filters, today):
    listings = Listing.objects.filter(product=OuterRef("product_id"), active=True, store__active=True)
    if filters["network"]:
        listings = listings.filter(store__retailer=filters["network"])
    recent = Observation.objects.filter(listing__product=OuterRef("product_id"),
                                       listing__active=True, observed_at__date=today)
    if filters["network"]:
        recent = recent.filter(listing__store__retailer=filters["network"])
    rows = base.annotate(collected=Exists(recent), has_network=Exists(listings), with_issue=Exists(
        listings.filter(status__in=(Listing.Status.CONFLICT, Listing.Status.ERROR))
    ))
    if filters["status"]:
        rows = rows.filter(status=filters["status"])
    if filters["network"]:
        rows = rows.filter(has_network=True)
    if filters["issues"]:
        rows = rows.filter(with_issue=True)
    if filters["missing"]:
        rows = rows.filter(collected=False)
    if filters["promotion"]:
        rows = rows.filter(product__own_prices__kind="promotion", product__own_prices__starts_at__date__lte=today,
                           product__own_prices__ends_at__gt=timezone.localtime().replace(
                               hour=0, minute=0, second=0, microsecond=0
                           ), product__own_prices__cancelled_at__isnull=True).distinct()
    order = {"name": "product__name", "status": "status", "newest": "-pk"}[filters["order"]]
    return rows.order_by(order, "pk")


@login_required
@view_access
@never_cache
@require_GET
def day_queue(request):
    today = timezone.localdate()
    own_enabled = settings.PRICING_ENABLE_OWN_PRICES
    filters = read_filters(request.GET) if request.GET.get("filtered") else request.session.get(
        SESSION_KEY, read_filters({})
    )
    base = DayItem.objects.filter(day=today, product__active=True).select_related("product", "buyer")
    total = base.count() if own_enabled else MonitoredQuery.objects.count()
    pending = base.filter(status=DayItem.Status.PENDING).count() if own_enabled else None
    data = own_rows(base, filters, today) if own_enabled else monitored_rows(filters, today)
    page = Paginator(data, 25).get_page(request.GET.get("pagina"))
    parameters = request.GET.copy()
    parameters.pop("pagina", None)
    return render(request, "pricing/queue.html", {
        "page": page, "filters": filters, "own_enabled": own_enabled,
        "today": today, "total": total, "reviewed": total - pending if pending is not None else None,
        "pending": pending, "statuses": DayItem.Status.choices, "networks": Store.Retailer.choices,
        "alerts_open": Alert.objects.filter(resolved_at__isnull=True).count(),
        "latest_run": CollectionRun.objects.filter(finished_at__isnull=False).order_by("-finished_at").first(),
        "paging_query": parameters.urlencode(),
    })


@login_required
@view_access
@never_cache
@require_POST
def queue_settings(request):
    request.session[SESSION_KEY] = read_filters(request.POST)
    messages.success(request, "Filtros da fila salvos nesta sessão.")
    return redirect("pricing:day_queue")


@login_required
@view_access
@never_cache
@require_POST
def queue_batch(request):
    raw = request.POST.getlist("selected")
    if len(raw) > 25 or any(not i.isascii() or not i.isdigit() or len(i) > 18 for i in raw):
        messages.error(request, "Selecione até 25 itens da fila.")
        return redirect("pricing:day_queue")
    if not raw or request.POST.get("confirm") != "1":
        messages.error(request, "Selecione os itens e confirme a atualização.")
        return redirect("pricing:day_queue")
    ids = {int(i) for i in raw}
    if settings.PRICING_ENABLE_OWN_PRICES:
        if not request.user.has_perm("pricing.add_pricedraft"):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        rows = DayItem.objects.filter(pk__in=ids, day=timezone.localdate(), product__active=True)
        for item in rows.select_related("product"):
            window = int(timezone.now().timestamp()) // 300
            enqueue_product_collection(item.product, "manual", f"manual:{item.product_id}:{window}")
    else:
        rows = MonitoredQuery.objects.filter(pk__in=ids)
        for item in rows:
            enqueue_search(item.query)
    messages.success(request, f"Atualização solicitada para {rows.count()} item(ns).")
    return redirect("pricing:day_queue")

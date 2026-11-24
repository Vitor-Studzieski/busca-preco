from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .forms import PriceDraftForm, PublishPriceForm
from .models import Product
from .selectors import comparison
from .services import comparison_rows


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
        if request.POST.get("return_to_search") and settings.PRICING_ENABLE_OWN_PRICES:
            return redirect(reverse("pricing:search") + f"?produto={pk}")
        return redirect("pricing:product", pk=pk)
    price, amount, compared = comparison(product)
    return render(request, "pricing/product.html", {
        "product": product, "rows": list(comparison_rows(product, timezone.now())),
        "drafts": product.price_drafts.select_related("author")[:10] if can_draft else [],
        "can_draft": can_draft, "form": form, "price": price, "amount": amount,
        "publish_ready": bool(compared and all(row["eligible"] for row in compared)),
        "publish_form": PublishPriceForm(), "own_enabled": settings.PRICING_ENABLE_OWN_PRICES,
        "own_prices": product.own_prices.order_by("-starts_at")[:15],
    })

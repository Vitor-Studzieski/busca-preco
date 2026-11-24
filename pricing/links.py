from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .identifiers import normalize_gtin
from .models import Listing, Product, Store
from .workflow_models import AuditLog


@login_required
@permission_required(("pricing.view_product", "pricing.add_pricedraft"), raise_exception=True)
@never_cache
@require_POST
def change_link(request, pk, listing_id):
    from django.http import Http404

    if not settings.PRICING_ENABLE_OWN_PRICES:
        raise Http404
    action = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()
    destination = reverse("pricing:search") + f"?produto={pk}"
    if action not in ("confirm", "detach") or not reason or len(reason) > 300:
        messages.error(request, "Informe a ação e um motivo de até 300 caracteres.")
        return redirect(destination)
    try:
        with transaction.atomic():
            product = get_object_or_404(Product.objects.select_for_update(), pk=pk, active=True)
            listing = get_object_or_404(Listing, pk=listing_id, active=True, store__active=True)
            Store.objects.select_for_update().get(pk=listing.store_id)
            listing = Listing.objects.select_for_update().get(pk=listing_id)
            before = listing.product_id
            if action == "detach":
                if before != pk:
                    raise Http404
                listing.product = None
                listing.match_method = ""
            else:
                listing_gtin = normalize_gtin(listing.gtin)
                exact = bool(product.gtin and listing_gtin == product.gtin
                             and Product.objects.filter(active=True, gtin=product.gtin).count() == 1)
                if listing.gtin and product.gtin and listing_gtin != product.gtin:
                    messages.error(request, "O GTIN do anúncio diverge do cadastro do Pompeia.")
                    return redirect(destination)
                if (not listing.external_code or listing.status != Listing.Status.OK
                        or not exact and not settings.PRICING_ALLOW_MANUAL_LINKS):
                    messages.error(request, "É preciso confirmar o GTIN e a identidade da oferta.")
                    return redirect(destination)
                if Listing.objects.filter(store_id=listing.store_id, product=product, active=True).exclude(
                    pk=listing.pk
                ).exists():
                    messages.error(request, "Já há outro anúncio vinculado nesta unidade. Revise o vínculo atual.")
                    return redirect(destination)
                listing.product = product
                listing.match_method = Listing.Match.GTIN if exact else Listing.Match.MANUAL
                if exact:
                    listing.gtin = listing_gtin
            listing.confirmed_by = request.user
            if before != listing.product_id or action == "detach":
                listing.confirmed_at = timezone.now()
            listing.save(update_fields=["product", "gtin", "match_method", "confirmed_by", "confirmed_at"])
            AuditLog.objects.create(actor=request.user, action=f"listing.{action}", object_key=str(listing_id),
                                    data={"before": before, "after": listing.product_id, "reason": reason})
    except IntegrityError:
        messages.error(request, "O anúncio mudou enquanto você editava. Confira o vínculo e tente de novo.")
    else:
        messages.success(request, "Vínculo atualizado.")
    return redirect(destination)

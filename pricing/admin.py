from django.contrib import admin

from .forms import ListingForm, ProductForm
from .models import Listing, PriceDraft, Product, Store
from .workflow_models import AlertRule, SearchAlias


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductForm
    list_display = ["sku", "name", "package", "gtin", "current_price"]
    search_fields = ["sku", "name", "gtin"]


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    form = ListingForm
    list_display = ["store", "name", "external_code", "product", "match_method", "status"]
    list_filter = ["store", "status", "match_method"]
    search_fields = ["name", "external_code", "gtin", "url", "product__sku"]
    autocomplete_fields = ["product"]
    readonly_fields = ["name", "external_code", "gtin", "match_method", "status", "checked_at", "error"]

    def get_readonly_fields(self, request, obj=None):
        return [*self.readonly_fields, "store", "url"] if obj else self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        if "product" in form.changed_data:
            obj.match_method = Listing.Match.MANUAL if obj.product_id else ""
            obj.save(update_fields=["product", "match_method"])


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ["retailer", "unit", "url"]
    readonly_fields = ["slug", "retailer", "unit", "url"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PriceDraft)
class PriceDraftAdmin(admin.ModelAdmin):
    list_display = ["product", "amount", "author", "created_at"]
    search_fields = ["product__sku", "product__name", "author__username"]
    readonly_fields = ["product", "amount", "author", "created_at", "note"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(AlertRule)
admin.site.register(SearchAlias)

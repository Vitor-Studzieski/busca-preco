from decimal import Decimal

from django import forms

from .collectors import CollectionError, validate_product_url
from .models import Listing, PriceDraft, Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "package", "gtin", "current_price"]
        localized_fields = ["current_price"]


class ListingForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = ["store", "url", "product"]

    def clean(self):
        data = super().clean()
        store, url, product = (data.get(field) for field in ("store", "url", "product"))
        if store and url:
            try:
                data["url"] = validate_product_url(store.retailer, store.url, url)
            except CollectionError as error:
                self.add_error("url", str(error))
        if product and not self.instance.external_code:
            self.add_error("product", "Colete o anúncio antes de confirmar o vínculo com o produto.")
        elif product and Listing.objects.filter(
            store_id=self.instance.store_id, product=product,
        ).exclude(pk=self.instance.pk).exists():
            self.add_error("product", "Já existe um anúncio vinculado a esse produto nesta unidade.")
        return data


class PriceDraftForm(forms.ModelForm):
    class Meta:
        model = PriceDraft
        fields = ["amount", "note"]
        localized_fields = ["amount"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class PublishPriceForm(forms.Form):
    from .workflow_models import OwnPrice

    amount = forms.DecimalField(label="Valor", min_value=Decimal("0.01"), max_digits=12, decimal_places=2,
                                localize=True)
    kind = forms.ChoiceField(label="Tipo de preço", choices=OwnPrice.Kind.choices)
    starts_at = forms.DateTimeField(label="Início", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    ends_at = forms.DateTimeField(label="Fim", required=False,
                                 widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    note = forms.CharField(label="Justificativa", max_length=500, required=False)
    confirm = forms.BooleanField(label="Confirmo este preço e a vigência")

    def clean(self):
        data = super().clean()
        data.pop("confirm", None)
        return data

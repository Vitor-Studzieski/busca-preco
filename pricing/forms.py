import re
from decimal import Decimal
from pathlib import Path

from django import forms
from django.contrib.staticfiles import finders

from .collectors import CollectionError, validate_product_url
from .models import Listing, PriceDraft, Product, Store
from .price_alerts import LEVELS, valid_rule
from .workflow_models import AlertRule, OwnPrice


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


class AlertRuleForm(forms.ModelForm):
    direction = forms.ChoiceField(
        required=False,
        choices=(("", "Selecione"), ("higher", "Concorrente acima"), ("lower", "Concorrente abaixo")),
    )
    severity = forms.ChoiceField(required=False, choices=(("", "Selecione"), *LEVELS))

    class Meta:
        model = AlertRule
        fields = ["title", "enabled", "direction", "amount", "percentage", "severity", "window_minutes"]

    def clean(self):
        data = super().clean()
        if not self.errors and data.get("enabled") and not valid_rule(AlertRule(**data)):
            raise forms.ValidationError("Defina direção, limite positivo, severidade e janela antes de ativar a regra.")
        return data


class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = ["active", "display_order", "logo"]

    def clean_logo(self):
        asset = self.cleaned_data["logo"]
        if not asset:
            return asset
        if not re.fullmatch(r"pricing/stores/[a-zA-Z0-9_-]+\.(?:png|webp|jpg)", asset):
            raise forms.ValidationError("Informe um recurso estático aprovado em pricing/stores/.")
        filename = finders.find(asset)
        if not filename or Path(filename).stat().st_size > 256 * 1024:
            raise forms.ValidationError("Recurso não encontrado ou acima de 256 KiB.")
        signature = Path(filename).read_bytes()[:12]
        valid = (
            asset.endswith(".png") and signature.startswith(b"\x89PNG\r\n\x1a\n")
            or asset.endswith(".jpg") and signature.startswith(b"\xff\xd8\xff")
            or asset.endswith(".webp") and signature[:4] == b"RIFF" and signature[8:] == b"WEBP"
        )
        if not valid:
            raise forms.ValidationError("O conteúdo não corresponde ao formato de imagem informado.")
        return asset

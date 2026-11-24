from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .identifiers import normalize_gtin, search_text


class Product(models.Model):
    sku = models.CharField("SKU Pompeia", max_length=80, unique=True)
    name = models.CharField("produto", max_length=255)
    package = models.CharField("embalagem", max_length=100)
    gtin = models.CharField("EAN/GTIN", max_length=14, blank=True, db_index=True)
    search_name = models.CharField(max_length=420, editable=False)
    current_price = models.DecimalField("preço vigente", max_digits=12, decimal_places=2,
                                        null=True, blank=True,
                                        validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        ordering = ["name", "package", "sku"]
        verbose_name = "produto Pompeia"
        verbose_name_plural = "produtos Pompeia"
        constraints = [models.CheckConstraint(condition=Q(current_price__gt=0),
                                              name="product_current_price_positive")]

    def clean(self):
        if self.gtin and not normalize_gtin(self.gtin):
            raise ValidationError({"gtin": "Informe um EAN/GTIN válido, com dígito verificador."})

    def save(self, *args, **kwargs):
        self.gtin = normalize_gtin(self.gtin) or self.gtin
        self.search_name = search_text(f"{self.name} {self.package}")
        fields = kwargs.get("update_fields")
        if fields is not None and ({"name", "package"} & set(fields)):
            kwargs["update_fields"] = {*fields, "search_name"}
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} · {self.package} ({self.sku})"


class Store(models.Model):
    class Retailer(models.TextChoices):
        LIDER = "lider", "Super Líder"
        TAUSTE = "tauste", "Tauste"
        CONFIANCA = "confianca", "Confiança"

    slug = models.SlugField(unique=True)
    retailer = models.CharField("rede", max_length=20, choices=Retailer.choices)
    unit = models.CharField("unidade", max_length=80)
    url = models.URLField("endereço do catálogo", max_length=500)

    class Meta:
        ordering = ["pk"]
        verbose_name = "loja monitorada"
        verbose_name_plural = "lojas monitoradas"

    def __str__(self):
        return f"{self.get_retailer_display()} · {self.unit}"


class Listing(models.Model):
    class Match(models.TextChoices):
        GTIN = "gtin", "EAN/GTIN"
        MANUAL = "manual", "Revisão manual"

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando coleta"
        OK = "ok", "Coleta concluída"
        ERROR = "error", "Falha na coleta"
        CONFLICT = "conflict", "Identidade divergente"

    store = models.ForeignKey(Store, models.PROTECT, verbose_name="loja")
    url = models.URLField("URL pública do produto", max_length=500)
    external_code = models.CharField("código no concorrente", max_length=120, blank=True,
                                     editable=False)
    name = models.CharField("descrição no concorrente", max_length=255, blank=True)
    gtin = models.CharField("EAN/GTIN observado", max_length=14, blank=True, editable=False)
    product = models.ForeignKey(Product, models.SET_NULL, related_name="listings", null=True,
                                blank=True, verbose_name="produto Pompeia")
    match_method = models.CharField("vínculo", max_length=10, choices=Match.choices, blank=True,
                                    editable=False)
    status = models.CharField("estado", max_length=10, choices=Status.choices,
                              default=Status.PENDING, editable=False)
    checked_at = models.DateTimeField("última tentativa", null=True, editable=False)
    error = models.CharField("detalhe da última tentativa", max_length=300, blank=True,
                             editable=False)

    class Meta:
        verbose_name = "anúncio monitorado"
        verbose_name_plural = "anúncios monitorados"
        constraints = [
            models.UniqueConstraint(fields=["store", "url"], name="listing_unique_store_url"),
            models.UniqueConstraint(fields=["store", "external_code"],
                                    condition=~Q(external_code=""),
                                    name="listing_unique_store_external_code"),
            models.UniqueConstraint(fields=["store", "product"],
                                    name="listing_unique_store_product"),
        ]

    def clean(self):
        if self.product_id and self.gtin and self.product.gtin and self.gtin != self.product.gtin:
            raise ValidationError({"product": "O EAN do anúncio diverge do EAN do produto Pompeia."})

    def __str__(self):
        return f"{self.store} · {self.name or self.url}"


class Observation(models.Model):
    class Condition(models.TextChoices):
        REGULAR = "regular", "Regular"
        PROMOTION = "promotion", "Promoção"
        CLUB = "club", "Clube"
        UNKNOWN = "unknown", "Condição não identificada"

    class Availability(models.TextChoices):
        AVAILABLE = "available", "Disponível"
        UNAVAILABLE = "unavailable", "Indisponível"
        UNKNOWN = "unknown", "Estoque não informado"

    listing = models.ForeignKey(Listing, models.CASCADE, related_name="observations")
    price = models.DecimalField("preço observado", max_digits=12, decimal_places=2,
                                validators=[MinValueValidator(Decimal("0.01"))])
    price_unit = models.CharField("unidade do preço", max_length=2, blank=True, default="")
    club_price = models.DecimalField("preço de clube", max_digits=12, decimal_places=2,
                                     null=True, blank=True,
                                     validators=[MinValueValidator(Decimal("0.01"))])
    condition = models.CharField(max_length=10, choices=Condition.choices)
    availability = models.CharField(max_length=12, choices=Availability.choices)
    source_url = models.URLField(max_length=500)
    observed_at = models.DateTimeField()

    class Meta:
        ordering = ["-observed_at", "-pk"]
        indexes = [models.Index(fields=["listing", "-observed_at", "-id"],
                                 name="observation_latest_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="observation_price_positive"),
            models.CheckConstraint(
                condition=Q(club_price__gt=0, club_price__lt=models.F("price")),
                name="observation_club_discount_valid",
            ),
        ]


class PriceDraft(models.Model):
    product = models.ForeignKey(Product, models.PROTECT, related_name="price_drafts")
    amount = models.DecimalField("preço proposto", max_digits=12, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    note = models.CharField("justificativa", max_length=500, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "rascunho de preço"
        verbose_name_plural = "rascunhos de preço"
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0),
                                              name="draft_price_positive")]


class InitialAccountSetup(models.Model):
    completed_at = models.DateTimeField(auto_now_add=True)

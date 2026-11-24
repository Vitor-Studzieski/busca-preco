from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class OwnPrice(models.Model):
    class Kind(models.TextChoices):
        REGULAR = "regular", "Regular"
        PROMOTION = "promotion", "Promoção"

    product = models.ForeignKey("pricing.Product", models.PROTECT, related_name="own_prices")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="own_price_positive"),
            models.CheckConstraint(condition=Q(kind__in=("regular", "promotion")), name="own_price_kind_valid"),
            models.CheckConstraint(condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                                   name="own_price_interval_valid"),
            models.CheckConstraint(condition=Q(kind="regular") | Q(ends_at__isnull=False),
                                   name="own_promotion_has_end"),
        ]
        indexes = [models.Index(fields=["product", "kind", "starts_at"], name="own_price_lookup_idx")]


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True)
    action = models.CharField(max_length=40)
    object_key = models.CharField(max_length=100, blank=True)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class CollectionRun(models.Model):
    key = models.CharField(max_length=80, unique=True)
    trigger = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    stats = models.JSONField(default=dict)


class CollectionJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando atualização"
        RUNNING = "running", "Atualizando"
        UPDATED = "updated", "Atualizado"
        NO_PRICE = "no_price", "Sem preço confirmado"
        MISSING = "missing", "Produto não encontrado"
        UNAVAILABLE = "unavailable", "Produto indisponível"
        BLOCKED = "blocked", "Acesso limitado pela rede"
        ERROR = "error", "Erro de coleta"

    key = models.CharField(max_length=80, unique=True)
    lookup_key = models.CharField(max_length=64, blank=True, db_index=True)
    store = models.ForeignKey("pricing.Store", models.PROTECT)
    run = models.ForeignKey(CollectionRun, models.PROTECT, null=True, related_name="jobs")
    listing = models.ForeignKey("pricing.Listing", models.PROTECT, null=True)
    product = models.ForeignKey("pricing.Product", models.PROTECT, null=True)
    query = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.PENDING)
    available_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict)

    class Meta:
        indexes = [models.Index(fields=["status", "available_at", "id"], name="collection_job_claim_idx"),
                   models.Index(fields=["lookup_key", "store", "-finished_at"], name="collection_job_lookup_idx")]


class NetworkHealth(models.Model):
    retailer = models.CharField(max_length=20, unique=True)
    failures = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True)
    last_success_at = models.DateTimeField(null=True)
    last_status = models.CharField(max_length=14, blank=True)


class AlertRule(models.Model):
    title = models.CharField(max_length=100)
    enabled = models.BooleanField(default=False)
    direction = models.CharField(max_length=20, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    percentage = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    severity = models.CharField(max_length=20, blank=True)
    window_minutes = models.PositiveIntegerField(null=True, blank=True)


class Alert(models.Model):
    key = models.CharField(max_length=120)
    kind = models.CharField(max_length=24)
    product = models.ForeignKey("pricing.Product", models.PROTECT, null=True)
    listing = models.ForeignKey("pricing.Listing", models.PROTECT, null=True)
    own_price = models.ForeignKey(OwnPrice, models.PROTECT, null=True)
    detail = models.CharField(max_length=300)
    opened_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key"], condition=Q(resolved_at__isnull=True),
                                               name="unique_open_alert")]


class AlertAcknowledgment(models.Model):
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT)
    alert = models.ForeignKey(Alert, models.PROTECT, related_name="acknowledgments")
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["buyer", "alert"], name="unique_buyer_alert_ack")]


class SearchAlias(models.Model):
    abbreviation = models.CharField(max_length=32, unique=True)
    expansion = models.CharField(max_length=100)
    active = models.BooleanField(default=True)


class DayItem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "A precificar"
        REVIEW = "review", "Em análise"
        PUBLISHED = "published", "Publicado"

    product = models.ForeignKey("pricing.Product", models.PROTECT)
    day = models.DateField()
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "day"], name="unique_day_product")]


class BuyerDevice(models.Model):
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE)
    session = models.OneToOneField("sessions.Session", models.CASCADE)
    browser = models.CharField(max_length=180, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)


class RateWindow(models.Model):
    key = models.CharField(max_length=150, primary_key=True)
    expires_at = models.DateTimeField(db_index=True)
    count = models.PositiveIntegerField(default=0)


class MonitoredQuery(models.Model):
    key = models.CharField(max_length=64, unique=True)
    query = models.CharField(max_length=255)
    last_used_at = models.DateTimeField(default=timezone.now)

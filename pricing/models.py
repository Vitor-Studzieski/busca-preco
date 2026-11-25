from django.db import models


class Store(models.Model):
    class Retailer(models.TextChoices):
        LIDER = "lider", "Super Líder"
        TAUSTE = "tauste", "Tauste"
        CONFIANCA = "confianca", "Confiança"

    slug = models.SlugField(max_length=50, unique=True)
    retailer = models.CharField(max_length=20, choices=Retailer.choices)
    unit = models.CharField(max_length=80)
    url = models.URLField(max_length=500)
    active = models.BooleanField(default=True)
    logo = models.CharField(max_length=180, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "markets"
        ordering = ["display_order", "pk"]

    def __str__(self):
        return f"{self.get_retailer_display()} · {self.unit}"

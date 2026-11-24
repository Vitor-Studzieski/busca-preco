from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .collectors import CollectedOffer, CollectionError
from .models import Listing, Observation, PriceDraft, Product, Store
from .services import collect_listing


class PricingFlowTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(sku="0021", name="Café Exemplo", package="500 g",
                                              gtin="7891234567895", current_price=Decimal("24.50"))
        self.pompeia = Store.objects.get(slug="lider-pompeia")
        self.herculandia = Store.objects.get(slug="lider-herculandia")
        self.tauste = Store.objects.get(slug="tauste-marilia")
        self.first = Listing.objects.create(store=self.pompeia,
                                             url=f"{self.pompeia.url}/produto/m/cafe-748")
        self.second = Listing.objects.create(store=self.herculandia,
                                              url=f"{self.herculandia.url}/produto/m/cafe-748")
        self.third = Listing.objects.create(store=self.tauste,
                                             url=f"{self.tauste.url}123-cafe.html")

    def collect(self, listing, code, price, gtin="7891234567895"):
        offer = CollectedOffer(code, "Café Exemplo 500 g", Decimal(price), "regular",
                               "available", gtin, listing.url)
        with patch("pricing.services.collect_offer", return_value=offer):
            collect_listing(listing)
        listing.refresh_from_db()

    def create_buyer(self, *, can_draft=True):
        buyer = get_user_model().objects.create_user("compras", password="any-test-password")
        codenames = ["view_product", "add_pricedraft"] if can_draft else ["view_product"]
        buyer.user_permissions.set(Permission.objects.filter(content_type__app_label="pricing",
                                                             codename__in=codenames))
        self.client.force_login(buyer)
        return buyer

    @patch("pricing.views.search_stores", return_value=[])
    def test_search_and_compare_distinct_codes_and_units(self, search_stores):
        self.collect(self.first, "00035", "25.10")
        self.collect(self.second, "00035", "26.20")
        self.collect(self.third, "SKU-X", "27.30")
        self.create_buyer()
        for query in ("cafe", "0021", "7891234567895"):
            result = self.client.get(reverse("pricing:search"), {"q": query})
            self.assertEqual(result.context["products"], [self.product])
        page = self.client.get(reverse("pricing:product", args=[self.product.pk]))
        self.assertContains(page, "Código 00035", count=2)
        for content in ("Herculândia", "Tauste", "Confiança", "SKU-X", "26,20", "27,30",
                        "24,50", "Sem anúncio vinculado"):
            self.assertContains(page, content)

    def test_missing_or_shared_gtin_leaves_listing_for_review(self):
        Product.objects.create(sku="00-other", name="Outro café", package="500 g",
                               gtin="7891234567895")
        self.collect(self.first, "00035", "25.10")
        self.collect(self.third, "SKU-X", "27.30", gtin="")
        self.assertIsNone(self.first.product_id)
        self.assertIsNone(self.third.product_id)
        self.assertEqual(self.first.observations.count(), 1)

    def test_changed_external_code_does_not_replace_last_price(self):
        self.collect(self.first, "00035", "25.10")
        self.collect(self.first, "00036", "50.00")
        self.assertEqual(self.first.status, Listing.Status.CONFLICT)
        self.assertEqual(self.first.external_code, "00035")
        self.assertEqual(self.first.observations.get().price, Decimal("25.10"))

    def test_discovery_keeps_one_listing_per_url_after_rerun(self):
        url = f"{self.pompeia.url}/produto/m/novo-100"
        with patch("pricing.management.commands.discover_listings.discover_product_urls",
                   return_value=[url]):
            for _ in range(2):
                call_command("discover_listings", unidade=self.pompeia.slug, stdout=StringIO())
        listing = Listing.objects.get(store=self.pompeia, url=url)
        self.assertEqual(listing.status, Listing.Status.PENDING)

    def test_public_and_club_prices_are_displayed_separately(self):
        offer = CollectedOffer(
            "SKU-X", "Café Exemplo 500 g", Decimal("27.30"), "regular",
            "available", "7891234567895", self.third.url, club_price=Decimal("25.30"),
        )
        with patch("pricing.services.collect_offer", return_value=offer):
            collect_listing(self.third)
        self.create_buyer()
        page = self.client.get(reverse("pricing:product", args=[self.product.pk]))
        self.assertContains(page, "27,30")
        self.assertContains(page, "Clube · R$ 25,30")

    def test_admin_can_link_an_offer_without_gtin_after_collection(self):
        self.collect(self.third, "SKU-X", "27.30", gtin="")
        admin = get_user_model().objects.create_superuser("admin", password="any-test-password")
        self.assertTrue(self.client.login(username=admin.username, password="any-test-password"))
        url = reverse("admin:pricing_listing_change", args=[self.third.pk])
        self.assertRedirects(self.client.post(url, {"product": self.product.pk, "_save": "Salvar"}),
                             reverse("admin:pricing_listing_changelist"))
        self.third.refresh_from_db()
        self.assertEqual(self.third.product, self.product)
        self.assertEqual(self.third.match_method, Listing.Match.MANUAL)
        self.assertEqual(self.third.external_code, "SKU-X")
        page = self.client.get(reverse("pricing:product", args=[self.product.pk]))
        self.assertContains(page, "27,30")

    def test_csv_updates_catalog_by_sku_and_keeps_leading_zeroes(self):
        with TemporaryDirectory() as directory:
            csv_path = Path(directory) / "catalogo.csv"
            csv_path.write_text(
                "sku;nome;embalagem;ean;preco_vigente\n"
                "0021;Café atualizado;500 g;7891234567895;25,42\n",
                encoding="utf-8",
            )
            call_command("import_products", str(csv_path), stdout=StringIO())
        self.product.refresh_from_db()
        self.assertEqual(self.product.sku, "0021")
        self.assertEqual(self.product.name, "Café atualizado")
        self.assertEqual(self.product.current_price, Decimal("25.42"))

    def test_failed_source_keeps_historical_offer_and_marks_it(self):
        self.collect(self.first, "00035", "25.10")
        Observation.objects.update(observed_at=timezone.now() - timedelta(days=2))
        with patch("pricing.services.collect_offer", side_effect=CollectionError("HTTP 403", status=403)):
            collect_listing(self.first)
        self.create_buyer()
        page = self.client.get(reverse("pricing:product", args=[self.product.pk]))
        for content in ("Falha na coleta", "Desatualizado", "25,10"):
            self.assertContains(page, content)

    def test_draft_preserves_current_price_and_requires_permission(self):
        url = reverse("pricing:product", args=[self.product.pk])
        self.create_buyer(can_draft=False)
        self.assertEqual(self.client.post(url, {"amount": "23,90"}).status_code, 403)
        buyer = get_user_model().objects.get(username="compras")
        buyer.user_permissions.add(Permission.objects.get(content_type__app_label="pricing",
                                                           codename="add_pricedraft"))
        self.assertRedirects(self.client.post(url, {"amount": "23,90", "note": "Comparação manual"}), url)
        self.assertEqual(PriceDraft.objects.get(author=buyer).amount, Decimal("23.90"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_price, Decimal("24.50"))

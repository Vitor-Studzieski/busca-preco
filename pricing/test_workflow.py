from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .collectors import CollectedOffer
from .jobs import claim_job, enqueue_search, finish_job, schedule_due, work_once
from .models import Listing, Observation, Product, Store
from .offer_search import SearchOffer, StoreSearch
from .price_workflow import cancel_price, publish_price
from .workflow_models import Alert, AuditLog, CollectionJob, CollectionRun, MonitoredQuery, OwnPrice


class WorkflowTests(TestCase):
    def setUp(self):
        self.password = "Outono+986Pomar2026"
        self.user = get_user_model().objects.create_superuser("operador", password=self.password)
        self.client.force_login(self.user)
        self.store = Store.objects.get(slug="lider-pompeia")

    def test_buyer_can_render_all_operational_pages(self):
        for name in ("pricing:search", "pricing:day_queue", "pricing:alerts", "pricing:health", "buyer_devices"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])

    def test_shared_queue_and_account_bound_progress(self):
        path = reverse("pricing:refresh")
        response = self.client.post(path, {"q": "Detergente 500 ml"})
        self.client.post(path, {"q": "detergente 0,5 l"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(CollectionJob.objects.count(), 4)
        progress = reverse("pricing:progress")
        token = response.json()["token"]
        self.assertFalse(self.client.get(progress, HTTP_X_COLLECTION_TICKET=token).json()["complete"])
        second = get_user_model().objects.create_superuser("segunda")
        self.client.force_login(second)
        self.assertEqual(self.client.get(progress, HTTP_X_COLLECTION_TICKET=token).status_code, 404)

    def test_live_success_persists_real_offer_before_scheduling_both_days(self):
        enqueue_search("Detergente 500 ml", store_id=self.store.pk)
        offer = CollectedOffer("410", "Detergente 500 ml", Decimal("2.51"), "regular",
                               "available", "", self.store.url)
        with patch("pricing.jobs.search_unit", return_value=StoreSearch(
            self.store, (SearchOffer(offer),), timezone.now()
        )):
            self.assertTrue(work_once())
        self.assertEqual(MonitoredQuery.objects.count(), 1)
        page = self.client.get(reverse("pricing:search"), {"q": "detergente 500ml"})
        self.assertContains(page, "2,51")
        local = ZoneInfo("America/Sao_Paulo")
        for hour in (3, 4, 4, 14, 14):
            schedule_due(datetime(2026, 11, 24, hour, tzinfo=local))
        self.assertEqual(CollectionRun.objects.count(), 2)
        self.assertTrue(all(run.jobs.count() == 4 for run in CollectionRun.objects.all()))

    def test_block_is_shared_across_lider_units(self):
        enqueue_search("Tomate kg")
        first, paused = claim_job()
        while first and first.store.retailer != "lider":
            finish_job(first, CollectionJob.Status.MISSING, {})
            first, paused = claim_job()
        self.assertFalse(paused)
        finish_job(first, CollectionJob.Status.BLOCKED, {"reason": "Acesso limitado."})
        second, paused = claim_job()
        self.assertEqual(second.store.retailer, "lider")
        self.assertTrue(paused)

    def test_persistent_login_and_revoke_other_device(self):
        first, second = Client(), Client()
        first.post(reverse("login"), {"username": self.user.username,
                                     "password": self.password, "remember": "on"})
        second.post(reverse("login"), {"username": self.user.username, "password": self.password})
        self.assertEqual(int(first.cookies["sessionid"]["max-age"]), 30 * 86400)
        self.assertEqual(second.cookies["sessionid"]["max-age"], "")
        self.assertEqual(second.get(reverse("pricing:search")).status_code, 200)
        path = reverse("revoke_other_devices")
        first.post(path, {"password": "senha errada"})
        self.assertEqual(second.get(reverse("pricing:search")).status_code, 200)
        first.post(path, {"password": self.password})
        self.assertEqual(second.get(reverse("pricing:search")).status_code, 302)

    def test_publish_requires_today_and_resolves_alert_only_on_cancel(self):
        product = Product.objects.create(sku="test-price", name="Detergente", package="500 ml")
        now = timezone.now()
        values = {"amount": Decimal("4.50"), "kind": OwnPrice.Kind.PROMOTION, "note": "",
                  "starts_at": now - timedelta(minutes=10), "ends_at": now + timedelta(days=1)}
        with self.assertRaises(ValidationError):
            publish_price(product, self.user, values)
        for store in Store.objects.filter(active=True):
            listing = Listing.objects.create(store=store, product=product, url=store.url,
                                             status=Listing.Status.OK, match_method=Listing.Match.GTIN)
            Observation.objects.create(listing=listing, price="4.70", condition="regular",
                                       availability="available", source_url=store.url, observed_at=now)
        price = publish_price(product, self.user, values)
        active = Alert.objects.get(kind="promotion")
        self.client.post(reverse("pricing:acknowledge", args=[active.pk]))
        active.refresh_from_db()
        self.assertIsNone(active.resolved_at)
        with self.assertRaises(ValidationError):
            publish_price(product, self.user, values)
        cancel_price(price.pk, product, self.user, "Fim da campanha")
        active.refresh_from_db()
        self.assertIsNotNone(active.resolved_at)
        self.assertEqual(AuditLog.objects.filter(action__startswith="price.").count(), 2)

    def test_postgres_exclusion_and_immutable_audit(self):
        if connection.vendor != "postgresql":
            self.skipTest("Invariantes exclusivos do PostgreSQL")
        product = Product.objects.create(sku="constraint", name="Detergente", package="500 ml")
        record = OwnPrice.objects.create(product=product, buyer=self.user, kind="regular",
                                         amount="10.00", starts_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            OwnPrice.objects.create(product=product, buyer=self.user, kind="regular",
                                    amount="11.00", starts_at=record.starts_at + timedelta(hours=1))
        entry = AuditLog.objects.create(actor=self.user, action="check")
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).update(action="substituir")

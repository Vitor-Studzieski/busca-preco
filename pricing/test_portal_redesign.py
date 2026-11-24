from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.admin import OTPAdminSite
from django_otp.plugins.otp_totp.models import TOTPDevice

from .jobs import enqueue_search, normalized_lookup
from .models import Listing, Observation, Product, Store
from .price_alerts import evaluate_for_listing
from .workflow_models import Alert, AlertRule, AuditLog, CollectionJob, MonitoredQuery, OwnPrice


class PortalRedesignTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser("compras")
        self.client.force_login(self.operator)
        self.store = Store.objects.get(slug="lider-pompeia")

    def test_initial_page_and_independent_sections(self):
        search = self.client.get(reverse("pricing:search"))
        self.assertContains(search, 'class="sidebar"')
        self.assertContains(search, "Unidades consultadas")
        self.assertNotContains(search, 'class="market-grid"')
        self.assertContains(self.client.get(reverse("pricing:day_queue")), "Pesquisas monitoradas")
        self.assertContains(self.client.get(reverse("pricing:alerts")), "Não reconhecidos")
        self.assertContains(self.client.get(reverse("pricing:health")), "Próxima janela")

    def test_queue_saved_filter_and_explicit_batch(self):
        q = "Detergente 500 ml"
        key = normalized_lookup(q)
        monitor = MonitoredQuery.objects.create(key=key, query=q)
        target = reverse("pricing:queue_batch")
        self.client.post(target, {"selected": monitor.pk})
        self.assertFalse(CollectionJob.objects.exists())
        response = self.client.post(target, {"selected": monitor.pk, "confirm": "1"})
        self.assertRedirects(response, reverse("pricing:day_queue"))
        self.assertEqual(CollectionJob.objects.count(), 4)
        response = self.client.post(reverse("pricing:queue_settings"), {"network": "lider"})
        self.assertRedirects(response, reverse("pricing:day_queue"))
        self.assertEqual(self.client.get(reverse("pricing:day_queue")).context["filters"]["network"], "lider")

    def test_retry_joins_existing_job_for_same_store(self):
        a = enqueue_search("arroz 5 kg", store_id=self.store.pk)
        b = enqueue_search("arroz 5000 g", store_id=self.store.pk, force=True)
        self.assertEqual(a[0].pk, b[0].pk)

    @override_settings(PRICING_ENABLE_OWN_PRICES=True)
    def test_future_price_and_history_in_main_flow(self):
        product = Product.objects.create(sku="SKU-110", name="Detergente", package="500 ml",
                                         gtin="7894900011517", current_price="4.90")
        now = timezone.now()
        for store in Store.objects.all():
            listing = Listing.objects.create(store=store, product=product, url=store.url,
                                             match_method=Listing.Match.GTIN, status=Listing.Status.OK)
            Observation.objects.create(listing=listing, price="4.75", condition="promotion",
                                       availability="available", source_url=store.url, observed_at=now)
        response = self.client.get(reverse("pricing:search"), {"q": product.gtin})
        self.assertContains(response, "Comparação do Pompeia")
        self.assertContains(response, "Histórico de preços")
        self.assertContains(response, "Publicar no portal")
        start = timezone.localtime(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        end = timezone.localtime(now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(reverse("pricing:publish", args=[product.pk]), {
            "amount": "4,50", "kind": "promotion", "starts_at": start, "ends_at": end,
            "confirm": "on",
        })
        self.assertRedirects(response, reverse("pricing:search") + f"?produto={product.pk}")
        self.assertEqual(OwnPrice.objects.get(product=product).amount, Decimal("4.50"))

    @override_settings(PRICING_ENABLE_OWN_PRICES=True)
    def test_price_rules_require_complete_opt_in_and_resolve(self):
        product = Product.objects.create(sku="SKU-A", name="Produto", package="1 kg", current_price="8.90")
        listing = Listing.objects.create(store=self.store, product=product, url=self.store.url,
                                         match_method=Listing.Match.GTIN, status=Listing.Status.OK)
        now = timezone.now()
        Observation.objects.create(listing=listing, price="10.90", condition="regular",
                                   availability="available", source_url=self.store.url, observed_at=now)
        rule = AlertRule.objects.create(title="Regra de teste")
        evaluate_for_listing(listing, now)
        self.assertFalse(Alert.objects.exists())
        rule.enabled = True
        rule.direction, rule.severity, rule.window_minutes = "higher", "medium", 60
        rule.amount, rule.percentage = Decimal("1.00"), Decimal("8.00")
        rule.save()
        evaluate_for_listing(listing, now)
        self.assertTrue(Alert.objects.filter(kind="price", resolved_at__isnull=True).exists())
        rule.enabled = False
        rule.save()
        evaluate_for_listing(listing, now)
        self.assertTrue(Alert.objects.filter(kind="price", resolved_at__isnull=False).exists())

    @override_settings(PRICING_ENABLE_OWN_PRICES=True)
    def test_relink_requires_gtin_and_audits_change(self):
        gtin = "7894900011517"
        product = Product.objects.create(sku="SKU-G", name="Produto", package="1 kg", gtin=gtin)
        listing = Listing.objects.create(store=self.store, url=self.store.url, external_code="EXT",
                                         gtin=gtin, status=Listing.Status.OK)
        path = reverse("pricing:change_link", args=[product.pk, listing.pk])
        self.client.post(path, {"action": "confirm", "reason": "Revisão por código"})
        listing.refresh_from_db()
        self.assertEqual(listing.product_id, product.pk)
        self.assertEqual(listing.confirmed_by_id, self.operator.pk)
        self.assertTrue(AuditLog.objects.filter(action="listing.confirm", actor=self.operator).exists())
        self.client.post(path, {"action": "detach", "reason": "Conferência adicional"})
        listing.refresh_from_db()
        self.assertIsNone(listing.product_id)

    def test_otp_is_required_for_technical_admin_in_production_profile(self):
        from django.test import RequestFactory

        site = OTPAdminSite()
        request = RequestFactory().get("/manutencao/")
        request.user = self.operator
        request.user.is_verified = lambda: False
        self.assertFalse(site.has_permission(request))
        device = TOTPDevice.objects.create(user=self.operator, name="Teste")
        request.user.otp_device = device
        request.user.is_verified = lambda: request.user.otp_device is not None
        self.assertTrue(site.has_permission(request))

    @override_settings(PRICING_ENABLE_OWN_PRICES=True)
    def test_queue_promotion_filters_and_batch_for_catalog(self):
        from .workflow_models import CollectionRun, DayItem

        product = Product.objects.create(sku="QUEUE-A", name="Promocional", package="500 g")
        other = Product.objects.create(sku="QUEUE-B", name="Regular", package="500 g")
        today = timezone.localdate()
        now = timezone.now()
        item = DayItem.objects.create(product=product, day=today, buyer=self.operator)
        DayItem.objects.create(product=other, day=today, buyer=self.operator, status=DayItem.Status.REVIEW)
        OwnPrice.objects.create(product=product, buyer=self.operator, amount="2.00", kind="promotion",
                                starts_at=now, ends_at=now + timedelta(days=2))
        Listing.objects.create(store=self.store, product=product, url=self.store.url, status=Listing.Status.CONFLICT)
        response = self.client.get(reverse("pricing:day_queue"), {
            "filtered": "1", "status": "pending", "network": "lider", "issues": "1",
            "missing": "1", "promotion": "1", "order": "status",
        })
        self.assertContains(response, "Promocional")
        self.assertNotContains(response, "QUEUE-B")
        self.client.post(reverse("pricing:queue_batch"), {"selected": item.pk, "confirm": "1"})
        self.assertEqual(CollectionRun.objects.get(trigger="manual").jobs.count(), 4)

    def test_private_progress_ticket_stays_out_of_the_query_string(self):
        path = reverse("pricing:progress")
        ticket = self.client.post(reverse("pricing:refresh"), {"q": "Café 500 g"}).json()["token"]
        self.assertEqual(self.client.get(path, {"token": ticket}).status_code, 404)
        self.assertEqual(self.client.get(path, HTTP_X_COLLECTION_TICKET=ticket).status_code, 200)

    def test_dispositivos_password_change_revokes_previous_credentials(self):
        from django.test import Client

        self.operator.set_password("AntesDaTroca!802Portal")
        self.operator.save(update_fields=["password"])
        first, second = Client(), Client()
        for browser in (first, second):
            browser.post(reverse("login"), {"username": "compras", "password": "AntesDaTroca!802Portal"})
        response = first.post(reverse("buyer_devices"), {
            "old_password": "AntesDaTroca!802Portal",
            "new_password1": "NovaCredencial!510Portal",
            "new_password2": "NovaCredencial!510Portal",
        })
        self.assertRedirects(response, reverse("buyer_devices"))
        self.assertEqual(second.get(reverse("pricing:search")).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="account.password_change").exists())

    def test_worker_persists_confirmed_identity_and_records_run(self):
        from unittest.mock import patch

        from .collectors import CollectedOffer
        from .jobs import enqueue_product_collection, work_once
        from .offer_search import SearchOffer, StoreSearch
        from .workflow_models import CollectionRun

        Store.objects.exclude(pk=self.store.pk).update(active=False)
        product = Product.objects.create(sku="JOB-A", name="Refrigerante", package="2 l",
                                         gtin="7894900011517")
        enqueue_product_collection(product, "manual", "teste-run-job")
        offer = CollectedOffer("321", "Refrigerante 2 l", Decimal("8.90"), "regular",
                               "available", "7894900011517", self.store.url)
        with patch("pricing.jobs.search_unit", return_value=StoreSearch(
            self.store, (SearchOffer(offer),), timezone.now()
        )):
            self.assertTrue(work_once())
        run = CollectionRun.objects.get(key="teste-run-job")
        self.assertEqual(run.stats["processed"], 1)
        listing = Listing.objects.get(store=self.store, product=product)
        self.assertEqual(listing.match_method, Listing.Match.GTIN)
        self.assertEqual(Observation.objects.get(listing=listing).collection_run_id, run.pk)

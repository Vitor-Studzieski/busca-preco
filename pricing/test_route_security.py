from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.request import Request

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import caches
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .collectors.http import (
    CollectionError, StorefrontRedirectHandler, fetch_html, storefront_deadline, validate_product_url,
)
from .models import PriceDraft, Product


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class RouteAccessTests(TestCase):
    def setUp(self):
        for cache in caches.all():
            cache.clear()
        self.password = "Pomar+Abril_9756Rubro"
        users = get_user_model().objects
        self.admin = users.create_superuser("admin-teste", password=self.password)
        self.buyer = users.create_user("comprador-teste", password=self.password)
        self.buyer.user_permissions.set(Permission.objects.filter(
            content_type__app_label="pricing", codename__in=("view_product", "add_pricedraft"),
        ))
        self.product = Product.objects.create(sku="SEG-001", name="Produto teste", package="1 kg")
        self.detail = reverse("pricing:product", args=[self.product.pk])
        self.client = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)

    def test_visitor_buyer_and_administrator_access_routes_directly(self):
        guarded_routes = [reverse("pricing:search"), self.detail, reverse("add_buyer"), reverse("logout")]
        for route in guarded_routes:
            self.assertEqual(self.client.get(route).status_code, 302, route)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        self.assertRedirects(self.client.get(reverse("initial_setup")), reverse("login"))

        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("pricing:search")).status_code, 200)
        self.assertEqual(self.client.get(self.detail).status_code, 200)
        self.assertEqual(self.client.get(reverse("add_buyer")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        self.assertEqual(self.client.get(reverse("admin:auth_user_add")).status_code, 302)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("add_buyer")).status_code, 200)

    def test_side_effects_require_post_csrf_and_the_correct_permission(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 403)
        self.assertEqual(self.client.post(self.detail, {"amount": "12,90"}).status_code, 403)
        self.assertFalse(PriceDraft.objects.exists())
        self.assertIn("no-store", self.client.get(self.detail)["Cache-Control"])
        token = self.client.cookies["csrftoken"].value
        draft = {"amount": "12,90", "csrfmiddlewaretoken": token}
        self.assertRedirects(self.client.post(self.detail, draft), self.detail)
        self.assertEqual(PriceDraft.objects.get(product=self.product).author, self.buyer)

        form_data = {"username": "nova-conta", "password1": self.password,
                     "password2": self.password, "csrfmiddlewaretoken": token}
        self.assertEqual(self.client.post(reverse("add_buyer"), form_data).status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username="nova-conta").exists())
        self.assertRedirects(self.client.post(reverse("logout"), {"csrfmiddlewaretoken": token}), reverse("login"))
        self.assertEqual(self.client.get(self.detail).status_code, 302)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("add_buyer")).status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="nova-conta").exists())
        self.assertEqual(self.client.post(reverse("add_buyer"), {"username": "nova-conta"}).status_code, 403)

    def test_read_only_account_cannot_create_drafts_with_a_valid_token(self):
        self.buyer.user_permissions.remove(Permission.objects.get(
            content_type__app_label="pricing", codename="add_pricedraft",
        ))
        self.client.force_login(self.buyer)
        self.client.get(reverse("pricing:search"))
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(self.detail, {"amount": "12,90", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PriceDraft.objects.exists())

    def test_login_accepts_a_local_destination_and_rejects_an_external_destination(self):
        for destination, expected in ((self.detail, self.detail), ("https://example.test/", reverse("pricing:search"))):
            with self.subTest(destination=destination):
                client = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
                self.assertEqual(client.post(reverse("login"), {"username": self.buyer.username}).status_code, 403)
                client.get(reverse("login"))
                response = client.post(reverse("login"), {
                    "username": self.buyer.username, "password": self.password, "next": destination,
                    "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
                })
                self.assertRedirects(response, expected, fetch_redirect_response=False)

    @override_settings(PRICING_SEARCH_RATE_LIMIT=2)
    def test_search_returns_429_per_account_before_contacting_sources(self):
        self.client.force_login(self.buyer)
        search = reverse("pricing:search")
        with patch("pricing.views.search_stores", return_value=[]) as query, patch(
                "pricing.request_limits.time", return_value=10):
            for term in ("Heineken 600 ml", "Contra-filé"):
                self.assertEqual(self.client.get(search, {"q": term}).status_code, 200)
            blocked = self.client.get(search, {"q": "Coca-Cola 2 litros"})
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked["Retry-After"], "50")
            self.assertIn("no-store", blocked["Cache-Control"])
            self.assertEqual(query.call_count, 2)
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(search, {"q": "Coca-Cola 2 litros"}).status_code, 200)


class StorefrontRouteTests(SimpleTestCase):
    base = "https://www.smlider.com.br/1"
    product = base + "/produto/m/exemplo-1"

    def validate(self, url):
        return validate_product_url("lider", self.base, url)

    def test_only_the_configured_https_unit_and_product_routes_are_allowed(self):
        self.assertEqual(self.validate(self.product), self.product)
        for url in (self.product.replace("https:", "http:"), self.product.replace("/1/", "/2/"),
                    self.base + "/busca?q=exemplo", "https://example.test/produto/m/exemplo-1"):
            with self.subTest(url=url), self.assertRaises(CollectionError):
                self.validate(url)

    def test_redirect_and_final_response_are_validated_before_reading(self):
        redirect = StorefrontRedirectHandler(self.validate)
        request = Request(self.product)
        next_product = self.base + "/produto/m/exemplo-2"
        self.assertEqual(redirect.redirect_request(request, None, 302, "Found", {}, next_product).full_url,
                         next_product)
        with self.assertRaises(CollectionError):
            redirect.redirect_request(request, None, 302, "Found", {}, next_product.replace("/1/", "/2/"))

        response = MagicMock()
        response.geturl.return_value = "https://example.test/produto/m/exemplo-1"
        connection = MagicMock()
        connection.__enter__.return_value = response
        with patch("pricing.collectors.http.build_opener", return_value=SimpleNamespace(open=lambda *a, **kw: connection)):
            with self.assertRaises(CollectionError):
                fetch_html(self.product, self.validate)
        response.read.assert_not_called()

    def test_transient_server_error_retries_once_without_retrying_access_refusal(self):
        for status, expected_calls in ((500, 2), (429, 1), (403, 1)):
            with self.subTest(status=status), storefront_deadline(monotonic() + 3), patch(
                "pricing.collectors.http.open_html", side_effect=CollectionError("Falha do servidor", status=status),
            ) as request, patch("pricing.collectors.http.sleep"), self.assertRaises(CollectionError):
                try:
                    fetch_html(self.product, self.validate)
                finally:
                    self.assertEqual(request.call_count, expected_calls)

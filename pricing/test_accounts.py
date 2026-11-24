from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import InitialAccountSetup


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class AccountFlowTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="localhost")
        self.user_model = get_user_model()
        self.password = "Pomar+Abril_9756Rubro"
        self.first_account = {
            "username": "gerencia",
            "password1": self.password,
            "password2": self.password,
        }

    def test_first_account_is_created_once_and_can_sign_in(self):
        self.assertRedirects(self.client.get(reverse("login")), reverse("initial_setup"))
        setup = self.client.get(reverse("initial_setup"))
        self.assertContains(setup, "Criar primeira conta")
        self.assertContains(setup, "pompeia-logo.png")
        self.assertRedirects(self.client.post(reverse("initial_setup"), self.first_account),
                             reverse("pricing:search"))
        administrator = self.user_model.objects.get()
        self.assertTrue(administrator.is_superuser and administrator.is_staff)
        self.assertEqual(self.client.session["_auth_user_id"], str(administrator.pk))
        self.client.post(reverse("logout"))
        self.assertContains(self.client.get(reverse("login")), "Entrar")
        self.assertRedirects(
            self.client.post(reverse("login"), {"username": "gerencia", "password": self.password}),
            reverse("pricing:search"),
        )
        with self.assertRaises(ProtectedError):
            administrator.delete()
        self.client.logout()
        self.assertRedirects(self.client.post(reverse("initial_setup"), self.first_account),
                             reverse("login"))
        self.assertEqual(self.user_model.objects.count(), 1)
        self.assertEqual(InitialAccountSetup.objects.count(), 1)

    def test_setup_stays_closed_when_only_marker_exists(self):
        InitialAccountSetup.objects.create()
        self.assertRedirects(self.client.post(reverse("initial_setup"), self.first_account),
                             reverse("login"))
        self.assertFalse(self.user_model.objects.exists())

    def test_existing_account_keeps_initial_setup_closed(self):
        existing_user = self.user_model.objects.create_user("existente", password=self.password)
        self.assertRedirects(self.client.post(reverse("initial_setup"), self.first_account),
                             reverse("login"))
        self.assertEqual(list(self.user_model.objects.all()), [existing_user])

    def test_initial_setup_rejects_remote_forwarded_and_untrusted_host_requests(self):
        setup = reverse("initial_setup")
        for headers in (
            {"REMOTE_ADDR": "192.0.2.20"},
            {"HTTP_X_FORWARDED_FOR": "192.0.2.20"},
            {"HTTP_HOST": "testserver"},
        ):
            with self.subTest(headers=headers):
                response = self.client.post(setup, self.first_account, **headers)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse("login"))
        self.assertFalse(self.user_model.objects.exists())

    @override_settings(DEBUG=False)
    def test_initial_setup_is_disabled_when_development_mode_is_off(self):
        response = self.client.post(reverse("initial_setup"), self.first_account)
        self.assertEqual(response.url, reverse("login"))
        self.assertFalse(self.user_model.objects.exists())

    def test_initial_setup_requires_csrf_and_valid_password(self):
        protected = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
        setup = reverse("initial_setup")
        self.assertEqual(protected.post(setup, self.first_account).status_code, 403)
        response = self.client.post(setup, {**self.first_account, "password2": "diferente"})
        self.assertTrue(response.context["form"]["password2"].errors)
        self.assertFalse(InitialAccountSetup.objects.exists())
        self.assertFalse(self.user_model.objects.exists())

    def test_administrator_creates_buyer_with_only_the_needed_permissions(self):
        administrator = self.user_model.objects.create_superuser("gerencia", password=self.password)
        self.client.force_login(administrator)
        url = reverse("add_buyer")
        self.assertContains(self.client.get(url), "Cadastrar comprador")
        self.assertRedirects(self.client.post(url, {**self.first_account, "username": "comprador"}), url)
        buyer = self.user_model.objects.get(username="comprador")
        self.assertFalse(buyer.is_superuser or buyer.is_staff)
        self.assertEqual(buyer.get_all_permissions(), {"pricing.view_product", "pricing.add_pricedraft"})
        self.client.logout()
        self.assertRedirects(
            self.client.post(reverse("login"), {"username": "comprador", "password": self.password}),
            reverse("pricing:search"),
        )
        self.assertEqual(self.client.get(url).status_code, 403)

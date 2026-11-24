import json
from decimal import Decimal
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote

from . import CollectionError, collect_offer, discover_product_urls, validate_product_url
from .extract import parse_offer

LIDER_URL = "https://www.smlider.com.br/1/produto/m/cafe-exemplo-12345"
TAUSTE_URL = "https://tauste.com.br/marilia/757-cafe-exemplo.html"
CONFIANCA_STORE = "https://www.confianca.com.br/marilia"
CONFIANCA_URL = f"{CONFIANCA_STORE}/p/cafe-exemplo/543"


def confianca_fixture(*, product=None, sku=None, path="/marilia/p/cafe-exemplo/543",
                       store_context=None, request_product_id="543"):
    catalog = {
        "products": {"543": {
            "id": "543",
            "route": "p/cafe-exemplo/543",
            "displayName": "Café Exemplo 500g",
            "childSKUs": ["CX-42"],
            "x_unitOfMeasurement": "KG",
            **(product or {}),
        }},
        "skus": {"CX-42": {
            "repositoryId": "CX-42",
            "barcode": "4006381333931",
            "active": True,
            "x_activeConfiancaEsmeralda": True,
            "soldAsPackage": True,
            "salePrices": {"DefaultPriceListEsmeralda": 20.4, "ClubPriceListEsmeralda": 19.5},
            "listPrices": {"DefaultPriceListEsmeralda": 21.4, "ClubPriceListEsmeralda": 21.4},
            **(sku or {}),
        }},
    }
    state = {
        "catalogRepository": catalog,
        "clientRepository": {
            "context": {
                "global": {
                    "site": "ConfiancaEsmeralda",
                    "priceListGroup": "DefaultPriceListEsmeralda",
                    "currencyCode": "BRL",
                    "path": path,
                    **(store_context or {}),
                },
                "request": {"productId": request_product_id},
            },
        },
    }
    encoded = quote(json.dumps(state, ensure_ascii=False), safe="")
    return f"<script>window.state = JSON.parse(decodeURI({json.dumps(encoded)}));</script>"


class CollectorTests(TestCase):
    def test_lider_distinguishes_current_and_previous_discount_prices(self):
        html = """
        <title>Café Exemplo 500g - Super Líder | Pompéia</title>
        <main>
            <div>Café Exemplo 500g</div>
            <p>Código: #<!-- -->000473</p>
            <div><span>R$ 17,90</span><span>- <!-- -->10<!-- -->%</span><span>R$ 19,90</span></div>
            <p>Subtotal: R$ 0,00</p>
        </main>
        """
        offer = parse_offer("lider", html, LIDER_URL)
        self.assertEqual(offer.external_code, "000473")
        self.assertEqual(offer.price, Decimal("17.90"))
        self.assertEqual(offer.condition, "promotion")

    def test_lider_uses_display_code_and_ignores_subtotal_and_recommendations(self):
        html = """
        <title>Café Exemplo 500g - Super Líder | Pompéia</title>
        <nav>Clube de vantagens</nav>
        <main>
            <div>Café Exemplo 500g</div>
            <p>Código: <b>#000473</b> Marca: Exemplo</p>
            <p>R$ <span>21,70</span></p>
            <p>Subtotal: R$ 0,00</p>
        </main>
        <aside>Produtos similares: Café diferente R$ 12,90</aside>
        """
        observed = parse_offer("lider", html, LIDER_URL)
        self.assertEqual(observed.external_code, "000473")
        self.assertEqual(observed.name, "Café Exemplo 500g")
        self.assertEqual(observed.price, Decimal("21.70"))
        self.assertEqual(observed.availability, "unknown")
        self.assertEqual(observed.condition, "unknown")
        self.assertEqual(observed.gtin, "")

    def test_lider_uses_code_even_if_price_comes_first(self):
        html = """
        <title>Café Exemplo 500g - Super Líder | Herculândia</title>
        <h1>Café Exemplo 500g</h1>
        <p>Clube</p><p>R$ 20,90</p><span>Código: #0244</span>
        <p>Subtotal: R$ 0,00</p>
        """
        observed = parse_offer("lider", html, LIDER_URL.replace("/1/", "/2/"))
        self.assertEqual(observed.condition, "club")
        self.assertEqual(observed.price, Decimal("20.90"))

    def test_tauste_uses_sale_price_and_ignores_reference_price_by_weight(self):
        html = """
        <h1>Café Exemplo 500g</h1>
        <div>De: R$ 21,90 Por: R$ 19,90 </div>
        <div>R$ 3,98/100g</div>
        <div>Em estoque</div>
        <span>COD.</span><span>757</span>
        <p>Quantidade:</p>
        """
        observed = parse_offer("tauste", html, TAUSTE_URL)
        self.assertEqual(observed.external_code, "757")
        self.assertEqual(observed.price, Decimal("19.90"))
        self.assertEqual(observed.condition, "promotion")
        self.assertEqual(observed.availability, "available")

    def test_lider_reads_the_explicit_price_per_kilo(self):
        html = """
        <title>CARNE BOV CONTRA FILE KG - Super Líder | Pompéia</title>
        <div>CARNE BOV CONTRA FILE KG</div><div>Código: # 000001</div>
        <div>R$ 50,90 / kg - 9% R$ 55,90</div><div>Subtotal: R$ 0,00</div>
        """
        offer = parse_offer("lider", html, LIDER_URL)
        self.assertEqual(offer.price, Decimal("50.90"))
        self.assertEqual(offer.price_unit, "kg")
        self.assertEqual(offer.condition, "promotion")

    def test_price_per_hundred_grams_is_secondary_to_the_package_price(self):
        html = """
        <h1>Contra Filé Bandeja 700g</h1><p>COD. 757</p>
        <p>R$ 47,65</p><p>R$ 6,81/100g</p><p>Quantidade:</p>
        """
        offer = parse_offer("tauste", html, TAUSTE_URL)
        self.assertEqual(offer.price, Decimal("47.65"))
        self.assertEqual(offer.price_unit, "")

    def test_ambiguous_prices_fail_closed(self):
        for text in ("R$ 19,90 R$ 21,90", "R$ 19,90 /kg R$ 19,90", "R$ 19,90 /kg - 10% R$ 21,90"):
            with self.subTest(text=text), self.assertRaises(CollectionError):
                parse_offer(
                    "tauste",
                    f"<h1>Café 500g</h1><span>COD. 757</span><div>{text}</div>",
                    TAUSTE_URL,
                )

    def test_confianca_requires_structured_identity_for_the_exact_page(self):
        html = confianca_fixture(sku={"x_activeConfiancaEsmeralda": False})
        observed = parse_offer("confianca", html, CONFIANCA_URL)
        self.assertEqual(observed.external_code, "CX-42")
        self.assertEqual(observed.name, "Café Exemplo 500g")
        self.assertEqual(observed.gtin, "4006381333931")
        self.assertEqual(observed.price, Decimal("20.40"))
        self.assertEqual(observed.club_price, Decimal("19.50"))
        self.assertEqual(observed.condition, "promotion")
        self.assertEqual(observed.availability, "unavailable")
        with self.assertRaises(CollectionError):
            parse_offer("confianca", html, CONFIANCA_URL.replace("cafe-exemplo", "outro-cafe"))

    def test_confianca_does_not_fall_back_to_global_or_other_city_prices(self):
        html = confianca_fixture(sku={
            "salePrice": 20.40,
            "listPrice": 21.40,
            "salePrices": {"DefaultPriceListSorocaba": 10, "ClubPriceListEsmeralda": 19.50},
            "listPrices": {"DefaultPriceListSorocaba": 12, "ClubPriceListEsmeralda": 21.40},
        })
        with self.assertRaises(CollectionError):
            parse_offer("confianca", html, CONFIANCA_URL)

    def test_confianca_requires_context_for_the_matching_store_and_product(self):
        for context in (
            {"site": "ConfiancaSorocaba"},
            {"currencyCode": "USD"},
            {"priceListGroup": "ClubPriceListEsmeralda"},
            {"path": "/marilia/p/outro-produto/543"},
        ):
            with self.subTest(context=context), self.assertRaises(CollectionError):
                parse_offer("confianca", confianca_fixture(store_context=context), CONFIANCA_URL)
        with self.assertRaises(CollectionError):
            parse_offer("confianca", confianca_fixture(request_product_id="999"), CONFIANCA_URL)

    def test_confianca_times_out_promotions_and_rejects_variable_weight(self):
        expired = confianca_fixture(sku={"salePriceEndDate": "2020-01-01T00:00:00Z"})
        observed = parse_offer("confianca", expired, CONFIANCA_URL)
        self.assertEqual(observed.condition, "regular")
        self.assertEqual(observed.price, Decimal("21.40"))
        self.assertIsNone(observed.club_price)
        with self.assertRaises(CollectionError):
            parse_offer("confianca", confianca_fixture(sku={"soldAsPackage": False}), CONFIANCA_URL)

    def test_mismatched_structured_metadata_does_not_supply_gtin(self):
        html = """
        <h1>Café Exemplo 500g</h1>
        <p>R$ 22,95 Em estoque COD. 757</p>
        <script type="application/ld+json">
        {"@type":"Product","name":"Café Exemplo 500g",
         "url":"/marilia/758-cafe-exemplo.html","sku":"758","gtin13":"4006381333931"}
        </script>
        """
        self.assertEqual(parse_offer("tauste", html, TAUSTE_URL).gtin, "")

    def test_validation_is_scoped_to_the_configured_retailer_and_store(self):
        store_url = "https://www.smlider.com.br/1"
        self.assertEqual(validate_product_url("lider", store_url, LIDER_URL), LIDER_URL)
        for product_url in (
            "https://www.example.com/1/produto/m/cafe",
            LIDER_URL.replace("/1/", "/2/"),
            LIDER_URL.replace("https:", "http:"),
            store_url,
        ):
            with self.subTest(product_url=product_url), self.assertRaises(CollectionError):
                validate_product_url("lider", store_url, product_url)

    def test_access_refusal_is_reported_without_fallback_requests(self):
        error = HTTPError(CONFIANCA_URL, 403, "Forbidden", {}, BytesIO())
        with patch("pricing.collectors.http.build_opener") as build_opener:
            opener = build_opener.return_value
            opener.open.side_effect = error
            with self.assertRaises(CollectionError) as raised:
                collect_offer("confianca", "https://www.confianca.com.br/marilia", CONFIANCA_URL)
            self.assertEqual(raised.exception.status, 403)
            opener.open.assert_called_once()


class DiscoveryTests(TestCase):
    @patch("pricing.collectors.discovery.fetch_html")
    def test_lider_filters_other_units_and_preserves_order_up_to_limit(self, fetch_html):
        store_url = "https://www.smlider.com.br/1"
        fetch_html.return_value = (
            """
            <a href="/2/produto/m/cafe-1">Outra unidade</a>
            <a href="/1/ofertas">Ofertas</a>
            <a href="/1/produto/m/cafe-2?utm_source=home">Café</a>
            <a href="https://smlider.com.br/1/produto/m/cafe-2">Repetido</a>
            <a href="/1/produto/m/leite-3">Leite</a>
            <a href="/1/produto/m/acucar-4">Açúcar</a>
            """,
            store_url,
        )
        actual = discover_product_urls("lider", store_url, 2)
        self.assertEqual(actual, [f"{store_url}/produto/m/cafe-2", f"{store_url}/produto/m/leite-3"])
        fetch_html.assert_called_once()

    @patch("pricing.collectors.discovery.fetch_html")
    def test_tauste_excludes_categories_other_cities_and_other_domains(self, fetch_html):
        store_url = "https://tauste.com.br/marilia/"
        fetch_html.return_value = (
            """
            <a href="bebidas.html">Categoria</a>
            <a href="/bauru/812-cafe.html">Outra cidade</a>
            <a href="https://www.example.com/marilia/812-cafe.html">Parceiro</a>
            <a href="812-cafe.html">Café</a>
            """,
            store_url,
        )
        self.assertEqual(discover_product_urls("tauste", store_url, 5), [f"{store_url}812-cafe.html"])

    @patch("pricing.collectors.discovery.fetch_html")
    def test_confianca_excludes_links_without_product_evidence(self, fetch_html):
        fetch_html.return_value = (
            '<a href="/marilia/ofertas">Ofertas</a>'
            '<a href="/marilia/p/cafe-1/123">Sem evidência de catálogo</a>'
            + confianca_fixture(path="/marilia", request_product_id=None),
            CONFIANCA_STORE,
        )
        self.assertEqual(discover_product_urls("confianca", CONFIANCA_STORE, 5), [CONFIANCA_URL])

    @patch("pricing.collectors.discovery.fetch_html")
    def test_confianca_discovers_product_routes_with_encoded_accents(self, fetch_html):
        fetch_html.return_value = (
            confianca_fixture(
                product={"route": "p/caf%C3%A9-exemplo/543"},
                path="/marilia",
                request_product_id=None,
            ),
            CONFIANCA_STORE,
        )
        self.assertEqual(
            discover_product_urls("confianca", CONFIANCA_STORE, 5),
            [f"{CONFIANCA_STORE}/p/caf%C3%A9-exemplo/543"],
        )

    @patch("pricing.collectors.discovery.fetch_html")
    def test_invalid_limit_fails_before_fetch(self, fetch_html):
        with self.assertRaises(CollectionError):
            discover_product_urls("lider", "https://www.smlider.com.br/1", 101)
        fetch_html.assert_not_called()

import json
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote, urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from django.urls import reverse

from .collectors import CollectedOffer, CollectionError
from .collectors.search import SearchPage, search_catalog
from .jobs import work_once
from .models import Product, Store
from .offer_search import SearchQuery, search_stores, search_unit


class CompetitorSearchTests(TestCase):
    def setUp(self):
        for cache in caches.all():
            cache.clear()

    def test_search_returns_offers_even_when_pompeia_catalog_is_empty(self):
        self.client.force_login(get_user_model().objects.create_superuser("operador"))
        expected = {
            "https://www.smlider.com.br/1": "10.49",
            "https://www.smlider.com.br/2": "10.59",
            "https://tauste.com.br/marilia/": "10.69",
            "https://www.confianca.com.br/marilia": "10.79",
        }

        def results(retailer, store_url, term, *, page_number=1):
            return SearchPage(((store_url + "#2l", "Coca-Cola 2000ml"),
                               (store_url + "#3l", "Coca Cola 3 L")))

        def offer(retailer, store_url, url):
            self.assertTrue(url.endswith("#2l"))
            return CollectedOffer("0012", "Coca-Cola 2 L", Decimal(expected[store_url]),
                                  "regular", "available", "", url)

        with patch("pricing.offer_search.search_catalog", side_effect=results) as catalog, patch(
            "pricing.offer_search.collect_offer", side_effect=offer,
        ) as details:
            self.client.get(reverse("pricing:search"), {"q": "Coca Cola 2 litros"})
            self.assertEqual(catalog.call_count, 0)
            self.client.post(reverse("pricing:refresh"), {"q": "Coca Cola 2 litros"})
            while work_once():
                pass
            response = self.client.get(reverse("pricing:search"), {"q": "Coca Cola 2 litros"})

        self.assertFalse(Product.objects.exists())
        self.assertEqual(catalog.call_count, 4)
        self.assertEqual(details.call_count, 4)
        for label in ("Pompéia", "Herculândia", "Tauste", "Confiança", "10,49", "10,59", "10,69", "10,79"):
            self.assertContains(response, label)
        self.assertNotContains(response, "Coca Cola 3 L")

    def test_failed_source_is_reported_while_other_sources_still_show_prices(self):
        self.client.force_login(get_user_model().objects.create_superuser("operador"))

        def results(retailer, store_url, term, *, page_number=1):
            if retailer == "tauste":
                raise CollectionError("O Tauste não respondeu.")
            return SearchPage(((store_url, "Coca Cola 2L"),))

        offer = CollectedOffer("012", "Coca Cola 2L", Decimal("10.90"),
                               "regular", "available", "", "https://www.smlider.com.br/1")
        with patch("pricing.offer_search.search_catalog", side_effect=results), patch(
            "pricing.offer_search.collect_offer", return_value=offer,
        ):
            job = self.client.post(reverse("pricing:refresh"), {"q": "Coca 2 litros"}).json()
            while work_once():
                pass
            response = self.client.get(reverse("pricing:search"), {"q": "Coca 2 litros"})
            partial = self.client.get(reverse("pricing:progress"), {"token": job["token"]}).json()
        self.assertEqual(sum(row["state"] == "updated" for row in partial["rows"]), 3)
        self.assertIn("O Tauste não respondeu.", [row["reason"] for row in partial["rows"]])
        self.assertContains(response, "10,90", count=3)

    def test_package_matching_accepts_equivalent_sizes_and_rejects_bundles(self):
        query = SearchQuery.from_text("Coca 2 litros")
        self.assertEqual(query.vendor_terms("tauste")[0], "coca-cola")
        for name in ("REFRIGERANTE COCACOLA 2L", "Refrigerante Coca-Cola Pet 2000 ml"):
            self.assertTrue(query.candidate(name, detail=True))
        for name in ("Coca Cola 2,5 L", "Coca-Cola 600 ml", "Coca Cola 2L + Fanta 2L",
                     "Pack Coca Cola 2L", "Coca Cola"):
            self.assertFalse(query.candidate(name, detail=True))

    def test_tauste_reads_product_result_links_and_excludes_category_links(self):
        html = '''<title>Resultados da busca por: coca-cola</title>
        <a href="/marilia/refrigerantes.html">Categoria</a>
        <a href="/marilia/refrigerante-coca-cola-pet-2000ml.html"><img alt="00000757"></a>
        <a class="product-item-link" href="/marilia/refrigerante-coca-cola-pet-2000ml.html">Refrigerante <strong>Coca-Cola</strong> Pet 2000ml</a>
        <a class="product-item-link" href="/bauru/refrigerante-coca-cola-pet-2000ml.html">Outra loja</a>'''
        with patch("pricing.collectors.search.fetch_html", side_effect=lambda url, validate: (html, validate(url))):
            results = search_catalog("tauste", "https://tauste.com.br/marilia/", "coca-cola")
        self.assertEqual(results.entries, ((
            "https://tauste.com.br/marilia/refrigerante-coca-cola-pet-2000ml.html",
            "Refrigerante Coca-Cola Pet 2000ml",
        ),))

    def test_confianca_reads_search_records_in_the_selected_market(self):
        search_path = "/search/?Ntt=coca+cola+2l&Nrpp=16"
        state = {
            "clientRepository": {"context": {"global": {
                "site": "ConfiancaEsmeralda", "priceListGroup": "DefaultPriceListEsmeralda",
                "currencyCode": "BRL", "path": "/marilia/search",
            }, "request": {"search": search_path}}},
            "searchRepository": {"pages": {search_path: {"results": {"records": [
                {"attributes": {"product.route": ["/p/refrigerante-coca-cola-2l/123"],
                                "product.displayName": ["Coca-Cola 2L"]}},
            ]}}}},
        }
        html = f'window.state = JSON.parse(decodeURI("{quote(json.dumps(state))}"))'
        with patch("pricing.collectors.search.fetch_html", side_effect=lambda url, validate: (html, validate(url))):
            page = search_catalog("confianca", "https://www.confianca.com.br/marilia", "coca cola 2l")
        [[url, name]] = page.entries
        self.assertEqual(urlsplit(url).path, "/marilia/p/refrigerante-coca-cola-2l/123")
        self.assertEqual(name, "Coca-Cola 2L")

    def test_search_validation_rejects_redirects_to_another_unit(self):
        def search_redirect(url, validate):
            validate(url.replace("/1/busca", "/2/busca"))

        with patch("pricing.collectors.search.fetch_html", side_effect=search_redirect), self.assertRaises(CollectionError):
            search_catalog("lider", "https://www.smlider.com.br/1", "coca cola 2l")

    def test_fallback_continues_when_the_first_matching_page_has_no_confirmed_price(self):
        store = Store.objects.get(slug="lider-pompeia")
        first = (store.url + "/first", "Heineken 600ml Garrafa")
        second = (store.url + "/second", "Heineken 600ml Retornável")
        offer = CollectedOffer("00027", second[1], Decimal("9.99"),
                               "regular", "available", "", second[0])
        with patch("pricing.offer_search.search_catalog", side_effect=[
            SearchPage((first,), has_next=True), SearchPage((second,)),
        ]) as catalog, patch("pricing.offer_search.collect_offer", side_effect=[
            CollectionError("Preço não exibido"), offer,
        ]):
            result = search_unit(store, SearchQuery.from_text("Heineken 600ml"))
        self.assertEqual([call.kwargs["page_number"] for call in catalog.call_args_list], [1, 2])
        self.assertEqual(result.offers[0].collected, offer)
        self.assertEqual(result.unpriced[0].url, first[0])

    def test_equivalent_package_format_and_terms(self):
        heineken = SearchQuery.from_text("Heineken 600 ml")
        self.assertTrue(heineken.candidate("CERV HEINEKEN GFA 0,6 LT", detail=True))
        self.assertFalse(heineken.candidate("HEINEKEN 6 X 600ML", detail=True))
        self.assertFalse(heineken.candidate("HEINEKEN LONG NECK 330ML", detail=True))
        self.assertTrue(SearchQuery.from_text("contra filé").candidate("CONTRAFILÉ BOVINO KG", detail=True))
        self.assertTrue(SearchQuery.from_text("cafe 500 gr").candidate("CAFE TRADICIONAL 500G", detail=True))
        self.assertTrue(SearchQuery.from_text("coca sem açúcar 2 litros").candidate("COCA-COLA ZERO 2L", detail=True))

    def test_lider_confirms_availability_and_price_separately_for_each_unit(self):
        first = Store.objects.get(slug="lider-pompeia")
        second = Store.objects.get(slug="lider-herculandia")
        name = "CERVEJA HEINEKEN GARRAFA 600ML RETORNÁVEL"

        def pages(retailer, store_url, term, *, page_number=1):
            links = () if store_url == first.url else ((store_url + "/produto/m/heineken-12", name),)
            return SearchPage(links)

        def offers(retailer, store_url, url):
            if store_url == first.url:
                self.assertEqual(url, first.url + "/produto/m/heineken-12")
                return CollectedOffer("0012", name, Decimal("9.79"), "unknown", "unavailable", "", url)
            return CollectedOffer("0012", name, Decimal("9.98"), "unknown", "available", "", url)

        with patch("pricing.offer_search.search_catalog", side_effect=pages), patch(
            "pricing.offer_search.collect_offer", side_effect=offers,
        ):
            result_first, result_second = search_stores((first, second), "Heineken 600ml")
        self.assertEqual(result_first.offers[0].collected.availability, "unavailable")
        self.assertEqual(result_first.offers[0].collected.price, Decimal("9.79"))
        self.assertEqual(result_second.offers[0].collected.price, Decimal("9.98"))

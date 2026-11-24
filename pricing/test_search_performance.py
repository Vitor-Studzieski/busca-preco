from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from time import monotonic
from unittest.mock import patch

from django.core.cache import caches
from django.test import TestCase, override_settings
from django.utils import timezone

from . import offer_search
from .collectors import CollectedOffer
from .models import Store
from .offer_search import SearchOffer, StoreSearch, search_stores


class SearchPerformanceTests(TestCase):
    def setUp(self):
        caches["pricing_search"].clear()
        self.first = Store.objects.get(slug="tauste-marilia")
        self.second = Store.objects.get(slug="confianca-marilia")

    def offer(self, store, name="Coca-Cola 2L", unit=""):
        result = CollectedOffer("001", name, Decimal("10.00"), "regular", "available", "",
                                store.url, price_unit=unit)
        return StoreSearch(store, (SearchOffer(result),), timezone.now())

    def test_normalized_cache_keeps_offers_and_observation_time_by_store(self):
        with patch("pricing.offer_search.search_unit", side_effect=lambda store, *args, **kw: self.offer(store)) as fetch:
            cold = search_stores((self.first, self.second), "Coca-Cola 2 litros")
            repeat = search_stores((self.second, self.first), "COCA 2000 ml")
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(cold, list(reversed(repeat)))
            search_stores((self.first,), "Coca-Cola 600ml")
            search_stores((self.first,), "Coca-Cola Zero 2L")
            self.assertEqual(fetch.call_count, 4)

    @override_settings(PRICING_SEARCH_FAILURE_TTL=0)
    def test_temporary_failure_has_its_own_expiry_and_status(self):
        def fetch(store, *args, **kwargs):
            return StoreSearch(store, (), issue="Falha temporária" if store == self.first else "")

        with patch("pricing.offer_search.search_unit", side_effect=fetch) as lookup:
            first = search_stores((self.first, self.second), "Heineken 600 ml")
            repeat = search_stores((self.first, self.second), "Heineken 600ml")
        self.assertEqual(lookup.call_count, 3)
        for results in (first, repeat):
            self.assertEqual(results[0].issue, "Falha temporária")
            self.assertEqual(results[1].issue, "")

    def test_two_concurrent_calls_share_one_source_lookup(self):
        started, release, joined = Event(), Event(), Event()
        original_schedule = offer_search.schedule_search

        def lookup(store, *args, **kwargs):
            started.set()
            if not release.wait(timeout=3):
                raise AssertionError("Lookup waited for test release")
            return self.offer(store)

        def schedule(key, worker):
            future = original_schedule(key, worker)
            if started.is_set():
                joined.set()
            return future

        with patch("pricing.offer_search.search_unit", side_effect=lookup) as fetch, ThreadPoolExecutor(2) as callers:
            first = callers.submit(search_stores, (self.first,), "Coca-Cola 2 L")
            try:
                self.assertTrue(started.wait(2))
                with patch("pricing.offer_search.schedule_search", side_effect=schedule):
                    second = callers.submit(search_stores, (self.first,), "Coca 2000ml")
                    self.assertTrue(joined.wait(2))
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
        self.assertEqual(fetch.call_count, 1)

    @override_settings(PRICING_SEARCH_TIMEOUT=0.35)
    def test_slow_source_does_not_block_prices_from_other_units(self):
        release = Event()

        def fetch(store, *args, **kwargs):
            if store == self.first:
                release.wait(timeout=3)
                return StoreSearch(store, (), issue=offer_search.TIMEOUT_ISSUE)
            return self.offer(store, "Contra-filé", "kg")

        with patch("pricing.offer_search.search_unit", side_effect=fetch):
            began = monotonic()
            try:
                slow, ready = search_stores((self.first, self.second), "contra-filé")
                self.assertLess(monotonic() - began, 1.5)
                self.assertEqual(slow.issue, offer_search.TIMEOUT_ISSUE)
                self.assertEqual(ready.offers[0].collected.price_unit, "kg")
            finally:
                with offer_search.pending_lock:
                    pending = list(offer_search.pending_searches.values())
                release.set()
                for job in pending:
                    job.result(timeout=2)

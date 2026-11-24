import time

from django.core.management.base import BaseCommand, CommandError

from pricing.models import Listing, Store
from pricing.services import collect_listing


class Command(BaseCommand):
    help = "Coleta as páginas públicas dos anúncios cadastrados."

    def add_arguments(self, parser):
        parser.add_argument("--loja", choices=list(Store.Retailer.values))
        parser.add_argument("--unidade", help="Identificador da unidade, como lider-pompeia.")

    def handle(self, *args, **options):
        listings = Listing.objects.select_related("store").order_by("store_id", "pk")
        if options["loja"]:
            listings = listings.filter(store__retailer=options["loja"])
        if options["unidade"]:
            if not Store.objects.filter(slug=options["unidade"]).exists():
                raise CommandError("Unidade desconhecida.")
            listings = listings.filter(store__slug=options["unidade"])
        total = failed = 0
        previous_store = None
        paused = set()
        for listing in listings.iterator(chunk_size=200):
            if listing.store.retailer in paused:
                continue
            if previous_store == listing.store_id:
                time.sleep(1)
            status, message, http_status = collect_listing(listing)
            total += 1
            failed += status != Listing.Status.OK
            self.stdout.write(f"{listing.store} · {message}")
            previous_store = listing.store_id
            if http_status in {401, 403, 429}:
                paused.add(listing.store.retailer)
                self.stderr.write(f"{listing.store} · Rede pausada nesta execução.")
        self.stdout.write(f"Tentativas: {total}. Com falha ou conflito: {failed}.")
        if failed:
            raise CommandError("Revise as falhas ou divergências no cadastro de anúncios.")

from django.core.management.base import BaseCommand, CommandError

from pricing.collectors import MAX_DISCOVERY_LINKS, CollectionError, discover_product_urls
from pricing.models import Listing, Store


class Command(BaseCommand):
    help = "Cadastra os links de produtos visíveis no catálogo inicial de cada unidade."

    def add_arguments(self, parser):
        parser.add_argument("--unidade", help="Identificador da unidade, como lider-pompeia.")
        parser.add_argument("--limite", type=int, default=15, help="Limite de links por unidade.")

    def handle(self, *args, **options):
        limit = options["limite"]
        if not 1 <= limit <= MAX_DISCOVERY_LINKS:
            raise CommandError(f"O limite deve ficar entre 1 e {MAX_DISCOVERY_LINKS}.")
        stores = Store.objects.all()
        if options["unidade"]:
            stores = stores.filter(slug=options["unidade"])
        if not stores.exists():
            raise CommandError("Nenhuma unidade encontrada.")

        failed = []
        paused = set()
        for store in stores:
            if store.retailer in paused:
                self.stdout.write(f"{store} · Rede pausada nesta execução.")
                continue
            try:
                urls = discover_product_urls(store.retailer, store.url, limit)
            except CollectionError as error:
                self.stderr.write(f"{store} · {error}")
                failed.append(store.slug)
                if error.status in {401, 403, 429}:
                    paused.add(store.retailer)
                continue
            added = 0
            for url in urls:
                _, created = Listing.objects.get_or_create(store=store, url=url)
                added += created
            self.stdout.write(f"{store} · {len(urls)} link(s) encontrado(s), {added} novo(s).")
        if failed:
            raise CommandError(f"Descoberta incompleta: {', '.join(failed)}.")

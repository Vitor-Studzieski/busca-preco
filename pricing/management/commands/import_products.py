import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pricing.models import Product


class Command(BaseCommand):
    help = "Importa produtos Pompeia de CSV UTF-8 separado por ponto e vírgula."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")

    def handle(self, *args, **options):
        required = {"sku", "nome", "embalagem", "ean"}
        count = 0
        seen_skus = set()
        try:
            if Path(options["arquivo"]).stat().st_size > 25 * 1024 * 1024:
                raise CommandError("O CSV excede o limite de 25 MiB.")
            with open(options["arquivo"], encoding="utf-8-sig", newline="") as source, transaction.atomic():
                rows = csv.DictReader(source, delimiter=";", strict=True)
                if not required.issubset(rows.fieldnames or []):
                    raise CommandError("Colunas obrigatórias: sku;nome;embalagem;ean.")
                for row in rows:
                    if None in row or any(value is None for value in row.values()):
                        raise CommandError(f"Linha {rows.line_num}: número de campos inválido.")
                    sku = row["sku"].strip()
                    if not sku or sku in seen_skus:
                        raise CommandError(f"Linha {rows.line_num}: SKU vazio ou repetido.")
                    seen_skus.add(sku)
                    product = Product.objects.select_for_update().filter(sku=sku).first() or Product(sku=sku)
                    product.name = row["nome"].strip()
                    product.package = row["embalagem"].strip()
                    product.gtin = row["ean"].strip()
                    price = row.get("preco_vigente", "").strip()
                    try:
                        if "preco_vigente" in row:
                            product.current_price = Decimal(price.replace(",", ".")) if price else None
                        product.full_clean(exclude=["search_name"])
                    except (InvalidOperation, ValidationError) as error:
                        raise CommandError(f"Linha {rows.line_num}: dados inválidos. {error}") from error
                    product.save()
                    count += 1
        except (OSError, UnicodeError, csv.Error) as error:
            raise CommandError(f"Não foi possível ler o CSV. {error}") from error
        self.stdout.write(self.style.SUCCESS(f"{count} produto(s) importado(s)."))

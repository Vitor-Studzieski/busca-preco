import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection, connections, transaction

MODELS = (
    "auth.group", "auth.user",
    "pricing.initialaccountsetup", "pricing.store", "pricing.product",
    "pricing.listing", "pricing.observation", "pricing.pricedraft",
)


def signature(path):
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows.sort(key=lambda row: (row["model"], row["pk"]))
    for row in rows:
        for key in ("groups", "user_permissions", "permissions"):
            value = row["fields"].get(key)
            if isinstance(value, list):
                value.sort()
    normalized = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return len(rows), hashlib.sha256(normalized.encode()).hexdigest()


class Command(BaseCommand):
    help = "Transfere o catálogo e contas de uma cópia SQLite migrada para PostgreSQL vazio."

    def add_arguments(self, parser):
        parser.add_argument("copia_sqlite", type=Path)

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Configure a conexão PostgreSQL antes de transferir os dados.")
        source = options["copia_sqlite"].resolve(strict=True)
        if not source.is_file():
            raise CommandError("Informe uma cópia local do SQLite.")
        connections.databases["legacy_source"] = {
            **settings.DATABASES["default"], "ENGINE": "django.db.backends.sqlite3",
            "NAME": source.as_uri() + "?mode=ro", "OPTIONS": {"uri": True},
            "USER": "", "PASSWORD": "", "HOST": "", "PORT": "",
        }
        from django.apps import apps

        models = [apps.get_model(name) for name in MODELS if name != "pricing.store"]
        with TemporaryDirectory(prefix="pompeia-transfer-") as temp:
            old = Path(temp) / "source.json"
            new = Path(temp) / "destination.json"
            call_command("dumpdata", *MODELS, database="legacy_source", use_natural_foreign_keys=True,
                         use_base_manager=True, output=str(old))
            os.chmod(old, 0o600)
            expected = signature(old)
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("LOCK TABLE pricing_store IN SHARE ROW EXCLUSIVE MODE")
                if any(model._base_manager.exists() for model in models):
                    raise CommandError("O destino já contém registros. Use uma base PostgreSQL nova.")
                call_command("loaddata", str(old), verbosity=0)
                call_command("dumpdata", *MODELS, use_natural_foreign_keys=True,
                             use_base_manager=True, output=str(new))
                os.chmod(new, 0o600)
                actual = signature(new)
                if expected != actual:
                    raise CommandError("Contagem ou checksum divergente. A transação foi revertida.")
        self.stdout.write(f"Transferência validada: {actual[0]} registros. SHA-256: {actual[1]}")

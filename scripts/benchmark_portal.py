"""Benchmark com fontes reais em banco PostgreSQL isolado e vazio."""
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter, sleep

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django.setup()

from benchmark import TERMS, summary  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connections  # noqa: E402
from django.test import Client, override_settings  # noqa: E402

from pricing.management.commands.collection_worker import work_with_connection  # noqa: E402
from pricing.workflow_models import CollectionJob  # noqa: E402


def worker():
    while work_with_connection():
        pass
    connections.close_all()


def main():
    if os.environ.get("POSTGRES_DB") != "pompeia_benchmark" or CollectionJob.objects.exists():
        raise SystemExit("Use um banco PostgreSQL isolado e vazio chamado pompeia_benchmark.")
    logging.getLogger("pricing").setLevel(logging.WARNING)
    user = get_user_model().objects.create_superuser(username="benchmark")
    entries, per_store = [], {}
    terms = TERMS[:int(sys.argv[1])] if len(sys.argv) > 1 else TERMS
    with override_settings(ALLOWED_HOSTS=["testserver"], PRICING_SEARCH_RATE_LIMIT=60):
        client = Client()
        client.force_login(user)
        with ThreadPoolExecutor(max_workers=3) as workers:
            for term in terms:
                start = perf_counter()
                cold = client.get("/", {"q": term})
                cold_ms = (perf_counter() - start) * 1000
                assert cold.status_code == 200, cold.status_code
                start = perf_counter()
                ticket = client.post("/pesquisa/atualizar/", {"q": term}).json()
                runners = [workers.submit(worker) for _ in range(3)]
                for future in runners:
                    future.result()
                elapsed = perf_counter() - start
                results = client.get("/pesquisa/progresso/", HTTP_X_COLLECTION_TICKET=ticket["token"]).json()
                start = perf_counter()
                assert client.get("/", {"q": term}).status_code == 200
                warm_ms = (perf_counter() - start) * 1000
                for row in results["rows"]:
                    if row.get("duration_ms") is not None:
                        per_store.setdefault(row["store"], []).append(row["duration_ms"] / 1000)
                entries.append({"term": term, "cold_ms": cold_ms, "warm_ms": warm_ms, "live_s": elapsed,
                                "rows": [{"store": r["store"], "state": r["state"], "reason": r.get("reason", ""),
                                          "duration_ms": r.get("duration_ms")} for r in results["rows"]]})
                sleep(1)
    print(json.dumps({"samples": entries, "cold": summary([e["cold_ms"] / 1000 for e in entries]),
                      "warm": summary([e["warm_ms"] / 1000 for e in entries]),
                      "live": summary([e["live_s"] for e in entries]),
                      "per_store": {i: summary(v) for i, v in per_store.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Mede a busca original por rede sem gravar ofertas. Execute somente com acesso autorizado."""
import json
import os
import statistics
import sys
from collections import defaultdict
from time import perf_counter, sleep

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django.setup()

from django.core.cache import caches  # noqa: E402

from pricing import offer_search  # noqa: E402
from pricing.models import Store  # noqa: E402

TERMS = (
    "arroz 5 kg", "feijao carioca 1 kg", "cafe 500 g", "leite integral 1 l", "coca cola 2 l",
    "detergente ype 500 ml", "oleo soja 900 ml", "acucar 1 kg", "sal 1 kg", "farinha trigo 1 kg",
    "contra file kg", "banana prata kg", "tomate kg", "batata kg", "cebola kg",
    "cerveja heineken 600 ml", "papel higienico 4 rolos", "manteiga 200 g", "macarrao 500 g",
    "biscoito 200 g", "iogurte 170 g", "sabao em po 1 kg", "amaciante 2 l",
    "levite integral 1 l", "cerv 350 ml", "refrig cola zero 2 l", "detg liq ype 500 ml",
    "7894900011517", "00000757", "7891000100103",
)


def summary(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {"n": len(ordered), "p50_s": round(statistics.median(ordered), 3),
            "p95_s": round(ordered[(95 * len(ordered) - 1) // 100], 3)}


def main():
    stores = list(Store.objects.all())
    original = offer_search.search_unit
    durations = defaultdict(list)
    blocked = set()
    samples = []

    def timed(store, query, **kwargs):
        start = perf_counter()
        try:
            return original(store, query, **kwargs)
        finally:
            durations[store.slug].append(perf_counter() - start)

    offer_search.search_unit = timed
    for term in TERMS[:int(sys.argv[1]) if len(sys.argv) > 1 else len(TERMS)]:
        active = [store for store in stores if store.retailer not in blocked]
        if not active:
            break
        caches["pricing_search"].clear()
        start = perf_counter()
        results = offer_search.search_stores(active, term)
        elapsed = perf_counter() - start
        rows = []
        for result in results:
            issue = result.issue
            if any(f"HTTP {code}" in issue for code in (401, 403, 429)):
                blocked.add(result.store.retailer)
            status = ("bloqueado" if result.store.retailer in blocked else
                      "timeout" if "tempo disponível" in issue else "erro" if issue else
                      "confirmado" if result.offers else "sem_preco" if result.unpriced else
                      "nao_encontrado")
            rows.append({"unidade": result.store.slug, "estado": status,
                         "ofertas_confirmadas": len(result.offers), "motivo": issue})
        samples.append({"consulta": term, "tempo_s": round(elapsed, 3), "unidades": rows})
        sleep(2)
    print(json.dumps({"amostras": samples, "tempo_total": summary([s["tempo_s"] for s in samples]),
                      "por_unidade": {k: summary(v) for k, v in durations.items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

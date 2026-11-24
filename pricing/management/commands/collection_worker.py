from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection, connections

from pricing.jobs import schedule_due, work_once


def work_with_connection():
    close_old_connections()
    try:
        return work_once()
    finally:
        connections.close_all()


class Command(BaseCommand):
    help = "Processa a fila persistente e inicia as duas janelas diárias de coleta."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Agenda e processa um item.")

    def handle(self, *args, **options):
        if options["once"]:
            schedule_due()
            work_with_connection()
            return

        slots = 3 if connection.vendor == "postgresql" else 1
        next_tick = 0
        pending = set()
        with ThreadPoolExecutor(max_workers=slots) as workers:
            while True:
                close_old_connections()
                tick = monotonic()
                if tick >= next_tick:
                    schedule_due()
                    next_tick = tick + 30
                for future in tuple(pending):
                    if future.done():
                        future.result()
                        pending.remove(future)
                while len(pending) < slots:
                    pending.add(workers.submit(work_with_connection))
                sleep(1)

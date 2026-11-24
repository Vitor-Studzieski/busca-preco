import signal
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connections

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

        slots = 3
        shutdown = Event()
        previous_sigterm_handler = signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
        next_tick = 0
        pending = set()
        idle_delay = 1
        try:
            with ThreadPoolExecutor(max_workers=slots) as workers:
                while not shutdown.is_set():
                    close_old_connections()
                    tick = monotonic()
                    if tick >= next_tick:
                        schedule_due()
                        next_tick = tick + 30
                    did_work = False
                    for future in tuple(pending):
                        if future.done():
                            did_work = future.result() or did_work
                            pending.remove(future)
                    if pending:
                        while not shutdown.is_set() and len(pending) < slots:
                            pending.add(workers.submit(work_with_connection))
                        if did_work:
                            idle_delay = 1
                        shutdown.wait(1)
                    else:
                        if did_work:
                            idle_delay = 1
                        else:
                            shutdown.wait(idle_delay)
                            idle_delay = min(idle_delay * 2, 5)
                        while not shutdown.is_set() and len(pending) < slots:
                            pending.add(workers.submit(work_with_connection))
                for future in pending:
                    future.result()
        finally:
            connections.close_all()
            signal.signal(signal.SIGTERM, previous_sigterm_handler)

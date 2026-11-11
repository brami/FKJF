"""Versanddienst für Newsletter (läuft als systemd-Dienst fv-web-newsletter).

    python manage.py newsletter_dienst            # dauerhaft
    python manage.py newsletter_dienst --einmal   # bis nichts mehr zu tun ist (Entwicklung)
"""

import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from seiten import newsletter
from seiten.models import Versand


class Command(BaseCommand):
    help = "Verschickt Newsletter: Probe, Pause, dann jede E-Mail einzeln."

    def add_arguments(self, parser):
        parser.add_argument("--einmal", action="store_true",
                            help="Beenden, sobald kein Versand mehr läuft (Pausen werden abgewartet).")

    def handle(self, einmal=False, **opts):
        self.ende = False
        signal.signal(signal.SIGTERM, self._beenden)
        signal.signal(signal.SIGINT, self._beenden)
        self.stdout.write("Newsletter-Dienst gestartet.")
        while not self.ende:
            if not connection.in_atomic_block:   # (in Tests läuft alles in einer Transaktion)
                close_old_connections()
            newsletter.herzschlag()
            try:
                warten = newsletter.schritt()
            except Exception as fehler:   # Datenbank kurz weg o. Ä.: weiterlaufen
                self.stderr.write(f"Fehler: {fehler}")
                warten = 10.0
            if einmal and not Versand.objects.filter(status=Versand.Status.LAEUFT).exists():
                break
            self._schlafen(warten)
        self.stdout.write("Newsletter-Dienst beendet.")

    def _beenden(self, *args):
        self.ende = True

    def _schlafen(self, sekunden):
        ende = time.monotonic() + sekunden
        while not self.ende and time.monotonic() < ende:
            time.sleep(min(0.5, max(0.0, ende - time.monotonic())))

"""Belegung der Postfächer einlesen (vom Mailserver, z. B. alle 15 Minuten):

    doveadm -f flow quota get -A | fv-manage mail_belegung
"""

import sys

from django.core.management.base import BaseCommand

from seiten.mail import belegung_einlesen


class Command(BaseCommand):
    help = "Liest die Ausgabe von „doveadm -f flow quota get -A“ von der Standardeingabe."

    def handle(self, *args, **opts):
        n = belegung_einlesen(sys.stdin.read())
        self.stdout.write(f"Belegung für {n} Postfächer übernommen.")

"""Plus-Adressen übernehmen, an die Mail zugestellt wurde (vom Mailserver regelmäßig):

    <Empfängeradressen aus dem Exim-Protokoll> | fv-manage mail_plusadressen

Eine Adresse je Zeile und zugestellter Mail; ein Zeitstempel davor wird ignoriert.
Nur Plus-Adressen von Postfächern und Aliasen werden gespeichert – sichtbar nur für
die jeweilige Person (Konto → Mail), nicht für den Vorstand.
"""

import sys

from django.core.management.base import BaseCommand

from seiten.mail import plusadressen_einlesen


class Command(BaseCommand):
    help = "Liest zugestellte Plus-Adressen von der Standardeingabe."

    def handle(self, *args, **opts):
        n = plusadressen_einlesen(sys.stdin.read())
        self.stdout.write(f"{n} Plus-Adressen aktualisiert.")

"""Abwesenheitsnotizen als Sieve-Regeln schreiben (vom Mailserver regelmäßig aufgerufen).

    fv-manage mail_sieve --ziel /run/fv-web-sieve

Je Postfach eine Datei <nummer>.sieve (Nummer = Verzeichnis /var/vmail/konten/<nummer>).
Geschrieben wird nur, was sich geändert hat; Dateien gelöschter Postfächer werden
entfernt. Der Mailserver übernimmt die Dateien in die Postfächer.
"""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from seiten.mail import sieve_skript


class Command(BaseCommand):
    help = "Schreibt die Abwesenheitsnotizen als Sieve-Dateien in ein Verzeichnis."

    def add_arguments(self, parser):
        parser.add_argument("--ziel", required=True, help="Verzeichnis für die .sieve-Dateien")

    def handle(self, *args, **opts):
        ziel = Path(opts["ziel"])
        ziel.mkdir(parents=True, exist_ok=True)
        User = get_user_model()
        geschrieben, vorhanden = 0, set()
        for u in User.objects.filter(profil__hat_postfach=True).select_related("profil"):
            datei = ziel / f"{u.pk}.sieve"
            vorhanden.add(datei.name)
            inhalt = sieve_skript(u)
            if not datei.exists() or datei.read_text(encoding="utf-8") != inhalt:
                tmp = datei.with_suffix(".tmp")
                tmp.write_text(inhalt, encoding="utf-8")
                tmp.replace(datei)
                geschrieben += 1
        for alt in ziel.glob("*.sieve"):
            if alt.name not in vorhanden:
                alt.unlink()
        self.stdout.write(f"{geschrieben} Sieve-Dateien aktualisiert, {len(vorhanden)} Postfächer.")

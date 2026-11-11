"""Gelöschte Seiten auflisten und wiederherstellen.

    sudo fv-manage seite_wiederherstellen          gelöschte Seiten auflisten
    sudo fv-manage seite_wiederherstellen <nr>     Seite <nr> wiederherstellen

Titel, Datum, Sichtbarkeit und Text kommen aus dem Versionsverlauf. Die Dateien der
Anhänge wurden beim Löschen entfernt: Liegen sie noch nicht wieder auf dem Server,
nennt der Befehl die Pfade und den Befehl, sie aus der Datensicherung zu holen.
Danach denselben Befehl noch einmal aufrufen – er ergänzt die fehlenden Anhänge.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from seiten.models import Anhang, Seite, Stufe


class Command(BaseCommand):
    help = "Gelöschte Seiten auflisten bzw. eine Seite mit Anhängen wiederherstellen."

    def add_arguments(self, parser):
        parser.add_argument("nr", nargs="?", type=int, help="Nummer der Seite (aus der Liste)")

    def handle(self, nr=None, **opts):
        if nr is None:
            return self.liste()
        self.wiederherstellen(nr)

    def liste(self):
        vorhanden = set(Seite.objects.values_list("id", flat=True))
        gesehen = set()
        zeilen = []
        for h in Seite.history.filter(history_type="-").order_by("-history_date"):
            if h.id in vorhanden or h.id in gesehen:
                continue
            gesehen.add(h.id)
            von = h.history_user.get_username() if h.history_user else "–"
            zeilen.append(f"{h.id:>5}  {timezone.localtime(h.history_date):%d.%m.%Y %H:%M}  {von:<20} {h.titel}")
        if not zeilen:
            self.stdout.write("Keine gelöschten Seiten.")
            return
        self.stdout.write("  Nr.  gelöscht am       von                  Titel")
        for z in zeilen:
            self.stdout.write(z)
        self.stdout.write("Wiederherstellen: sudo fv-manage seite_wiederherstellen <Nr.>")

    @transaction.atomic
    def wiederherstellen(self, nr):
        seite = Seite.objects.filter(pk=nr).first()
        if seite is None:
            h = Seite.history.filter(id=nr, history_type="-").order_by("-history_date").first()
            if h is None:
                raise CommandError(f"Zu Nummer {nr} gibt es keine gelöschte Seite.")
            seite = h.instance
            if seite.stufe_id and not Stufe.objects.filter(pk=seite.stufe_id).exists():
                ersatz = Stufe.objects.filter(darf_bearbeiten=True).order_by("-rang").first()
                seite.stufe = ersatz
                self.stdout.write(f"Die Stufe der Seite gibt es nicht mehr – vorerst sichtbar für: "
                                  f"{ersatz.name if ersatz else 'Öffentlich'}.")
            seite._change_reason = "wiederhergestellt"
            seite.save()
            self.stdout.write(f"Seite wiederhergestellt: „{seite.titel}“ ({seite.get_absolute_url()})")
        else:
            self.stdout.write(f"Seite „{seite.titel}“ ist vorhanden – ergänze fehlende Anhänge.")

        vorhanden = set(Anhang.objects.values_list("id", flat=True))
        fehlend, ok = [], 0
        letzte = {}
        for h in Anhang.history.filter(seite_id=nr).order_by("history_date"):
            letzte[h.id] = h
        for aid, h in letzte.items():
            if h.history_type != "-" or aid in vorhanden:
                continue
            a = h.instance
            dateien = [f for f in (a.datei, a.bild, a.vorschaubild) if f]
            pfade = [f.storage.path(f.name) for f in dateien if not f.storage.exists(f.name)]
            if pfade:
                fehlend.append((a, pfade))
                continue
            a.seite_id = nr
            a._change_reason = "wiederhergestellt"
            a.save()
            ok += 1
        if ok:
            self.stdout.write(f"{ok} Anhang/Anhänge wiederhergestellt.")
        if fehlend:
            self.stdout.write(f"{len(fehlend)} Anhang/Anhänge: Dateien fehlen und müssen aus der "
                              "Datensicherung geholt werden:")
            alle = []
            for a, pfade in fehlend:
                self.stdout.write(f"  {a.dateiname}")
                alle += pfade
            self.stdout.write("Befehl (Stand vor dem Löschen wählen, siehe sudo fv-web-restore -l):")
            self.stdout.write("  sudo fv-web-restore -r <stand> " + " ".join(f"-d {p}" for p in alle))
            self.stdout.write(f"Danach erneut: sudo fv-manage seite_wiederherstellen {nr}")

"""Gesperrte Postfächer nach der Löschfrist löschen (täglich vom Mailserver aufgerufen).

    fv-manage mail_aufraeumen                 Vorstand an bald fällige Löschungen erinnern
    fv-manage mail_aufraeumen --faellig       Nummern der fälligen Postfächer ausgeben
                                              (Verzeichnis /var/vmail/konten/<nummer>)
    fv-manage mail_aufraeumen --geloescht 17  Löschung von Postfach 17 eintragen: Adressen
                                              sperren, Vorstand benachrichtigen

Die Webseite löscht selbst keine Postfächer – das darf nur der Mailserver (Benutzer
vmail). Er fragt --faellig ab, löscht die Verzeichnisse und meldet sie mit
--geloescht zurück.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from seiten import mail


class Command(BaseCommand):
    help = "Erinnert an fällige Löschungen gesperrter Postfächer und trägt Löschungen ein."

    def add_arguments(self, parser):
        parser.add_argument("--faellig", action="store_true",
                            help="Nummern der Postfächer ausgeben, deren Löschfrist abgelaufen ist.")
        parser.add_argument("--geloescht", nargs="+", type=int, metavar="NUMMER",
                            help="Diese Postfächer wurden gelöscht.")

    def handle(self, *args, **opts):
        if opts["faellig"]:
            for p in mail.faellige_postfaecher():
                self.stdout.write(str(p.user_id))
            return
        if opts["geloescht"]:
            User = get_user_model()
            erledigt = []
            for nr in opts["geloescht"]:
                user = User.objects.filter(pk=nr, profil__hat_postfach=True).first()
                if user is None:
                    raise CommandError(f"Kein Postfach mit der Nummer {nr}.")
                if not mail.faellige_postfaecher().filter(user=user).exists():
                    raise CommandError(f"Postfach {nr} ist nicht zur Löschung fällig.")
                erledigt.append((user.get_full_name() or user.username, mail.postfach_geloescht(user)))
            mail._an_vorstand("Postfächer gelöscht", "mail/geloescht.txt", {"geloescht": erledigt})
            for name, adressen in erledigt:
                self.stdout.write(f"Gelöscht eingetragen: {name} ({', '.join(adressen) or '–'})")
            return
        for p in mail.vorwarnen():
            self.stdout.write(f"Erinnerung verschickt: {p.user} – Löschung am "
                              f"{mail.loeschdatum(p):%d.%m.%Y}")

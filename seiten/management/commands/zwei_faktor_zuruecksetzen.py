"""Zwei-Faktor-Anmeldung einer Person zurücksetzen (z. B. Smartphone verloren, keine
Wiederherstellungscodes).

    sudo fv-manage zwei_faktor_zuruecksetzen <benutzername oder e-mail>

Danach meldet sich die Person nur mit dem Passwort an. Gehört sie zu einer Stufe mit
Bearbeitungsrecht, muss sie die Zwei-Faktor-Anmeldung direkt danach neu einrichten.
"""

from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from seiten import rechte


class Command(BaseCommand):
    help = "Zwei-Faktor-Anmeldung (Authenticator-App, Wiederherstellungscodes) einer Person löschen."

    def add_arguments(self, parser):
        parser.add_argument("person", help="Benutzername oder E-Mail-Adresse")

    def handle(self, person, **opts):
        User = get_user_model()
        treffer = list(User.objects.filter(Q(username=person) | Q(email__iexact=person)))
        if len(treffer) != 1:
            raise CommandError(f"Keine eindeutige Person „{person}“ gefunden.")
        user = treffer[0]
        geloescht = Authenticator.objects.filter(user=user)
        arten = sorted(set(geloescht.values_list("type", flat=True)))
        anzahl, _ = geloescht.delete()
        if not anzahl:
            self.stdout.write(f"{user.username}: keine Zwei-Faktor-Anmeldung eingerichtet – nichts zu tun.")
            return
        self.stdout.write(f"{user.username}: Zwei-Faktor-Anmeldung zurückgesetzt ({', '.join(arten)}).")
        if rechte.darf_bearbeiten(user):
            self.stdout.write("Die Person darf bearbeiten und muss sie bei der nächsten Anmeldung "
                              "neu einrichten.")

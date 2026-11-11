"""Legt ein Vorstandskonto an (oder ergänzt ein bestehendes) und gibt einen Link aus,
mit dem die Person ihr Passwort selbst setzt.

    python manage.py vorstand_anlegen vorname.nachname adresse@example.org [--admin] [--stufe NAME]

Ohne --stufe kommt die Person in die höchste Stufe mit Bearbeitungsrecht.

Auf dem Server:  sudo fv-manage vorstand_anlegen …
Es wird kein Passwort erzeugt oder angezeigt. Der Link ist 7 Tage gültig und nur
einmal verwendbar.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from seiten.konto import einladungs_link
from seiten.models import Stufe


class Command(BaseCommand):
    help = "Vorstandskonto anlegen und Link zum Setzen des Passworts ausgeben."

    def add_arguments(self, parser):
        parser.add_argument("benutzername")
        parser.add_argument("email")
        parser.add_argument("--vorname", default="")
        parser.add_argument("--nachname", default="")
        parser.add_argument(
            "--admin", action="store_true",
            help="Zusätzlich volle Verwaltungsrechte (Benutzer und Stufen pflegen).",
        )
        parser.add_argument(
            "--stufe", default=None,
            help="Name der Stufe (Vorgabe: höchste Stufe mit Bearbeitungsrecht).",
        )

    def handle(self, benutzername, email, vorname, nachname, admin, stufe=None, **opts):
        if stufe:
            ziel = Stufe.objects.filter(name=stufe).first()
            if ziel is None:
                namen = ", ".join(Stufe.objects.values_list("name", flat=True)) or "–"
                raise CommandError(f"Stufe „{stufe}“ gibt es nicht. Vorhanden: {namen}")
        else:
            ziel = Stufe.objects.filter(darf_bearbeiten=True).order_by("-rang").first()
            if ziel is None:
                raise CommandError("Es gibt keine Stufe mit Bearbeitungsrecht. "
                                   "Bitte mit --stufe angeben oder zuerst eine anlegen.")
        try:
            validate_email(email)
        except Exception:
            raise CommandError(f"Ungültige E-Mail-Adresse: {email}")
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exclude(username=benutzername).exists():
            raise CommandError(f"Die E-Mail-Adresse {email} gehört bereits zu einem anderen Konto.")
        user, neu = User.objects.get_or_create(username=benutzername, defaults={"email": email})
        user.email = email
        if vorname:
            user.first_name = vorname
        if nachname:
            user.last_name = nachname
        user.is_active = True
        user.is_staff = True
        if admin:
            user.is_superuser = True
        if neu:
            user.set_unusable_password()
        user.save()
        user.groups.add(ziel.gruppe)

        self.stdout.write(f"{'Angelegt' if neu else 'Aktualisiert'}: {user.username} "
                          f"({ziel.name}{', Administrator' if user.is_superuser else ''})")
        self.stdout.write("Link zum Setzen des Passworts (7 Tage gültig, nur einmal verwendbar):")
        self.stdout.write(einladungs_link(user))

"""Legt ein Vorstandskonto an (oder ergänzt ein bestehendes) und gibt einen Link aus,
mit dem die Person ihr Passwort selbst setzt.

    python manage.py vorstand_anlegen vorname.nachname adresse@example.org [--admin]

Auf dem Server:  sudo fv-manage vorstand_anlegen …
Es wird kein Passwort erzeugt oder angezeigt. Der Link ist 7 Tage gültig und nur
einmal verwendbar.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def passwort_link(user) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return settings.FV_BASIS_URL + reverse("password_reset_confirm", args=[uid, token])


class Command(BaseCommand):
    help = "Vorstandskonto anlegen und Link zum Setzen des Passworts ausgeben."

    def add_arguments(self, parser):
        parser.add_argument("benutzername")
        parser.add_argument("email")
        parser.add_argument("--vorname", default="")
        parser.add_argument("--nachname", default="")
        parser.add_argument(
            "--admin", action="store_true",
            help="Zusätzlich volle Verwaltungsrechte (Benutzer und Gruppen pflegen).",
        )

    def handle(self, benutzername, email, vorname, nachname, admin, **opts):
        try:
            validate_email(email)
        except Exception:
            raise CommandError(f"Ungültige E-Mail-Adresse: {email}")
        User = get_user_model()
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
        user.groups.add(Group.objects.get(name="Vorstand"))

        self.stdout.write(f"{'Angelegt' if neu else 'Aktualisiert'}: {user.username} "
                          f"(Vorstand{', Administrator' if user.is_superuser else ''})")
        self.stdout.write("Link zum Setzen des Passworts (7 Tage gültig, nur einmal verwendbar):")
        self.stdout.write(passwort_link(user))

"""Passwörter: Argon2id im Format, das auch Dovecot (libsodium) prüfen kann.

Gespeichert wird wie bei Django üblich „argon2$argon2id$v=19$m=…,t=…,p=1$salz$hash“.
Ohne das Präfix „argon2“ ist das genau das Format, das Dovecot als {ARGON2ID}
erwartet. libsodium – und damit Dovecot – kann nur Parallelität 1; Djangos
Standard ist 8. Speicher und Durchläufe entsprechen den Vorgaben von Dovecot
(„doveadm pw -s ARGON2ID“: m=65536, t=3).
"""

from django.contrib.auth.hashers import Argon2PasswordHasher
from django.core.exceptions import ValidationError


class Argon2DovecotHasher(Argon2PasswordHasher):
    # Name bleibt "argon2": vorhandene Django-Argon2-Hashes werden erkannt und bei
    # der nächsten Anmeldung auf diese Parameter umgestellt.
    algorithm = "argon2"
    time_cost = 3
    memory_cost = 65536   # KiB = 64 MiB
    parallelism = 1


class PostfachMindestlaenge:
    """Konten mit Postfach brauchen ein längeres Passwort (Mail hat keine Zwei-Faktor-Anmeldung)."""

    def __init__(self, min_length=12):
        self.min_length = min_length

    def validate(self, password, user=None):
        profil = getattr(user, "profil", None) if user is not None and user.pk else None
        if profil and profil.vereins_email and len(password) < self.min_length:
            raise ValidationError(
                f"Für Konten mit Postfach muss das Passwort mindestens {self.min_length} Zeichen haben.",
                code="password_too_short_postfach",
            )

    def get_help_text(self):
        return f"Bei Konten mit Postfach mindestens {self.min_length} Zeichen."

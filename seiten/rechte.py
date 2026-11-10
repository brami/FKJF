"""Zentrale Rechteprüfung.

Jede Entscheidung, wer was sehen oder bearbeiten darf, wird hier getroffen.
Ansichten, Vorlagen und der Newsletter fragen ausschließlich diese Funktionen.

Regel (siehe webseite/anforderungen_django.md):
- Gruppen sind Stufen: Öffentlich (0) < Fördermitglieder (1) < Mitglieder (2) < Vorstand (3).
- Maßgeblich ist die höchste Stufe aller Gruppen eines Benutzers.
- Eine Seite ist sichtbar, wenn die Stufe des Benutzers >= Stufe der Seite ist.
- Nur der Vorstand bearbeitet Seiten und sieht den Versionsverlauf.
"""

from django.contrib.auth import get_user_model
from django.db.models import Q

from .stufen import GRUPPE_ZU_STUFE, Stufe


def stufe_von(user) -> int:
    """Höchste Stufe eines Benutzers. Nicht angemeldet oder deaktiviert: Öffentlich."""
    if user is None or not user.is_authenticated or not user.is_active:
        return Stufe.OEFFENTLICH
    if user.is_superuser:
        return Stufe.VORSTAND
    namen = user.groups.values_list("name", flat=True)
    return max((GRUPPE_ZU_STUFE.get(n, Stufe.OEFFENTLICH) for n in namen),
               default=Stufe.OEFFENTLICH)


def darf_lesen(user, seite) -> bool:
    return stufe_von(user) >= seite.stufe


def darf_bearbeiten(user) -> bool:
    return stufe_von(user) >= Stufe.VORSTAND


def sichtbare_seiten(user, queryset=None):
    from .models import Seite

    qs = Seite.objects.all() if queryset is None else queryset
    return qs.filter(stufe__lte=stufe_von(user))


def benutzer_mit_mindeststufe(stufe: int):
    """Alle aktiven Benutzer, deren höchste Stufe >= stufe ist."""
    User = get_user_model()
    aktive = User.objects.filter(is_active=True)
    if stufe <= Stufe.OEFFENTLICH:
        return aktive
    gruppen = [name for name, s in GRUPPE_ZU_STUFE.items() if s >= stufe]
    return aktive.filter(Q(is_superuser=True) | Q(groups__name__in=gruppen)).distinct()


def newsletter_empfaenger(seite):
    """Empfänger eines Newsletters: alle aktiven Benutzer, die die Seite sehen dürfen.

    Liefert (mit_email, ohne_email) als zwei Querysets.
    """
    alle = benutzer_mit_mindeststufe(seite.stufe)
    ohne = alle.filter(Q(email="") | Q(email__isnull=True))
    mit = alle.exclude(pk__in=ohne.values("pk"))
    return mit, ohne

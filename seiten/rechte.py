"""Zentrale Rechteprüfung.

Jede Entscheidung, wer was sehen oder bearbeiten darf, wird hier getroffen.
Ansichten, Vorlagen und der Newsletter fragen ausschließlich diese Funktionen.

Regel:
- Stufen sind frei benennbar und nach Rang geordnet (Modell Stufe); „Öffentlich“
  (Rang 0, Seiten ohne Stufe) ist fest die unterste.
- Maßgeblich ist der höchste Rang aller Stufen eines Benutzers.
- Eine Seite ist sichtbar, wenn dieser Rang >= Rang der Seite ist.
- Bearbeiten darf, wer einer Stufe mit „darf bearbeiten“ angehört (und Administratoren).
"""

from django.contrib.auth import get_user_model
from django.db.models import Max, Q

from .stufen import OEFFENTLICH_RANG

_ADMIN_RANG = 10**6   # Administratoren sehen alles


def stufe_von(user) -> int:
    """Höchster Rang eines Benutzers. Nicht angemeldet oder deaktiviert: Öffentlich (0)."""
    if user is None or not user.is_authenticated or not user.is_active:
        return OEFFENTLICH_RANG
    if user.is_superuser:
        return _ADMIN_RANG
    cache = getattr(user, "_fv_rang", None)
    if cache is None:
        cache = user.groups.aggregate(r=Max("stufe__rang"))["r"] or OEFFENTLICH_RANG
        user._fv_rang = cache
    return cache


def _rang(seite) -> int:
    return seite.stufe.rang if seite.stufe_id else OEFFENTLICH_RANG


def darf_lesen(user, seite) -> bool:
    return stufe_von(user) >= _rang(seite)


def darf_bearbeiten(user) -> bool:
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    cache = getattr(user, "_fv_bearbeiten", None)
    if cache is None:
        cache = user.groups.filter(stufe__darf_bearbeiten=True).exists()
        user._fv_bearbeiten = cache
    return cache


def sichtbare_seiten(user, queryset=None):
    from .models import Seite

    qs = Seite.objects.all() if queryset is None else queryset
    return qs.filter(Q(stufe__isnull=True) | Q(stufe__rang__lte=stufe_von(user)))


def benutzer_mit_mindestrang(rang: int):
    """Alle aktiven Benutzer, deren höchster Rang >= rang ist."""
    User = get_user_model()
    aktive = User.objects.filter(is_active=True)
    if rang <= OEFFENTLICH_RANG:
        return aktive
    return aktive.filter(Q(is_superuser=True) | Q(groups__stufe__rang__gte=rang)).distinct()


def newsletter_empfaenger(seite):
    """Empfänger eines Newsletters: alle aktiven Benutzer, die die Seite sehen dürfen.

    Liefert (mit_email, ohne_email) als zwei Querysets.
    """
    alle = benutzer_mit_mindestrang(_rang(seite))
    ohne = alle.filter(Q(email="") | Q(email__isnull=True))
    mit = alle.exclude(pk__in=ohne.values("pk"))
    return mit, ohne

"""Zentrale Rechteprüfung.

Jede Entscheidung, wer was sehen oder bearbeiten darf, wird hier getroffen.
Ansichten, Vorlagen und der Newsletter fragen ausschließlich diese Funktionen.

Regel:
- Stufen sind frei benennbar und nach Rang geordnet (Modell Stufe); „Öffentlich“
  (Rang 0, Seiten ohne Stufe) ist fest die unterste.
- Maßgeblich ist der höchste Rang aller Stufen eines Benutzers.
- Eine Seite ist sichtbar, wenn dieser Rang >= Rang der Seite ist.
- Bearbeiten darf, wer einer Stufe mit „darf bearbeiten“ angehört (und Administratoren).
- Kreise schränken zusätzlich ein: Hat eine Seite oder ein Anhang einen Kreis, sehen
  sie nur Personen in diesem Kreis – und wer bearbeiten darf. Ein Anhang setzt immer
  das Leserecht für seine Seite voraus.
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


def kreise_von(user) -> set:
    """Nummern der Kreise, in denen die Person ist (leer für nicht Angemeldete)."""
    if user is None or not user.is_authenticated or not user.is_active:
        return set()
    cache = getattr(user, "_fv_kreise", None)
    if cache is None:
        cache = set(user.kreise.values_list("pk", flat=True))
        user._fv_kreise = cache
    return cache


def im_kreis(user, kreis_id) -> bool:
    return kreis_id is None or darf_bearbeiten(user) or kreis_id in kreise_von(user)


def darf_lesen(user, seite) -> bool:
    return stufe_von(user) >= _rang(seite) and im_kreis(user, seite.kreis_id)


def darf_anhang(user, anhang) -> bool:
    return darf_lesen(user, anhang.seite) and im_kreis(user, anhang.kreis_id)


def anhaenge_zuordnen(user, seiten):
    """Trägt an jeder Seite die Anhänge ein, die die Person sehen darf
    (Seite.sichtbare_anhaenge, bilder, dateien, titelbild)."""
    for s in seiten:
        s._fv_anhaenge = [a for a in s.anhaenge.all() if im_kreis(user, a.kreis_id)]
    return seiten


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
    qs = qs.filter(Q(stufe__isnull=True) | Q(stufe__rang__lte=stufe_von(user)))
    if not darf_bearbeiten(user):
        qs = qs.filter(Q(kreis__isnull=True) | Q(kreis__in=kreise_von(user)))
    return qs


def benutzer_mit_mindestrang(rang: int):
    """Alle aktiven Benutzer, deren höchster Rang >= rang ist."""
    User = get_user_model()
    aktive = User.objects.filter(is_active=True)
    if rang <= OEFFENTLICH_RANG:
        return aktive
    return aktive.filter(Q(is_superuser=True) | Q(groups__stufe__rang__gte=rang)).distinct()


def leser(seite):
    """Alle aktiven Benutzer, die die Seite sehen dürfen (Stufe und Kreis)."""
    alle = benutzer_mit_mindestrang(_rang(seite))
    if seite.kreis_id:
        bearbeiter = Q(is_superuser=True) | Q(groups__stufe__darf_bearbeiten=True)
        alle = alle.filter(bearbeiter | Q(kreise=seite.kreis_id)).distinct()
    return alle


def newsletter_empfaenger(seite):
    """Empfänger eines Newsletters: alle aktiven Benutzer, die die Seite sehen dürfen.

    Liefert (mit_email, ohne_email) als zwei Querysets.
    """
    alle = leser(seite)
    ohne = alle.filter(Q(email="") | Q(email__isnull=True))
    mit = alle.exclude(pk__in=ohne.values("pk"))
    return mit, ohne

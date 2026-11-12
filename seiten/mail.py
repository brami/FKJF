"""Mail: Postfächer, Aliase, Verteiler und gesperrte Adressen – gepflegt in der Webseite.

Der Mailserver (Exim, Dovecot) liest den Stand über Datenbanksichten
(Migration 0012): ``dovecot_benutzer`` (Anmeldung, Postfach-Verzeichnis),
``exim_adressen`` (welche Adresse ist was), ``exim_verteiler`` (Empfänger der
Verteiler) und ``exim_absender`` (mit welchen Adressen eine Person senden darf).
Die Funktionen ``exim_*`` hier liefern dasselbe in Python; die Tests stellen auf
PostgreSQL sicher, dass beides übereinstimmt.

Plus-Adressen (name+zusatz@…) kommen im Postfach von name@… an. Der Mailserver meldet
sie (mail_plusadressen); die Person sieht sie im Konto und kann einzelne sperren
(Sicht ``exim_plus_gesperrt``). Verteiler können ein Archiv haben (Sichten
``mail_archive``, ``dovecot_archiv_leser``); lesen dürfen es die aktuellen
Empfänger mit Postfach.

Regeln (Konzept Mailserver, Abschnitte 3, 9 und 11):
- Jede Adresse gibt es nur einmal: Vereinsadressen, Aliase, Verteiler, gesperrte
  Adressen und externe Adressen der Konten.
- Ändert sich die Vereinsadresse, wird die alte zum Alias.
- Frei gewordene Adressen bleiben FV_MAIL_SPERRFRIST_TAGE gesperrt; dieselbe Person
  darf sie wieder erhalten.
- Ein Postfach ist gesperrt, solange das Konto deaktiviert ist oder keine
  Vereinsadresse hat. Nach FV_MAIL_LOESCHFRIST_TAGE wird es gelöscht (der Vorstand
  wird FV_MAIL_VORWARNUNG_TAGE vorher erinnert).
"""

import csv
import plistlib
import re
import uuid
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import konto as kontomodul
from .bearbeiten import nur_vorstand
from .models import (Abwesenheit, AdressSperre, Alias, Belegung, PlusAdresse, Profil, Verteiler,
                     Webseite, zustelladresse)


def normal(adresse) -> str:
    return (adresse or "").strip().lower()


def heute():
    return timezone.localdate()


# ------------------------------------------------------- Adressen prüfen

def adresse_pruefen(adresse, *, user=None, alias=None, verteiler=None, vereinsadresse=False):
    """Prüft, ob eine Vereinsadresse, ein Alias oder ein Verteiler diese Adresse erhalten darf.

    ``user``: Person, der die Adresse gehören soll (ihre eigenen Aliase und gesperrten
    früheren Adressen stehen ihr offen). ``alias``/``verteiler``: der Eintrag, der gerade
    bearbeitet wird. Wirft ValidationError mit verständlichem Text.
    """
    a = normal(adresse)
    if not a:
        return a
    validate_email(a)
    if "+" in a.split("@")[0]:
        raise ValidationError("Ein „+“ ist in Vereinsadressen nicht möglich "
                              "(name+stichwort@ ist für Plus-Adressen reserviert).")
    dom = settings.FV_MAIL_DOMAIN
    if dom and not a.endswith("@" + dom):
        raise ValidationError(f"Vereinsadressen enden auf @{dom}.")
    User = get_user_model()
    uid = user.pk if user is not None and user.pk else None

    profil = Profil.objects.select_related("user").filter(vereins_email__iexact=a).first()
    if profil and profil.user_id != uid:
        raise ValidationError(f"Die Adresse ist bereits Vereinsadresse von {profil.user}.")
    if profil and profil.user_id == uid and not vereinsadresse:
        raise ValidationError("Das ist bereits die Vereinsadresse dieser Person.")

    al = Alias.objects.select_related("user").filter(adresse__iexact=a)
    if alias is not None and alias.pk:
        al = al.exclude(pk=alias.pk)
    al = al.first()
    if al and not (vereinsadresse and al.user_id == uid):
        raise ValidationError(f"Die Adresse ist bereits Alias von {al.user}.")

    vt = Verteiler.objects.filter(adresse__iexact=a)
    if verteiler is not None and verteiler.pk:
        vt = vt.exclude(pk=verteiler.pk)
    if vt.exists():
        raise ValidationError("Die Adresse ist bereits ein Verteiler.")

    if User.objects.filter(email__iexact=a).exists():
        raise ValidationError("Die Adresse ist als externe Adresse eines Kontos eingetragen.")

    sp = AdressSperre.objects.filter(adresse__iexact=a, frei_ab__gt=heute()).first()
    if sp and not (uid and sp.user_id == uid):
        raise ValidationError(
            f"Die Adresse ist bis {sp.frei_ab:%d.%m.%Y} gesperrt (frei geworden"
            f"{' bei ' + str(sp.user) if sp.user_id else ''}). Eine frühere Adresse wird erst "
            "nach der Sperrfrist neu vergeben, damit niemand fremde Mails erhält.")
    return a


def extern_pruefen(adresse, user=None):
    """Externe Adresse eines Kontos: darf keine Vereinsadresse, kein Alias, kein Verteiler sein."""
    a = normal(adresse)
    if not a:
        return
    if Alias.objects.filter(adresse__iexact=a).exists() or \
            Verteiler.objects.filter(adresse__iexact=a).exists():
        raise ValidationError("Diese Adresse ist eine Vereinsadresse (Alias oder Verteiler) und "
                              "kann nicht als externe Adresse dienen.")


def sperren(adresse, user=None, grund=""):
    a = normal(adresse)
    if not a:
        return
    AdressSperre.objects.update_or_create(adresse=a, defaults={
        "frei_ab": heute() + timedelta(days=settings.FV_MAIL_SPERRFRIST_TAGE),
        "user": user, "grund": grund[:200],
    })


# ------------------------------------------------- Signale (apps.ready)

def _profil_vorher(sender, instance, **kwargs):
    alt = None
    if instance.pk:
        alt = Profil.objects.filter(pk=instance.pk).values_list("vereins_email", flat=True).first()
    instance._fv_alte_adresse = alt


def _profil_nachher(sender, instance, **kwargs):
    alt, neu = normal(getattr(instance, "_fv_alte_adresse", None)), normal(instance.vereins_email)
    user = instance.user
    if neu:
        # frühere eigene Adresse (Alias oder Sperre) wird wieder Hauptadresse
        for a in Alias.objects.filter(user=user, adresse__iexact=neu):
            a._fv_ohne_sperre = True
            a.delete()
        AdressSperre.objects.filter(adresse__iexact=neu, user=user).delete()
    if alt and alt != neu:
        if neu:
            Alias.objects.get_or_create(adresse=alt, defaults={"user": user,
                                                                "art": Alias.Art.AUTOMATISCH})
        else:
            sperren(alt, user, "Vereinsadresse entfernt")
    postfach_status(user)


def _adresse_vorher(sender, instance, **kwargs):
    instance._fv_alte_adresse = (sender.objects.filter(pk=instance.pk).values_list("adresse", flat=True)
                                 .first() if instance.pk else None)


def _alte_adresse_sperren(instance, user, grund):
    alt = normal(getattr(instance, "_fv_alte_adresse", None))
    if alt and alt != normal(instance.adresse):
        sperren(alt, user, grund)


def _alias_nachher(sender, instance, created, **kwargs):
    AdressSperre.objects.filter(adresse__iexact=instance.adresse, user=instance.user).delete()
    _alte_adresse_sperren(instance, instance.user, "Alias geändert")


def _verteiler_nachher(sender, instance, created, **kwargs):
    _alte_adresse_sperren(instance, None, "Verteiler umbenannt")


def _alias_geloescht(sender, instance, **kwargs):
    if not getattr(instance, "_fv_ohne_sperre", False):
        sperren(instance.adresse, instance.user, "Alias gelöscht")


def _verteiler_geloescht(sender, instance, **kwargs):
    sperren(instance.adresse, None, "Verteiler gelöscht")


def _user_nachher(sender, instance, **kwargs):
    postfach_status(instance)


def postfach_status(user):
    """Sperrdatum des Postfachs führen: gesperrt = Konto deaktiviert oder keine Vereinsadresse."""
    p = Profil.objects.filter(user_id=user.pk).first()
    if p is None or not p.hat_postfach:
        return
    aktiv = Profil.objects.filter(pk=p.pk).values_list("user__is_active", flat=True).first()
    gesperrt = not aktiv or not p.vereins_email
    if gesperrt and p.postfach_gesperrt_seit is None:
        Profil.objects.filter(pk=p.pk).update(postfach_gesperrt_seit=timezone.now(), vorwarnung_am=None)
    elif not gesperrt and p.postfach_gesperrt_seit is not None:
        Profil.objects.filter(pk=p.pk).update(postfach_gesperrt_seit=None, vorwarnung_am=None)


def signale_verbinden():
    from django.db.models.signals import post_delete, post_save, pre_save

    User = get_user_model()
    pre_save.connect(_profil_vorher, sender=Profil, dispatch_uid="fv_profil_vorher")
    post_save.connect(_profil_nachher, sender=Profil, dispatch_uid="fv_profil_nachher")
    pre_save.connect(_adresse_vorher, sender=Alias, dispatch_uid="fv_alias_vorher")
    post_save.connect(_alias_nachher, sender=Alias, dispatch_uid="fv_alias_nachher")
    pre_save.connect(_adresse_vorher, sender=Verteiler, dispatch_uid="fv_verteiler_vorher")
    post_save.connect(_verteiler_nachher, sender=Verteiler, dispatch_uid="fv_verteiler_nachher")
    post_delete.connect(_alias_geloescht, sender=Alias, dispatch_uid="fv_alias_geloescht")
    post_delete.connect(_verteiler_geloescht, sender=Verteiler, dispatch_uid="fv_verteiler_geloescht")
    post_save.connect(_user_nachher, sender=User, dispatch_uid="fv_user_nachher")

    from allauth.account.signals import password_changed, password_reset

    def _passwort_hinweis(request, user, **kwargs):
        p = getattr(user, "profil", None)
        if request is not None and p and p.vereins_email:
            messages.info(request, "Das neue Passwort gilt auch für Ihr Postfach. Bitte tragen Sie es "
                                   "jetzt in allen Mailprogrammen ein (Telefon, Rechner, Tablet) – "
                                   "sonst wird der Zugang nach mehreren Fehlversuchen kurz gesperrt.")

    password_changed.connect(_passwort_hinweis, dispatch_uid="fv_pw_hinweis")
    password_reset.connect(_passwort_hinweis, dispatch_uid="fv_pw_reset_hinweis")


# ------------------------------------------------ Was gilt für wen

def _mitglieder_q(v: Verteiler):
    return Q(pk__in=v.personen.values("pk")) | Q(groups__stufe__in=v.stufen.all())


def verteiler_personen(v: Verteiler):
    User = get_user_model()
    return (User.objects.filter(is_active=True).filter(_mitglieder_q(v)).distinct()
            .select_related("profil").order_by("last_name", "first_name", "username"))


def verteiler_empfaenger(v: Verteiler) -> list[str]:
    """Zustelladressen (Wahl jeder Person: extern oder Verein) und weitere Empfänger."""
    if not v.aktiv:
        return []
    adressen = {normal(zustelladresse(u)) for u in verteiler_personen(v)} | set(v.weitere())
    return sorted(a for a in adressen if a)


def verteiler_von(user):
    """Aktive Verteiler, denen die Person angehört (persönlich oder über die Stufe)."""
    return (Verteiler.objects.filter(aktiv=True)
            .filter(Q(personen=user) | Q(stufen__gruppe__user=user)).distinct().order_by("adresse"))


def erlaubte_absender(user) -> list[str]:
    p = getattr(user, "profil", None)
    if not user.is_active or not p or not p.vereins_email:
        return []
    adressen = {p.vereins_email}
    adressen |= {a.adresse for a in user.aliase.all()}
    adressen |= {v.adresse for v in verteiler_von(user)}
    return sorted(adressen)


def exim_adressen() -> set:
    """(adresse, art, ziel, offen) – wie die Sicht exim_adressen."""
    out = set()
    for p in Profil.objects.select_related("user").exclude(vereins_email__isnull=True):
        out.add((p.vereins_email, "postfach" if p.user.is_active else "gesperrt", p.vereins_email, True))
    for a in Alias.objects.select_related("user", "user__profil"):
        haupt = getattr(a.user, "profil", None)
        haupt = haupt.vereins_email if haupt else None
        art = "alias" if a.user.is_active and haupt else "gesperrt"
        out.add((a.adresse, art, haupt, True))
    for v in Verteiler.objects.filter(aktiv=True):
        out.add((v.adresse, "verteiler", None, v.offen))
    for s in AdressSperre.objects.filter(frei_ab__gt=heute()):
        out.add((s.adresse, "gesperrt", None, True))
    return out


def exim_verteiler() -> set:
    return {(v.adresse, e) for v in Verteiler.objects.filter(aktiv=True) for e in verteiler_empfaenger(v)}


def exim_plus_gesperrt() -> set:
    return {(a,) for a in PlusAdresse.objects.filter(gesperrt=True).values_list("adresse", flat=True)}


def archiv_leser(v: Verteiler) -> list[str]:
    """Vereinsadressen der aktuellen Empfänger mit Postfach (dürfen das Archiv lesen)."""
    if not v.archiv:
        return []
    return sorted({u.profil.vereins_email for u in verteiler_personen(v)
                   if getattr(u, "profil", None) and u.profil.vereins_email})


def mail_archive() -> set:
    return {(v.pk, v.adresse, v.archiv_tage, v.aktiv) for v in Verteiler.objects.filter(archiv=True)}


def archiv_leser_alle() -> set:
    return {(v.pk, v.adresse, b) for v in Verteiler.objects.filter(archiv=True) for b in archiv_leser(v)}


def archive_von(user):
    """Verteiler-Archive, die die Person lesen darf."""
    p = getattr(user, "profil", None)
    if not user.is_active or not p or not p.vereins_email:
        return []
    return [v for v in verteiler_von(user).filter(archiv=True)]


def exim_absender() -> set:
    User = get_user_model()
    out = set()
    for u in User.objects.filter(is_active=True, profil__vereins_email__isnull=False):
        for a in erlaubte_absender(u):
            out.add((u.profil.vereins_email, a))
    return out


# ------------------------------------------------- Abwesenheit (Sieve)

def _sieve_text(t: str) -> str:
    t = (t or "").replace("\r\n", "\n").replace("\\", "\\\\").replace('"', '\\"')
    return '"' + t + '"'


def sieve_skript(user) -> str:
    """Sieve-Regel mit der Abwesenheitsnotiz (leer, wenn ausgeschaltet).

    Der Mailserver antwortet höchstens einmal je Absender und Woche und nicht auf
    Verteiler-, Newsletter- oder automatische Mails (Regeln der Sieve-Erweiterung
    „vacation“).
    """
    kopf = "# Abwesenheitsnotiz – erzeugt von der Webseite, bitte nicht von Hand ändern\n"
    abw = Abwesenheit.objects.filter(user=user).first()
    if abw is None or not abw.aktiv:
        return kopf
    adressen = ", ".join(_sieve_text(a) for a in erlaubte_absender(user))
    aktion = (f"vacation :days 7 :subject {_sieve_text(abw.betreff)}"
              f"{' :addresses [' + adressen + ']' if adressen else ''}\n    {_sieve_text(abw.text)};\n")
    bedingungen = []
    if abw.von:
        bedingungen.append(f'currentdate :value "ge" "date" "{abw.von.isoformat()}"')
    if abw.bis:
        bedingungen.append(f'currentdate :value "le" "date" "{abw.bis.isoformat()}"')
    if not bedingungen:
        return kopf + 'require ["vacation"];\n' + aktion
    return (kopf + 'require ["vacation", "date", "relational"];\n'
            f"if allof ({', '.join(bedingungen)}) {{\n    {aktion}}}\n")


# ------------------------------------------------------ Plus-Adressen

def plus_teile(adresse):
    """„kai.maier+shop@d“ → („kai.maier@d“, „shop“); ohne Plus: (adresse, "")."""
    a = normal(adresse)
    if "@" not in a:
        return a, ""
    lokal, domain = a.rsplit("@", 1)
    if "+" not in lokal:
        return a, ""
    basis, zusatz = lokal.split("+", 1)
    return f"{basis}@{domain}", zusatz


def plus_besitzer(adresse):
    """Person, in deren Postfach die Plus-Adresse ankommt (Vereinsadresse oder Alias)."""
    basis, zusatz = plus_teile(adresse)
    if not zusatz:
        return None
    p = Profil.objects.select_related("user").filter(vereins_email__iexact=basis).first()
    if p:
        return p.user
    a = Alias.objects.select_related("user").filter(adresse__iexact=basis).first()
    return a.user if a else None


def plusadressen_einlesen(text: str, jetzt=None) -> int:
    """Vom Mailserver gemeldete Plus-Adressen übernehmen (eine Adresse je Zeile und Mail;
    davor darf ein Zeitstempel stehen, er wird ignoriert)."""
    jetzt = jetzt or timezone.now()
    zaehler = {}
    for zeile in text.splitlines():
        teile = zeile.split()
        if not teile:
            continue
        adresse = normal(teile[-1].strip("<>"))
        if plus_teile(adresse)[1]:
            zaehler[adresse] = zaehler.get(adresse, 0) + 1
    n = 0
    for adresse, anzahl in zaehler.items():
        user = plus_besitzer(adresse)
        if user is None:
            continue
        obj, neu = PlusAdresse.objects.get_or_create(
            adresse=adresse, defaults={"user": user, "erste": jetzt, "letzte": jetzt, "anzahl": anzahl})
        if not neu:
            PlusAdresse.objects.filter(pk=obj.pk).update(user=user, letzte=jetzt,
                                                         anzahl=obj.anzahl + anzahl)
        n += 1
    return n


@login_required
@require_POST
def plus_sperren(request, pk):
    pa = get_object_or_404(PlusAdresse, pk=pk, user=request.user)
    sperren_ = request.POST.get("aktion") == "sperren"
    PlusAdresse.objects.filter(pk=pa.pk).update(gesperrt=sperren_,
                                                gesperrt_am=timezone.now() if sperren_ else None)
    messages.success(request, f"{pa.adresse} ist {'gesperrt – Mails daran werden abgelehnt' if sperren_ else 'wieder freigegeben'}.")
    return redirect(reverse_lazy("konto") + "#plus")


# ------------------------------------------------------ Belegung

_ZEILE = re.compile(r"Username=(?P<u>\S+)\s.*?Type=(?P<t>STORAGE|MESSAGE)\s+Value=(?P<v>\d+)"
                    r"\s+Limit=(?P<l>\S+)")


def belegung_einlesen(text: str, jetzt=None) -> int:
    """Ausgabe von „doveadm -f flow quota get -A“ übernehmen (STORAGE in KiB)."""
    jetzt = jetzt or timezone.now()
    werte = {}
    for zeile in text.splitlines():
        m = _ZEILE.search(zeile)
        if not m:
            continue
        w = werte.setdefault(normal(m["u"]), {})
        if m["t"] == "STORAGE":
            w["bytes"] = int(m["v"]) * 1024
            w["grenze_bytes"] = int(m["l"]) * 1024 if m["l"].isdigit() else None
        else:
            w["nachrichten"] = int(m["v"])
    n = 0
    for adresse, w in werte.items():
        p = Profil.objects.filter(vereins_email__iexact=adresse).first()
        if p is None:
            continue
        Belegung.objects.update_or_create(user_id=p.user_id, defaults={**w, "stand": jetzt})
        n += 1
    return n


def gb(b) -> str:
    return f"{(b or 0) / 1024**3:.1f}".replace(".", ",")


# ------------------------------------------- Löschen gesperrter Postfächer

def loeschdatum(profil):
    if not profil.postfach_gesperrt_seit:
        return None
    return profil.postfach_gesperrt_seit + timedelta(days=settings.FV_MAIL_LOESCHFRIST_TAGE)


def gesperrte_postfaecher():
    return (Profil.objects.select_related("user")
            .filter(hat_postfach=True, postfach_gesperrt_seit__isnull=False)
            .order_by("postfach_gesperrt_seit"))


def faellige_postfaecher(jetzt=None):
    jetzt = jetzt or timezone.now()
    grenze = jetzt - timedelta(days=settings.FV_MAIL_LOESCHFRIST_TAGE)
    return gesperrte_postfaecher().filter(postfach_gesperrt_seit__lte=grenze)


def vorstand_adressen() -> list[str]:
    web = Webseite.aktuell()
    if web.antwort_an:
        return [web.antwort_an]
    User = get_user_model()
    leute = User.objects.filter(is_active=True, groups__stufe__darf_bearbeiten=True).distinct()
    return sorted({zustelladresse(u) for u in leute if zustelladresse(u)})


def _an_vorstand(betreff_text, vorlage, ctx):
    an = vorstand_adressen()
    if not an:
        return False
    ctx = {**ctx, "webseite": Webseite.aktuell(), "basis": settings.FV_BASIS_URL}
    send_mail(kontomodul.betreff(betreff_text), render_to_string(vorlage, ctx),
              kontomodul.absender(), an)
    return True


def vorwarnen(jetzt=None) -> list:
    """Erinnerung an den Vorstand für Postfächer, die bald gelöscht werden."""
    jetzt = jetzt or timezone.now()
    grenze = jetzt - timedelta(days=settings.FV_MAIL_LOESCHFRIST_TAGE - settings.FV_MAIL_VORWARNUNG_TAGE)
    profile = list(gesperrte_postfaecher().filter(postfach_gesperrt_seit__lte=grenze,
                                                  vorwarnung_am__isnull=True))
    if profile and _an_vorstand("Postfächer werden bald gelöscht", "mail/vorwarnung.txt", {
            "postfaecher": [(p, loeschdatum(p)) for p in profile]}):
        Profil.objects.filter(pk__in=[p.pk for p in profile]).update(vorwarnung_am=jetzt)
    return profile


@transaction.atomic
def postfach_geloescht(user):
    """Vom Server gemeldet: Das Postfach-Verzeichnis ist gelöscht. Adressen sperren."""
    p = Profil.objects.get(user=user)
    adressen = [a for a in [p.vereins_email] if a] + [a.adresse for a in user.aliase.all()]
    for a in user.aliase.all():
        a.delete()          # sperrt die Adresse
    if p.vereins_email:
        p.vereins_email = None
        p.save()            # sperrt die Adresse
    Profil.objects.filter(pk=p.pk).update(hat_postfach=False, postfach_gesperrt_seit=None,
                                          vorwarnung_am=None)
    Belegung.objects.filter(user=user).delete()
    Abwesenheit.objects.filter(user=user).delete()
    PlusAdresse.objects.filter(user=user).delete()
    return adressen


# --------------------------------------------- Apple-Einrichtungsprofil

def mobileconfig(user) -> bytes:
    p = user.profil
    server = settings.FV_MAIL_SERVER
    web = Webseite.aktuell()
    ns = uuid.uuid5(uuid.NAMESPACE_DNS, server or "mail.invalid")
    konto_uuid = str(uuid.uuid5(ns, f"konto-{user.pk}")).upper()
    profil_uuid = str(uuid.uuid5(ns, f"profil-{user.pk}")).upper()
    kennung = ".".join(reversed((server or "mail.invalid").split(".")))
    name = user.get_full_name() or user.username
    konto = {
        "PayloadType": "com.apple.mail.managed",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"{kennung}.mail.{user.pk}",
        "PayloadUUID": konto_uuid,
        "PayloadDisplayName": f"Postfach {p.vereins_email}",
        "EmailAccountDescription": web.name,
        "EmailAccountName": name,
        "EmailAccountType": "EmailTypeIMAP",
        "EmailAddress": p.vereins_email,
        "IncomingMailServerHostName": server,
        "IncomingMailServerPortNumber": settings.FV_MAIL_IMAP_PORT,
        "IncomingMailServerUseSSL": True,
        "IncomingMailServerUsername": p.vereins_email,
        "IncomingMailServerAuthentication": "EmailAuthPassword",
        "OutgoingMailServerHostName": server,
        "OutgoingMailServerPortNumber": settings.FV_MAIL_SMTP_PORT,
        "OutgoingMailServerUseSSL": True,
        "OutgoingMailServerUsername": p.vereins_email,
        "OutgoingMailServerAuthentication": "EmailAuthPassword",
        "OutgoingPasswordSameAsIncomingPassword": True,
        "PreventMove": False,
        "SMIMEEnabled": False,
    }
    gesamt = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"{kennung}.profil.{user.pk}",
        "PayloadUUID": profil_uuid,
        "PayloadDisplayName": f"{web.name}: Postfach",
        "PayloadDescription": "Richtet das Vereinspostfach in Apple Mail ein. Das Passwort "
                              "(dasselbe wie für die Webseite) wird bei der Installation abgefragt.",
        "PayloadOrganization": web.fuss,
        "PayloadRemovalDisallowed": False,
        "PayloadContent": [konto],
    }
    return plistlib.dumps(gesamt, fmt=plistlib.FMT_XML)


# ---------------------------------------------------------------- Konto

def mail_kontext(user) -> dict:
    """Bereich „Mail“ auf der Kontoseite (nur für Konten mit Vereinsadresse)."""
    p = getattr(user, "profil", None)
    if not p or not p.vereins_email:
        return {}
    belegung = Belegung.objects.filter(user=user).first()
    grenze = (belegung.grenze_bytes if belegung and belegung.grenze_bytes
              else int(settings.FV_MAIL_QUOTA_GB * 1024**3))
    prozent = round(100 * belegung.bytes / grenze) if belegung and grenze else None
    return {
        "mail": {
            "adresse": p.vereins_email,
            "aliase": list(user.aliase.all()),
            "verteiler": list(verteiler_von(user)),
            "belegung": belegung,
            "belegt_gb": gb(belegung.bytes) if belegung else None,
            "grenze_gb": gb(grenze),
            "prozent": min(prozent, 100) if prozent is not None else None,
            "voll": prozent is not None and prozent >= 90,
            "abwesenheit": Abwesenheit.objects.filter(user=user).first(),
            "plusadressen": list(user.plusadressen.order_by("gesperrt", "-letzte")),
            "plus_beispiel": p.vereins_email.replace("@", "+stichwort@", 1),
            "archive": archive_von(user),
            "server": settings.FV_MAIL_SERVER,
            "imap_port": settings.FV_MAIL_IMAP_PORT,
            "smtp_port": settings.FV_MAIL_SMTP_PORT,
            "anleitung": settings.FV_MAIL_ANLEITUNG_URL,
            "nutzungsordnung": Webseite.aktuell().nutzungsordnung,
        }
    }


class AbwesenheitForm(forms.ModelForm):
    class Meta:
        model = Abwesenheit
        fields = ["aktiv", "von", "bis", "betreff", "text"]
        widgets = {
            "von": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "bis": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "text": forms.Textarea(attrs={"rows": 6}),
        }
        help_texts = {
            "von": "Leer = ab sofort.",
            "bis": "Leer = bis zum Ausschalten. Letzter Tag der Abwesenheit.",
            "text": "Antwort an Absender, höchstens einmal je Absender und Woche. Nicht an "
                    "Newsletter, Verteiler oder automatische Mails.",
        }

    def clean(self):
        d = super().clean()
        if d.get("von") and d.get("bis") and d["bis"] < d["von"]:
            self.add_error("bis", "Das Ende liegt vor dem Beginn.")
        if d.get("aktiv") and not (d.get("text") or "").strip():
            self.add_error("text", "Bitte einen Text für die Antwort eingeben.")
        return d


def _nur_mit_postfach(request):
    p = getattr(request.user, "profil", None)
    if not p or not p.vereins_email:
        raise Http404
    return p


@login_required
def abwesenheit(request):
    _nur_mit_postfach(request)
    obj = Abwesenheit.objects.filter(user=request.user).first() or Abwesenheit(
        user=request.user, text=f"Vielen Dank für Ihre Nachricht. Ich bin bis … nicht erreichbar.\n\n"
                                f"In dringenden Fällen wenden Sie sich bitte an "
                                f"{Webseite.aktuell().ansprechpartner}.")
    form = AbwesenheitForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Die Abwesenheitsnotiz ist gespeichert. Der Mailserver übernimmt "
                                  "sie innerhalb weniger Minuten.")
        return redirect("konto")
    return render(request, "mail/abwesenheit.html", {"form": form})


@login_required
def einrichtungsprofil(request):
    _nur_mit_postfach(request)
    if not settings.FV_MAIL_SERVER:
        raise Http404
    antwort = HttpResponse(mobileconfig(request.user), content_type="application/x-apple-aspen-config")
    antwort["Content-Disposition"] = 'attachment; filename="postfach.mobileconfig"'
    return antwort


# ------------------------------------------------- Übersicht Vorstand

def _person(u):
    return (u.get_full_name() or u.username) if u else ""


def adressliste():
    """Alle Adressen für die Übersicht: (adresse, art, person/empfänger, hinweis)."""
    zeilen = []
    for p in Profil.objects.select_related("user").exclude(vereins_email__isnull=True):
        zeilen.append((p.vereins_email, "Postfach", _person(p.user),
                       "" if p.user.is_active else "Konto deaktiviert"))
    for a in Alias.objects.select_related("user"):
        zeilen.append((a.adresse, "Alias", _person(a.user),
                       a.get_art_display() + ("" if a.user.is_active else ", Konto deaktiviert")))
    for v in Verteiler.objects.all():
        zeilen.append((v.adresse, "Verteiler", v.beschreibung, "" if v.aktiv else "ausgeschaltet"))
    for s in AdressSperre.objects.select_related("user").filter(frei_ab__gt=heute()):
        zeilen.append((s.adresse, "gesperrt", _person(s.user), f"frei ab {s.frei_ab:%d.%m.%Y}"))
    return sorted(zeilen)


def _teile():
    adressen = adressliste()
    verteiler = [(v, verteiler_personen(v), v.weitere(), verteiler_empfaenger(v))
                 for v in Verteiler.objects.prefetch_related("stufen")]
    User = get_user_model()
    postfaecher = (User.objects.filter(profil__vereins_email__isnull=False)
                   .select_related("profil", "belegung").order_by("profil__vereins_email"))
    grenze_std = int(settings.FV_MAIL_QUOTA_GB * 1024**3)
    belegung = []
    for u in postfaecher:
        b = getattr(u, "belegung", None)
        grenze = (b.grenze_bytes if b and b.grenze_bytes else grenze_std)
        prozent = round(100 * b.bytes / grenze) if b and grenze else None
        belegung.append({"user": u, "adresse": u.profil.vereins_email, "b": b,
                         "belegt": gb(b.bytes) if b else "–", "grenze": gb(grenze),
                         "prozent": prozent, "voll": prozent is not None and prozent >= 90})
    t = heute()
    abwesend = [a for a in Abwesenheit.objects.select_related("user", "user__profil").filter(aktiv=True)
                if a.bis is None or a.bis >= t]
    gesperrt = [(p, loeschdatum(p)) for p in gesperrte_postfaecher()]
    return {"adressen": adressen, "verteiler": verteiler, "belegung": belegung,
            "abwesend": abwesend, "gesperrt": gesperrt, "heute": t}


def _csv(name, kopf, zeilen):
    antwort = HttpResponse(content_type="text/csv; charset=utf-8")
    antwort["Content-Disposition"] = f'attachment; filename="mail-{name}.csv"'
    antwort.write("﻿")   # für Excel
    w = csv.writer(antwort, delimiter=";")
    w.writerow(kopf)
    w.writerows(zeilen)
    return antwort


@nur_vorstand
def uebersicht(request):
    d = _teile()
    teil = request.GET.get("csv")
    if teil == "adressen":
        return _csv(teil, ["Adresse", "Art", "Person / Beschreibung", "Hinweis"], d["adressen"])
    if teil == "verteiler":
        return _csv(teil, ["Verteiler", "Empfänger"],
                    [(v.adresse, e) for v, _, _, alle in d["verteiler"] for e in alle])
    if teil == "belegung":
        return _csv(teil, ["Adresse", "Person", "Belegt (GB)", "Grenze (GB)", "Prozent", "Mails", "Stand"],
                    [(z["adresse"], _person(z["user"]), z["belegt"], z["grenze"],
                      z["prozent"] if z["prozent"] is not None else "",
                      z["b"].nachrichten if z["b"] else "",
                      timezone.localtime(z["b"].stand).strftime("%d.%m.%Y %H:%M") if z["b"] else "")
                     for z in d["belegung"]])
    if teil == "abwesend":
        return _csv(teil, ["Person", "Adresse", "Von", "Bis"],
                    [(_person(a.user), a.user.profil.vereins_email if hasattr(a.user, "profil") else "",
                      a.von.strftime("%d.%m.%Y") if a.von else "", a.bis.strftime("%d.%m.%Y") if a.bis else "")
                     for a in d["abwesend"]])
    if teil == "gesperrt":
        return _csv(teil, ["Person", "Gesperrt seit", "Löschung am"],
                    [(_person(p.user), timezone.localtime(p.postfach_gesperrt_seit).strftime("%d.%m.%Y"),
                      timezone.localtime(ld).strftime("%d.%m.%Y")) for p, ld in d["gesperrt"]])
    return render(request, "mail/uebersicht.html", d)

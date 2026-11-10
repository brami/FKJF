"""Benutzerkonten: Einladung, Anmelde-Einstellungen, Pflicht zur Zwei-Faktor-Anmeldung."""

import time

from allauth.account import app_settings as account_settings
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.internal.flows.login import get_authentication_records
from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from allauth.mfa.utils import is_mfa_enabled
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from . import rechte


class KontoAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """Keine Selbstregistrierung: Konten legt der Vorstand an."""
        return False

    def is_reauthentication_required(self, *, app: str, **kwargs) -> bool:
        """Zwei-Faktor einrichten direkt nach der Anmeldung ohne erneute Passwortabfrage.

        allauth fragt sonst vor jeder Änderung an der Zwei-Faktor-Anmeldung das
        Passwort erneut ab – auch unmittelbar nach dem Anmelden, wohin die Pflicht
        den Vorstand gerade geleitet hat. Eine Anmeldung, die kürzer als die
        Frist für die erneute Eingabe (5 Minuten) zurückliegt, genügt deshalb.
        """
        if app == "allauth.mfa" and self._kuerzlich_angemeldet():
            return False
        return super().is_reauthentication_required(app=app, **kwargs)

    def _kuerzlich_angemeldet(self) -> bool:
        request = getattr(self, "request", None)
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        records = get_authentication_records(request, user)
        if not records:
            return False
        return time.time() - records[-1]["at"] < account_settings.REAUTHENTICATION_TIMEOUT


# --------------------------------------------------------------- Einladung

def einladungs_link(user) -> str:
    """Link, mit dem die Person ihr Passwort selbst setzt.

    Es ist der Link aus „Passwort vergessen“: gültig für PASSWORD_RESET_TIMEOUT
    (7 Tage), nur einmal verwendbar und ungültig, sobald sich Passwort oder
    E-Mail-Adresse ändern.
    """
    pfad = reverse("account_reset_password_from_key", kwargs={
        "uidb36": user_pk_to_url_str(user),
        "key": default_token_generator.make_token(user),
    })
    return settings.FV_BASIS_URL + pfad


def sende_einladung(user) -> str:
    """Schickt die Einladung per E-Mail und gibt den Link zurück."""
    link = einladungs_link(user)
    tage = settings.PASSWORD_RESET_TIMEOUT // 86400
    ctx = {"user": user, "link": link, "tage": tage, "basis": settings.FV_BASIS_URL}
    send_mail(
        subject=settings.ACCOUNT_EMAIL_SUBJECT_PREFIX + "Einladung zur Webseite",
        message=render_to_string("konto/einladung.txt", ctx),
        from_email=None,
        recipient_list=[user.email],
    )
    return link


def mails_werden_verschickt() -> bool:
    return settings.FV_MAIL == "smtp"


# --------------------------------------------------- Zwei-Faktor-Pflicht

class ZweiFaktorPflichtMiddleware:
    """Vorstand und Administratoren müssen die Zwei-Faktor-Anmeldung einrichten.

    Bis dahin führt jede Seite zur Einrichtung. Erreichbar bleiben nur die
    Konto-Seiten (Einrichtung, Abmelden, Passwort) und statische Dateien.
    """

    FREI = ("/konto/", "/static/", "/gesund/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (settings.FV_ZWEI_FAKTOR_PFLICHT
                and user is not None and user.is_authenticated
                and rechte.darf_bearbeiten(user)
                and not request.path.startswith(self.FREI)
                and not is_mfa_enabled(user, ["totp"])):
            return redirect("mfa_activate_totp")
        return self.get_response(request)


# ------------------------------------------------------------ Kontoseite

@login_required
def konto(request):
    return render(request, "konto/uebersicht.html", {
        "zwei_faktor": is_mfa_enabled(request.user, ["totp"]),
        "pflicht": settings.FV_ZWEI_FAKTOR_PFLICHT and rechte.darf_bearbeiten(request.user),
        "stufe": rechte.stufe_von(request.user),
    })


def kontext(request):
    """Kontextprozessor: Darf die angemeldete Person bearbeiten (Vorstand)?"""
    return {"fv_darf_bearbeiten": rechte.darf_bearbeiten(getattr(request, "user", None))}

"""Benutzerkonten: Einladung, Anmelde-Einstellungen, Pflicht zur Zwei-Faktor-Anmeldung."""

import time

from allauth.account import app_settings as account_settings
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.forms import ResetPasswordForm
from allauth.account.internal.flows.login import get_authentication_records
from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.mfa.utils import is_mfa_enabled
from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from email.utils import parseaddr
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from . import rechte


def webseite():
    from .models import Webseite
    return Webseite.aktuell()


def betreff(text: str) -> str:
    return f"[{webseite().name}] {text}"


def mit_name(name: str, adresse: str) -> str:
    """„Name <adresse>“ – Umlaute bleiben lesbar, Django kodiert beim Versand."""
    name = " ".join(name.replace('"', "").split())
    if not name:
        return adresse
    if any(z in name for z in '()<>@,;:\\.[]'):   # Sonderzeichen: Namen in Anführungszeichen
        name = f'"{name}"'
    return f"{name} <{adresse}>"


def absender_adresse() -> str:
    """Nur die Adresse aus FV_MAIL_ABSENDER."""
    return parseaddr(settings.DEFAULT_FROM_EMAIL)[1]


def absender() -> str:
    """Absender der E-Mails. Ohne Namen in FV_MAIL_ABSENDER wird der Name der Webseite ergänzt."""
    name, adresse = parseaddr(settings.DEFAULT_FROM_EMAIL)
    return settings.DEFAULT_FROM_EMAIL if name else mit_name(webseite().name, adresse)


class KontoAdapter(DefaultAccountAdapter):
    def format_email_subject(self, subject):
        return betreff(str(subject))

    def get_from_email(self):
        return absender()

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


class MfaAdapter(DefaultMFAAdapter):
    def get_totp_issuer(self):
        return webseite().name


# ------------------------------------------------- Vereinsadresse (Postfach)

class VereinsadresseBackend(ModelBackend):
    """Anmelden mit der Vereinsadresse (zusätzlich zu Benutzername und externer Adresse)."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        from .models import Profil

        if not email or password is None:
            return None
        profil = (Profil.objects.select_related("user")
                  .filter(vereins_email__iexact=email.strip()).first())
        if profil is None:
            return None
        user = profil.user
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


class PasswortVergessenForm(ResetPasswordForm):
    """„Passwort vergessen“ auch mit der Vereinsadresse – der Link geht aber immer an
    die externe Adresse: Das Postfach hat dasselbe Passwort und wäre ohne es nicht
    erreichbar."""

    def clean_email(self):
        from .models import Profil

        eingabe = (self.cleaned_data.get("email") or "").strip()
        profil = (Profil.objects.select_related("user")
                  .filter(vereins_email__iexact=eingabe, user__is_active=True).first())
        if profil and profil.user.email:
            self.cleaned_data["email"] = profil.user.email
        return super().clean_email()


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
    ctx = {"user": user, "link": link, "tage": tage, "basis": settings.FV_BASIS_URL,
           "webseite": webseite()}
    send_mail(
        subject=betreff("Einladung zur Webseite"),
        message=render_to_string("konto/einladung.txt", ctx),
        from_email=absender(),
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
            # Hinweis, warum man hier landet (wird auf der Einrichtungsseite angezeigt)
            messages.info(request, "Wer Seiten bearbeiten darf, muss die Zwei-Faktor-Anmeldung "
                                   "verwenden. Bitte richten Sie sie jetzt ein; danach können "
                                   "Sie die Webseite wie gewohnt nutzen.")
            return redirect("mfa_activate_totp")
        return self.get_response(request)


# ------------------------------------------------------------ Kontoseite

class ZustellungForm(forms.Form):
    zustellung = forms.ChoiceField(label="Vereinsmails (z. B. Newsletter)", widget=forms.RadioSelect)

    def __init__(self, *args, profil, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Profil
        self.fields["zustellung"].choices = [
            (Profil.Zustellung.EXTERN, f"an meine externe Adresse ({profil.user.email})"),
            (Profil.Zustellung.VEREIN, f"an meine Vereinsadresse ({profil.vereins_email})"),
        ]
        self.fields["zustellung"].initial = profil.zustellung


@login_required
def konto(request):
    from .models import profil_von

    profil = profil_von(request.user)
    form = None
    if profil.vereins_email:
        form = ZustellungForm(request.POST or None, profil=profil)
        if request.method == "POST" and form.is_valid():
            profil.zustellung = form.cleaned_data["zustellung"]
            profil.save()
            messages.success(request, "Ihre Einstellung wurde gespeichert.")
            return redirect("konto")
    from .mail import mail_kontext

    return render(request, "konto/uebersicht.html", {
        "zwei_faktor": is_mfa_enabled(request.user, ["totp"]),
        "pflicht": settings.FV_ZWEI_FAKTOR_PFLICHT and rechte.darf_bearbeiten(request.user),
        "profil": profil,
        "zustellung_form": form,
        **mail_kontext(request.user),
    })


def kontext(request):
    """Kontextprozessor: Einstellungen der Webseite; darf die angemeldete Person bearbeiten?"""
    return {
        "fv_darf_bearbeiten": rechte.darf_bearbeiten(getattr(request, "user", None)),
        "fv_webseite": webseite(),
    }

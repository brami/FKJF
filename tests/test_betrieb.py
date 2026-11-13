"""Tests für Funktionen, die Installation und Betrieb brauchen."""

import re
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.urls import reverse

from seiten import rechte

pytestmark = pytest.mark.django_db


def test_gesund(client):
    r = client.get(reverse("gesund"))
    assert r.status_code == 200 and r.content == b"ok"


# ------------------------------------------------------------ /health, /health/live

def test_health_live(client):
    for pfad in ("/health/live", "/health/live/"):
        r = client.get(pfad)
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert r["Cache-Control"] == "no-store"


@pytest.fixture
def newsletter_dienst_laeuft():
    from seiten import newsletter
    newsletter.herzschlag()
    yield
    from django.core.cache import cache
    cache.delete(newsletter.HERZSCHLAG)


def test_health_ok_ohne_statusdatei(client, settings, newsletter_dienst_laeuft):
    settings.FV_STATUS_DATEI = ""
    for pfad in ("/health", "/health/"):
        r = client.get(pfad)
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert r["Cache-Control"] == "no-store"


def test_health_newsletter_dienst_fehlt(client, settings):
    settings.FV_STATUS_DATEI = ""
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "warning", "probleme": ["Newsletter-Versand meldet sich nicht"]}


def test_health_mit_statusdatei(client, settings, tmp_path, newsletter_dienst_laeuft):
    import json
    import time
    datei = tmp_path / "status.json"
    settings.FV_STATUS_DATEI = str(datei)
    # fehlt: Prüfung läuft nicht
    r = client.get("/health")
    assert r.status_code == 503 and "fv-web-status" in r.json()["probleme"][0]
    # aktuell, nur Hinweis: ok
    datei.write_text(json.dumps({"zeit": time.time(), "probleme": [], "hinweise": ["Neustart nötig"]}))
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "hinweise": ["Neustart nötig"]}
    # Probleme vom Server werden übernommen (auch mit Umlauten)
    datei.write_text(json.dumps({"zeit": time.time(), "probleme": ["Dienst Mailserver (Exim) läuft nicht"],
                                 "hinweise": []}), encoding="utf-8")
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["probleme"] == ["Dienst Mailserver (Exim) läuft nicht"]
    assert "läuft".encode() in r.content          # nicht als \u00e4 kodiert
    # veraltet
    datei.write_text(json.dumps({"zeit": time.time() - 3600, "probleme": [], "hinweise": []}))
    r = client.get("/health")
    assert r.status_code == 503 and "fv-web-status" in r.json()["probleme"][0]


def test_health_ohne_anmeldung_auch_bei_zwei_faktor_pflicht(client, settings, newsletter_dienst_laeuft):
    """Angemeldeter Vorstand ohne Zwei-Faktor wird nicht zur Einrichtung umgeleitet."""
    from seiten.models import Stufe
    settings.FV_STATUS_DATEI = ""
    u = User.objects.create_user("v", "v@example.org", "geheim-geheim-123")
    u.groups.add(Stufe.objects.filter(darf_bearbeiten=True).first().gruppe)
    client.force_login(u)
    assert client.get("/health").status_code == 200
    assert client.get("/health/live").status_code == 200


def test_vorstand_anlegen_und_passwort_setzen(client):
    out = StringIO()
    call_command("vorstand_anlegen", "vera.vorstand", "vera@example.org",
                 "--vorname", "Vera", "--admin", stdout=out)
    u = User.objects.get(username="vera.vorstand")
    assert rechte.darf_bearbeiten(u) and u.is_staff and u.is_superuser
    assert not u.has_usable_password()

    pfad = re.search(r"https?://[^/]+(/konto/password/reset/key/\S+)", out.getvalue()).group(1)
    r = client.get(pfad)  # allauth leitet auf eine Adresse ohne Schlüssel im Pfad weiter
    assert r.status_code == 302
    form_url = r["Location"]
    r = client.post(form_url, {"password1": "Sehr-sicheres-Pw-2026",
                               "password2": "Sehr-sicheres-Pw-2026"})
    assert r.status_code == 302
    assert client.login(username="vera.vorstand", password="Sehr-sicheres-Pw-2026")

    # Link ist danach verbraucht
    client.logout()
    assert "ungültig" in client.get(pfad, follow=True).content.decode().lower()


def test_vorstand_anlegen_bestehendes_konto_behaelt_passwort():
    u = User.objects.create_user("max", "alt@example.org", "altes-passwort-123")
    call_command("vorstand_anlegen", "max", "neu@example.org", stdout=StringIO())
    u.refresh_from_db()
    assert u.email == "neu@example.org" and u.check_password("altes-passwort-123")
    assert rechte.darf_bearbeiten(u) and not u.is_superuser


def test_vorstand_anlegen_adresse_schon_vergeben():
    User.objects.create_user("anna", "anna@example.org", "pw")
    with pytest.raises(CommandError):
        call_command("vorstand_anlegen", "bert", "ANNA@example.org", stdout=StringIO())


def test_vorstand_anlegen_ungueltige_adresse():
    with pytest.raises(CommandError):
        call_command("vorstand_anlegen", "x", "keine-adresse", stdout=StringIO())


def test_deploy_pruefung_ohne_fehler_im_dateimodus(settings):
    """Die Installation bricht bei Fehlern der Deploy-Prüfung ab (check --deploy --fail-level ERROR)."""
    import subprocess, sys, os
    env = {**os.environ, "FV_SECRET_KEY": "x" * 60, "FV_MAIL": "datei",
           "FV_ALLOWED_HOSTS": "example.org", "FV_DEBUG": "0"}
    env.pop("DJANGO_SETTINGS_MODULE", None)
    r = subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "ERROR"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.parametrize("wert, erwartet", [
    (None, "[Webseite] "),
    ("[foerderverein-kf-jf-kreuzau.de]", "[foerderverein-kf-jf-kreuzau.de] "),
    ("[Webseite Förderverein]  ", "[Webseite Förderverein] "),
])
def test_betreff_der_fehlermails_aus_env(wert, erwartet):
    import os
    import subprocess
    import sys
    umgebung = {k: v for k, v in os.environ.items() if k != "FV_ADMINS_BETREFF"}
    umgebung.update(DJANGO_SETTINGS_MODULE="config.settings", FV_DEBUG="1", FV_SECRET_KEY="x",
                    FV_ADMINS=" betreuung@example.org , zweite@example.org")
    if wert is not None:
        umgebung["FV_ADMINS_BETREFF"] = wert
    r = subprocess.run([sys.executable, "-c",
                        "import django; django.setup(); from django.conf import settings as s; "
                        "print(repr(s.EMAIL_SUBJECT_PREFIX)); print(s.ADMINS)"],
                       env=umgebung, capture_output=True, text=True, check=True)
    praefix, admins = r.stdout.strip().splitlines()
    assert praefix == repr(erwartet)
    assert admins == "['betreuung@example.org', 'zweite@example.org']"


@pytest.mark.django_db
def test_fehlermail_mit_betreff(settings, client):
    """Ein Programmfehler erzeugt eine Mail an FV_ADMINS mit dem eingestellten Betreff."""
    from django.core import mail
    from django.test import Client
    from django.urls import path

    def kaputt(request):
        raise RuntimeError("Testfehler")

    import types
    urls = types.ModuleType("fehler_urls")
    urls.urlpatterns = [path("kaputt/", kaputt)]
    import sys
    sys.modules["fehler_urls"] = urls
    settings.ROOT_URLCONF = "fehler_urls"
    settings.ADMINS = ["betreuung@example.org"]
    settings.EMAIL_SUBJECT_PREFIX = "[foerderverein-kf-jf-kreuzau.de] "
    assert Client(raise_request_exception=False).get("/kaputt/").status_code == 500
    m = mail.outbox[-1]
    assert m.to == ["betreuung@example.org"]
    assert m.subject.startswith("[foerderverein-kf-jf-kreuzau.de] ERROR")
    assert "Testfehler" in m.body

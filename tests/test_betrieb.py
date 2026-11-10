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


def test_vorstand_anlegen_und_passwort_setzen(client):
    out = StringIO()
    call_command("vorstand_anlegen", "vera.vorstand", "vera@example.org",
                 "--vorname", "Vera", "--admin", stdout=out)
    u = User.objects.get(username="vera.vorstand")
    assert rechte.darf_bearbeiten(u) and u.is_staff and u.is_superuser
    assert not u.has_usable_password()

    pfad = re.search(r"https?://[^/]+(/passwort/setzen/\S+)", out.getvalue()).group(1)
    r = client.get(pfad)  # leitet auf eine Adresse ohne Token im Pfad weiter
    assert r.status_code == 302
    form_url = r["Location"]
    r = client.post(form_url, {"new_password1": "Sehr-sicheres-Pw-2026",
                               "new_password2": "Sehr-sicheres-Pw-2026"})
    assert r.status_code == 302 and r["Location"] == "/passwort/gesetzt/"
    assert client.login(username="vera.vorstand", password="Sehr-sicheres-Pw-2026")

    # Link ist danach verbraucht
    client.logout()
    assert "ungültig" in client.get(pfad, follow=True).content.decode()


def test_vorstand_anlegen_bestehendes_konto_behaelt_passwort():
    u = User.objects.create_user("max", "alt@example.org", "altes-passwort-123")
    call_command("vorstand_anlegen", "max", "neu@example.org", stdout=StringIO())
    u.refresh_from_db()
    assert u.email == "neu@example.org" and u.check_password("altes-passwort-123")
    assert rechte.darf_bearbeiten(u) and not u.is_superuser


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

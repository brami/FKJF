"""Deutsche Fehlerseiten: 404 (Variante A: neutral, Anmeldung anbieten), 403, CSRF, 500, 400."""

import pytest
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from django.urls import reverse
from django.views import defaults

from seiten.models import Seite
from tests.hilfen import FOERDERMITGLIEDER, MITGLIEDER, stufe as S

pytestmark = pytest.mark.django_db


@pytest.fixture
def intern():
    return Seite.objects.create(titel="Geheimes Protokoll", stufe=S(MITGLIEDER), inhalt="<p>x</p>")


def test_geschuetzte_seite_ohne_anmeldung_neutral_mit_anmelden(client, intern):
    url = reverse("seite", args=[intern.pk])
    r = client.get(url)
    html = r.content.decode()
    assert r.status_code == 404
    assert "Seite nicht gefunden" in html and "nur für angemeldete Personen" in html
    assert "Geheimes Protokoll" not in html                       # verrät nichts
    assert f'{reverse("account_login")}?next={url}' in html.replace("%2F", "/")


def test_unbekannte_adresse_sieht_genauso_aus(client, intern):
    import re
    def ohne_ruecksprung(r):
        return re.sub(r"next=[^\"]*", "next=X", r.content.decode())
    geschuetzt = client.get(reverse("seite", args=[intern.pk]))
    unbekannt = client.get(reverse("seite", args=[99999]))
    # gleicher Status und Text, nur die Rücksprungadresse unterscheidet sich
    assert geschuetzt.status_code == unbekannt.status_code == 404
    assert ohne_ruecksprung(geschuetzt) == ohne_ruecksprung(unbekannt)


def test_nach_anmeldung_zurueck_zur_seite(client, intern):
    User.objects.create_user("max", "max@example.org", "Gutes-Passwort-2026").groups.add(
        S(MITGLIEDER).gruppe)
    url = reverse("seite", args=[intern.pk])
    r = client.post(f'{reverse("account_login")}?next={url}',
                    {"login": "max", "password": "Gutes-Passwort-2026"})
    assert r.status_code == 302 and r["Location"] == url
    assert "Geheimes Protokoll" in client.get(url).content.decode()


def test_angemeldet_ohne_recht(client, intern):
    fritz = User.objects.create_user("fritz", "f@example.org", "pw")
    fritz.groups.add(S(FOERDERMITGLIEDER).gruppe)
    client.force_login(fritz)
    r = client.get(reverse("seite", args=[intern.pk]))
    html = " ".join(r.content.decode().split())
    assert r.status_code == 404 and "für Ihre Stufe nicht freigegeben" in html
    assert "an den Vorstand" in html and "Anmelden</a>" not in html


def test_anhang_ohne_recht_ebenso(client, intern):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from seiten.models import Anhang
    a = Anhang.objects.create(seite=intern, datei=SimpleUploadedFile("p.pdf", b"%PDF-1.4"))
    r = client.get(reverse("anhang", args=[a.pk]))
    assert r.status_code == 404 and "Anmelden" in r.content.decode()


def test_formular_abgelaufen():
    c = Client(enforce_csrf_checks=True)
    r = c.post(reverse("account_login"), {"login": "x", "password": "y"})
    html = r.content.decode()
    assert r.status_code == 403 and "Formular abgelaufen" in html and "CSRF" not in html


def test_kein_zugriff_deutsch(client):
    vera = User.objects.create_user("vera", "v@example.org", "pw")
    vera.groups.add(S("Vorstand").gruppe)
    client.force_login(vera)
    r = client.get(reverse("admin:seiten_stufe_changelist"))
    assert r.status_code == 403 and "Kein Zugriff" in r.content.decode()


def test_500_ohne_datenbank(django_assert_num_queries):
    """Muss auch funktionieren, wenn die Datenbank die Ursache des Fehlers ist."""
    with django_assert_num_queries(0):
        r = defaults.server_error(RequestFactory().get("/"))
    assert r.status_code == 500 and "Es ist ein Fehler aufgetreten" in r.content.decode()


def test_400_deutsch():
    r = defaults.bad_request(RequestFactory().get("/"), Exception())
    assert r.status_code == 400 and "Ungültige Anfrage" in r.content.decode()

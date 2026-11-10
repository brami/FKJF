"""Tests der Bearbeitungsoberfläche."""

from datetime import date

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from seiten.models import Anhang, Seite
from seiten.stufen import Stufe

pytestmark = pytest.mark.django_db


@pytest.fixture
def vorstand():
    u = User.objects.create_user("vorstand", "v@example.org", "pw", first_name="Vera")
    u.groups.add(Group.objects.get(name="Vorstand"))
    return u


@pytest.fixture
def mitglied():
    u = User.objects.create_user("mitglied", "m@example.org", "pw")
    u.groups.add(Group.objects.get(name="Mitglieder"))
    return u


@pytest.fixture
def seite():
    return Seite.objects.create(titel="Einladung", datum=date(2026, 3, 1),
                                stufe=Stufe.MITGLIEDER, inhalt="<p>Erste Fassung</p>")


def formdaten(**werte):
    daten = {
        "titel": "Einladung zur Mitgliederversammlung",
        "datum": "2026-03-01",
        "stufe": str(Stufe.FOERDERMITGLIEDER),
        "inhalt": "<h2>Tagesordnung</h2><ol><li>Bericht</li></ol>",
        "anhang-TOTAL_FORMS": "0",
        "anhang-INITIAL_FORMS": "0",
        "anhang-MIN_NUM_FORMS": "0",
        "anhang-MAX_NUM_FORMS": "1000",
    }
    daten.update(werte)
    return daten


def pdf(name="einladung.pdf", inhalt=b"%PDF-1.4 x"):
    return SimpleUploadedFile(name, inhalt, content_type="application/pdf")


# --- Zugriff ---------------------------------------------------------------

ADRESSEN = [
    ("seite_neu", False, "GET"),
    ("seite_bearbeiten", True, "GET"),
    ("seite_loeschen", True, "GET"),
    ("seite_verlauf", True, "GET"),
    ("seite_bearbeiten", True, "POST"),
    ("seite_loeschen", True, "POST"),
]


@pytest.mark.parametrize("name,mit_pk,methode", ADRESSEN)
def test_nicht_angemeldet_wird_zur_anmeldung_geleitet(client, seite, name, mit_pk, methode):
    url = reverse(name, args=[seite.pk] if mit_pk else [])
    r = client.get(url) if methode == "GET" else client.post(url, formdaten())
    assert r.status_code == 302 and "/konto/login/" in r["Location"]
    assert Seite.objects.filter(pk=seite.pk, titel="Einladung").exists()


@pytest.mark.parametrize("name,mit_pk,methode", ADRESSEN)
def test_mitglied_bekommt_404(client, seite, mitglied, name, mit_pk, methode):
    client.force_login(mitglied)
    url = reverse(name, args=[seite.pk] if mit_pk else [])
    r = client.get(url) if methode == "GET" else client.post(url, formdaten())
    assert r.status_code == 404
    assert Seite.objects.filter(pk=seite.pk, titel="Einladung").exists()


def test_mitglied_kein_zugriff_auf_fassung_und_wiederherstellen(client, seite, mitglied):
    client.force_login(mitglied)
    h = seite.history.first().history_id
    assert client.get(reverse("seite_fassung", args=[seite.pk, h])).status_code == 404
    assert client.post(reverse("seite_wiederherstellen", args=[seite.pk, h])).status_code == 404


def test_bearbeiten_links_nur_fuer_vorstand(client, seite, vorstand, mitglied):
    client.force_login(mitglied)
    assert "Bearbeiten" not in client.get(seite.get_absolute_url()).content.decode()
    assert "Neue Seite" not in client.get(reverse("startseite")).content.decode()
    client.force_login(vorstand)
    assert "Bearbeiten" in client.get(seite.get_absolute_url()).content.decode()
    assert "Neue Seite" in client.get(reverse("startseite")).content.decode()


# --- Anlegen und Ändern ----------------------------------------------------

def test_neue_seite_mit_anhaengen(client, vorstand):
    client.force_login(vorstand)
    r = client.post(reverse("seite_neu"), formdaten(
        dateien=[pdf("einladung.pdf"), pdf("satzungsaenderung.pdf")]))
    s = Seite.objects.get()
    assert r.status_code == 302 and r["Location"] == s.get_absolute_url()
    assert s.titel == "Einladung zur Mitgliederversammlung"
    assert s.stufe == Stufe.FOERDERMITGLIEDER
    assert sorted(s.anhaenge.values_list("dateiname", flat=True)) == [
        "einladung.pdf", "satzungsaenderung.pdf"]
    assert s.history.first().history_user == vorstand


def test_editor_seite_laedt_mit_angepasster_csp(client, vorstand):
    client.force_login(vorstand)
    r = client.get(reverse("seite_neu"))
    assert r.status_code == 200
    assert "tinymce.min.js" in r.content.decode()
    assert "'unsafe-inline'" in r["Content-Security-Policy"].split("style-src")[1].split(";")[0]
    assert "'unsafe-inline'" not in r["Content-Security-Policy"].split("script-src")[1].split(";")[0]


def test_aendern_wird_bereinigt_und_versioniert(client, vorstand, seite):
    client.force_login(vorstand)
    client.post(reverse("seite_bearbeiten", args=[seite.pk]),
                formdaten(inhalt="<p>Neu</p><script>alert(1)</script>"))
    seite.refresh_from_db()
    assert seite.inhalt == "<p>Neu</p>"
    assert seite.history.count() == 2


def test_ungueltige_datei_wird_abgelehnt(client, vorstand):
    client.force_login(vorstand)
    r = client.post(reverse("seite_neu"), formdaten(
        dateien=[pdf("ok.pdf"), SimpleUploadedFile("boese.exe", b"MZ")]))
    assert r.status_code == 200
    assert "boese.exe" in r.content.decode()
    assert not Seite.objects.exists()  # nichts halb gespeichert
    assert not Anhang.objects.exists()


def test_zu_grosse_datei_wird_abgelehnt(client, vorstand, settings):
    settings.ANHANG_MAX_BYTES = 5
    client.force_login(vorstand)
    r = client.post(reverse("seite_neu"), formdaten(dateien=[pdf(inhalt=b"0123456789")]))
    assert r.status_code == 200
    assert "größer als" in r.content.decode()
    assert not Seite.objects.exists()


def test_anhang_umbenennen_und_entfernen(client, vorstand, seite):
    a1 = Anhang.objects.create(seite=seite, datei=pdf("a.pdf"))
    a2 = Anhang.objects.create(seite=seite, datei=pdf("b.pdf"))
    pfad2 = a2.datei.path
    client.force_login(vorstand)
    client.post(reverse("seite_bearbeiten", args=[seite.pk]), formdaten(**{
        "anhang-TOTAL_FORMS": "2", "anhang-INITIAL_FORMS": "2",
        "anhang-0-id": str(a1.pk), "anhang-0-bezeichnung": "Tagesordnung",
        "anhang-1-id": str(a2.pk), "anhang-1-bezeichnung": "", "anhang-1-DELETE": "on",
    }))
    a1.refresh_from_db()
    assert a1.bezeichnung == "Tagesordnung"
    assert not Anhang.objects.filter(pk=a2.pk).exists()
    import os
    assert not os.path.exists(pfad2)


# --- Löschen ---------------------------------------------------------------

def test_loeschen_entfernt_seite_und_dateien(client, vorstand, seite):
    a = Anhang.objects.create(seite=seite, datei=pdf())
    pfad = a.datei.path
    client.force_login(vorstand)
    assert "wirklich gelöscht" in client.get(reverse("seite_loeschen", args=[seite.pk])).content.decode()
    r = client.post(reverse("seite_loeschen", args=[seite.pk]))
    assert r.status_code == 302
    assert not Seite.objects.exists() and not Anhang.objects.exists()
    import os
    assert not os.path.exists(pfad)


# --- Versionsverlauf -------------------------------------------------------

def test_verlauf_vergleich_und_wiederherstellen(client, vorstand, seite):
    client.force_login(vorstand)
    client.post(reverse("seite_bearbeiten", args=[seite.pk]), formdaten(
        titel="Einladung (geändert)", stufe=str(Stufe.MITGLIEDER), datum="2026-03-01",
        inhalt="<p>Zweite Fassung</p>"))
    seite.refresh_from_db()
    assert seite.inhalt == "<p>Zweite Fassung</p>"

    verlauf = client.get(reverse("seite_verlauf", args=[seite.pk])).content.decode()
    assert "angelegt" in verlauf and "geändert" in verlauf and "Vera" in verlauf

    erste = seite.history.earliest()
    import html
    vergleich = html.unescape(client.get(
        reverse("seite_fassung", args=[seite.pk, erste.history_id])).content.decode()).replace("\xa0", " ")
    assert "Erste Fassung" in vergleich and "Zweite Fassung" in vergleich
    assert "Einladung (geändert)" in vergleich  # geänderter Titel in der Feldtabelle

    r = client.post(reverse("seite_wiederherstellen", args=[seite.pk, erste.history_id]))
    assert r.status_code == 302
    seite.refresh_from_db()
    assert seite.titel == "Einladung" and seite.inhalt == "<p>Erste Fassung</p>"
    neueste = seite.history.latest()
    assert neueste.history_change_reason.startswith("Wiederhergestellt")
    assert seite.history.count() == 3


def test_wiederherstellen_nur_per_post(client, vorstand, seite):
    client.force_login(vorstand)
    h = seite.history.first().history_id
    assert client.get(reverse("seite_wiederherstellen", args=[seite.pk, h])).status_code == 405


def test_fassung_einer_anderen_seite_nicht_abrufbar(client, vorstand, seite):
    andere = Seite.objects.create(titel="Andere", stufe=Stufe.VORSTAND)
    client.force_login(vorstand)
    h = andere.history.first().history_id
    assert client.get(reverse("seite_fassung", args=[seite.pk, h])).status_code == 404
    assert client.post(reverse("seite_wiederherstellen", args=[seite.pk, h])).status_code == 404


def test_fassungszeit_in_ortszeit(client, vorstand, seite):
    from datetime import datetime, timezone as tz
    h = seite.history.first()
    h.history_date = datetime(2026, 11, 10, 15, 57, tzinfo=tz.utc)
    h.save()
    client.force_login(vorstand)
    html = client.get(reverse("seite_fassung", args=[seite.pk, h.history_id])).content.decode()
    assert "16:57" in html and "15:57" not in html

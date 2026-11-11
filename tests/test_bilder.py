"""Tests für Bilder unter den Anhängen: Titelbild, Galerie, Vorschau, Metadaten, Rechte."""

import os
from io import BytesIO

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from seiten.models import Anhang, Seite
from seiten.stufen import Stufe

pytestmark = pytest.mark.django_db


def foto(name="foto.jpg", groesse=(4000, 3000), drehung=None, gps=True, fmt="JPEG", modus="RGB"):
    """Testbild wie vom Handy: groß, mit Kamera- und GPS-Daten, optional gedreht."""
    img = Image.new(modus, groesse, (200, 30, 30, 128) if modus == "RGBA" else (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "Testkamera"          # Hersteller
    if drehung:
        exif[0x0112] = drehung           # Ausrichtung
    if gps:
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (50.0, 46.0, 30.0)  # Breitengrad
    puffer = BytesIO()
    if fmt == "PNG":
        img.save(puffer, fmt)
    else:
        img.save(puffer, fmt, exif=exif)
    return SimpleUploadedFile(name, puffer.getvalue(), content_type="image/jpeg")


def oeffnen(feld):
    with feld.open("rb") as f:
        img = Image.open(BytesIO(f.read()))
        img.load()
    return img


@pytest.fixture
def seite():
    return Seite.objects.create(titel="Sommerfest", stufe=Stufe.OEFFENTLICH, inhalt="<p>Schön war’s.</p>")


@pytest.fixture
def vorstand(client):
    u = User.objects.create_user("vera", "vera@example.org", "pw")
    u.groups.add(Group.objects.get(name="Vorstand"))
    return u


# --- Verarbeitung ------------------------------------------------------------

def test_foto_wird_verkleinert_und_ohne_metadaten_gespeichert(seite):
    a = Anhang.objects.create(seite=seite, datei=foto())
    assert a.ist_bild and a.dateiname == "foto.jpg"
    for feld, max_px in [(a.datei, 2400), (a.bild, 1200), (a.vorschaubild, 600)]:
        img = oeffnen(feld)
        assert max(img.size) == max_px
        assert len(img.getexif()) == 0, "EXIF-/GPS-Daten müssen entfernt sein"


def test_ausrichtung_wird_angewendet(seite):
    a = Anhang.objects.create(seite=seite, datei=foto(groesse=(4000, 3000), drehung=6))
    breite, hoehe = oeffnen(a.datei).size
    assert hoehe > breite  # um 90° gedreht gespeichert, EXIF-Ausrichtung entfällt


def test_png_mit_transparenz_bleibt_png(seite):
    a = Anhang.objects.create(seite=seite, datei=foto("logo.png", (800, 400), gps=False,
                                                      fmt="PNG", modus="RGBA"))
    img = oeffnen(a.bild)
    assert img.format == "PNG" and img.mode == "RGBA" and a.dateiname == "logo.png"


def test_webp_wird_jpeg(seite):
    a = Anhang.objects.create(seite=seite, datei=foto("bild.webp", (1000, 800), fmt="WEBP"))
    assert oeffnen(a.datei).format == "JPEG" and a.dateiname == "bild.jpg"


def test_pdf_ist_kein_bild(seite):
    a = Anhang.objects.create(seite=seite, datei=SimpleUploadedFile("antrag.pdf", b"%PDF-1.4"))
    assert not a.ist_bild and not a.bild and not a.vorschaubild


def test_dateien_werden_beim_loeschen_entfernt(seite):
    a = Anhang.objects.create(seite=seite, datei=foto())
    pfade = [a.datei.path, a.bild.path, a.vorschaubild.path]
    a.delete()
    assert not any(os.path.exists(p) for p in pfade)


# --- Hochladen über die Bearbeitungsmaske -------------------------------------

def formdaten(seite, **werte):
    daten = {"titel": seite.titel, "datum": "2026-07-01", "stufe": str(seite.stufe),
             "inhalt": seite.inhalt, "anhang-TOTAL_FORMS": "0", "anhang-INITIAL_FORMS": "0",
             "anhang-MIN_NUM_FORMS": "0", "anhang-MAX_NUM_FORMS": "1000"}
    daten.update(werte)
    return daten


def test_kein_echtes_bild_wird_abgelehnt(client, vorstand, seite):
    client.force_login(vorstand)
    falsch = SimpleUploadedFile("foto.jpg", b"das ist kein Bild")
    r = client.post(reverse("seite_bearbeiten", args=[seite.pk]), formdaten(seite, dateien=[falsch]))
    assert r.status_code == 200 and "kein lesbares Bild" in r.content.decode()
    assert not Anhang.objects.exists()


def test_svg_nicht_erlaubt(client, vorstand, seite):
    client.force_login(vorstand)
    svg = SimpleUploadedFile("bild.svg", b"<svg onload='alert(1)'/>")
    client.post(reverse("seite_bearbeiten", args=[seite.pk]), formdaten(seite, dateien=[svg]))
    assert not Anhang.objects.exists()


def test_titelbild_auswaehlen(client, vorstand, seite):
    a1 = Anhang.objects.create(seite=seite, datei=foto("eins.jpg", (800, 600)))
    a2 = Anhang.objects.create(seite=seite, datei=foto("zwei.jpg", (800, 600)))
    assert seite.titelbild() == a1  # ohne Auswahl: erstes Bild
    client.force_login(vorstand)
    client.post(reverse("seite_bearbeiten", args=[seite.pk]), formdaten(seite, **{
        "anhang-TOTAL_FORMS": "2", "anhang-INITIAL_FORMS": "2",
        "anhang-0-id": str(a1.pk), "anhang-1-id": str(a2.pk), "anhang-1-titelbild": "on"}))
    seite.refresh_from_db()
    assert seite.titelbild() == a2 and seite.galerie() == [a1]


def test_nur_ein_titelbild(client, vorstand, seite):
    a1 = Anhang.objects.create(seite=seite, datei=foto("eins.jpg", (800, 600)))
    a2 = Anhang.objects.create(seite=seite, datei=foto("zwei.jpg", (800, 600)))
    client.force_login(vorstand)
    r = client.post(reverse("seite_bearbeiten", args=[seite.pk]), formdaten(seite, **{
        "anhang-TOTAL_FORMS": "2", "anhang-INITIAL_FORMS": "2",
        "anhang-0-id": str(a1.pk), "anhang-0-titelbild": "on",
        "anhang-1-id": str(a2.pk), "anhang-1-titelbild": "on"}))
    assert "nur ein Bild" in r.content.decode()


# --- Anzeige ------------------------------------------------------------------

def test_seite_zeigt_aufmacher_galerie_und_dateien(client, seite):
    a1 = Anhang.objects.create(seite=seite, datei=foto("eins.jpg", (800, 600)), bezeichnung="Grillstand")
    a2 = Anhang.objects.create(seite=seite, datei=foto("zwei.jpg", (800, 600)))
    pdf = Anhang.objects.create(seite=seite, datei=SimpleUploadedFile("plan.pdf", b"%PDF-1.4"))
    html = client.get(seite.get_absolute_url()).content.decode()
    aufmacher = html[html.index('class="aufmacher"'):html.index('class="text"')]
    assert a1.bild_url() in aufmacher and "Grillstand" in aufmacher
    galerie = html[html.index('class="galerie"'):]
    assert a2.vorschau_url() in galerie and a1.vorschau_url() not in galerie
    dateien = html[html.index('class="anhaenge"'):]
    assert pdf.get_absolute_url() in dateien and a2.get_absolute_url() not in dateien


def test_startseite_zeigt_vorschaubild(client, seite):
    a = Anhang.objects.create(seite=seite, datei=foto("eins.jpg", (800, 600)))
    html = client.get(reverse("startseite")).content.decode()
    assert a.vorschau_url() in html


def test_bilder_werden_angezeigt_nicht_heruntergeladen(client, seite):
    a = Anhang.objects.create(seite=seite, datei=foto("eins.jpg", (800, 600)))
    for url in [a.get_absolute_url(), a.bild_url(), a.vorschau_url()]:
        r = client.get(url)
        assert r.status_code == 200 and r["Content-Type"] == "image/jpeg"
        assert not r["Content-Disposition"].startswith("attachment")


@pytest.mark.parametrize("variante", ["bild", "vorschau"])
def test_bilder_geschuetzter_seiten_nur_mit_recht(client, variante):
    intern = Seite.objects.create(titel="Intern", stufe=Stufe.MITGLIEDER)
    a = Anhang.objects.create(seite=intern, datei=foto("eins.jpg", (800, 600)))
    url = reverse("anhang_variante", args=[a.pk, variante])
    assert client.get(url).status_code == 302          # nicht angemeldet -> Anmeldung
    assert a.vorschau_url() not in client.get(reverse("startseite")).content.decode()
    foerder = User.objects.create_user("f", "f@example.org", "pw")
    foerder.groups.add(Group.objects.get(name="Fördermitglieder"))
    client.force_login(foerder)
    assert client.get(url).status_code == 404          # angemeldet ohne Recht
    mitglied = User.objects.create_user("m", "m@example.org", "pw")
    mitglied.groups.add(Group.objects.get(name="Mitglieder"))
    client.force_login(mitglied)
    assert client.get(url).status_code == 200


def test_unbekannte_variante(client, seite):
    a = Anhang.objects.create(seite=seite, datei=foto("eins.jpg", (800, 600)))
    assert client.get(reverse("anhang_variante", args=[a.pk, "datei"])).status_code == 404

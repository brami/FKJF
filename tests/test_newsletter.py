"""Newsletter: Empfänger, Reihenfolge, Probe und Pause, Abbruch, Inhalt der E-Mail, Fehler."""

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail.backends.locmem import EmailBackend
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from seiten import newsletter
from seiten.models import Anhang, Empfang, Profil, Seite, Versand, Webseite
from tests.hilfen import FOERDERMITGLIEDER, MITGLIEDER, VORSTAND, stufe as S

pytestmark = pytest.mark.django_db


def person(name, stufe=None, email=None, vorname="", nachname="", vereins_email=None,
           zustellung="extern", aktiv=True):
    u = User.objects.create_user(name, f"{name}@extern.example" if email is None else email,
                                 "pw", first_name=vorname, last_name=nachname, is_active=aktiv)
    if stufe:
        u.groups.add(S(stufe).gruppe)
    if vereins_email:
        Profil.objects.update_or_create(user=u, defaults={
            "vereins_email": vereins_email, "zustellung": zustellung})
    return u


@pytest.fixture
def verein(settings):
    settings.FV_NEWSLETTER_PAUSE = 300
    settings.FV_NEWSLETTER_ABSTAND = 0
    settings.DEFAULT_FROM_EMAIL = "webmaster@verein.example"
    settings.FV_BASIS_URL = "https://verein.example"
    w = Webseite.aktuell()
    w.antwort_an = "vorstand@verein.example"
    w.save()
    return {
        "vera": person("vera", VORSTAND, vorname="Vera", nachname="Vorsitz",
                       vereins_email="vera@verein.example"),
        "viktor": person("viktor", VORSTAND, vorname="Viktor", nachname="Kasse"),
        "max": person("max", MITGLIEDER, vorname="Max", nachname="Muster"),
        "mia": person("mia", MITGLIEDER, vorname="Mia", nachname="Adler",
                      vereins_email="mia@verein.example", zustellung="verein"),
        "otto": person("otto", MITGLIEDER, email="", vorname="Otto", nachname="Ohnemail"),
        "fritz": person("fritz", FOERDERMITGLIEDER, vorname="Fritz", nachname="Förder"),
        "alt": person("alt", MITGLIEDER, aktiv=False),
        "gast": person("gast"),   # Konto ohne Stufe
    }


@pytest.fixture
def seite():
    s = Seite.objects.create(titel="Jahreshauptversammlung", stufe=S(MITGLIEDER),
                             inhalt='<p>Einladung zur <a href="/seite/1/">JHV</a>.</p><ul><li>Punkt 1</li></ul>')
    Anhang.objects.create(seite=s, datei=SimpleUploadedFile("tagesordnung.pdf", b"%PDF-1.4 TO"))
    return s


def starten(seite, absender, **kw):
    werte = dict(modus=Versand.Modus.LINK, ankuendigung="", mit_anhaengen=False,
                 stufen=list(newsletter.stufen_fuer(seite)), ohne_stufe=False)
    werte.update(kw)
    return newsletter.versand_anlegen(seite, absender, **werte)


def alles_senden(jetzt=None):
    jetzt = jetzt or timezone.now()
    for _ in range(100):
        if not Versand.objects.filter(status=Versand.Status.LAEUFT).exists():
            return
        newsletter.schritt(jetzt)


# ------------------------------------------------------------------ Empfänger

def test_empfaenger_probe_zuerst_dann_hoechste_stufe(verein, seite):
    v = starten(seite, verein["vera"])
    namen = list(v.empfaenge.values_list("name", "stufe", "status"))
    assert namen == [
        ("Vera Vorsitz", "Probe", "offen"),
        ("Viktor Kasse", "Vorstand", "offen"),
        ("Mia Adler", "Mitglieder", "offen"),
        ("Max Muster", "Mitglieder", "offen"),
        ("Otto Ohnemail", "Mitglieder", "ohne"),
    ]   # Fördermitglieder sehen die Seite nicht, deaktivierte Konten fehlen


def test_zustelladresse_nach_wahl_der_person(verein, seite):
    v = starten(seite, verein["vera"])
    adressen = dict(v.empfaenge.values_list("name", "adresse"))
    assert adressen["Mia Adler"] == "mia@verein.example"
    assert adressen["Max Muster"] == "max@extern.example"


def test_auswahl_einzelner_stufen(verein, seite):
    v = starten(seite, verein["vera"], stufen=[S(VORSTAND)])
    assert list(v.empfaenge.values_list("name", flat=True)) == ["Vera Vorsitz", "Viktor Kasse"]
    # Stufen unterhalb der Seite werden ignoriert
    v = starten(seite, verein["vera"], stufen=[S(FOERDERMITGLIEDER)])
    assert v.empfaenge.count() == 1


def test_konten_ohne_stufe_nur_bei_oeffentlichen_seiten(verein, seite):
    v = starten(seite, verein["vera"], ohne_stufe=True)
    assert "gast" not in v.empfaenge.values_list("name", flat=True)
    oeffentlich = Seite.objects.create(titel="Sommerfest", stufe=None)
    v = starten(oeffentlich, verein["vera"], stufen=[], ohne_stufe=True)
    assert list(v.empfaenge.values_list("name", flat=True)) == ["Vera Vorsitz", "gast"]
    v = starten(oeffentlich, verein["vera"], ohne_stufe=True)
    assert v.empfaenge.count() == 8 - 1   # alle aktiven Konten, der deaktivierte nicht
    assert list(v.empfaenge.values_list("stufe", flat=True))[-1] == "ohne Stufe"


# ------------------------------------------------------------------ Ablauf

def test_probe_pause_und_dann_einzeln(verein, seite):
    v = starten(seite, verein["vera"])
    jetzt = timezone.now()
    newsletter.schritt(jetzt)
    assert [m.to for m in mail.outbox] == [["vera@extern.example"]]
    v.refresh_from_db()
    assert v.in_pause(jetzt)
    # während der Pause geht nichts weiter
    assert newsletter.schritt(jetzt + timedelta(seconds=60)) > 0
    assert len(mail.outbox) == 1
    # nach der Pause: jede Mail einzeln, in Reihenfolge
    spaeter = jetzt + timedelta(seconds=301)
    newsletter.schritt(spaeter)
    assert mail.outbox[-1].to == ["viktor@extern.example"]
    alles_senden(spaeter)
    assert [m.to[0] for m in mail.outbox] == [
        "vera@extern.example", "viktor@extern.example", "mia@verein.example", "max@extern.example"]
    v.refresh_from_db()
    assert v.status == Versand.Status.FERTIG and v.beendet
    assert v.zaehlung() == {"offen": 0, "gesendet": 4, "fehler": 0, "ohne": 1, "nicht": 0}


def test_abstand_zwischen_mails(verein, seite, settings):
    settings.FV_NEWSLETTER_ABSTAND = 10
    starten(seite, verein["vera"])
    t = timezone.now()
    newsletter.schritt(t)
    newsletter.schritt(t + timedelta(seconds=301))
    assert len(mail.outbox) == 2
    newsletter.schritt(t + timedelta(seconds=305))
    assert len(mail.outbox) == 2
    newsletter.schritt(t + timedelta(seconds=312))
    assert len(mail.outbox) == 3


def test_pause_vorzeitig_beenden(client, verein, seite):
    v = starten(seite, verein["vera"])
    newsletter.schritt()
    client.force_login(verein["vera"])
    assert "Probe ist in Ordnung" in client.get(v.get_absolute_url()).content.decode()
    client.post(reverse("newsletter_fortsetzen", args=[v.pk]))
    alles_senden()
    assert len(mail.outbox) == 4


def test_abbrechen_jederzeit(client, verein, seite):
    v = starten(seite, verein["vera"])
    t = timezone.now()
    newsletter.schritt(t)
    newsletter.schritt(t + timedelta(seconds=301))   # Viktor
    client.force_login(verein["viktor"])
    client.post(reverse("newsletter_abbrechen", args=[v.pk]))
    alles_senden(t + timedelta(seconds=999))
    newsletter.schritt(t + timedelta(seconds=999))
    assert len(mail.outbox) == 2
    v.refresh_from_db()
    assert v.status == Versand.Status.ABGEBROCHEN and v.abgebrochen_von == verein["viktor"]
    assert v.zaehlung()["nicht"] == 2


def test_fehler_einzelner_mail_stoppt_nicht(verein, seite, monkeypatch):
    original = EmailBackend.send_messages

    def senden(self, nachrichten):
        if any("max@" in a for m in nachrichten for a in m.to):
            raise OSError("550 Postfach unbekannt")
        return original(self, nachrichten)

    monkeypatch.setattr(EmailBackend, "send_messages", senden)
    v = starten(seite, verein["vera"])
    t = timezone.now() + timedelta(seconds=301)
    newsletter.schritt()
    alles_senden(t)
    e = v.empfaenge.get(name="Max Muster")
    assert e.status == Empfang.Status.FEHLER and "550" in e.fehler
    assert v.zaehlung()["gesendet"] == 3


def test_seite_mehrfach_versendbar(verein, seite):
    starten(seite, verein["vera"])
    starten(seite, verein["viktor"])
    assert seite.versaende.count() == 2


def test_dienst_einmal(verein, seite, settings):
    settings.FV_NEWSLETTER_PAUSE = 0
    starten(seite, verein["vera"])
    call_command("newsletter_dienst", "--einmal", stdout=StringIO())
    assert len(mail.outbox) == 4


# ------------------------------------------------------------------ Inhalt

def test_nur_link_mit_ankuendigung(verein, seite):
    starten(seite, verein["viktor"], ankuendigung="Liebe Mitglieder,\nbitte vormerken!")
    newsletter.schritt()
    m = mail.outbox[0]
    assert m.subject == f"[{Webseite.aktuell().name}] Jahreshauptversammlung"
    assert "bitte vormerken!" in m.body and "Weiterlesen: https://verein.example/seite/" in m.body
    html = m.alternatives[0][0]
    assert "Liebe Mitglieder,<br>bitte vormerken!" in html
    assert "Punkt 1</li>" not in html and "Weiterlesen" in html


def test_volltext(verein, seite):
    starten(seite, verein["viktor"], modus=Versand.Modus.VOLLTEXT)
    newsletter.schritt()
    m = mail.outbox[0]
    html = m.alternatives[0][0]
    assert "<li>Punkt 1</li>" in html
    assert 'href="https://verein.example/seite/1/"' in html   # Links absolut
    assert "- Punkt 1" in m.body and "JHV (https://verein.example/seite/1/)" in m.body


def test_absender_und_antwortadressen(verein, seite):
    starten(seite, verein["viktor"])
    newsletter.schritt()
    m = mail.outbox[0]
    name = Webseite.aktuell().name
    # ohne Vereinsadresse: Systemadresse mit Namen der Person
    assert m.from_email == f'"Viktor Kasse ({name})" <webmaster@verein.example>'
    assert m.reply_to == ["viktor@extern.example", "vorstand@verein.example"]
    # mit Vereinsadresse: diese ist Absender und Antwortadresse
    mail.outbox.clear()
    Versand.objects.update(status=Versand.Status.FERTIG)
    starten(seite, verein["vera"])
    newsletter.schritt()
    m = mail.outbox[0]
    assert m.from_email == "Vera Vorsitz <vera@verein.example>"
    assert m.reply_to == ["vera@verein.example", "vorstand@verein.example"]


def test_anhaenge_klein_angehaengt_gross_als_link(verein, seite, settings):
    starten(seite, verein["viktor"], mit_anhaengen=True)
    newsletter.schritt()
    m = mail.outbox[0]
    assert [a[0] for a in m.attachments] == ["tagesordnung.pdf"]
    mail.outbox.clear()
    Versand.objects.update(status=Versand.Status.FERTIG)
    settings.FV_NEWSLETTER_MAX_ANHANG_MB = 0
    starten(seite, verein["viktor"], mit_anhaengen=True)
    newsletter.schritt()
    m = mail.outbox[0]
    assert m.attachments == []
    assert "zu groß für die E-Mail" in m.body and "/anhang/" in m.body


def test_ohne_anhaenge_nur_links(verein, seite):
    starten(seite, verein["viktor"])
    newsletter.schritt()
    assert mail.outbox[0].attachments == [] and "tagesordnung.pdf" in mail.outbox[0].body


def test_html_zu_text():
    assert newsletter.html_zu_text("<p>A&amp;B</p><p>C<br>D</p>") == "A&B\n\nC\nD"


# ------------------------------------------------------------------ Oberfläche

def test_nur_bearbeiter(client, verein, seite):
    url = reverse("newsletter_neu", args=[seite.pk])
    assert client.get(url).status_code == 302
    client.force_login(verein["max"])
    assert client.get(url).status_code == 404
    assert client.get(reverse("newsletter_uebersicht")).status_code == 404


def test_formular_und_start(client, verein, seite):
    client.force_login(verein["vera"])
    url = reverse("newsletter_neu", args=[seite.pk])
    html = client.get(url).content.decode()
    assert "Vorstand" in html and "Mitglieder" in html and "Fördermitglieder" not in html
    assert "Otto Ohnemail" in html   # Liste ohne E-Mail-Adresse
    assert "Konten ohne Stufe" not in html
    r = client.post(url, {"modus": "volltext", "ankuendigung": "Hallo",
                          "stufen": [S(VORSTAND).pk], "mit_anhaengen": "on"})
    v = Versand.objects.get()
    assert r.status_code == 302 and r["Location"] == v.get_absolute_url()
    assert v.modus == "volltext" and v.mit_anhaengen and v.ankuendigung == "Hallo"
    assert v.empfaenge.count() == 2
    # ohne Stufe: Fehler
    r = client.post(url, {"modus": "link"})
    assert "mindestens eine Stufe" in r.content.decode()


def test_status_warnt_ohne_dienst(client, verein, seite):
    v = starten(seite, verein["vera"])
    client.force_login(verein["vera"])
    cache.delete(newsletter.HERZSCHLAG)
    assert "Versanddienst meldet sich nicht" in client.get(v.get_absolute_url()).content.decode()
    newsletter.herzschlag()
    html = client.get(v.get_absolute_url()).content.decode()
    assert "Versanddienst meldet sich nicht" not in html and 'http-equiv="refresh"' in html


def test_link_auf_seite_und_kopf(client, verein, seite):
    client.force_login(verein["vera"])
    html = client.get(seite.get_absolute_url()).content.decode()
    assert reverse("newsletter_neu", args=[seite.pk]) in html
    assert reverse("newsletter_uebersicht") in html

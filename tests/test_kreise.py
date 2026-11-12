"""Kreise: zusätzliche Beschränkung von Seiten und Anhängen auf eine Personenliste
(z. B. „Ausflug 2027“), Newsletter an Kreise, Verteiler mit Kreisen."""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse

from seiten import mail as mailmodul
from seiten import newsletter, rechte
from seiten.models import Anhang, Empfang, Kreis, Profil, Seite, Verteiler
from tests.hilfen import MITGLIEDER, VORSTAND, stufe as S

pytestmark = pytest.mark.django_db


def person(name, stufe=None, vereins_email=None):
    u = User.objects.create_user(name, f"{name}@extern.example", "pw", first_name=name.title())
    if stufe:
        u.groups.add(S(stufe).gruppe)
    if vereins_email:
        Profil.objects.create(user=u, vereins_email=vereins_email)
    return u


@pytest.fixture
def ausflug():
    vera = person("vera", VORSTAND)               # Vorstand, fährt nicht mit
    max_ = person("max", MITGLIEDER)              # fährt mit
    mia = person("mia", MITGLIEDER)               # fährt nicht mit
    kreis = Kreis.objects.create(name="Ausflug 2027")
    kreis.personen.add(max_)
    einladung = Seite.objects.create(titel="Einladung Ausflug", stufe=S(MITGLIEDER), inhalt="<p>Wir fahren</p>")
    liste = Anhang.objects.create(seite=einladung, kreis=kreis,
                                  datei=SimpleUploadedFile("telefonliste.pdf", b"%PDF-1.4 geheim"))
    programm = Anhang.objects.create(seite=einladung, datei=SimpleUploadedFile("programm.pdf", b"%PDF-1.4"))
    infos = Seite.objects.create(titel="Infos für Mitfahrende", stufe=S(MITGLIEDER), kreis=kreis,
                                 inhalt="<p>Treffpunkt</p>")
    return {"vera": vera, "max": max_, "mia": mia, "kreis": kreis, "einladung": einladung,
            "liste": liste, "programm": programm, "infos": infos}


# ------------------------------------------------------------------ Rechte

def test_rechte_fuer_seite_und_anhang(ausflug):
    a = ausflug
    assert rechte.darf_lesen(a["max"], a["infos"])
    assert not rechte.darf_lesen(a["mia"], a["infos"])
    assert rechte.darf_lesen(a["vera"], a["infos"])          # Vorstand sieht alles
    assert not rechte.darf_lesen(None, a["infos"])
    assert rechte.darf_anhang(a["max"], a["liste"])
    assert not rechte.darf_anhang(a["mia"], a["liste"])
    assert rechte.darf_anhang(a["mia"], a["programm"])
    assert rechte.darf_anhang(a["vera"], a["liste"])


def test_anhang_setzt_leserecht_der_seite_voraus(ausflug):
    gast = person("gast", None)
    ausflug["kreis"].personen.add(gast)                      # im Kreis, aber keine Stufe
    assert not rechte.darf_anhang(User.objects.get(pk=gast.pk), ausflug["liste"])


def test_sichtbare_seiten(ausflug):
    titel = lambda u: set(rechte.sichtbare_seiten(u).values_list("titel", flat=True))  # noqa: E731
    assert titel(ausflug["max"]) == {"Einladung Ausflug", "Infos für Mitfahrende"}
    assert titel(ausflug["mia"]) == {"Einladung Ausflug"}
    assert titel(ausflug["vera"]) == {"Einladung Ausflug", "Infos für Mitfahrende"}


def test_leser_einer_kreisseite(ausflug):
    assert set(rechte.leser(ausflug["infos"])) == {ausflug["max"], ausflug["vera"]}


def test_ohne_zuordnung_nur_anhaenge_ohne_kreis(ausflug):
    assert [a.dateiname for a in Seite.objects.get(pk=ausflug["einladung"].pk).dateien()] == ["programm.pdf"]


# ------------------------------------------------------------------ Ansichten

def test_seite_zeigt_eingeschraenkte_anhaenge_nur_im_kreis(client, ausflug):
    url = ausflug["einladung"].get_absolute_url()
    client.force_login(ausflug["mia"])
    html = client.get(url).content.decode()
    assert "programm.pdf" in html and "telefonliste" not in html
    assert client.get(ausflug["liste"].get_absolute_url()).status_code == 404
    client.force_login(ausflug["max"])
    html = client.get(url).content.decode()
    assert "telefonliste.pdf" in html and "nur Kreis Ausflug 2027" in html
    r = client.get(ausflug["liste"].get_absolute_url())
    assert r.status_code == 200 and b"geheim" in b"".join(r.streaming_content)


def test_kreisseite_fuer_andere_nicht_vorhanden(client, ausflug):
    client.force_login(ausflug["mia"])
    assert client.get(ausflug["infos"].get_absolute_url()).status_code == 404
    assert "Infos für Mitfahrende" not in client.get(reverse("startseite")).content.decode()
    client.force_login(ausflug["max"])
    assert client.get(ausflug["infos"].get_absolute_url()).status_code == 200
    html = client.get(reverse("startseite")).content.decode()
    assert "Infos für Mitfahrende" in html and "Kreis Ausflug 2027" in html


def test_startseite_zaehlt_nur_sichtbare_anhaenge(client, ausflug):
    client.force_login(ausflug["mia"])
    assert "1 Anhang" in client.get(reverse("startseite")).content.decode()
    client.force_login(ausflug["max"])
    assert "2 Anhänge" in client.get(reverse("startseite")).content.decode()


def test_eingeschraenktes_titelbild(client, ausflug):
    from tests.test_bilder import foto as jpeg
    kreis = ausflug["kreis"]
    geheim = Anhang.objects.create(seite=ausflug["einladung"], datei=jpeg("geheim.jpg"), kreis=kreis,
                                   titelbild=True)
    offen = Anhang.objects.create(seite=ausflug["einladung"], datei=jpeg("bus.jpg"))
    client.force_login(ausflug["mia"])
    html = client.get(ausflug["einladung"].get_absolute_url()).content.decode()
    assert offen.bild_url() in html and geheim.bild_url() not in html
    assert client.get(geheim.bild_url()).status_code == 404
    client.force_login(ausflug["max"])
    assert geheim.bild_url() in client.get(ausflug["einladung"].get_absolute_url()).content.decode()


def test_vorstand_setzt_kreis_beim_bearbeiten(client, ausflug):
    client.force_login(ausflug["vera"])
    s = ausflug["einladung"]
    url = reverse("seite_bearbeiten", args=[s.pk])
    html = client.get(url).content.decode()
    assert "Nur für Kreis" in html and "Ausflug 2027" in html
    daten = {"titel": s.titel, "datum": s.datum.isoformat(), "stufe": S(MITGLIEDER).pk,
             "kreis": ausflug["kreis"].pk, "inhalt": s.inhalt,
             "anhang-TOTAL_FORMS": "2", "anhang-INITIAL_FORMS": "2",
             "anhang-MIN_NUM_FORMS": "0", "anhang-MAX_NUM_FORMS": "1000",
             "anhang-0-id": ausflug["liste"].pk, "anhang-0-seite": s.pk, "anhang-0-bezeichnung": "",
             "anhang-0-kreis": "",
             "anhang-1-id": ausflug["programm"].pk, "anhang-1-seite": s.pk, "anhang-1-bezeichnung": "",
             "anhang-1-kreis": ausflug["kreis"].pk}
    r = client.post(url, daten)
    assert r.status_code == 302, r.content.decode()[:2000]
    s.refresh_from_db()
    assert s.kreis == ausflug["kreis"]
    assert Anhang.objects.get(pk=ausflug["liste"].pk).kreis is None
    assert Anhang.objects.get(pk=ausflug["programm"].pk).kreis == ausflug["kreis"]


def test_kreis_in_verwendung_nicht_loeschbar(ausflug):
    from django.db.models import ProtectedError
    with pytest.raises(ProtectedError):
        ausflug["kreis"].delete()


def test_kreise_in_der_verwaltung(client, ausflug):
    client.force_login(ausflug["vera"])
    html = client.get(reverse("admin:seiten_kreis_change", args=[ausflug["kreis"].pk])).content.decode()
    assert "Infos für Mitfahrende" in html and "telefonliste.pdf" in html
    client.force_login(ausflug["mia"])
    assert client.get(reverse("admin:seiten_kreis_changelist")).status_code in (302, 403, 404)


def test_verlauf_haelt_personen_fest(ausflug):
    ausflug["kreis"].personen.add(ausflug["mia"])
    assert ausflug["kreis"].history.count() >= 1


# ------------------------------------------------------------------ Newsletter

def test_newsletter_einladung_anhaenge_je_person(ausflug, settings):
    settings.FV_BASIS_URL = "https://verein.example"
    v = newsletter.versand_anlegen(ausflug["einladung"], ausflug["vera"], modus="link", ankuendigung="",
                                   mit_anhaengen=True, stufen=[S(MITGLIEDER), S(VORSTAND)], ohne_stufe=False)
    mails = {e.user.username: newsletter.baue_mail(v, e) for e in v.empfaenge.select_related("user")}
    namen = lambda m: {a[0] for a in m.attachments}  # noqa: E731
    assert namen(mails["max"]) == {"programm.pdf", "telefonliste.pdf"}
    assert namen(mails["mia"]) == {"programm.pdf"}
    assert "telefonliste" not in mails["mia"].body


def test_newsletter_kreisseite_nur_an_den_kreis(ausflug):
    v = newsletter.versand_anlegen(ausflug["infos"], ausflug["vera"], modus="link", ankuendigung="",
                                   mit_anhaengen=False, stufen=[S(MITGLIEDER), S(VORSTAND)], ohne_stufe=False)
    assert set(v.empfaenge.exclude(stufe="Probe").values_list("user__username", flat=True)) == {"max"}


def test_newsletter_an_kreis(ausflug):
    v = newsletter.versand_anlegen(ausflug["einladung"], ausflug["vera"], modus="link", ankuendigung="",
                                   mit_anhaengen=False, stufen=[], ohne_stufe=False,
                                   kreise=[ausflug["kreis"]])
    e = v.empfaenge.exclude(stufe="Probe").get()
    assert e.user == ausflug["max"] and e.stufe == "Kreis Ausflug 2027"
    assert list(v.kreise.all()) == [ausflug["kreis"]]


def test_newsletter_formular_mit_kreis(client, ausflug):
    client.force_login(ausflug["vera"])
    url = reverse("newsletter_neu", args=[ausflug["infos"].pk])
    html = client.get(url).content.decode()
    assert "nur Kreis Ausflug 2027" in html and "An Kreise" in html
    r = client.post(url, {"modus": "link", "ankuendigung": "", "kreise": [ausflug["kreis"].pk]})
    assert r.status_code == 302
    assert Empfang.objects.exclude(stufe="Probe").get().user == ausflug["max"]
    r = client.post(url, {"modus": "link", "ankuendigung": ""})
    assert "mindestens eine Stufe oder einen Kreis" in r.content.decode()


# ------------------------------------------------------------------ Verteiler

def test_verteiler_mit_kreis(ausflug, settings):
    settings.FV_MAIL_DOMAIN = "verein.example"
    v = Verteiler.objects.create(adresse="ausflug@verein.example")
    v.kreise.add(ausflug["kreis"])
    assert mailmodul.verteiler_empfaenger(v) == ["max@extern.example"]
    Profil.objects.create(user=ausflug["max"], vereins_email="max@verein.example")
    assert "ausflug@verein.example" in mailmodul.erlaubte_absender(ausflug["max"])


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Sichten gibt es nur in PostgreSQL")
def test_sichten_mit_kreisen(ausflug):
    Profil.objects.create(user=ausflug["max"], vereins_email="max@verein.example")
    v = Verteiler.objects.create(adresse="ausflug@verein.example", archiv=True)
    v.kreise.add(ausflug["kreis"])

    def sicht(name):
        with connection.cursor() as c:
            c.execute(f"SELECT * FROM {name}")
            return {tuple(z) for z in c.fetchall()}

    assert sicht("exim_verteiler") == mailmodul.exim_verteiler()
    assert sicht("exim_absender") == mailmodul.exim_absender()
    assert sicht("dovecot_archiv_leser") == mailmodul.archiv_leser_alle()
    assert ("ausflug@verein.example", "max@extern.example") in mailmodul.exim_verteiler()

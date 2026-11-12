"""Name und feste Texte der Webseite: einstellbar statt im Quellcode."""

import pytest
from django.contrib.auth.models import Group, User
from django.core import mail
from django.urls import reverse

from seiten import konto
from seiten.models import Webseite

pytestmark = pytest.mark.django_db


@pytest.fixture
def anders():
    """Ein anderer Verein übernimmt die Anwendung."""
    w = Webseite.aktuell()
    w.name, w.slogan, w.inhaber = "Schachclub Musterstadt", "", "Schachclub Musterstadt 1920 e. V."
    w.ansprechpartner, w.unterschrift = "die Geschäftsstelle", "Ihre Geschäftsstelle"
    w.save()
    return w


def test_bisherige_vereinstexte_uebernommen(client):
    w = Webseite.aktuell()
    assert w.name == "Förderverein KF/JF Kreuzau" and w.unterschrift == "Der Vorstand"
    html = client.get(reverse("startseite")).content.decode()
    assert "Förderverein KF/JF Kreuzau" in html
    assert "Die Unterstützung der Jugendarbeit in der Feuerwehr Kreuzau" in html
    assert "Förderverein der Kinder- und Jugendfeuerwehr Kreuzau" in html


def test_immer_genau_ein_eintrag():
    Webseite(name="Zweiter").save()
    assert Webseite.objects.count() == 1 and Webseite.aktuell().name == "Zweiter"


def test_texte_erscheinen_ueberall(client, anders):
    html = client.get(reverse("startseite")).content.decode()
    assert "<title>Schachclub Musterstadt</title>" in html
    assert "Schachclub Musterstadt 1920 e. V." in html
    assert "Förderverein" not in html and 'class="slogan"' not in html
    login = client.get(reverse("account_login")).content.decode()
    assert "– Schachclub Musterstadt" in login and "wenden Sie sich bitte an die Geschäftsstelle" in login


def test_einladung_nutzt_einstellungen(anders, settings):
    settings.DEFAULT_FROM_EMAIL = "webmaster@example.org"
    u = User.objects.create_user("anna", "anna@example.org", first_name="Anna")
    konto.sende_einladung(u)
    m = mail.outbox[-1]
    assert m.subject == "[Schachclub Musterstadt] Einladung zur Webseite"
    assert m.from_email == "Schachclub Musterstadt <webmaster@example.org>"
    assert "„Schachclub Musterstadt“" in m.body and m.body.rstrip().endswith("Ihre Geschäftsstelle")
    assert "Förderverein" not in m.body and "Vorstand" not in m.body


def test_absender_mit_eigenem_namen_bleibt(settings):
    settings.DEFAULT_FROM_EMAIL = "Webmaster <webmaster@example.org>"
    assert konto.absender() == "Webmaster <webmaster@example.org>"


def test_allauth_mails_und_zwei_faktor_nutzen_namen(client, anders, settings):
    settings.DEFAULT_FROM_EMAIL = "webmaster@example.org"
    User.objects.create_user("anna", "anna@example.org", "pw")
    client.post(reverse("account_reset_password"), {"email": "anna@example.org"})
    m = mail.outbox[-1]
    assert m.subject.startswith("[Schachclub Musterstadt] ")
    assert m.from_email == "Schachclub Musterstadt <webmaster@example.org>"
    assert konto.MfaAdapter().get_totp_issuer() == "Schachclub Musterstadt"


def test_verwaltungskopf_zeigt_namen(client, anders):
    client.force_login(User.objects.create_superuser("root", "root@example.org", "pw"))
    html = client.get(reverse("admin:index")).content.decode()
    assert "Schachclub Musterstadt – Verwaltung" in html


def test_einstellungen_nur_fuer_administratoren(client):
    vera = User.objects.create_user("vera", "vera@example.org", "pw")
    vera.groups.add(Group.objects.get(name="Vorstand"))
    client.force_login(vera)
    assert client.get(reverse("admin:seiten_webseite_change", args=[1])).status_code == 403

    client.force_login(User.objects.create_superuser("root", "root@example.org", "pw"))
    r = client.get(reverse("admin:seiten_webseite_changelist"))
    assert r.status_code == 302 and r["Location"].endswith("/seiten/webseite/1/change/")
    r = client.post(reverse("admin:seiten_webseite_change", args=[1]), {
        "name": "Neu", "slogan": "", "inhaber": "", "ansprechpartner": "uns",
        "unterschrift": "Wir"})
    assert r.status_code == 302 and Webseite.aktuell().name == "Neu"
    assert client.get(reverse("admin:seiten_webseite_add")).status_code == 403


def test_fusszeile_verlinkt_quellcode(client, settings):
    """AGPL § 13: Nutzer der Webseite erhalten Zugang zum Quellcode."""
    settings.FV_QUELLCODE_URL = "https://example.org/quellcode"
    html = client.get("/").content.decode()
    assert '<a href="https://example.org/quellcode" rel="license">Quellcode (AGPL)</a>' in html


def test_fusszeile_verlinkt_impressum_datenschutz_und_ueber(client):
    from seiten.models import Seite
    web = Webseite.aktuell()
    assert "Impressum" not in client.get("/").content.decode()
    web.impressum = Seite.objects.create(titel="Impressum", inhalt="<p>Verein</p>")
    web.datenschutz = Seite.objects.create(titel="Datenschutzerklärung", inhalt="<p>DSGVO</p>")
    web.save()
    html = client.get("/").content.decode()
    assert f'href="{web.impressum.get_absolute_url()}">Impressum</a>' in html
    assert f'href="{web.datenschutz.get_absolute_url()}">Datenschutz</a>' in html
    assert f'href="{reverse("ueber")}">Über diese Webseite</a>' in html


def test_impressum_nur_oeffentliche_seiten():
    from seiten.models import Seite, Stufe
    from django.forms import modelform_factory
    oeffentlich = Seite.objects.create(titel="Impressum")
    intern = Seite.objects.create(titel="Intern", stufe=Stufe.objects.get(name="Mitglieder"))
    auswahl = set(modelform_factory(Webseite, fields=["impressum"])().fields["impressum"].queryset)
    assert oeffentlich in auswahl and intern not in auswahl


def test_ueber_diese_webseite_mit_lizenzhinweisen(client, settings):
    settings.FV_QUELLCODE_URL = "https://example.org/quellcode"
    html = client.get(reverse("ueber")).content.decode()
    for text in ("Copyright © 2026 Michael Bramer", "GNU Affero General Public License",
                 "ohne jede Gewährleistung", "https://example.org/quellcode", "TinyMCE",
                 "Creative Commons"):
        assert text in html


def test_lizenztexte_werden_ausgeliefert(client):
    r = client.get(reverse("lizenz_programm"))
    assert r.status_code == 200 and "GNU AFFERO GENERAL PUBLIC LICENSE" in r.content.decode()
    r = client.get(reverse("lizenz_doku"))
    assert r.status_code == 200 and "Attribution-ShareAlike 4.0" in r.content.decode()

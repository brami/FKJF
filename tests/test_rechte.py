"""Tests der Rechteprüfung.

Jede Kombination aus Benutzerart und Sichtbarkeit einer Seite wird für
Seitenansicht, Startseite und Anhang-Download geprüft.
"""

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.urls import reverse

from seiten import rechte
from seiten.models import Anhang, Seite
from seiten.stufen import Stufe

pytestmark = pytest.mark.django_db

# Benutzerart -> höchste Stufe, die er sehen darf
BENUTZERARTEN = {
    "anonym": Stufe.OEFFENTLICH,
    "ohne_gruppe": Stufe.OEFFENTLICH,
    "foerdermitglied": Stufe.FOERDERMITGLIEDER,
    "mitglied": Stufe.MITGLIEDER,
    "vorstand": Stufe.VORSTAND,
    "superuser": Stufe.VORSTAND,
    "deaktiviert": Stufe.OEFFENTLICH,  # war Vorstand, Konto deaktiviert
}
GRUPPE = {
    "foerdermitglied": "Fördermitglieder",
    "mitglied": "Mitglieder",
    "vorstand": "Vorstand",
    "deaktiviert": "Vorstand",
}


def benutzer(art):
    if art == "anonym":
        return None
    if art == "superuser":
        return User.objects.create_superuser(art, f"{art}@example.org", "pw")
    u = User.objects.create_user(art, f"{art}@example.org", "pw",
                                 is_active=(art != "deaktiviert"))
    if art in GRUPPE:
        u.groups.add(Group.objects.get(name=GRUPPE[art]))
    return u


@pytest.fixture
def seiten():
    erg = {}
    for stufe in Stufe:
        s = Seite.objects.create(titel=f"Seite {stufe.label}", stufe=stufe,
                                 inhalt=f"<p>Inhalt {stufe.label}</p>")
        a = Anhang(seite=s, bezeichnung=f"Anhang {stufe.label}")
        a.datei.save("einladung.pdf", ContentFile(b"%PDF-1.4 test"), save=False)
        a.save()
        erg[stufe] = (s, a)
    return erg


def client_fuer(client, user):
    if user is not None:
        client.force_login(user)
    return client


@pytest.mark.parametrize("art,max_stufe", BENUTZERARTEN.items())
def test_stufe_von(art, max_stufe):
    u = benutzer(art)
    assert rechte.stufe_von(u) == max_stufe


@pytest.mark.parametrize("art,max_stufe", BENUTZERARTEN.items())
@pytest.mark.parametrize("stufe", list(Stufe))
def test_seite_und_anhang(client, seiten, art, max_stufe, stufe):
    u = benutzer(art)
    c = client_fuer(client, u)
    seite, anhang = seiten[stufe]
    erlaubt = max_stufe >= stufe

    r_seite = c.get(reverse("seite", args=[seite.pk]))
    r_anhang = c.get(reverse("anhang", args=[anhang.pk]))

    if erlaubt:
        assert r_seite.status_code == 200
        assert seite.titel in r_seite.content.decode()
        assert r_anhang.status_code == 200
        assert b"".join(r_anhang.streaming_content) == b"%PDF-1.4 test"
        assert 'filename="einladung.pdf"' in r_anhang["Content-Disposition"]
    elif u is None or not u.is_active:
        # Nicht angemeldet (deaktivierte Konten können sich nicht anmelden)
        assert r_seite.status_code == 302 and "/anmelden/" in r_seite["Location"]
        assert r_anhang.status_code == 302 and "/anmelden/" in r_anhang["Location"]
    else:
        # Angemeldet ohne Recht: 404, verrät nicht, dass es die Seite gibt
        assert r_seite.status_code == 404
        assert r_anhang.status_code == 404


@pytest.mark.parametrize("art,max_stufe", BENUTZERARTEN.items())
def test_startseite_zeigt_nur_sichtbare(client, seiten, art, max_stufe):
    c = client_fuer(client, benutzer(art))
    html = c.get(reverse("startseite")).content.decode()
    for stufe, (seite, _) in seiten.items():
        assert (seite.titel in html) == (max_stufe >= stufe), (art, stufe)


def test_mehrere_gruppen_hoechste_zaehlt():
    u = benutzer("foerdermitglied")
    u.groups.add(Group.objects.get(name="Mitglieder"))
    assert rechte.stufe_von(u) == Stufe.MITGLIEDER


def test_startseite_nach_datum_absteigend(client):
    from datetime import date
    Seite.objects.create(titel="Alt", stufe=Stufe.OEFFENTLICH, datum=date(2025, 1, 1))
    Seite.objects.create(titel="Neu", stufe=Stufe.OEFFENTLICH, datum=date(2026, 1, 1))
    html = client.get(reverse("startseite")).content.decode()
    assert html.index("Neu") < html.index("Alt")


@pytest.mark.parametrize("stufe,erwartet", [
    (Stufe.OEFFENTLICH, {"ohne_gruppe", "foerdermitglied", "mitglied", "vorstand", "superuser"}),
    (Stufe.FOERDERMITGLIEDER, {"foerdermitglied", "mitglied", "vorstand", "superuser"}),
    (Stufe.MITGLIEDER, {"mitglied", "vorstand", "superuser"}),
    (Stufe.VORSTAND, {"vorstand", "superuser"}),
])
def test_newsletter_empfaenger(stufe, erwartet):
    for art in BENUTZERARTEN:
        benutzer(art)
    ohne_mail = User.objects.create_user("ohnemail", "", "pw")
    ohne_mail.groups.add(Group.objects.get(name="Mitglieder"))

    seite = Seite.objects.create(titel="Einladung", stufe=stufe)
    mit, ohne = rechte.newsletter_empfaenger(seite)

    assert set(mit.values_list("username", flat=True)) == erwartet
    if stufe <= Stufe.MITGLIEDER:
        assert list(ohne.values_list("username", flat=True)) == ["ohnemail"]
    else:
        assert not ohne.exists()


def test_benutzer_in_mehreren_gruppen_nur_einmal_empfaenger():
    u = benutzer("vorstand")
    u.groups.add(Group.objects.get(name="Mitglieder"))
    seite = Seite.objects.create(titel="Info", stufe=Stufe.FOERDERMITGLIEDER)
    mit, _ = rechte.newsletter_empfaenger(seite)
    assert list(mit.values_list("username", flat=True)) == ["vorstand"]


@pytest.mark.parametrize("art,erlaubt", [
    ("anonym", False), ("ohne_gruppe", False), ("foerdermitglied", False),
    ("mitglied", False), ("vorstand", True), ("superuser", True), ("deaktiviert", False),
])
def test_bearbeiten_nur_vorstand(art, erlaubt):
    assert rechte.darf_bearbeiten(benutzer(art)) == erlaubt


@pytest.mark.parametrize("art,status", [
    ("mitglied", 403),       # is_staff, aber nicht im Vorstand
    ("vorstand", 200),
])
def test_verwaltung_nur_vorstand(client, art, status):
    u = benutzer(art)
    u.is_staff = True
    u.save()
    client.force_login(u)
    r = client.get(reverse("admin:seiten_seite_changelist"))
    assert r.status_code == status

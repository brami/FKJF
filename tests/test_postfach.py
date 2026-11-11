"""Tests: Vereinsadresse (Postfach), Argon2 für Dovecot, Zustellung der Vereinsmails."""

import re

import nacl.exceptions
import nacl.pwhash
import pytest
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import Group, User
from django.core import mail
from django.db import connection
from django.test import override_settings
from django.urls import reverse

import config.settings as produktiv
from seiten.models import Profil, profil_von, zustelladresse

pytestmark = pytest.mark.django_db

ARGON2 = ["seiten.passwort.Argon2DovecotHasher", "django.contrib.auth.hashers.PBKDF2PasswordHasher"]
PW = "Ein-gutes-Passwort-2026"


def konto(name, vereins_email=None, gruppe="Vorstand", **kw):
    u = User.objects.create_user(name, f"{name}@privat.example", PW, **kw)
    u.groups.add(Group.objects.get(name=gruppe))
    if vereins_email:
        Profil.objects.create(user=u, vereins_email=vereins_email)
    return u


def dovecot_form(django_hash: str) -> str:
    """So, wie die Datenbank-Sicht den Hash an Dovecot liefert."""
    return "{ARGON2ID}" + django_hash[len("argon2"):]


# --- Argon2 im Dovecot-Format ---------------------------------------------------

def test_produktiv_wird_argon2_fuer_dovecot_verwendet():
    assert produktiv.PASSWORD_HASHERS[0] == "seiten.passwort.Argon2DovecotHasher"


@override_settings(PASSWORD_HASHERS=ARGON2)
def test_hash_format_wie_dovecot():
    h = make_password(PW)
    assert h.startswith("argon2$argon2id$v=19$m=65536,t=3,p=1$")
    assert check_password(PW, h)


@override_settings(PASSWORD_HASHERS=ARGON2)
def test_hash_mit_libsodium_pruefbar():
    """libsodium ist die Bibliothek, mit der Dovecot ARGON2ID prüft."""
    h = dovecot_form(make_password(PW))
    assert h.startswith("{ARGON2ID}$argon2id$")
    phc = h[len("{ARGON2ID}"):].encode()
    assert nacl.pwhash.argon2id.verify(phc, PW.encode())
    with pytest.raises(nacl.exceptions.InvalidkeyError):
        nacl.pwhash.argon2id.verify(phc, b"falsch")


@override_settings(PASSWORD_HASHERS=ARGON2)
def test_alter_hash_wird_bei_anmeldung_umgestellt(client):
    u = konto("vera")
    u.password = make_password(PW, hasher="pbkdf2_sha256")
    u.save()
    client.post(reverse("account_login"), {"login": "vera", "password": PW})
    u.refresh_from_db()
    assert u.password.startswith("argon2$argon2id$") and "p=1$" in u.password


# --- Anmelden und „Passwort vergessen“ ------------------------------------------

@pytest.mark.parametrize("login", ["vera.vorstand@verein.example", "Vera.Vorstand@VEREIN.example"])
def test_anmelden_mit_vereinsadresse(client, login):
    konto("vera", "vera.vorstand@verein.example")
    r = client.post(reverse("account_login"), {"login": login, "password": PW})
    assert r.status_code == 302
    assert client.get(reverse("konto")).status_code == 200


def test_vereinsadresse_falsches_passwort_oder_deaktiviert(client):
    u = konto("vera", "vera.vorstand@verein.example")
    client.post(reverse("account_login"), {"login": "vera.vorstand@verein.example", "password": "falsch"})
    assert client.get(reverse("konto")).status_code == 302
    u.is_active = False
    u.save()
    client.post(reverse("account_login"), {"login": "vera.vorstand@verein.example", "password": PW})
    assert client.get(reverse("konto")).status_code == 302


def test_anmelden_mit_externer_adresse_weiterhin(client):
    konto("vera", "vera.vorstand@verein.example")
    client.post(reverse("account_login"), {"login": "vera@privat.example", "password": PW})
    assert client.get(reverse("konto")).status_code == 200


def test_passwort_vergessen_mit_vereinsadresse_geht_an_externe_adresse(client):
    konto("vera", "vera.vorstand@verein.example")
    client.post(reverse("account_reset_password"), {"email": "vera.vorstand@verein.example"})
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["vera@privat.example"]


def test_passwort_vergessen_geht_nie_an_vereinsadresse(client):
    konto("vera", "vera.vorstand@verein.example")
    for eingabe in ["vera@privat.example", "VERA.VORSTAND@verein.example"]:
        client.post(reverse("account_reset_password"), {"email": eingabe})
    assert [m.to for m in mail.outbox] == [["vera@privat.example"]] * 2


# --- Passwortregeln --------------------------------------------------------------

def test_postfach_braucht_zwoelf_zeichen():
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    mit = konto("vera", "vera.vorstand@verein.example")
    ohne = konto("max", gruppe="Mitglieder")
    validate_password("Kurz-2026x", ohne)              # 10 Zeichen: ohne Postfach erlaubt
    with pytest.raises(ValidationError, match="Postfach"):
        validate_password("Kurz-2026x", mit)
    validate_password("Laenger-2026x", mit)


# --- Zustellung der Vereinsmails --------------------------------------------------

def test_zustelladresse():
    ohne = konto("max", gruppe="Mitglieder")
    vera = konto("vera", "vera.vorstand@verein.example")
    assert zustelladresse(ohne) == "max@privat.example"
    assert zustelladresse(vera) == "vera@privat.example"          # Standard: extern
    p = profil_von(vera)
    p.zustellung = Profil.Zustellung.VEREIN
    p.save()
    vera.refresh_from_db()
    assert zustelladresse(vera) == "vera.vorstand@verein.example"


def test_ohne_vereinsadresse_immer_extern():
    u = konto("max", gruppe="Mitglieder")
    p = Profil.objects.create(user=u, zustellung=Profil.Zustellung.VEREIN)
    assert p.zustellung == Profil.Zustellung.EXTERN


def test_zustellung_selbst_waehlen(client):
    vera = konto("vera", "vera.vorstand@verein.example")
    client.force_login(vera)
    html = client.get(reverse("konto")).content.decode()
    assert "vera.vorstand@verein.example" in html and 'name="zustellung"' in html
    client.post(reverse("konto"), {"zustellung": "verein"})
    assert Profil.objects.get(user=vera).zustellung == "verein"


def test_ohne_postfach_keine_auswahl(client):
    client.force_login(konto("max", gruppe="Mitglieder"))
    assert 'name="zustellung"' not in client.get(reverse("konto")).content.decode()


# --- Verwaltung -------------------------------------------------------------------

@pytest.fixture
def vorstand_client(client):
    client.force_login(konto("chef"))
    return client


def aenderung(user, **werte):
    daten = {"username": user.username, "email": user.email, "is_active": "on",
             "groups": [g.pk for g in user.groups.all()],
             "profil-TOTAL_FORMS": "1", "profil-INITIAL_FORMS": "0",
             "profil-MIN_NUM_FORMS": "0", "profil-MAX_NUM_FORMS": "1",
             "profil-0-vereins_email": "", "profil-0-zustellung": "extern"}
    daten.update(werte)
    return daten


def test_vorstand_traegt_vereinsadresse_ein(vorstand_client):
    max_ = konto("max", gruppe="Mitglieder")
    r = vorstand_client.post(reverse("admin:auth_user_change", args=[max_.pk]),
                             aenderung(max_, **{"profil-0-vereins_email": "Max.Muster@Verein.example"}))
    assert r.status_code == 302
    assert Profil.objects.get(user=max_).vereins_email == "max.muster@verein.example"


def test_vereinsadresse_darf_keine_externe_adresse_sein(vorstand_client):
    konto("anna", gruppe="Mitglieder")
    max_ = konto("max", gruppe="Mitglieder")
    r = vorstand_client.post(reverse("admin:auth_user_change", args=[max_.pk]),
                             aenderung(max_, **{"profil-0-vereins_email": "anna@privat.example"}))
    assert r.status_code == 200 and "bereits als externe Adresse" in r.content.decode()


def test_externe_adresse_darf_keine_vereinsadresse_sein(vorstand_client):
    konto("vera", "vera.vorstand@verein.example")
    max_ = konto("max", gruppe="Mitglieder")
    r = vorstand_client.post(reverse("admin:auth_user_change", args=[max_.pk]),
                             aenderung(max_, email="vera.vorstand@verein.example"))
    assert r.status_code == 200 and "bereits zu einem anderen Konto" in r.content.decode()


# --- Datenbank-Sicht für Dovecot (nur PostgreSQL) ---------------------------------

@pytest.mark.skipif(connection.vendor != "postgresql", reason="Sicht gibt es nur in PostgreSQL")
@override_settings(PASSWORD_HASHERS=ARGON2)
def test_dovecot_sicht():
    vera = konto("vera", "Vera.Vorstand@verein.example")
    konto("max", gruppe="Mitglieder")                         # ohne Postfach
    alt = konto("otto", "otto@verein.example")
    alt.password = make_password(PW, hasher="pbkdf2_sha256")  # noch kein Argon2
    alt.save()
    with connection.cursor() as c:
        c.execute("SELECT benutzer, passwort, aktiv FROM dovecot_benutzer ORDER BY benutzer")
        zeilen = c.fetchall()
    assert [z[0] for z in zeilen] == ["vera.vorstand@verein.example"]
    benutzer, passwort, aktiv = zeilen[0]
    assert aktiv is True and passwort == dovecot_form(vera.password)
    assert nacl.pwhash.argon2id.verify(passwort[len("{ARGON2ID}"):].encode(), PW.encode())
    vera.is_active = False
    vera.save()
    with connection.cursor() as c:
        c.execute("SELECT aktiv FROM dovecot_benutzer")
        assert c.fetchone()[0] is False

"""Tests der Anmeldung: Konten, Einladung, Passwort vergessen, Zwei-Faktor-Pflicht,
Benutzerverwaltung durch den Vorstand."""

import re

import pytest
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.contrib.auth.models import Group, User
from django.core import mail
from django.urls import reverse

pytestmark = pytest.mark.django_db


def konto(name, gruppe=None, **kw):
    u = User.objects.create_user(name, f"{name}@example.org", "Gutes-Passwort-2026", **kw)
    if gruppe:
        u.groups.add(Group.objects.get(name=gruppe))
    return u


# --- Anmeldung ---------------------------------------------------------------

def test_keine_registrierung(client):
    html = client.get("/konto/signup/").content.decode()
    assert 'name="password1"' not in html


@pytest.mark.parametrize("login", ["anna", "anna@example.org", "ANNA@example.org"])
def test_anmelden_mit_benutzername_oder_email(client, login):
    konto("anna", "Mitglieder")
    r = client.post(reverse("account_login"), {"login": login, "password": "Gutes-Passwort-2026"})
    assert r.status_code == 302
    assert client.get(reverse("konto")).status_code == 200


def test_falsches_passwort(client):
    konto("anna")
    r = client.post(reverse("account_login"), {"login": "anna", "password": "falsch"})
    assert r.status_code == 200
    assert client.get(reverse("konto")).status_code == 302  # nicht angemeldet


def test_deaktiviertes_konto_kann_sich_nicht_anmelden(client):
    konto("anna", is_active=False)
    client.post(reverse("account_login"), {"login": "anna", "password": "Gutes-Passwort-2026"})
    assert client.get(reverse("konto")).status_code == 302


def test_alte_anmeldeadresse_leitet_weiter(client):
    r = client.get("/anmelden/?next=/seite/1/")
    assert r.status_code == 302 and r["Location"] == "/konto/login/?next=/seite/1/"


def test_email_verwaltung_gesperrt(client):
    client.force_login(konto("anna"))
    r = client.get("/konto/email/")
    assert r.status_code == 302 and r["Location"] == reverse("konto")


def test_passwort_vergessen(client):
    konto("anna")
    client.post(reverse("account_reset_password"), {"email": "anna@example.org"})
    assert len(mail.outbox) == 1
    pfad = re.search(r"https?://[^/\s]+(/konto/password/reset/key/\S+)", mail.outbox[0].body).group(1)
    form = client.get(pfad)["Location"]
    client.post(form, {"password1": "Neues-Passwort-2026", "password2": "Neues-Passwort-2026"})
    assert User.objects.get(username="anna").check_password("Neues-Passwort-2026")


def test_kontoseite(client):
    client.force_login(konto("anna", "Mitglieder", first_name="Anna"))
    html = client.get(reverse("konto")).content.decode()
    assert "anna@example.org" in html and "Mitglieder" in html and "Passwort ändern" in html


# --- Zwei-Faktor-Pflicht -----------------------------------------------------

@pytest.fixture
def pflicht(settings):
    settings.FV_ZWEI_FAKTOR_PFLICHT = True


def test_vorstand_muss_zwei_faktor_einrichten(client, pflicht):
    konto("vera", "Vorstand")
    r = client.post(reverse("account_login"), {"login": "vera", "password": "Gutes-Passwort-2026"})
    assert r.status_code == 302
    for url in ["/", reverse("seite_neu"), reverse("admin:index")]:
        r = client.get(url)
        assert r.status_code == 302 and r["Location"] == reverse("mfa_activate_totp"), url
    # Einrichtung, Konto und Abmelden bleiben erreichbar
    assert client.get(reverse("mfa_activate_totp")).status_code == 200
    assert client.get(reverse("konto")).status_code == 200


def test_mitglied_ohne_zwei_faktor_pflicht(client, pflicht):
    client.force_login(konto("max", "Mitglieder"))
    assert client.get("/").status_code == 200


def test_vorstand_mit_zwei_faktor_hat_zugang(client, pflicht):
    vera = konto("vera", "Vorstand")
    TOTP.activate(vera, generate_totp_secret())
    client.force_login(vera)
    assert client.get("/").status_code == 200
    assert client.get(reverse("seite_neu")).status_code == 200


def test_anmeldung_fragt_zweiten_faktor_ab(client, pflicht):
    vera = konto("vera", "Vorstand")
    TOTP.activate(vera, generate_totp_secret())
    r = client.post(reverse("account_login"), {"login": "vera", "password": "Gutes-Passwort-2026"})
    assert r.status_code == 302 and r["Location"] == reverse("mfa_authenticate")
    assert client.get(reverse("konto")).status_code == 302  # noch nicht angemeldet


def test_verwaltung_meldet_ueber_normale_anmeldung_an(client):
    r = client.get(reverse("admin:login") + "?next=/verwaltung/")
    assert r.status_code == 302 and r["Location"].startswith("/konto/login/")


# --- Benutzerverwaltung durch den Vorstand -----------------------------------

@pytest.fixture
def vorstand_client(client):
    client.force_login(konto("vera", "Vorstand"))
    return client


def neuer_benutzer(**werte):
    daten = {"username": "neu.mitglied", "first_name": "Neu", "last_name": "Mitglied",
             "email": "neu@example.org",
             "groups": [Group.objects.get(name="Mitglieder").pk], "einladen": "on"}
    daten.update(werte)
    return daten


def test_vorstand_legt_benutzer_an_und_laedt_ein(vorstand_client):
    r = vorstand_client.post(reverse("admin:auth_user_add"), neuer_benutzer(), follow=True)
    assert r.status_code == 200
    u = User.objects.get(username="neu.mitglied")
    assert not u.has_usable_password()
    assert list(u.groups.values_list("name", flat=True)) == ["Mitglieder"]
    assert not u.is_staff and not u.is_superuser
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["neu@example.org"]
    assert "Einladung" in mail.outbox[0].subject
    # Mailversand ist im Test nicht "smtp": Link wird dem Vorstand angezeigt
    assert "/konto/password/reset/key/" in r.content.decode()


def test_einladungslink_funktioniert(client, vorstand_client):
    vorstand_client.post(reverse("admin:auth_user_add"), neuer_benutzer())
    pfad = re.search(r"https?://[^/\s]+(/konto/password/reset/key/\S+)", mail.outbox[0].body).group(1)
    vorstand_client.logout()
    form = client.get(pfad)["Location"]
    client.post(form, {"password1": "Mein-Passwort-2026", "password2": "Mein-Passwort-2026"})
    assert client.login(username="neu.mitglied", password="Mein-Passwort-2026")


def test_doppelte_email_wird_abgelehnt(vorstand_client):
    konto("anna")
    r = vorstand_client.post(reverse("admin:auth_user_add"), neuer_benutzer(email="ANNA@example.org"))
    assert r.status_code == 200 and "bereits zu einem anderen Konto" in r.content.decode()
    assert not User.objects.filter(username="neu.mitglied").exists()


def test_einladung_erneut_senden(vorstand_client):
    anna = konto("anna", "Mitglieder")
    vorstand_client.post(reverse("admin:auth_user_changelist"),
                         {"action": "einladung_senden", "_selected_action": [anna.pk]})
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["anna@example.org"]


def test_vorstand_kann_sich_nicht_zum_administrator_machen(vorstand_client):
    vera = User.objects.get(username="vera")
    url = reverse("admin:auth_user_change", args=[vera.pk])
    html = vorstand_client.get(url).content.decode()
    assert 'name="is_superuser"' not in html and 'name="is_staff"' not in html
    vorstand_client.post(url, {"username": "vera", "email": "vera@example.org", "is_active": "on",
                               "groups": [Group.objects.get(name="Vorstand").pk],
                               "is_superuser": "on", "is_staff": "on"})
    vera.refresh_from_db()
    assert not vera.is_superuser and not vera.is_staff


def test_vorstand_sieht_keine_administratorkonten(vorstand_client):
    admin = User.objects.create_superuser("admin", "admin@example.org", "pw")
    html = vorstand_client.get(reverse("admin:auth_user_changelist")).content.decode()
    assert "admin@example.org" not in html
    assert vorstand_client.get(reverse("admin:auth_user_change", args=[admin.pk])).status_code in (302, 404)


def test_vorstand_setzt_keine_fremden_passwoerter(vorstand_client):
    anna = konto("anna")
    r = vorstand_client.get(reverse("admin:auth_user_password_change", args=[anna.pk]))
    assert r.status_code == 403


def test_nur_die_drei_gruppen_waehlbar(vorstand_client):
    Group.objects.create(name="Sonstige")
    html = vorstand_client.get(reverse("admin:auth_user_add")).content.decode()
    assert "Sonstige" not in html and "Fördermitglieder" in html


def test_anmeldeseite_ohne_registrierungshinweis(client):
    html = client.get(reverse("account_login")).content.decode()
    assert "/konto/signup/" not in html and "Passwort vergessen" in html


def test_passwort_aendern_in_der_verwaltung_nutzt_normale_seite(vorstand_client):
    r = vorstand_client.get(reverse("admin:password_change"))
    assert r.status_code == 302 and r["Location"] == reverse("account_change_password")


def test_zwei_faktor_aendern_verlangt_spaeter_wieder_das_passwort(client, pflicht):
    """Nur direkt nach der Anmeldung entfällt die erneute Passwortabfrage."""
    import time
    vera = konto("vera", "Vorstand")
    TOTP.activate(vera, generate_totp_secret())
    client.force_login(vera)
    s = client.session
    s["account_authentication_methods_user"] = str(vera.pk)
    s["account_authentication_methods"] = [{"method": "password", "at": time.time() - 3600}]
    s.save()
    r = client.get(reverse("mfa_deactivate_totp"))
    assert r.status_code == 302 and "/konto/reauthenticate/" in r["Location"]

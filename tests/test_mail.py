"""Tests: Mail in der Webseite – Adressen, Aliase, Verteiler, Sperren, Abwesenheit,
Belegung, Löschen gesperrter Postfächer, Übersicht und Sichten für den Mailserver."""

import plistlib
from datetime import date, timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import Group, User
from django.core import mail as djmail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from seiten import mail
from seiten.models import (Abwesenheit, AdressSperre, Alias, Belegung, Profil, Stufe, Verteiler,
                           Webseite)

pytestmark = pytest.mark.django_db
PW = "Ein-gutes-Passwort-2026"
DOM = "verein.example"


@pytest.fixture(autouse=True)
def _domain(settings):
    settings.FV_MAIL_DOMAIN = DOM
    settings.FV_MAIL_SERVER = f"mail.{DOM}"


def konto(name, vereins_email=None, gruppe="Mitglieder", **kw):
    u = User.objects.create_user(name, f"{name}@privat.example", PW, first_name=name.title(), **kw)
    if gruppe:
        u.groups.add(Group.objects.get(name=gruppe))
    if vereins_email:
        Profil.objects.create(user=u, vereins_email=vereins_email)
    return u


def verteiler(adresse, stufen=(), personen=(), weitere="", **kw):
    v = Verteiler.objects.create(adresse=adresse, weitere_adressen=weitere, **kw)
    v.stufen.set([Stufe.objects.get(name=s) for s in stufen])
    v.personen.set(personen)
    return v


# --------------------------------------------------------- Adressen prüfen

def test_adresse_nur_einmal():
    max_ = konto("max", f"max@{DOM}")
    Alias.objects.create(user=max_, adresse=f"m@{DOM}")
    verteiler(f"vorstand@{DOM}")
    for belegt in (f"max@{DOM}", f"M@{DOM}", f"vorstand@{DOM}"):
        with pytest.raises(ValidationError):
            mail.adresse_pruefen(belegt)
    assert mail.adresse_pruefen(f"Neu@{DOM}") == f"neu@{DOM}"


def test_externe_adresse_kollidiert():
    User.objects.create_user("ext", f"ext@{DOM}", PW)
    with pytest.raises(ValidationError, match="externe Adresse"):
        mail.adresse_pruefen(f"ext@{DOM}")


def test_nur_vereinsdomain_und_kein_plus():
    with pytest.raises(ValidationError, match=f"@{DOM}"):
        mail.adresse_pruefen("max@anders.example")
    with pytest.raises(ValidationError, match="Plus"):
        mail.adresse_pruefen(f"max+test@{DOM}")


def test_gesperrte_adresse_nur_fuer_dieselbe_person():
    max_ = konto("max")
    mail.sperren(f"alt@{DOM}", max_)
    with pytest.raises(ValidationError, match="gesperrt"):
        mail.adresse_pruefen(f"alt@{DOM}", user=konto("anna"))
    assert mail.adresse_pruefen(f"alt@{DOM}", user=max_)
    # nach der Sperrfrist wieder frei
    AdressSperre.objects.update(frei_ab=date.today())
    assert mail.adresse_pruefen(f"alt@{DOM}", user=konto("eva"))


# --------------------------------------------- Adressänderung, Alias, Sperre

def test_geaenderte_vereinsadresse_wird_alias():
    max_ = konto("max", f"max.maier@{DOM}")
    p = max_.profil
    p.vereins_email = f"max.mueller@{DOM}"
    p.save()
    a = Alias.objects.get(adresse=f"max.maier@{DOM}")
    assert a.user == max_ and a.art == Alias.Art.AUTOMATISCH
    # zurück: Alias wird wieder Hauptadresse, ohne Sperre
    p.vereins_email = f"max.maier@{DOM}"
    p.save()
    assert not Alias.objects.filter(adresse=f"max.maier@{DOM}").exists()
    assert Alias.objects.filter(adresse=f"max.mueller@{DOM}", user=max_).exists()
    assert not AdressSperre.objects.filter(adresse=f"max.maier@{DOM}").exists()


def test_entfernte_adresse_und_alias_werden_gesperrt(settings):
    settings.FV_MAIL_SPERRFRIST_TAGE = 365
    max_ = konto("max", f"max@{DOM}")
    a = Alias.objects.create(user=max_, adresse=f"m@{DOM}")
    a.delete()
    sp = AdressSperre.objects.get(adresse=f"m@{DOM}")
    assert sp.user == max_ and sp.frei_ab == timezone.localdate() + timedelta(days=365)
    max_.profil.vereins_email = None
    max_.profil.save()
    assert AdressSperre.objects.filter(adresse=f"max@{DOM}", user=max_).exists()


def test_geaenderter_alias_und_verteiler_sperren_alte_adresse():
    a = Alias.objects.create(user=konto("max", f"max@{DOM}"), adresse=f"m@{DOM}")
    a.adresse = f"mm@{DOM}"
    a.save()
    v = verteiler(f"kasse@{DOM}")
    v.adresse = f"finanzen@{DOM}"
    v.save()
    assert set(AdressSperre.objects.values_list("adresse", flat=True)) == {f"m@{DOM}", f"kasse@{DOM}"}


def test_geloeschter_verteiler_wird_gesperrt():
    verteiler(f"kasse@{DOM}").delete()
    assert AdressSperre.objects.filter(adresse=f"kasse@{DOM}").exists()


def test_postfach_gesperrt_bei_deaktivierung_und_wieder_frei():
    max_ = konto("max", f"max@{DOM}")
    assert Profil.objects.get(user=max_).postfach_gesperrt_seit is None
    max_.is_active = False
    max_.save()
    p = Profil.objects.get(user=max_)
    assert p.hat_postfach and p.postfach_gesperrt_seit is not None
    max_.is_active = True
    max_.save()
    assert Profil.objects.get(user=max_).postfach_gesperrt_seit is None


# -------------------------------------------------------------- Verteiler

def test_verteiler_empfaenger_nach_stufe_person_und_weitere():
    vera = konto("vera", f"vera@{DOM}", gruppe="Vorstand")
    Profil.objects.filter(user=vera).update(zustellung=Profil.Zustellung.VEREIN)
    konto("valter", gruppe="Vorstand")
    konto("weg", gruppe="Vorstand", is_active=False)
    konto("mia", gruppe="Mitglieder")                   # andere Stufe: nicht dabei
    gast = konto("gast", gruppe=None)
    v = verteiler(f"vorstand@{DOM}", stufen=["Vorstand"], personen=[gast], weitere="Betreuung@Example.org")
    assert mail.verteiler_empfaenger(v) == sorted([
        f"vera@{DOM}", "valter@privat.example", "gast@privat.example", "betreuung@example.org"])
    v.aktiv = False
    v.save()
    assert mail.verteiler_empfaenger(v) == []


def test_erlaubte_absender():
    vera = konto("vera", f"vera@{DOM}", gruppe="Vorstand")
    Alias.objects.create(user=vera, adresse=f"v@{DOM}")
    verteiler(f"vorstand@{DOM}", stufen=["Vorstand"])
    verteiler(f"kasse@{DOM}", personen=[konto("kai", f"kai@{DOM}")])
    assert mail.erlaubte_absender(vera) == sorted([f"vera@{DOM}", f"v@{DOM}", f"vorstand@{DOM}"])
    assert mail.erlaubte_absender(konto("ohne")) == []


# ----------------------------------------------------------- Abwesenheit

def test_sieve_ohne_notiz_ist_leer():
    max_ = konto("max", f"max@{DOM}")
    assert "vacation" not in mail.sieve_skript(max_)


def test_sieve_mit_zeitraum_und_maskierung():
    max_ = konto("max", f"max@{DOM}")
    Alias.objects.create(user=max_, adresse=f"m@{DOM}")
    Abwesenheit.objects.create(user=max_, aktiv=True, von=date(2026, 12, 20), bis=date(2027, 1, 6),
                               betreff='Urlaub "Winter"', text="Bin weg.\nPfad C:\\temp")
    s = mail.sieve_skript(max_)
    assert 'require ["vacation", "date", "relational"];' in s
    assert 'currentdate :value "ge" "date" "2026-12-20"' in s
    assert 'currentdate :value "le" "date" "2027-01-06"' in s
    assert ':subject "Urlaub \\"Winter\\""' in s
    assert '"Bin weg.\nPfad C:\\\\temp"' in s
    assert f':addresses ["m@{DOM}", "max@{DOM}"]' in s
    assert ":days 7" in s


def test_sieve_ohne_zeitraum():
    max_ = konto("max", f"max@{DOM}")
    Abwesenheit.objects.create(user=max_, aktiv=True, text="Weg.")
    s = mail.sieve_skript(max_)
    assert 'require ["vacation"];' in s and "currentdate" not in s


def test_kommando_mail_sieve(tmp_path):
    max_ = konto("max", f"max@{DOM}")
    Abwesenheit.objects.create(user=max_, aktiv=True, text="Weg.")
    (tmp_path / "999.sieve").write_text("alt")
    out = StringIO()
    call_command("mail_sieve", "--ziel", str(tmp_path), stdout=out)
    assert "vacation" in (tmp_path / f"{max_.pk}.sieve").read_text()
    assert not (tmp_path / "999.sieve").exists()
    call_command("mail_sieve", "--ziel", str(tmp_path), stdout=out)
    assert "0 Sieve-Dateien aktualisiert" in out.getvalue()


def test_abwesenheit_im_konto(client):
    max_ = konto("max", f"max@{DOM}")
    client.force_login(max_)
    url = reverse("mail_abwesenheit")
    assert "Abwesenheitsnotiz" in client.get(url).content.decode()
    r = client.post(url, {"aktiv": "on", "von": "2026-12-20", "bis": "2026-12-01",
                          "betreff": "Urlaub", "text": "x"})
    assert "Das Ende liegt vor dem Beginn" in r.content.decode()
    r = client.post(url, {"aktiv": "on", "von": "", "bis": "", "betreff": "Urlaub", "text": ""})
    assert "Bitte einen Text" in r.content.decode()
    r = client.post(url, {"aktiv": "on", "von": "2026-12-20", "bis": "2027-01-06",
                          "betreff": "Urlaub", "text": "Bin weg."})
    assert r.status_code == 302
    assert Abwesenheit.objects.get(user=max_).bis == date(2027, 1, 6)


def test_abwesenheit_nur_mit_postfach(client):
    client.force_login(konto("ohne"))
    assert client.get(reverse("mail_abwesenheit")).status_code == 404
    assert client.get(reverse("mail_einrichtungsprofil")).status_code == 404


# -------------------------------------------------------------- Belegung

DOVEADM = (f"Username=max@{DOM} Quota name=User quota Type=STORAGE Value=1048576 Limit=5242880 %=20\n"
           f"Username=max@{DOM} Quota name=User quota Type=MESSAGE Value=1234 Limit=- %=0\n"
           f"Username=unbekannt@{DOM} Quota name=User quota Type=STORAGE Value=1 Limit=- %=0\n")


def test_belegung_einlesen():
    max_ = konto("max", f"max@{DOM}")
    assert mail.belegung_einlesen(DOVEADM) == 1
    b = Belegung.objects.get(user=max_)
    assert b.bytes == 1024**3 and b.grenze_bytes == 5 * 1024**3 and b.nachrichten == 1234
    assert b.prozent == 20


def test_belegung_kommando_liest_stdin(monkeypatch):
    max_ = konto("max", f"max@{DOM}")
    monkeypatch.setattr("sys.stdin", StringIO(DOVEADM))
    out = StringIO()
    call_command("mail_belegung", stdout=out)
    assert "1 Postfächer" in out.getvalue() and Belegung.objects.filter(user=max_).exists()


def test_kontoseite_zeigt_mail(client):
    max_ = konto("max", f"max@{DOM}")
    Alias.objects.create(user=max_, adresse=f"m@{DOM}")
    verteiler(f"mitglieder@{DOM}", stufen=["Mitglieder"])
    mail.belegung_einlesen(DOVEADM.replace("1048576", "4900000"))
    client.force_login(max_)
    html = client.get(reverse("konto")).content.decode()
    assert f"m@{DOM}" in html and f"mitglieder@{DOM}" in html
    assert "fast voll" in html and "<progress" in html
    assert "Einrichtungsprofil herunterladen" in html and f"mail.{DOM}, Port 993" in html


def test_kontoseite_ohne_postfach_ohne_mail(client):
    client.force_login(konto("ohne"))
    assert 'id="mail"' not in client.get(reverse("konto")).content.decode()


# ------------------------------------------------------ Apple-Profil

def test_einrichtungsprofil(client):
    max_ = konto("max", f"max@{DOM}")
    client.force_login(max_)
    r = client.get(reverse("mail_einrichtungsprofil"))
    assert r["Content-Type"] == "application/x-apple-aspen-config"
    plist = plistlib.loads(r.content)
    k = plist["PayloadContent"][0]
    assert k["EmailAddress"] == f"max@{DOM}" and k["IncomingMailServerHostName"] == f"mail.{DOM}"
    assert k["IncomingMailServerPortNumber"] == 993 and k["IncomingMailServerUseSSL"] is True
    assert "IncomingPassword" not in k and "OutgoingPassword" not in k   # Passwort nie im Profil
    # gleiche Kennungen bei erneutem Herunterladen (ersetzt statt verdoppelt)
    assert plistlib.loads(client.get(reverse("mail_einrichtungsprofil")).content)["PayloadUUID"] == \
        plist["PayloadUUID"]


# --------------------------------------------- Löschen gesperrter Postfächer

def test_vorwarnung_faellig_und_geloescht(settings):
    settings.FV_MAIL_LOESCHFRIST_TAGE = 90
    settings.FV_MAIL_VORWARNUNG_TAGE = 14
    Webseite.objects.update_or_create(pk=1, defaults={"antwort_an": "vorstand@privat.example"})
    max_ = konto("max", f"max@{DOM}")
    Alias.objects.create(user=max_, adresse=f"m@{DOM}")
    max_.is_active = False
    max_.save()
    jetzt = timezone.now()
    # noch nicht fällig
    Profil.objects.filter(user=max_).update(postfach_gesperrt_seit=jetzt - timedelta(days=70))
    assert mail.vorwarnen() == [] and not djmail.outbox
    # Vorwarnung nach 76 Tagen, nur einmal
    Profil.objects.filter(user=max_).update(postfach_gesperrt_seit=jetzt - timedelta(days=77))
    call_command("mail_aufraeumen", stdout=StringIO())
    assert len(djmail.outbox) == 1 and "Max" in djmail.outbox[0].body
    assert djmail.outbox[0].to == ["vorstand@privat.example"]
    call_command("mail_aufraeumen", stdout=StringIO())
    assert len(djmail.outbox) == 1
    out = StringIO()
    call_command("mail_aufraeumen", "--faellig", stdout=out)
    assert out.getvalue() == ""
    # fällig nach 90 Tagen
    Profil.objects.filter(user=max_).update(postfach_gesperrt_seit=jetzt - timedelta(days=91))
    out = StringIO()
    call_command("mail_aufraeumen", "--faellig", stdout=out)
    assert out.getvalue().split() == [str(max_.pk)]
    call_command("mail_aufraeumen", "--geloescht", str(max_.pk), stdout=StringIO())
    p = Profil.objects.get(user=max_)
    assert not p.hat_postfach and p.vereins_email is None and p.postfach_gesperrt_seit is None
    assert set(AdressSperre.objects.values_list("adresse", flat=True)) == {f"max@{DOM}", f"m@{DOM}"}
    assert "gelöscht" in djmail.outbox[-1].subject
    out = StringIO()
    call_command("mail_aufraeumen", "--faellig", stdout=out)
    assert out.getvalue() == ""


def test_geloescht_nur_wenn_faellig():
    from django.core.management.base import CommandError

    max_ = konto("max", f"max@{DOM}")
    with pytest.raises(CommandError, match="nicht zur Löschung fällig"):
        call_command("mail_aufraeumen", "--geloescht", str(max_.pk), stdout=StringIO())


def test_wiederaktivieren_verhindert_loeschung():
    max_ = konto("max", f"max@{DOM}")
    max_.is_active = False
    max_.save()
    Profil.objects.filter(user=max_).update(postfach_gesperrt_seit=timezone.now() - timedelta(days=100))
    max_.is_active = True
    max_.save()
    assert not mail.faellige_postfaecher().exists()


# -------------------------------------------------------- Verwaltung

@pytest.fixture
def vorstand_client(client):
    client.force_login(konto("chef", gruppe="Vorstand"))
    return client


def test_verteiler_in_der_verwaltung(vorstand_client):
    url = reverse("admin:seiten_verteiler_add")
    daten = {"adresse": f"Vorstand@{DOM}", "beschreibung": "Vorstand",
             "stufen": [Stufe.objects.get(name="Vorstand").pk], "weitere_adressen": "",
             "offen": "on", "aktiv": "on"}
    assert vorstand_client.post(url, daten).status_code == 302
    assert Verteiler.objects.get().adresse == f"vorstand@{DOM}"
    r = vorstand_client.post(url, {**daten, "adresse": f"VORSTAND@{DOM}"})
    assert "bereits ein Verteiler" in r.content.decode()
    r = vorstand_client.post(url, {**daten, "adresse": f"kasse@{DOM}", "weitere_adressen": "kein-mail"})
    assert "keine gültige" in r.content.decode()


def test_mitglied_sieht_keine_verwaltung_der_verteiler(client):
    client.force_login(konto("mia"))
    assert client.get(reverse("admin:seiten_verteiler_changelist")).status_code in (302, 403, 404)


def _aenderung(user, **werte):
    daten = {"username": user.username, "email": user.email, "is_active": "on",
             "first_name": user.first_name, "last_name": user.last_name,
             "groups": [g.pk for g in user.groups.all()],
             "profil-TOTAL_FORMS": "1", "profil-INITIAL_FORMS": "1",
             "profil-MIN_NUM_FORMS": "0", "profil-MAX_NUM_FORMS": "1",
             "profil-0-id": user.profil.pk, "profil-0-user": user.pk,
             "profil-0-vereins_email": user.profil.vereins_email or "", "profil-0-zustellung": "extern",
             "aliase-TOTAL_FORMS": "0", "aliase-INITIAL_FORMS": "0",
             "aliase-MIN_NUM_FORMS": "0", "aliase-MAX_NUM_FORMS": "1000"}
    daten.update(werte)
    return daten


def test_alias_in_der_benutzerverwaltung(vorstand_client):
    max_ = konto("max", f"max.maier@{DOM}")
    konto("anna", f"anna@{DOM}")
    url = reverse("admin:auth_user_change", args=[max_.pk])
    r = vorstand_client.post(url, _aenderung(max_, **{"aliase-TOTAL_FORMS": "1",
                                                      "aliase-0-adresse": f"M.Maier@{DOM}"}))
    assert r.status_code == 302 and Alias.objects.get(user=max_).adresse == f"m.maier@{DOM}"
    r = vorstand_client.post(url, _aenderung(max_, **{"aliase-TOTAL_FORMS": "2", "aliase-INITIAL_FORMS": "1",
                                                      "aliase-0-id": Alias.objects.get().pk,
                                                      "aliase-0-user": max_.pk,
                                                      "aliase-0-adresse": f"m.maier@{DOM}",
                                                      "aliase-1-adresse": f"anna@{DOM}"}))
    assert r.status_code == 200 and "Vereinsadresse von" in r.content.decode()


def test_vereinsadresse_aendern_in_der_verwaltung(vorstand_client):
    max_ = konto("max", f"max.maier@{DOM}")
    url = reverse("admin:auth_user_change", args=[max_.pk])
    r = vorstand_client.post(url, _aenderung(max_, **{"profil-0-vereins_email": f"max.mueller@{DOM}"}))
    assert r.status_code == 302
    assert Alias.objects.get(user=max_).adresse == f"max.maier@{DOM}"


def test_gesperrte_adresse_in_der_verwaltung(vorstand_client):
    mail.sperren(f"frei@{DOM}", konto("alt"))
    max_ = konto("max", f"max@{DOM}")
    r = vorstand_client.post(reverse("admin:auth_user_change", args=[max_.pk]),
                             _aenderung(max_, **{"profil-0-vereins_email": f"frei@{DOM}"}))
    assert r.status_code == 200 and "gesperrt" in r.content.decode()


# -------------------------------------------------------- Übersicht

def test_uebersicht_nur_vorstand(client):
    client.force_login(konto("mia"))
    assert client.get(reverse("mail_uebersicht")).status_code == 404


def test_uebersicht_und_csv(vorstand_client):
    max_ = konto("max", f"max@{DOM}")
    Alias.objects.create(user=max_, adresse=f"m@{DOM}")
    verteiler(f"vorstand@{DOM}", stufen=["Vorstand"])
    mail.sperren(f"weg@{DOM}")
    Abwesenheit.objects.create(user=max_, aktiv=True, text="x", bis=date.today() + timedelta(days=3))
    mail.belegung_einlesen(DOVEADM)
    html = vorstand_client.get(reverse("mail_uebersicht")).content.decode()
    for text in (f"max@{DOM}", f"m@{DOM}", f"vorstand@{DOM}", f"weg@{DOM}", "frei ab", "Abwesenheiten"):
        assert text in html
    r = vorstand_client.get(reverse("mail_uebersicht") + "?csv=adressen")
    assert r["Content-Type"].startswith("text/csv")
    inhalt = r.content.decode("utf-8-sig")
    assert f"m@{DOM};Alias;Max" in inhalt
    for teil in ("verteiler", "belegung", "abwesend", "gesperrt"):
        assert vorstand_client.get(reverse("mail_uebersicht") + f"?csv={teil}").status_code == 200


def test_navigation_zeigt_mail_fuer_vorstand(vorstand_client):
    assert reverse("mail_uebersicht") in vorstand_client.get(reverse("startseite")).content.decode()


# ------------------------------------------------- Sichten (PostgreSQL)

def _sicht(name):
    with connection.cursor() as c:
        c.execute(f"SELECT * FROM {name}")
        return {tuple(z) for z in c.fetchall()}


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Sichten gibt es nur in PostgreSQL")
def test_sichten_stimmen_mit_python_ueberein():
    vera = konto("vera", f"vera@{DOM}", gruppe="Vorstand")
    Profil.objects.filter(user=vera).update(zustellung=Profil.Zustellung.VEREIN)
    Alias.objects.create(user=vera, adresse=f"v@{DOM}")
    konto("valter", f"valter@{DOM}", gruppe="Vorstand")
    weg = konto("weg", f"weg@{DOM}", gruppe="Vorstand")
    Alias.objects.create(user=weg, adresse=f"w@{DOM}")
    weg.is_active = False
    weg.save()
    gast = konto("gast", gruppe=None)
    verteiler(f"vorstand@{DOM}", stufen=["Vorstand"], personen=[gast],
              weitere="betreuung@example.org\nzweite@example.org", offen=False)
    verteiler(f"aus@{DOM}", stufen=["Vorstand"], aktiv=False)
    mail.sperren(f"frueher@{DOM}")
    assert _sicht("exim_adressen") == mail.exim_adressen()
    assert _sicht("exim_verteiler") == mail.exim_verteiler()
    assert _sicht("exim_absender") == mail.exim_absender()
    assert (f"w@{DOM}", "gesperrt", f"weg@{DOM}", True) in mail.exim_adressen()
    assert (f"vorstand@{DOM}", "verteiler", None, False) in mail.exim_adressen()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Sichten gibt es nur in PostgreSQL")
def test_dovecot_sicht_mit_verzeichnis_nach_nummer(settings):
    settings.PASSWORD_HASHERS = ["seiten.passwort.Argon2DovecotHasher"]
    max_ = konto("max", f"max@{DOM}")
    max_.set_password(PW)
    max_.save()
    with connection.cursor() as c:
        c.execute("SELECT benutzer, home, nummer FROM dovecot_benutzer")
        assert c.fetchall() == [(f"max@{DOM}", f"/var/vmail/konten/{max_.pk}", max_.pk)]

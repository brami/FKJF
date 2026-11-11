"""Frei benennbare Stufen: anlegen, umbenennen, einfügen, löschen, Bearbeitungsrecht,
Formular, Verwaltung und die Übernahme der bisherigen festen Stufen (Migration)."""

from datetime import date
from io import StringIO

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from django.urls import reverse

from seiten import rechte
from seiten.forms import SeiteForm
from seiten.models import Seite, Stufe
from tests.hilfen import MITGLIEDER, VORSTAND, stufe as S

pytestmark = pytest.mark.django_db


def person(name, *stufen):
    u = User.objects.create_user(name, f"{name}@example.org", "pw")
    for s in stufen:
        u.groups.add(s.gruppe)
    return u


def test_bisherige_stufen_uebernommen():
    werte = list(Stufe.objects.values_list("name", "rang", "darf_bearbeiten"))
    assert werte == [("Fördermitglieder", 10, False), ("Mitglieder", 20, False), ("Vorstand", 30, True)]
    assert all(s.gruppe.name == s.name for s in Stufe.objects.all())


def test_neue_stufe_legt_gruppe_an_und_umbenennen_zieht_mit():
    s = Stufe.objects.create(name="Jugendwarte", rang=25)
    assert Group.objects.filter(name="Jugendwarte", stufe=s).exists()
    s.name = "Jugendleitung"
    s.save()
    s.gruppe.refresh_from_db()
    assert s.gruppe.name == "Jugendleitung"
    assert not Group.objects.filter(name="Jugendwarte").exists()


def test_eingefuegte_stufe_liegt_dazwischen():
    """Eine Stufe zwischen Mitglieder (20) und Vorstand (30)."""
    betreuer = Stufe.objects.create(name="Betreuer", rang=25)
    intern = Seite.objects.create(titel="Betreuerinfo", stufe=betreuer)
    mitglied = person("max", S(MITGLIEDER))
    b = person("bea", betreuer)
    vorstand = person("vera", S(VORSTAND))
    assert not rechte.darf_lesen(mitglied, intern)
    assert rechte.darf_lesen(b, intern) and rechte.darf_lesen(vorstand, intern)
    # Betreuer sehen alles von Mitgliedern, aber nichts vom Vorstand
    assert rechte.darf_lesen(b, Seite.objects.create(titel="M", stufe=S(MITGLIEDER)))
    assert not rechte.darf_lesen(b, Seite.objects.create(titel="V", stufe=S(VORSTAND)))
    assert not rechte.darf_bearbeiten(b)


def test_ganz_eigene_stufen_fuer_andere_anwendung():
    """Ein anderer Verein ersetzt die Stufen vollständig."""
    Stufe.objects.all().delete()
    leser = Stufe.objects.create(name="Leser", rang=1)
    redaktion = Stufe.objects.create(name="Redaktion", rang=2, darf_bearbeiten=True)
    l, r = person("lisa", leser), person("rolf", redaktion)
    seite = Seite.objects.create(titel="Entwurf", stufe=redaktion)
    assert not rechte.darf_lesen(l, seite) and rechte.darf_lesen(r, seite)
    assert rechte.darf_bearbeiten(r) and not rechte.darf_bearbeiten(l)
    assert not Group.objects.filter(name__in=["Mitglieder", "Vorstand"]).exists()


def test_bearbeitungsrecht_haengt_an_der_stufe_nicht_am_namen():
    vorstand = S(VORSTAND)
    vera = person("vera", vorstand)
    assert rechte.darf_bearbeiten(vera)
    vorstand.darf_bearbeiten = False
    vorstand.save()
    vera = User.objects.get(pk=vera.pk)   # Zwischenspeicher am Objekt verwerfen
    assert not rechte.darf_bearbeiten(vera)


def test_stufe_mit_seiten_nicht_loeschbar():
    Seite.objects.create(titel="x", stufe=S(MITGLIEDER))
    with pytest.raises(ProtectedError):
        S(MITGLIEDER).delete()


def test_stufe_loeschen_entfernt_gruppe_und_zuordnung():
    s = Stufe.objects.create(name="Ehemalige", rang=5)
    u = person("eva", s)
    s.delete()
    assert not Group.objects.filter(name="Ehemalige").exists()
    assert not u.groups.exists()


def test_newsletter_empfaenger_mit_eigener_stufe():
    betreuer = Stufe.objects.create(name="Betreuer", rang=25)
    person("max", S(MITGLIEDER))
    person("bea", betreuer)
    person("vera", S(VORSTAND))
    mit, _ = rechte.newsletter_empfaenger(Seite.objects.create(titel="x", stufe=betreuer))
    assert set(mit.values_list("username", flat=True)) == {"bea", "vera"}


def test_formular_reihenfolge_oeffentlich_und_vorschlag():
    Stufe.objects.create(name="Betreuer", rang=25)
    form = SeiteForm()
    auswahl = [label for _, label in form.fields["stufe"].choices]
    assert auswahl == ["Öffentlich (ohne Anmeldung)", "Fördermitglieder", "Mitglieder",
                       "Betreuer", "Vorstand"]
    # Vorschlag: höchste Stufe ohne Bearbeitungsrecht
    assert form.initial["stufe"].name == "Betreuer"


def test_anzeige_des_stufennamens(client):
    s = Stufe.objects.create(name="Betreuer", rang=25)
    seite = Seite.objects.create(titel="Dienstplan", stufe=s)
    client.force_login(person("bea", s))
    assert "Betreuer" in client.get(seite.get_absolute_url()).content.decode()
    assert "Betreuer" in client.get(reverse("startseite")).content.decode()


def test_fassungsvergleich_zeigt_namen_und_geloeschte_stufe(client):
    alt = Stufe.objects.create(name="Alt", rang=5)
    seite = Seite.objects.create(titel="T", datum=date(2026, 1, 1), stufe=alt)
    erste = seite.history.earliest()
    seite.stufe = S(MITGLIEDER)
    seite.save()
    alt.delete()
    client.force_login(person("vera", S(VORSTAND)))
    html = client.get(reverse("seite_fassung", args=[seite.pk, erste.history_id])).content.decode()
    assert "(gelöschte Stufe)" in html and "Mitglieder" in html
    # Wiederherstellen einer Fassung mit gelöschter Stufe wird abgelehnt
    r = client.post(reverse("seite_wiederherstellen", args=[seite.pk, erste.history_id]))
    assert r.status_code == 302
    seite.refresh_from_db()
    assert seite.stufe == S(MITGLIEDER)


def test_stufen_verwaltung_nur_fuer_administratoren(client):
    url = reverse("admin:seiten_stufe_changelist")
    client.force_login(person("vera", S(VORSTAND)))
    assert client.get(url).status_code == 403
    client.force_login(User.objects.create_superuser("root", "root@example.org", "pw"))
    r = client.get(url)
    assert r.status_code == 200 and "Fördermitglieder" in r.content.decode()


def test_benutzerverwaltung_bietet_alle_stufen_an(client):
    Stufe.objects.create(name="Betreuer", rang=25)
    Group.objects.create(name="Sonstige")   # Gruppe ohne Stufe wird nicht angeboten
    client.force_login(person("vera", S(VORSTAND)))
    html = client.get(reverse("admin:auth_user_add")).content.decode()
    assert "Betreuer" in html and "Sonstige" not in html


def test_vorstand_anlegen_mit_stufe():
    redaktion = Stufe.objects.create(name="Redaktion", rang=40, darf_bearbeiten=True)
    call_command("vorstand_anlegen", "rolf", "rolf@example.org", stdout=StringIO())
    assert list(User.objects.get(username="rolf").groups.all()) == [redaktion.gruppe]
    call_command("vorstand_anlegen", "vera", "vera@example.org", "--stufe", "Vorstand",
                 stdout=StringIO())
    assert User.objects.get(username="vera").groups.get().name == "Vorstand"
    with pytest.raises(CommandError):
        call_command("vorstand_anlegen", "x", "x@example.org", "--stufe", "Gibtsnicht",
                     stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_migration_uebernimmt_bisherige_werte():
    """Seiten und Verlauf mit den alten Zahlwerten 0–3 landen in den richtigen Stufen."""
    executor = MigrationExecutor(connection)
    executor.migrate([("seiten", "0005_dovecot_sicht")])
    apps = executor.loader.project_state([("seiten", "0005_dovecot_sicht")]).apps
    AltSeite = apps.get_model("seiten", "Seite")
    AltVerlauf = apps.get_model("seiten", "HistoricalSeite")
    for wert in range(4):
        s = AltSeite.objects.create(titel=f"S{wert}", stufe=wert, inhalt="")
        AltVerlauf.objects.create(id=s.pk, titel=s.titel, stufe=wert, inhalt="",
                                  datum=s.datum, erstellt=s.erstellt, geaendert=s.geaendert,
                                  history_date=s.geaendert, history_type="+")

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())

    erwartet = {"S0": None, "S1": "Fördermitglieder", "S2": "Mitglieder", "S3": "Vorstand"}
    for s in Seite.objects.all():
        assert (s.stufe.name if s.stufe else None) == erwartet[s.titel]
    for h in Seite.history.all():
        assert (Stufe.objects.get(pk=h.stufe_id).name if h.stufe_id else None) == erwartet[h.titel]


def test_umbenennen_auf_vorhandenen_gruppennamen_abgelehnt():
    from django.core.exceptions import ValidationError
    s = S(MITGLIEDER)
    s.name = "Vorstand"
    with pytest.raises(ValidationError):
        s.full_clean()


def test_neue_seite_schlaegt_mitglieder_vor_nicht_oeffentlich(client):
    """Im Formular der Ansicht (mit leerer Seite als instance) – nicht nur bei SeiteForm()."""
    client.force_login(person("vera", S(VORSTAND)))
    html = client.get(reverse("seite_neu")).content.decode()
    mitglieder = S(MITGLIEDER).pk
    assert f'<option value="{mitglieder}" selected>' in html

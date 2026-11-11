"""Wartungsbefehle für die Betreuung: Zwei-Faktor zurücksetzen, gelöschte Seite zurückholen."""

from io import StringIO
from pathlib import Path

import pytest
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from seiten.models import Anhang, Seite, Stufe
from tests.hilfen import MITGLIEDER, VORSTAND, stufe as S

pytestmark = pytest.mark.django_db


def befehl(*args):
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


def test_zwei_faktor_zuruecksetzen():
    vera = User.objects.create_user("vera", "vera@example.org", "pw")
    vera.groups.add(S(VORSTAND).gruppe)
    TOTP.activate(vera, "JBSWY3DPEHPK3PXP")
    out = befehl("zwei_faktor_zuruecksetzen", "VERA@example.org")
    assert "zurückgesetzt (totp)" in out and "neu einrichten" in out
    assert not Authenticator.objects.filter(user=vera).exists()
    assert "nichts zu tun" in befehl("zwei_faktor_zuruecksetzen", "vera")
    with pytest.raises(CommandError):
        befehl("zwei_faktor_zuruecksetzen", "niemand")


def _loeschen(client, seite):
    vera = User.objects.create_user("vera", "vera@example.org", "pw")
    vera.groups.add(S(VORSTAND).gruppe)
    client.force_login(vera)
    assert client.post(reverse("seite_loeschen", args=[seite.pk])).status_code == 302
    assert not Seite.objects.filter(pk=seite.pk).exists()


def test_geloeschte_seite_mit_anhang_zurueckholen(client, settings):
    settings.FV_ZWEI_FAKTOR_PFLICHT = False
    s = Seite.objects.create(titel="Protokoll JHV", stufe=S(MITGLIEDER), inhalt="<p>Text</p>")
    a = Anhang.objects.create(seite=s, datei=SimpleUploadedFile("protokoll.pdf", b"%PDF-1.4 x"),
                              bezeichnung="Protokoll")
    pfad = Path(a.datei.path)
    nr = s.pk
    _loeschen(client, s)
    assert not pfad.exists()   # Datei wurde mit gelöscht

    assert "Protokoll JHV" in befehl("seite_wiederherstellen")
    out = befehl("seite_wiederherstellen", str(nr))
    s = Seite.objects.get(pk=nr)
    assert s.titel == "Protokoll JHV" and s.stufe == S(MITGLIEDER) and "Text" in s.inhalt
    assert "Dateien fehlen" in out and f"-d {pfad}" in out and not s.anhaenge.exists()
    assert s.history.first().history_change_reason == "wiederhergestellt"

    # Datei aus der Sicherung zurückgeholt -> zweiter Aufruf ergänzt den Anhang
    pfad.write_bytes(b"%PDF-1.4 x")
    out = befehl("seite_wiederherstellen", str(nr))
    a = s.anhaenge.get()
    assert a.bezeichnung == "Protokoll" and a.dateiname == "protokoll.pdf"
    assert "1 Anhang" in out
    assert "Keine gelöschten Seiten" in befehl("seite_wiederherstellen")


def test_wiederherstellen_ohne_stufe_nicht_oeffentlich(client, settings):
    settings.FV_ZWEI_FAKTOR_PFLICHT = False
    alt = Stufe.objects.create(name="Betreuer", rang=25)
    s = Seite.objects.create(titel="Dienstplan", stufe=alt)
    nr = s.pk
    _loeschen(client, s)
    alt.delete()
    befehl("seite_wiederherstellen", str(nr))
    assert Seite.objects.get(pk=nr).stufe == S(VORSTAND)


def test_unbekannte_nummer():
    with pytest.raises(CommandError):
        befehl("seite_wiederherstellen", "999")

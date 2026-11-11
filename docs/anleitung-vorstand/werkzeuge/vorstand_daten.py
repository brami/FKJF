"""Ergänzt die Beispieldaten um Vorstandskonten (nach demo_daten.py ausführen).

Aufruf: python manage.py shell < vorstand_daten.py
"""
from allauth.mfa.totp.internal.auth import TOTP
from django.contrib.auth.models import User

from seiten.models import Profil, Stufe, Webseite

GEHEIM = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"   # Testgeheimnis für die Authenticator-App
vorstand = Stufe.objects.get(name="Vorstand")

vera = User.objects.create_user("vera.vorsitz", "vera.vorsitz@example.org", "Anleitung-2026!",
                                first_name="Vera", last_name="Vorsitz")
vera.groups.add(vorstand.gruppe)
Profil.objects.update_or_create(user=vera, defaults={
    "vereins_email": "vera.vorsitz@foerderverein-kf-jf-kreuzau.de", "zustellung": "verein"})
TOTP.activate(vera, GEHEIM)

neu = User.objects.create_user("victor.neu", "victor.neu@example.org", "Anleitung-2026!",
                               first_name="Victor", last_name="Neu")
neu.groups.add(vorstand.gruppe)          # noch ohne Zwei-Faktor-Anmeldung

for name, vor, nach, stufe in [("felix.foerder", "Felix", "Förder", "Fördermitglieder"),
                               ("frieda.gruen", "Frieda", "Grün", "Fördermitglieder"),
                               ("tom.kessler", "Tom", "Kessler", "Mitglieder")]:
    u = User.objects.create_user(name, f"{name}@example.org", "Anleitung-2026!",
                                 first_name=vor, last_name=nach)
    u.groups.add(Stufe.objects.get(name=stufe).gruppe)
User.objects.create_user("hans.ohne", "", first_name="Hans", last_name="Ohnemail").groups.add(
    Stufe.objects.get(name="Mitglieder").gruppe)

w = Webseite.aktuell()
w.antwort_an = "vorstand@foerderverein-kf-jf-kreuzau.de"
w.save()
print("Vorstandsdaten angelegt.")

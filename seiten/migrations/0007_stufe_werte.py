"""Frei benennbare Stufen (Teil 2): bisherige Zahlwerte auf die neuen Stufen abbilden.

0 (Öffentlich) -> keine Stufe; 1/2/3 -> Fördermitglieder/Mitglieder/Vorstand.
Eigene Migration, damit Daten- und Schemaänderungen auf PostgreSQL in getrennten
Transaktionen laufen.
"""

from django.db import migrations

ALT_ZU_RANG = {1: 10, 2: 20, 3: 30}


def vorwaerts(apps, schema_editor):
    Stufe = apps.get_model("seiten", "Stufe")
    zuordnung = {alt: Stufe.objects.get(rang=rang).pk for alt, rang in ALT_ZU_RANG.items()}
    for modell in ("Seite", "HistoricalSeite"):
        M = apps.get_model("seiten", modell)
        M.objects.filter(stufe=0).update(stufe_neu=None)
        for alt, pk in zuordnung.items():
            M.objects.filter(stufe=alt).update(stufe_neu=pk)


def rueckwaerts(apps, schema_editor):
    Stufe = apps.get_model("seiten", "Stufe")
    rang_zu_alt = {rang: alt for alt, rang in ALT_ZU_RANG.items()}
    for modell in ("Seite", "HistoricalSeite"):
        M = apps.get_model("seiten", modell)
        M.objects.filter(stufe_neu__isnull=True).update(stufe=0)
        for stufe in Stufe.objects.all():
            # Neu hinzugekommene Stufen landen bei der nächstniedrigeren bisherigen
            alt = max([a for r, a in rang_zu_alt.items() if r <= stufe.rang], default=0)
            M.objects.filter(stufe_neu=stufe.pk).update(stufe=alt)


class Migration(migrations.Migration):
    dependencies = [("seiten", "0006_stufe")]
    operations = [migrations.RunPython(vorwaerts, rueckwaerts)]

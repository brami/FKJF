"""Frei benennbare Stufen (Teil 1): Modell anlegen, bisherige Gruppen übernehmen,
neues Feld an Seite und Verlauf ergänzen."""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

# Bisherige feste Stufen -> Rang (mit Abständen für spätere Stufen)
BISHER = [("Fördermitglieder", 10, False), ("Mitglieder", 20, False), ("Vorstand", 30, True)]


def stufen_anlegen(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Stufe = apps.get_model("seiten", "Stufe")
    for name, rang, bearbeiten in BISHER:
        gruppe, _ = Group.objects.get_or_create(name=name)
        Stufe.objects.get_or_create(gruppe=gruppe, defaults={
            "name": name, "rang": rang, "darf_bearbeiten": bearbeiten})


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("seiten", "0005_dovecot_sicht"),
    ]

    operations = [
        migrations.CreateModel(
            name="Stufe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True)),
                ("rang", models.PositiveSmallIntegerField(
                    help_text="Höhere Zahl = höhere Stufe. Abstände (10, 20, 30 …) lassen Platz für spätere Stufen.",
                    unique=True, validators=[django.core.validators.MinValueValidator(1)])),
                ("darf_bearbeiten", models.BooleanField(
                    default=False, verbose_name="darf bearbeiten",
                    help_text="Seiten anlegen und ändern, Benutzer verwalten, Versionsverlauf, Newsletter. "
                              "Für diese Stufe ist die Zwei-Faktor-Anmeldung Pflicht.")),
                ("gruppe", models.OneToOneField(
                    editable=False, on_delete=django.db.models.deletion.PROTECT,
                    related_name="stufe", to="auth.group")),
            ],
            options={"verbose_name": "Stufe", "verbose_name_plural": "Stufen", "ordering": ["rang"]},
        ),
        migrations.RunPython(stufen_anlegen, migrations.RunPython.noop),
        migrations.AddField(
            model_name="seite", name="stufe_neu",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="+", to="seiten.stufe"),
        ),
        migrations.AddField(
            model_name="historicalseite", name="stufe_neu",
            field=models.ForeignKey(null=True, blank=True, db_constraint=False,
                                    on_delete=django.db.models.deletion.DO_NOTHING,
                                    related_name="+", to="seiten.stufe"),
        ),
    ]

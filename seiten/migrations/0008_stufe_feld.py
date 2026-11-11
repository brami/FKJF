"""Frei benennbare Stufen (Teil 3): altes Zahlfeld entfernen, neues Feld umbenennen."""

import django.db.models.deletion
from django.db import migrations, models

HILFE = "Die Seite sehen diese Stufe und alle höheren. Leer = Öffentlich (ohne Anmeldung)."


class Migration(migrations.Migration):
    dependencies = [("seiten", "0007_stufe_werte")]

    operations = [
        migrations.RemoveField(model_name="seite", name="stufe"),
        migrations.RemoveField(model_name="historicalseite", name="stufe"),
        migrations.RenameField(model_name="seite", old_name="stufe_neu", new_name="stufe"),
        migrations.RenameField(model_name="historicalseite", old_name="stufe_neu", new_name="stufe"),
        migrations.AlterField(
            model_name="seite", name="stufe",
            field=models.ForeignKey(blank=True, help_text=HILFE, null=True,
                                    on_delete=django.db.models.deletion.PROTECT,
                                    related_name="seiten", to="seiten.stufe",
                                    verbose_name="Sichtbar für"),
        ),
        migrations.AlterField(
            model_name="historicalseite", name="stufe",
            field=models.ForeignKey(blank=True, db_constraint=False, help_text=HILFE, null=True,
                                    on_delete=django.db.models.deletion.DO_NOTHING,
                                    related_name="+", to="seiten.stufe",
                                    verbose_name="Sichtbar für"),
        ),
    ]

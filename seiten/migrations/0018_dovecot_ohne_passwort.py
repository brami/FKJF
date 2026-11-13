"""Sicht dovecot_benutzer: auch Postfächer ohne (Argon2-)Passwort aufführen.

Bisher fehlten Konten, deren Passwort noch nicht gesetzt oder noch nicht als Argon2
gespeichert ist (z. B. eingeladen, Einladung noch nicht angenommen). Für Dovecot gab
es diese Postfächer dann gar nicht – eingehende Mails wären abgewiesen worden.
Jetzt steht jedes Postfach in der Sicht; passwort ist NULL, solange keine Anmeldung
möglich ist. Die Passwortabfrage von Dovecot prüft passwort IS NOT NULL.
"""

from django.db import migrations

DOVECOT = """
CREATE OR REPLACE VIEW dovecot_benutzer AS
SELECT lower(p.vereins_email)                       AS benutzer,
       CASE WHEN u.password LIKE 'argon2$argon2id$%%'
            THEN '{ARGON2ID}' || substr(u.password, 7) END AS passwort,
       u.is_active                                  AS aktiv,
       '/var/vmail/konten/' || u.id                 AS home,
       u.id                                         AS nummer
FROM seiten_profil p
JOIN auth_user u ON u.id = p.user_id
WHERE p.vereins_email IS NOT NULL;
"""


def anlegen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOVECOT)


def zurueck(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        from importlib import import_module
        schema_editor.execute(import_module("seiten.migrations.0012_mail_sichten").DOVECOT)


class Migration(migrations.Migration):
    dependencies = [("seiten", "0017_kreise_sichten")]

    operations = [migrations.RunPython(anlegen, zurueck)]

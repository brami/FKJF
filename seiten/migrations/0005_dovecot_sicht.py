"""Datenbank-Sicht für Dovecot: Vereinsadresse und Passwort-Hash der Konten mit Postfach.

Nur PostgreSQL (auf dem Server). Dovecot erhält Leserecht nur auf diese Sicht
(fv-web-update vergibt es an die Rolle „dovecot“, falls vorhanden), nicht auf
die Tabellen. Geliefert werden nur Argon2id-Hashes – im Format {ARGON2ID}$argon2id$…,
das Dovecot direkt prüft.
"""

from django.db import migrations

SICHT = """
CREATE OR REPLACE VIEW dovecot_benutzer AS
SELECT lower(p.vereins_email)                       AS benutzer,
       '{ARGON2ID}' || substr(u.password, 7)        AS passwort,
       u.is_active                                  AS aktiv
FROM seiten_profil p
JOIN auth_user u ON u.id = p.user_id
WHERE p.vereins_email IS NOT NULL
  AND u.password LIKE 'argon2$argon2id$%%';
"""


def anlegen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SICHT)


def entfernen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP VIEW IF EXISTS dovecot_benutzer;")


class Migration(migrations.Migration):
    dependencies = [
        ("seiten", "0004_profil"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(anlegen, entfernen)]

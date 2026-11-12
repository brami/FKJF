"""Sichten für Plus-Adressen und Verteiler-Archive (nur PostgreSQL).

exim_plus_gesperrt     Plus-Adressen, die die Person gesperrt hat (Ablehnung bei der Annahme).
mail_archive           Verteiler mit Archiv: nummer (Verzeichnis), Adresse, Aufbewahrung in
                       Tagen (NULL = unbegrenzt), aktiv.
dovecot_archiv_leser   Wer welches Archiv lesen darf: aktive Empfänger des Verteilers mit
                       Postfach (über Stufe oder persönlich) – benutzer = Vereinsadresse.

Python-Gegenstücke: seiten.mail.exim_plus_gesperrt(), mail_archive(), archiv_leser_alle().
"""

from django.db import migrations

SICHTEN = """
CREATE OR REPLACE VIEW exim_plus_gesperrt AS
SELECT lower(pa.adresse) AS adresse
FROM seiten_plusadresse pa WHERE pa.gesperrt;

CREATE OR REPLACE VIEW mail_archive AS
SELECT v.id AS nummer, lower(v.adresse) AS verteiler, v.archiv_tage AS frist_tage, v.aktiv
FROM seiten_verteiler v WHERE v.archiv;

CREATE OR REPLACE VIEW dovecot_archiv_leser AS
WITH mitglieder AS (
    SELECT vp.verteiler_id, vp.user_id FROM seiten_verteiler_personen vp
    UNION
    SELECT vs.verteiler_id, ug.user_id
    FROM seiten_verteiler_stufen vs
    JOIN seiten_stufe s ON s.id = vs.stufe_id
    JOIN auth_user_groups ug ON ug.group_id = s.gruppe_id
)
SELECT DISTINCT v.id AS nummer, lower(v.adresse) AS verteiler, lower(p.vereins_email) AS benutzer
FROM seiten_verteiler v
JOIN mitglieder m ON m.verteiler_id = v.id
JOIN auth_user u ON u.id = m.user_id AND u.is_active
JOIN seiten_profil p ON p.user_id = u.id AND p.vereins_email IS NOT NULL
WHERE v.archiv;
"""


def anlegen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SICHTEN)


def entfernen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP VIEW IF EXISTS dovecot_archiv_leser; DROP VIEW IF EXISTS mail_archive; "
                              "DROP VIEW IF EXISTS exim_plus_gesperrt;")


class Migration(migrations.Migration):
    dependencies = [("seiten", "0013_plus_archiv")]

    operations = [migrations.RunPython(anlegen, entfernen)]

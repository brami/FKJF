"""Sichten für den Mailserver: Verteiler können auch Kreise als Empfänger haben.

Erneuert exim_verteiler, exim_absender und dovecot_archiv_leser (gleiche Spalten);
Mitglieder eines Verteilers sind jetzt: Personen, Stufen und Kreise.
"""

from importlib import import_module

from django.db import migrations

MITGLIEDER = """
    SELECT vp.verteiler_id, vp.user_id FROM seiten_verteiler_personen vp
    UNION
    SELECT vs.verteiler_id, ug.user_id
    FROM seiten_verteiler_stufen vs
    JOIN seiten_stufe s ON s.id = vs.stufe_id
    JOIN auth_user_groups ug ON ug.group_id = s.gruppe_id
    UNION
    SELECT vk.verteiler_id, kp.user_id
    FROM seiten_verteiler_kreise vk
    JOIN seiten_kreis_personen kp ON kp.kreis_id = vk.kreis_id
"""

SICHTEN = f"""
CREATE OR REPLACE VIEW exim_verteiler AS
WITH mitglieder AS ({MITGLIEDER})
SELECT DISTINCT lower(v.adresse) AS verteiler,
       lower(CASE WHEN p.zustellung = 'verein' AND p.vereins_email IS NOT NULL
                  THEN p.vereins_email ELSE u.email END) AS empfaenger
FROM seiten_verteiler v
JOIN mitglieder m ON m.verteiler_id = v.id
JOIN auth_user u ON u.id = m.user_id AND u.is_active
LEFT JOIN seiten_profil p ON p.user_id = u.id
WHERE v.aktiv
  AND coalesce(CASE WHEN p.zustellung = 'verein' AND p.vereins_email IS NOT NULL
                    THEN p.vereins_email ELSE u.email END, '') <> ''
UNION
SELECT lower(v.adresse), lower(x.adresse)
FROM seiten_verteiler v,
     regexp_split_to_table(v.weitere_adressen, E'\\\\s+') AS x(adresse)
WHERE v.aktiv AND x.adresse <> '';

CREATE OR REPLACE VIEW exim_absender AS
WITH konten AS (
    SELECT u.id, lower(p.vereins_email) AS benutzer
    FROM auth_user u JOIN seiten_profil p ON p.user_id = u.id
    WHERE u.is_active AND p.vereins_email IS NOT NULL
), mitglieder AS ({MITGLIEDER})
SELECT k.benutzer, k.benutzer AS adresse FROM konten k
UNION
SELECT k.benutzer, lower(a.adresse) FROM konten k JOIN seiten_alias a ON a.user_id = k.id
UNION
SELECT k.benutzer, lower(v.adresse)
FROM konten k
JOIN mitglieder m ON m.user_id = k.id
JOIN seiten_verteiler v ON v.id = m.verteiler_id AND v.aktiv;

CREATE OR REPLACE VIEW dovecot_archiv_leser AS
WITH mitglieder AS ({MITGLIEDER})
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
        schema_editor.execute(import_module("seiten.migrations.0012_mail_sichten").EXIM)
        schema_editor.execute(import_module("seiten.migrations.0014_plus_archiv_sichten").SICHTEN)


class Migration(migrations.Migration):
    dependencies = [("seiten", "0016_kreise")]

    operations = [migrations.RunPython(anlegen, entfernen)]

"""Datenbanksichten für den Mailserver (nur PostgreSQL).

dovecot_benutzer  Anmeldung (nur mit der Vereinsadresse) und Postfach-Verzeichnis
                  /var/vmail/konten/<nummer> – nach der Nummer des Kontos, damit eine
                  geänderte Adresse das Postfach nicht verschiebt.
exim_adressen     Jede Adresse mit Art: postfach, alias, verteiler, gesperrt (Konto
                  deaktiviert oder frei gewordene Adresse in der Sperrfrist; Mails
                  werden mit Hinweis abgelehnt). ziel = Vereinsadresse des Postfachs.
                  offen = alle dürfen schreiben (bei Verteilern einstellbar).
exim_verteiler    Empfänger je Verteiler: Zustelladressen der Personen (Wahl extern
                  oder Verein) und weitere Adressen.
exim_absender     Mit welchen Adressen eine angemeldete Person senden darf: Vereins-
                  adresse, Aliase, Verteiler, denen sie angehört.

Leserechte für die Rollen des Mailservers vergibt das Installationsskript.
Python-Gegenstücke: seiten.mail.exim_adressen() usw. (Tests vergleichen beides).
"""

from django.db import migrations

DOVECOT = """
CREATE OR REPLACE VIEW dovecot_benutzer AS
SELECT lower(p.vereins_email)                       AS benutzer,
       '{ARGON2ID}' || substr(u.password, 7)        AS passwort,
       u.is_active                                  AS aktiv,
       '/var/vmail/konten/' || u.id                 AS home,
       u.id                                         AS nummer
FROM seiten_profil p
JOIN auth_user u ON u.id = p.user_id
WHERE p.vereins_email IS NOT NULL
  AND u.password LIKE 'argon2$argon2id$%%';
"""

DOVECOT_ALT = """
DROP VIEW IF EXISTS dovecot_benutzer;
CREATE VIEW dovecot_benutzer AS
SELECT lower(p.vereins_email)                       AS benutzer,
       '{ARGON2ID}' || substr(u.password, 7)        AS passwort,
       u.is_active                                  AS aktiv
FROM seiten_profil p
JOIN auth_user u ON u.id = p.user_id
WHERE p.vereins_email IS NOT NULL
  AND u.password LIKE 'argon2$argon2id$%%';
"""

EXIM = """
CREATE OR REPLACE VIEW exim_adressen AS
SELECT lower(p.vereins_email) AS adresse,
       CASE WHEN u.is_active THEN 'postfach' ELSE 'gesperrt' END AS art,
       lower(p.vereins_email) AS ziel,
       true AS offen
FROM seiten_profil p JOIN auth_user u ON u.id = p.user_id
WHERE p.vereins_email IS NOT NULL
UNION ALL
SELECT lower(a.adresse),
       CASE WHEN u.is_active AND p.vereins_email IS NOT NULL THEN 'alias' ELSE 'gesperrt' END,
       lower(p.vereins_email),
       true
FROM seiten_alias a JOIN auth_user u ON u.id = a.user_id
LEFT JOIN seiten_profil p ON p.user_id = u.id
UNION ALL
SELECT lower(v.adresse), 'verteiler', NULL, v.offen
FROM seiten_verteiler v WHERE v.aktiv
UNION ALL
SELECT lower(s.adresse), 'gesperrt', NULL, true
FROM seiten_adresssperre s WHERE s.frei_ab > current_date;

CREATE OR REPLACE VIEW exim_verteiler AS
WITH mitglieder AS (
    SELECT vp.verteiler_id, vp.user_id FROM seiten_verteiler_personen vp
    UNION
    SELECT vs.verteiler_id, ug.user_id
    FROM seiten_verteiler_stufen vs
    JOIN seiten_stufe s ON s.id = vs.stufe_id
    JOIN auth_user_groups ug ON ug.group_id = s.gruppe_id
)
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
)
SELECT k.benutzer, k.benutzer AS adresse FROM konten k
UNION
SELECT k.benutzer, lower(a.adresse) FROM konten k JOIN seiten_alias a ON a.user_id = k.id
UNION
SELECT k.benutzer, lower(v.adresse)
FROM konten k
JOIN seiten_verteiler v ON v.aktiv
WHERE EXISTS (SELECT 1 FROM seiten_verteiler_personen vp
              WHERE vp.verteiler_id = v.id AND vp.user_id = k.id)
   OR EXISTS (SELECT 1 FROM seiten_verteiler_stufen vs
              JOIN seiten_stufe s ON s.id = vs.stufe_id
              JOIN auth_user_groups ug ON ug.group_id = s.gruppe_id
              WHERE vs.verteiler_id = v.id AND ug.user_id = k.id);
"""


def anlegen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOVECOT)
        schema_editor.execute(EXIM)


def entfernen(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP VIEW IF EXISTS exim_absender; DROP VIEW IF EXISTS exim_verteiler; "
                              "DROP VIEW IF EXISTS exim_adressen;")
        schema_editor.execute(DOVECOT_ALT)


class Migration(migrations.Migration):
    dependencies = [("seiten", "0011_mail")]

    operations = [migrations.RunPython(anlegen, entfernen)]

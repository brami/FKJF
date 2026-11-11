# Webseite Förderverein KF/JF Kreuzau

Django-6.1-Anwendung: öffentliche Seiten und geschützter Bereich mit frei benennbaren
Stufen (hier: Öffentlich < Fördermitglieder < Mitglieder < Vorstand), Anhängen mit Rechteprüfung,
Versionsverlauf und (in Arbeit) Newsletter.

Anforderungen: siehe Projekt-Dokument `webseite/anforderungen_django.md`.

## Entwicklung

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export FV_DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Newsletter in der Entwicklung verschicken: `python manage.py newsletter_dienst --einmal`
(mit `FV_NEWSLETTER_PAUSE=0`, sonst wartet er die Pause nach der Probe ab).

Tests: `python -m pytest`

## Aufbau

- `seiten/rechte.py` – **die einzige Stelle**, an der über Sichtbarkeit und
  Bearbeitungsrechte entschieden wird
- `seiten/models.py` – Seite und Anhang (mit Versionsverlauf, HTML-Bereinigung)
- `seiten/views.py` – Startseite, Seitenansicht, Anhang-Download
- `seiten/konto.py` – Anmeldung (django-allauth): keine Registrierung, Einladung per
  Link, Pflicht zur Zwei-Faktor-Anmeldung für den Vorstand
- `seiten/admin.py` – Benutzerverwaltung für den Vorstand (anlegen, einladen, Stufen zuordnen),
  Stufenverwaltung für Administratoren
- `seiten/bearbeiten.py` – Bearbeitung für den Vorstand: Seiten anlegen, ändern,
  löschen, Anhänge verwalten, Versionsverlauf mit Vergleich und Wiederherstellen
- `seiten/newsletter.py` – Newsletter: Empfänger, E-Mail, Versandschritt, Oberfläche;
  der Dienst ist `manage.py newsletter_dienst`
- `static/vendor/tinymce/` – Editor TinyMCE 8 (GPL-2.0-or-later), nur benötigte Teile
- `tests/` – Rechtematrix für alle Benutzerarten und Stufen

## Einstellungen (Umgebungsvariablen)

| Variable | Bedeutung |
|---|---|
| `FV_DEBUG` | `1` nur in der Entwicklung |
| `FV_SECRET_KEY` | Pflicht im Betrieb |
| `FV_ALLOWED_HOSTS` | z. B. `foerderverein-kf-jf-kreuzau.de` |
| `FV_DB_NAME`, `FV_DB_USER`, … | PostgreSQL; ohne `FV_DB_NAME` wird SQLite verwendet |
| `FV_PRIVATE_MEDIA_ROOT` | Ablage der Anhänge (außerhalb des Webverzeichnisses) |
| `FV_ADMIN_PFAD` | Pfad der Verwaltung, Standard `verwaltung/` |
| `FV_NEWSLETTER_PAUSE` | Sekunden zwischen Probe und Versand an alle, Standard 300 |
| `FV_NEWSLETTER_ABSTAND` | Sekunden zwischen zwei E-Mails, Standard 3 |
| `FV_NEWSLETTER_MAX_ANHANG_MB` | Anhänge bis zu dieser Gesamtgröße gehen mit, darüber nur Links; Standard 8 |

## Name und Texte der Webseite

Name, Slogan, Fußzeile („© …“), Ansprechpartner („Für ein Konto wenden Sie sich bitte
an …“) und die Unterschrift unter E-Mails pflegen Administratoren in der Verwaltung unter
*Einstellungen der Webseite*. Der Name erscheint auch im Fenstertitel, im Betreff der
E-Mails, als Absendername (wenn `FV_MAIL_ABSENDER` nur eine Adresse enthält) und in der
Authenticator-App. Für den Förderverein übernimmt die Migration die bisherigen Texte.
Im Quellcode steht damit nichts Vereinsspezifisches mehr.

## Newsletter

Auf jeder Seite gibt es für Bearbeitende „Als Newsletter versenden“. Beim Versand wird gewählt:

- **An:** die Stufe der Seite und/oder höhere Stufen (bei öffentlichen Seiten auch Konten
  ohne Stufe). Höhere Stufen erhalten die E-Mail zuerst.
- **Inhalt:** die ganze Seite in der E-Mail oder nur Vorschau und Link (zum Lesen
  geschützter Seiten ist dann eine Anmeldung nötig).
- **Ankündigung:** optionaler kurzer Text über der Seite.
- **Anhänge mitsenden:** Dateien (keine Bilder) bis `FV_NEWSLETTER_MAX_ANHANG_MB`
  zusammen; sonst stehen Links in der E-Mail.

Ablauf: Die Empfängerliste wird beim Start festgeschrieben. Der Dienst
`fv-web-newsletter` schickt zuerst eine **Probe an die versendende Person**, wartet
`FV_NEWSLETTER_PAUSE` Sekunden (vorzeitig fortsetzen möglich) und verschickt dann jede
E-Mail **einzeln** im Abstand `FV_NEWSLETTER_ABSTAND` an die Zustelladresse, die jede
Person unter *Mein Konto* gewählt hat. **Abbrechen** ist jederzeit möglich; vor jeder
E-Mail wird neu geprüft. Das Protokoll (unter *Newsletter* in der Kopfzeile) zeigt je
Empfänger gesendet, Fehler (mit Meldung), ohne E-Mail-Adresse oder nicht gesendet.
Eine Seite kann beliebig oft verschickt werden.

Absender ist die versendende Person: mit ihrer Vereinsadresse, falls vorhanden, sonst
„Name (Name der Webseite)“ mit der Adresse aus `FV_MAIL_ABSENDER` – fremde Adressen wie
gmail.com dürfen wir nicht als Absender eintragen, sonst landen die E-Mails im Spam.
Antworten gehen an die Person und an die *weitere Antwortadresse* aus den
Einstellungen der Webseite (z. B. die des Vorstands).

## Stufen

Wer was sieht, regeln **Stufen**. Jede Seite gehört zu einer Stufe; sie sehen alle
Personen dieser und jeder höheren Stufe. Hat jemand mehrere Stufen, zählt die höchste.

- **Öffentlich** ist fest die unterste Stufe (ohne Anmeldung; im Formular „leer“).
- Alle anderen Stufen legen Administratoren in der Verwaltung an (*Stufen*): **Name**
  (frei), **Rang** (höhere Zahl = höhere Stufe; Abstände wie 10/20/30 lassen Platz zum
  Einfügen) und **darf bearbeiten** (Seiten, Verlauf, Benutzer; dafür gilt die
  Zwei-Faktor-Pflicht). Mehrere Stufen dürfen bearbeiten.
- Zu jeder Stufe gehört automatisch eine gleichnamige Gruppe, über die Personen in der
  Benutzerverwaltung zugeordnet werden; Umbenennen zieht die Gruppe mit.
- Eine Stufe lässt sich nur löschen, solange ihr keine Seite zugeordnet ist.
- Für den Förderverein legt die Migration Fördermitglieder (10), Mitglieder (20) und
  Vorstand (30, darf bearbeiten) an. Andere Anwendungen benennen, ergänzen oder ersetzen sie.

## Anmeldung und Benutzer

- Konten legt der Vorstand in der Verwaltung an (*Benutzer → Hinzufügen*): Name,
  E-Mail-Adresse, Stufe. Ein Passwort wird nicht vergeben; die Person erhält eine
  **Einladung** mit einem Link (7 Tage gültig, einmal verwendbar) und setzt es selbst.
  Ist der Mailversand noch nicht eingerichtet, zeigt die Verwaltung den Link an.
- Anmelden mit Benutzername **oder** E-Mail-Adresse (jede Adresse nur einmal);
  „Passwort vergessen?“ schickt einen neuen Link.
- **Vorstand und Administratoren müssen die Zwei-Faktor-Anmeldung** (Authenticator-App)
  einrichten; bis dahin führt jede Seite zur Einrichtung. Abschalten nur zum Testen:
  `FV_ZWEI_FAKTOR_PFLICHT=0`.
- Die Verwaltung meldet immer über die normale Anmeldeseite an – die Zwei-Faktor-Anmeldung
  lässt sich dort nicht umgehen. Der Vorstand kann keine Administratorkonten sehen oder
  ändern, niemanden zum Administrator machen und keine fremden Passwörter setzen.
- Erstes Vorstandskonto auf dem Server: `sudo fv-manage vorstand_anlegen <name> <e-mail> --admin`
  (Stufe: die höchste mit Bearbeitungsrecht, oder `--stufe <Name>`)

## Postfach und Passwörter

Passwörter werden mit **Argon2id** gespeichert (`seiten/passwort.py`), in einem Format,
das auch **Dovecot** prüfen kann. Damit gibt es für Konten mit Postfach nur **ein**
Passwort für Webseite und Mail, verwaltet auf der Webseite (Einladung, ändern, vergessen).

- Jedes Konto hat eine **externe Adresse** (`E-Mail-Adresse`): für „Passwort vergessen“,
  Einladungen und – nach Wahl – Vereinsmails.
- Konten mit Postfach haben zusätzlich eine **Vereinsadresse** (Verwaltung → Benutzer →
  „Postfach und Vereinsmails“). Anmelden geht auch damit. „Passwort vergessen“ mit der
  Vereinsadresse schickt den Link trotzdem an die externe Adresse.
- Wohin **Vereinsmails** (z. B. Newsletter) gehen, wählt jede Person unter „Mein Konto“
  (Standard: externe Adresse).
- Konten mit Postfach brauchen ein Passwort mit mindestens 12 Zeichen (Mail hat keine
  Zwei-Faktor-Anmeldung).

**Für Dovecot** (gleicher Server) gibt es in PostgreSQL die Sicht `dovecot_benutzer`
mit den Spalten `benutzer` (Vereinsadresse, klein geschrieben), `passwort`
(`{ARGON2ID}$argon2id$…`) und `aktiv`. Die Datenbankrolle `dovecot` (Anmeldung nur lokal
über den Socket als Systembenutzer `dovecot`) darf nur diese Sicht lesen. Abfrage für
die Passwortprüfung:

```sql
SELECT benutzer AS "user", passwort AS password
  FROM dovecot_benutzer WHERE benutzer = lower('<anmeldename>') AND aktiv
```

Die Dovecot-Konfiguration (Debian 13: Dovecot 2.4) folgt mit der Einrichtung des
Mailservers. Vorher auf dem Server prüfen: `doveadm pw -l` muss `ARGON2ID` enthalten.

## Installation auf dem Server

Das Skript `deploy/setup-server-fv-web.sh` richtet einen Debian-13-vServer per SSH ein
(PostgreSQL, gunicorn, Caddy aus Debian; kein Docker). Es kann allein irgendwo liegen.
Die Anwendung holt **der Server selbst** von GitHub – über den Befehl `fv-web-update`,
den das Skript dort einrichtet. Updates gehen danach auch ohne das Skript.

```sh
# Nur prüfen (SSH, belegte Ports, DNS) – ändert nichts:
./setup-server-fv-web.sh -H <server> -d foerderverein-kf-jf-kreuzau.de -W -c

# Erstinstallation mit Vorstandskonto (gibt einen Link zum Setzen des Passworts aus):
./setup-server-fv-web.sh -H <server> -d foerderverein-kf-jf-kreuzau.de -W \
    -n fv-web -a vorname.nachname -m adresse@example.org

# Neue Version (main) einspielen:
ssh fkjs@<server> sudo fv-web-update

# Lokalen, noch nicht gepushten Stand testen (Skript im Repository aufrufen):
deploy/setup-server-fv-web.sh -H <server> -d foerderverein-kf-jf-kreuzau.de -U -L
```

Voraussetzung für die Erstinstallation: Anmeldung als `root` per SSH-Schlüssel. Danach
legt das Skript den Admin-Benutzer `fkjs` an und sperrt den root-Login. Alle Optionen: `-h`.

Privates Repository: mit `-R git@github.com:brami/FKJF.git` aufrufen. Der Server zeigt
dann seinen Deploy-Schlüssel an; diesen bei GitHub unter *Settings → Deploy keys* ohne
Schreibrecht eintragen und den Aufruf wiederholen.

Auf dem Server:

| Befehl | Zweck |
|---|---|
| `sudo fv-web-update [<ref>]` | Stand holen und installieren (Standard: `main`); `-f` erzwingt |
| `sudo fv-web-update --zurueck` | vorige Version wieder aktivieren |
| `sudo fv-web-update --status` | installierte Versionen anzeigen |
| `sudo fv-manage <befehl>` | Django-Befehle, z. B. `vorstand_anlegen` |
| `sudo systemctl status fv-web` / `journalctl -u fv-web` | Dienst und Protokoll |
| `sudo fv-web-backup` | Datensicherung sofort ausführen (sonst täglich ~03:30) |
| `sudo fv-web-restore -l` / `-t` | Sicherungen anzeigen / Wiederherstellung testen |
| `/etc/fv-web/env` | Einstellungen, z. B. Mailserver (`FV_MAIL=smtp`, `FV_SMTP_*`) |

**Domain ändern** (oder zum Testen eine andere Domain verwenden): Der Code ist nicht an die
Domain gebunden. Das Skript einfach mit der neuen Domain und `-U` aufrufen; es passt
Einstellungen und Caddy an und startet die Anwendung neu. Angemeldete Personen müssen sich
danach neu anmelden.

Jede Installation: Sicherung → Migration → Neustart → Statusprüfung. Startet die neue
Version nicht, wird automatisch die vorige wieder aktiviert (Migrationen werden dabei
nicht zurückgenommen).

## Übernahme aus Drupal

`scripts/drupal-export.sh` läuft als root auf dem bisherigen Drupal-Server und **ändert dort
nichts**. Es legt unter `/root/drupal-export-<zeit>/` ab:

- `sicherung/` – vollständige Sicherung (Datenbank, Dateien, settings.php) zum Aufbewahren;
  enthält Benutzerkonten und Zugangsdaten, **nicht weitergeben**
- `inhalte.tar.gz` – Übersicht und öffentliche Inhalte (Seiten, Adressen, Texte, verwendete
  Dateien) für die Übernahme

Die Inhalte gehören nicht ins Repository.

# Webseite Förderverein KF/JF Kreuzau

Django-6.1-Anwendung: öffentliche Seiten und geschützter Bereich mit Gruppenstufen
(Öffentlich < Fördermitglieder < Mitglieder < Vorstand), Anhängen mit Rechteprüfung,
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

Tests: `python -m pytest`

## Aufbau

- `seiten/rechte.py` – **die einzige Stelle**, an der über Sichtbarkeit und
  Bearbeitungsrechte entschieden wird
- `seiten/models.py` – Seite und Anhang (mit Versionsverlauf, HTML-Bereinigung)
- `seiten/views.py` – Startseite, Seitenansicht, Anhang-Download
- `seiten/konto.py` – Anmeldung (django-allauth): keine Registrierung, Einladung per
  Link, Pflicht zur Zwei-Faktor-Anmeldung für den Vorstand
- `seiten/admin.py` – Benutzerverwaltung für den Vorstand (anlegen, einladen, Gruppen)
- `seiten/bearbeiten.py` – Bearbeitung für den Vorstand: Seiten anlegen, ändern,
  löschen, Anhänge verwalten, Versionsverlauf mit Vergleich und Wiederherstellen
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

## Anmeldung und Benutzer

- Konten legt der Vorstand in der Verwaltung an (*Benutzer → Hinzufügen*): Name,
  E-Mail-Adresse, Gruppe. Ein Passwort wird nicht vergeben; die Person erhält eine
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

Jede Installation: Sicherung → Migration → Neustart → Statusprüfung. Startet die neue
Version nicht, wird automatisch die vorige wieder aktiviert (Migrationen werden dabei
nicht zurückgenommen).

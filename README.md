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

## Installation auf dem Server

Das Skript `deploy/setup-server-fv-web.sh` richtet einen Debian-13-vServer per SSH ein
und spielt die Anwendung ein (PostgreSQL, gunicorn, Caddy aus Debian; kein Docker).
Es läuft auf dem eigenen Rechner im ausgecheckten Repository und überträgt den Code
per `git archive` – auf dem Server werden keine Git-Zugangsdaten gebraucht.

```sh
# Nur prüfen (SSH, belegte Ports, DNS) – ändert nichts:
deploy/setup-server-fv-web.sh -H <server> -d foerderverein-kf-jf-kreuzau.de -W -c

# Erstinstallation mit Vorstandskonto (gibt einen Link zum Setzen des Passworts aus):
deploy/setup-server-fv-web.sh -H <server> -d foerderverein-kf-jf-kreuzau.de -W \
    -n fv-web -a vorname.nachname -m adresse@example.org

# Neue Version einspielen:
deploy/setup-server-fv-web.sh -H <server> -d foerderverein-kf-jf-kreuzau.de -U -r main
```

Voraussetzung: Anmeldung als `root` per SSH-Schlüssel. Danach legt das Skript den
Admin-Benutzer `juno` an und sperrt den root-Login. Alle Optionen: `-h`.

Auf dem Server:

| Befehl | Zweck |
|---|---|
| `sudo fv-manage <befehl>` | Django-Befehle, z. B. `vorstand_anlegen` |
| `sudo systemctl status fv-web` / `journalctl -u fv-web` | Dienst und Protokoll |
| `sudo fv-web-backup` | Datensicherung sofort ausführen (sonst täglich ~03:30) |
| `sudo fv-web-restore -l` / `-t` | Sicherungen anzeigen / Wiederherstellung testen |
| `/etc/fv-web/env` | Einstellungen, z. B. Mailserver (`FV_MAIL=smtp`, `FV_SMTP_*`) |

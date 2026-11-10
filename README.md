# Webseite Förderverein KF/JF Kreuzau

Django-6.1-Anwendung: öffentliche Seiten und geschützter Bereich mit Gruppenstufen
(Öffentlich < Fördermitglieder < Mitglieder < Vorstand), Anhängen mit Rechteprüfung,
Versionsverlauf und (in Arbeit) Newsletter.

Anforderungen: siehe Projekt-Dokument `webseite/anforderungen_django.md`.

## Entwicklung

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
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

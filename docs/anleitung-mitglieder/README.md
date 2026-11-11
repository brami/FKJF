# Anleitung für Mitglieder

`anleitung_mitglieder_webseite.pdf` – Anleitung für Personen mit Konto ohne
Bearbeitungsrechte: Einladung, Anmelden, Startseite, Beiträge und Anhänge,
Mein Konto, Passwort, Zwei-Faktor-Anmeldung, Newsletter, Smartphone, Häufige Fragen.

Layout: Vorlage `debsupport.sty` (Projektvorgabe, siehe latex/README.md im Claude-Projekt).

## PDF erzeugen

```sh
pdflatex anleitung_mitglieder_webseite.tex   # dreimal (Inhaltsverzeichnis, „Seite x von y“)
```

## Bildschirmfotos neu erzeugen (nach Änderungen an der Oberfläche)

Die Bilder stammen aus einer Testinstallation mit erfundenen Beispieldaten.

```sh
# 1. Testinstanz in einer eigenen Kopie des Repositorys (SQLite)
export FV_DEBUG=1 FV_SECRET_KEY=demo FV_MAIL=datei FV_MAIL_DATEIEN=/tmp/mails \
       FV_BASIS_URL=http://127.0.0.1:8123
python manage.py migrate && python manage.py createcachetable
python manage.py shell < docs/anleitung-mitglieder/werkzeuge/demo_daten.py
python manage.py shell -c "from django.contrib.auth.models import User; \
  from seiten.konto import sende_einladung; sende_einladung(User.objects.get(username='erika.neu'))"
python manage.py runserver 127.0.0.1:8123 --noreload &

# 2. Newsletter-Mail als HTML ablegen (siehe newsletter.baue_mail) und Fotos aufnehmen
pip install playwright        # nutzt ein installiertes Chrome/Chromium
python docs/anleitung-mitglieder/werkzeuge/fotos.py <Einladungslink aus /tmp/mails> newsletter.html
```

Danach die Ränder neben dem Seiteninhalt abschneiden (Desktop-Fotos: x = 250 … 1950)
und die Bilder nach `bilder/` kopieren.

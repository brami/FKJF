# Anleitung für den Vorstand

`anleitung_vorstand_webseite.pdf` – Zwei-Faktor-Anmeldung, Seiten anlegen/ändern/löschen,
Editor, Dateien und Bilder, Versionsverlauf, Newsletter (Probe, Pause, Abbrechen,
Protokoll), Benutzer anlegen/einladen/ändern/deaktivieren, häufige Fragen.

PDF erzeugen: `pdflatex anleitung_vorstand_webseite.tex` (dreimal).

## Bildschirmfotos neu erzeugen

Wie bei `docs/anleitung-mitglieder/`, zusätzlich:

```sh
python manage.py shell < docs/anleitung-mitglieder/werkzeuge/demo_daten.py
python manage.py shell < docs/anleitung-vorstand/werkzeuge/vorstand_daten.py
# Mailversand an einen Test-SMTP (zeigt die Erfolgsmeldungen der Verwaltung):
python -m aiosmtpd -n -l 127.0.0.1:1025 &
export FV_MAIL=smtp FV_SMTP_HOST=127.0.0.1 FV_SMTP_PORT=1025 FV_SMTP_TLS=aus FV_NEWSLETTER_PAUSE=300
python manage.py runserver 127.0.0.1:8123 --noreload &
python docs/anleitung-vorstand/werkzeuge/fotos_vorstand.py . /tmp/bilder_vorstand
```

Danach Ränder abschneiden (Webseite: x = 250 … 1950; Verwaltung je nach Bild) und
nach `bilder/` kopieren. Das Konto `vera.vorsitz` nutzt ein festes Testgeheimnis für
die Zwei-Faktor-Anmeldung (`vorstand_daten.py`) – nur für die Testinstanz.

## Lizenz

© 2026 Michael Bramer. Text, Bilder und Vorlage stehen unter
[CC BY-SA 4.0](../LICENSE) (Namensnennung: „Michael Bramer“).

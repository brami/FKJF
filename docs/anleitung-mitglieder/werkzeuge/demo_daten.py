"""Beispieldaten für die Bildschirmfotos der Mitglieder-Anleitung.

Aufruf: python manage.py shell < demo_daten.py
"""
import io
import math
import random
from datetime import date

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

from seiten.models import Anhang, Profil, Seite, Stufe

random.seed(7)


def bild(name, himmel, boden, motiv):
    """Einfaches gezeichnetes Bild (keine echten Fotos)."""
    w, h = 1600, 1000
    img = Image.new("RGB", (w, h), himmel)
    d = ImageDraw.Draw(img)
    for y in range(h // 2):   # Verlauf am Himmel
        t = y / (h / 2)
        c = tuple(int(himmel[i] * (1 - t) + 255 * t * 0.35 + himmel[i] * 0.65 * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    d.rectangle([0, int(h * 0.62), w, h], fill=boden)
    d.ellipse([w - 300, 80, w - 160, 220], fill=(255, 221, 120))
    if motiv == "zelte":
        for i, x in enumerate(range(150, w - 200, 330)):
            farbe = [(200, 40, 40), (240, 240, 240), (40, 90, 170), (230, 160, 30)][i % 4]
            d.polygon([(x, 620), (x + 130, 430), (x + 260, 620)], fill=farbe, outline=(60, 60, 60))
            d.polygon([(x + 110, 620), (x + 130, 520), (x + 150, 620)], fill=(50, 50, 50))
    elif motiv == "fahrzeug":
        d.rectangle([380, 420, 1180, 640], fill=(196, 20, 28))
        d.rectangle([1180, 470, 1380, 640], fill=(196, 20, 28))
        d.rectangle([1210, 495, 1340, 570], fill=(180, 210, 235))
        d.rectangle([420, 450, 1140, 500], fill=(235, 235, 235))
        for x in (520, 900, 1260):
            d.ellipse([x - 70, 590, x + 70, 730], fill=(30, 30, 30))
            d.ellipse([x - 30, 630, x + 30, 690], fill=(160, 160, 160))
        d.rectangle([600, 395, 960, 420], fill=(120, 120, 120))
    elif motiv == "wasser":
        for k in range(14):
            x0 = 300 + k * 18
            pts = [(x0 + s * 6, 600 - 380 * math.sin(math.pi * s / 120) + s * 1.2) for s in range(0, 121, 4)]
            d.line(pts, fill=(90, 160, 230), width=6)
        d.rectangle([180, 560, 330, 640], fill=(196, 20, 28))
        for x in range(1050, 1450, 60):
            d.ellipse([x, 600, x + 50, 650], fill=(70, 130, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def pdf(name, text):
    inhalt = f"%PDF-1.4\n% {text}\n%%EOF\n".encode()
    return SimpleUploadedFile(name, inhalt, content_type="application/pdf")


S = {s.name: s for s in Stufe.objects.all()}

max_ = User.objects.create_user("max.mustermann", "max.mustermann@example.org", "Anleitung-2026!",
                                first_name="Max", last_name="Mustermann")
max_.groups.add(S["Mitglieder"].gruppe)
mia = User.objects.create_user("mia.beispiel", "mia.beispiel@example.org", "Anleitung-2026!",
                               first_name="Mia", last_name="Beispiel")
mia.groups.add(S["Mitglieder"].gruppe)
Profil.objects.update_or_create(user=mia, defaults={"vereins_email": "mia.beispiel@foerderverein-kf-jf-kreuzau.de"})
neu = User.objects.create_user("erika.neu", "erika.neu@example.org", first_name="Erika", last_name="Neu")
neu.set_unusable_password()
neu.save()
neu.groups.add(S["Mitglieder"].gruppe)

Seite.objects.create(
    titel="Spenden für die Jugendarbeit", datum=date(2026, 9, 1), stufe=None,
    inhalt="<p>Mit Ihrer Spende unterstützen Sie die Kinder- und Jugendfeuerwehr Kreuzau: "
           "Ausrüstung, Zeltlager, Ausflüge und Ausbildung. Jeder Betrag hilft.</p>"
           "<p>Eine Spendenquittung stellen wir gern aus.</p>")

fest = Seite.objects.create(
    titel="Sommerfest der Jugendfeuerwehr", datum=date(2026, 10, 18), stufe=None,
    inhalt="<p>Bei bestem Wetter haben über 200 Gäste unser Sommerfest besucht. Die "
           "Jugendfeuerwehr zeigte eine Löschübung, die Kinderfeuerwehr betreute die Spielstraße.</p>"
           "<p>Vielen Dank an alle Helferinnen und Helfer!</p>")
Anhang.objects.create(seite=fest, datei=bild("fahrzeug.jpg", (120, 170, 220), (90, 150, 80), "fahrzeug"),
                      bezeichnung="Das neue Löschfahrzeug", titelbild=True)
Anhang.objects.create(seite=fest, datei=bild("loeschuebung.jpg", (140, 185, 230), (95, 145, 85), "wasser"),
                      bezeichnung="Löschübung der Jugendfeuerwehr")
Anhang.objects.create(seite=fest, datei=bild("zelte.jpg", (110, 160, 215), (100, 155, 90), "zelte"),
                      bezeichnung="Spielstraße")

jhv = Seite.objects.create(
    titel="Einladung zur Jahreshauptversammlung 2027", datum=date(2026, 11, 10), stufe=S["Mitglieder"],
    inhalt="<p>Liebe Mitglieder,</p><p>hiermit laden wir Sie herzlich zur Jahreshauptversammlung "
           "am <strong>Freitag, 12. März 2027, um 19:30 Uhr</strong> im Gerätehaus Kreuzau ein.</p>"
           "<p>Tagesordnung:</p><ol><li>Begrüßung</li><li>Bericht des Vorstands</li>"
           "<li>Kassenbericht und Bericht der Kassenprüfer</li><li>Entlastung des Vorstands</li>"
           "<li>Wahlen</li><li>Verschiedenes</li></ol>"
           "<p>Die vollständige Einladung und den Kassenbericht finden Sie unten als Anhang.</p>"
           "<p>Mit freundlichen Grüßen<br>Der Vorstand</p>")
Anhang.objects.create(seite=jhv, datei=pdf("Einladung_JHV_2027.pdf", "Einladung"),
                      bezeichnung="Einladung mit Tagesordnung")
Anhang.objects.create(seite=jhv, datei=pdf("Kassenbericht_2026.pdf", "Kassenbericht"),
                      bezeichnung="Kassenbericht 2026")

Seite.objects.create(
    titel="Arbeitseinsatz am Gerätehaus", datum=date(2026, 10, 30), stufe=S["Mitglieder"],
    inhalt="<p>Am Samstag, 21. November, räumen wir ab 10 Uhr das Lager auf. "
           "Wer helfen kann, meldet sich bitte beim Vorstand.</p>")
Seite.objects.create(
    titel="Danke an unsere Fördermitglieder", datum=date(2026, 8, 20), stufe=S["Fördermitglieder"],
    inhalt="<p>Dank Ihrer Beiträge konnten wir neue Helme für die Jugendfeuerwehr anschaffen.</p>")
Seite.objects.create(
    titel="Protokoll Vorstandssitzung November", datum=date(2026, 11, 5), stufe=S["Vorstand"],
    inhalt="<p>Nur für den Vorstand.</p>")

print("Demo-Daten angelegt.")

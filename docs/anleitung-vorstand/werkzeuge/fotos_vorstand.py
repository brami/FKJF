"""Bildschirmfotos für die Vorstands-Anleitung (headless Chrome).

Aufruf (Testinstanz läuft auf 127.0.0.1:8123, Daten aus demo_daten.py + vorstand_daten.py):
    python fotos_vorstand.py <Pfad zur App> <Zielordner>
"""
import io
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

BASIS = "http://127.0.0.1:8123"
APP = Path(sys.argv[1])
ZIEL = Path(sys.argv[2])
ZIEL.mkdir(parents=True, exist_ok=True)
PW = "Anleitung-2026!"
GEHEIM = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
DATEIEN = ZIEL.parent / "beispieldateien"
DATEIEN.mkdir(exist_ok=True)


def django(code):
    """Python-Code in der Testinstanz ausführen (z. B. Versanddienst einen Schritt)."""
    subprocess.run([sys.executable, "manage.py", "shell", "-c", code], cwd=APP, check=True,
                   env=os.environ, capture_output=True)


def totp_code():
    import base64, hashlib, hmac, struct
    key = base64.b32decode(GEHEIM)
    zaehler = int(time.time()) // 30
    h = hmac.new(key, struct.pack(">Q", zaehler), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def beispieldateien():
    for name, farbe in [("rauchmelder.jpg", (196, 20, 28)), ("gruppenfoto.jpg", (40, 90, 170))]:
        img = Image.new("RGB", (1200, 800), (150, 190, 230))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 520, 1200, 800], fill=(95, 150, 85))
        for x in range(150, 1050, 150):
            d.ellipse([x, 300, x + 80, 380], fill=(240, 200, 170))
            d.rectangle([x - 10, 380, x + 90, 560], fill=farbe)
        img.save(DATEIEN / name, quality=85)
    (DATEIEN / "Flyer_Rauchmelder.pdf").write_bytes(b"%PDF-1.4\n% Beispiel\n%%EOF\n")


def foto(page, name, ganz=False, element=None):
    page.wait_for_load_state("networkidle")
    pfad = ZIEL / f"{name}.png"
    if element:
        page.locator(element).first.screenshot(path=pfad)
    else:
        page.screenshot(path=pfad, full_page=ganz)
    print("✓", name)


beispieldateien()
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])

    def neu(breite=1100, hoehe=760):
        return browser.new_context(viewport={"width": breite, "height": hoehe},
                                   device_scale_factor=2, locale="de-DE", bypass_csp=True).new_page()

    # --- Erste Anmeldung eines neuen Vorstandsmitglieds: Zwei-Faktor ist Pflicht
    n = neu()
    n.goto(BASIS + "/konto/login/")
    n.fill("input[name=login]", "victor.neu")
    n.fill("input[name=password]", PW)
    n.click("button[type=submit]")
    n.goto(BASIS + "/")            # jede Seite führt zur Einrichtung
    foto(n, "v01_zwei_faktor_pflicht", ganz=True)

    # --- Anmeldung mit Code
    v = neu()
    v.goto(BASIS + "/konto/login/")
    v.fill("input[name=login]", "vera.vorsitz")
    v.fill("input[name=password]", PW)
    v.click("button[type=submit]")
    v.wait_for_load_state("networkidle")
    foto(v, "v02_code_eingeben")
    v.fill("input[name=code]", totp_code())
    v.click("button[type=submit]")
    v.wait_for_load_state("networkidle")
    v.goto(BASIS + "/")
    foto(v, "v03_startseite_vorstand")
    foto(v, "v03b_kopfzeile_vorstand", element="header")

    # --- Neue Seite
    v.click("text=+ Neue Seite")
    v.wait_for_function("window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized")
    foto(v, "v04_neue_seite_leer", ganz=True)
    v.fill("input[name=titel]", "Rauchmelder-Aktion der Jugendfeuerwehr")
    v.select_option("select[name=stufe]", label="Öffentlich (ohne Anmeldung)")
    v.evaluate("""tinymce.activeEditor.setContent(
      '<p>Am <strong>Samstag, 28. November</strong> informiert die Jugendfeuerwehr von 10 bis 14 Uhr '
      + 'vor dem Rathaus über Rauchmelder.</p><h2>Was erwartet Sie?</h2><ul><li>Vorführung im '
      + 'Rauchhaus</li><li>Beratung zum richtigen Einbau</li><li>Rauchmelder zum Selbstkostenpreis</li></ul>'
      + '<p>Weitere Informationen finden Sie im <a href="https://www.rauchmelder-lebensretter.de">'
      + 'Infoportal</a> und im angehängten Flyer.</p>')""")
    v.set_input_files("input[name=dateien]", [str(DATEIEN / "rauchmelder.jpg"),
                                               str(DATEIEN / "gruppenfoto.jpg"),
                                               str(DATEIEN / "Flyer_Rauchmelder.pdf")])
    foto(v, "v05_neue_seite_ausgefuellt", ganz=True)
    foto(v, "v05b_werkzeugleiste", element=".tox-editor-header")
    v.click("button:has-text('Speichern')")
    v.wait_for_load_state("networkidle")
    foto(v, "v06_seite_gespeichert", ganz=True)
    seite_url = v.url

    # --- Bearbeiten: Anhänge verwalten
    v.click("text=Bearbeiten")
    v.wait_for_function("window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized")
    v.locator("input[name$=bezeichnung]").nth(0).fill("Jugendfeuerwehr am Rauchhaus")
    v.locator("input[name$=bezeichnung]").nth(2).fill("Flyer zur Aktion (PDF)")
    foto(v, "v07_anhaenge", element="fieldset.anhaenge")
    v.evaluate("""tinymce.activeEditor.setContent(tinymce.activeEditor.getContent()
      .replace('10 bis 14 Uhr', '10 bis 15 Uhr'))""")
    v.click("button:has-text('Speichern')")
    v.wait_for_load_state("networkidle")

    # --- Versionsverlauf
    v.click("text=Versionsverlauf")
    foto(v, "v08_verlauf")
    v.click("text=Ansehen und vergleichen")
    foto(v, "v09_fassung", ganz=True)

    # --- Löschen (nur Bestätigungsseite)
    v.goto(seite_url)
    v.click("text=Löschen")
    foto(v, "v10_loeschen")

    # --- Newsletter
    v.goto(BASIS + "/")
    v.click("h2 >> text=Einladung zur Jahreshauptversammlung 2027")
    v.click("text=Als Newsletter versenden")
    v.fill("textarea[name=ankuendigung]",
           "Liebe Mitglieder,\nbitte merken Sie sich den Termin vor. Die Einladung mit "
           "Tagesordnung hängt an.")
    v.check("input[name=mit_anhaengen]")
    foto(v, "v11_newsletter_formular", ganz=True)
    v.click("button:has-text('Versand starten')")
    v.wait_for_load_state("networkidle")
    django("from seiten import newsletter; newsletter.herzschlag(); newsletter.schritt()")
    v.reload()
    foto(v, "v12_newsletter_pause", ganz=True)
    v.click("button:has-text('jetzt an alle senden')")
    v.wait_for_load_state("networkidle")
    django("from seiten import newsletter\nfor _ in range(20): newsletter.schritt()\n"
           "newsletter.herzschlag()")
    v.reload()
    foto(v, "v13_newsletter_fertig", ganz=True)
    v.goto(BASIS + "/newsletter/")
    foto(v, "v14_newsletter_uebersicht")

    # --- Verwaltung: Benutzer (breiteres Fenster, die Liste hat viele Spalten)
    v.set_viewport_size({"width": 1400, "height": 800})
    v.goto(BASIS + "/verwaltung/")
    foto(v, "v15_verwaltung")
    v.goto(BASIS + "/verwaltung/auth/user/")
    foto(v, "v16_benutzerliste", ganz=True)
    v.goto(BASIS + "/verwaltung/auth/user/add/")
    v.fill("input[name=username]", "lena.lustig")
    v.fill("input[name=first_name]", "Lena")
    v.fill("input[name=last_name]", "Lustig")
    v.fill("input[name=email]", "lena.lustig@example.org")
    v.get_by_label("Mitglieder", exact=True).check()
    foto(v, "v17_benutzer_anlegen", ganz=True)
    v.click("input[name=_save]")
    v.wait_for_load_state("networkidle")
    foto(v, "v18_benutzer_angelegt")
    v.goto(BASIS + "/verwaltung/auth/user/")
    v.click("text=mia.beispiel")
    foto(v, "v19_benutzer_bearbeiten", ganz=True)
    v.goto(BASIS + "/verwaltung/auth/user/")
    v.check("tr:has-text('hans.ohne') >> input.action-select")
    v.check("tr:has-text('tom.kessler') >> input.action-select")
    v.select_option("select[name=action]", "einladung_senden")
    foto(v, "v20_aktion_einladen", element="#changelist-form")
    v.click("button[name=index]")
    v.wait_for_load_state("networkidle")
    foto(v, "v21_einladung_meldungen", element="ul.messagelist")

    browser.close()

"""Bildschirmfotos für die Mitglieder-Anleitung (headless Chrome)."""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASIS = "http://127.0.0.1:8123"
ZIEL = Path(__file__).parent / "bilder"
ZIEL.mkdir(exist_ok=True)
EINLADUNG = sys.argv[1]
NEWSLETTER_HTML = Path(sys.argv[2])
PW = "Anleitung-2026!"


def foto(page, name, ganz=False, element=None):
    page.wait_for_load_state("networkidle")
    pfad = ZIEL / f"{name}.png"
    if element:
        page.locator(element).first.screenshot(path=pfad)
    else:
        page.screenshot(path=pfad, full_page=ganz)
    print("✓", name)


def anmelden(page, wer):
    page.goto(BASIS + "/konto/login/")
    page.fill("input[name=login]", wer)
    page.fill("input[name=password]", PW)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    def neu(breite=1100, hoehe=760, scale=2, mobil=False):
        return browser.new_context(viewport={"width": breite, "height": hoehe},
                                   device_scale_factor=scale, is_mobile=mobil, has_touch=mobil,
                                   locale="de-DE").new_page()

    # Gast
    g = neu()
    g.goto(BASIS + "/")
    foto(g, "01_startseite_gast")
    g.goto(BASIS + "/konto/login/")
    foto(g, "03_anmelden")
    g.fill("input[name=login]", "max.mustermann")
    foto(g, "03b_anmelden_ausgefuellt")
    g.goto(BASIS + "/konto/password/reset/")
    foto(g, "09_passwort_vergessen")
    g.fill("input[name=email]", "max.mustermann@example.org")
    g.click("button[type=submit]")
    foto(g, "09b_passwort_vergessen_gesendet")

    # Einladung: Passwort festlegen
    e = neu()
    e.goto(EINLADUNG)
    foto(e, "02_passwort_festlegen")

    # Mitglied
    m = neu()
    anmelden(m, "max.mustermann")
    foto(m, "04_startseite_mitglied")
    foto(m, "04b_kopfzeile", element="header")
    m.click("text=Einladung zur Jahreshauptversammlung 2027")
    foto(m, "05_seite_jhv", ganz=True)
    m.goto(BASIS + "/")
    m.click("h2 >> text=Sommerfest der Jugendfeuerwehr")
    foto(m, "06_seite_fest", ganz=True)
    m.goto(BASIS + "/konto/")
    foto(m, "07_mein_konto", ganz=True)
    m.goto(BASIS + "/konto/password/change/")
    foto(m, "08_passwort_aendern")
    m.goto(BASIS + "/konto/2fa/totp/activate")
    foto(m, "10_zwei_faktor", ganz=True)

    # Mitglied mit Vereinsadresse: Wahl der Zustelladresse
    v = neu()
    anmelden(v, "mia.beispiel")
    v.goto(BASIS + "/konto/")
    foto(v, "07b_konto_vereinsmails", ganz=True)

    # Newsletter-E-Mail, wie sie im Postfach aussieht
    n = neu(breite=760, hoehe=900)
    n.goto(NEWSLETTER_HTML.resolve().as_uri())
    foto(n, "11_newsletter_mail", ganz=True)

    # Handy
    h = neu(breite=390, hoehe=780, scale=3, mobil=True)
    anmelden(h, "max.mustermann")
    foto(h, "12_handy_startseite")

    browser.close()

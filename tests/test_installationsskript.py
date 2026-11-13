"""Strukturprüfungen für das Installationsskript (ergänzend zu shellcheck).

shellcheck kann nicht erkennen, wenn das Skript auf dem Server eine Funktion aufruft,
die nur im eingebetteten Befehl fv-web-update definiert ist – genau so ein Fehler
hätte einmal die Erstinstallation abgebrochen.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parent.parent / "deploy" / "setup-server-fv-web.sh"
TEXT = SKRIPT.read_text()


def zwischen(text, start, ende):
    return text.split(start, 1)[1].split(ende, 1)[0]


REMOTE = zwischen(TEXT, "REMOTE_SCRIPT=$(cat <<'REMOTE'\n", "\nREMOTE\n)")
UPDATE = zwischen(REMOTE, "<<'UPDATE'\n", "\nUPDATE\n")
BACKUP = zwischen(REMOTE, "<<'BACKUP'\n", "\nBACKUP\n")
RESTORE = zwischen(REMOTE, "<<'RESTORE'\n", "\nRESTORE\n")
# Server-Skript ohne die eingebetteten Programme
REMOTE_SELBST = REMOTE
for teil in (UPDATE, BACKUP, RESTORE):
    REMOTE_SELBST = REMOTE_SELBST.replace(teil, "")


def funktionen(text):
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", text, re.M))


def test_syntax():
    for name, text in [("Skript", TEXT), ("fv-web-update", UPDATE)]:
        r = subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True)
        assert r.returncode == 0, (name, r.stderr)


def test_server_skript_ruft_keine_funktionen_von_fv_web_update_auf():
    nur_im_update = funktionen(UPDATE) - funktionen(REMOTE_SELBST)
    for name in sorted(nur_im_update):
        # nur Aufrufe am Anfang eines Befehls (nicht z. B. "ufw status")
        befehl = rf"(^\s*|[;&|(]\s*|\b(then|do|else)\s+){name}(\s|;|$)"
        assert not re.search(befehl, REMOTE_SELBST, re.M), \
            f"{name} ist nur in fv-web-update definiert, wird aber im Server-Skript aufgerufen"


def test_alle_phasen_definiert():
    aufrufe = set(re.findall(r"^\s+\w+\)\s+(phase_\w+) ;;", REMOTE_SELBST, re.M))
    assert aufrufe and aufrufe <= funktionen(REMOTE_SELBST)


@pytest.mark.parametrize("paket", ["git", "postgresql", "caddy", "python3-venv", "restic"])
def test_benoetigte_pakete(paket):
    pakete = zwischen(REMOTE_SELBST, "apt_install ca-certificates", "\n  log ")
    assert re.search(rf"\b{re.escape(paket)}\b", pakete), f"Paket {paket} wird nicht installiert"


def test_update_braucht_git_und_holt_per_git():
    assert "git -C \"$WORK\" fetch" in UPDATE


def _funktion(text, name):
    """Quelltext einer Bash-Funktion: vom Kopf bis zur nächsten Funktionsdefinition
    (Heredocs wie die Caddy-Konfiguration enthalten selbst "}" am Zeilenanfang)."""
    m = re.search(rf"^{name}\(\) \{{", text, re.M)
    assert m, name
    weiter = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\(\) \{", re.M).search(text, m.end())
    return text[m.start():weiter.start() if weiter else len(text)]


@pytest.mark.skipif(subprocess.run(["which", "caddy"], capture_output=True).returncode != 0,
                    reason="caddy nicht installiert")
@pytest.mark.parametrize("mail", [False, True])
@pytest.mark.parametrize("modus", ["app", "platzhalter"])
def test_caddyfile_gueltig_und_mit_wartungsseite(tmp_path, modus, mail):
    """Die von fv-web-update erzeugte Caddy-Konfiguration ist gültig (echtes caddy validate);
    im Anwendungsbetrieb zeigt sie bei 502/503/504 die Wartungsseite."""
    funktionen_text = _funktion(UPDATE, "wartungsseite") + _funktion(UPDATE, "write_caddyfile")
    # in eine Sandbox umlenken: Zielpfade, Dienstverwaltung, Besitzrechte
    funktionen_text = (funktionen_text
                       .replace("/etc/caddy/Caddyfile", str(tmp_path / "Caddyfile"))
                       .replace("install -d -o root -g root -m 755", "install -d -m 755"))
    skript = f"""
set -euo pipefail
DATA={tmp_path}/data; DOMAIN=foerderverein.example; WITH_WWW=1; ACME_EMAIL=a@example.org
MAIL_HOST={"mail.foerderverein.example" if mail else '""'}; MAIL_WEB={"mta-sts.foerderverein.example" if mail else '""'}
ZUSATZ_DOMAINS={'"xn--frderverein-yrc.example kurz.example"' if mail else '""'}
log() {{ echo "$*"; }}
systemctl() {{ :; }}
{funktionen_text}
write_caddyfile {modus}
"""
    r = subprocess.run(["bash", "-c", skript], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    caddyfile = (tmp_path / "Caddyfile").read_text()
    v = subprocess.run(["caddy", "validate", "--adapter", "caddyfile",
                        "--config", str(tmp_path / "Caddyfile")], capture_output=True, text=True)
    assert v.returncode == 0, v.stdout + v.stderr
    if modus == "app":
        assert "handle_errors" in caddyfile and "/var/lib/fv-web/wartung" in caddyfile
        seite = (tmp_path / "data" / "wartung" / "index.html").read_text()
        assert "wird gerade aktualisiert" in seite
    else:
        assert "handle_errors" not in caddyfile
    if mail:
        assert "http://mail.foerderverein.example {" in caddyfile
        assert "/var/lib/fv-mail/acme" in caddyfile
        assert "mta-sts.foerderverein.example {" in caddyfile
        assert ("/.well-known/autoconfig/*" in caddyfile) == (modus == "app")
        # weitere Domains (mit und ohne www) leiten auf die Hauptdomain um
        assert "xn--frderverein-yrc.example, www.xn--frderverein-yrc.example {" in caddyfile
        assert "kurz.example, www.kurz.example {" in caddyfile
    else:
        assert "fv-mail" not in caddyfile


# ------------------------------------------------------------- Mailserver (-M)

def _heredoc(text, marke):
    m = re.search(rf"<<'{marke}'\n(.*?)\n{marke}\n", text, re.S)
    assert m, marke
    return m.group(1)


MAIL = zwischen(REMOTE, "phase_mail() {\n", "# ------------------------------------------------------------ Phase summary")


def test_mail_phase_eingebunden():
    assert "M) WITH_MAIL=1" in TEXT and "P) POSTMASTER=" in TEXT
    assert "mail)    phase_mail ;;" in REMOTE
    assert 'run_remote mail <<<"$REMOTE_SCRIPT"' in TEXT
    for paket in ("exim4-daemon-heavy", "dovecot-pgsql", "dovecot-sieve", "dovecot-lmtpd",
                  "dovecot-managesieved", "rspamd", "redis-server", "unbound", "certbot"):
        assert paket in MAIL, paket


def test_mail_rechte_in_update_und_phase_gleich():
    """Die Leserechte auf die Sichten stehen in fv-web-update und in phase_mail gleich."""
    rechte = _heredoc(_funktion(REMOTE, "mail_rechte_sql"), "SQL")
    assert rechte in UPDATE
    for sicht in ("dovecot_benutzer", "exim_adressen", "exim_verteiler", "exim_absender",
                  "exim_plus_gesperrt", "mail_archive"):
        assert sicht in rechte


def test_datensicherung_mit_postfaechern():
    assert "/var/vmail" in BACKUP and "/etc/fv-mail" in BACKUP


def test_mail_konfigurationen_ohne_platzhalterreste():
    for marke in ("EXIM", "DOVECOT", "FILTER"):
        text = _heredoc(MAIL, marke)
        assert set(re.findall(r"@[A-Z_]+@", text)) <= {"@DOMAIN@", "@HOST@", "@VMAIL_UID@",
                                                         "@QUOTA@", "@LISTEN@", "@ZUSATZ@"}, marke
    dovecot = _heredoc(MAIL, "DOVECOT")
    assert "dovecot_config_version = 2.4" in dovecot
    assert "passwort IS NOT NULL" in dovecot          # Postfach ohne Passwort: Zustellung ja, Anmeldung nein
    assert "autoexpunge = 90d" in dovecot


def test_fv_mail_werkzeug_shellcheck(tmp_path):
    datei = tmp_path / "fv-mail"
    datei.write_text(_heredoc(MAIL, "FVMAIL"))
    r = subprocess.run(["bash", "-n", str(datei)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if subprocess.run(["which", "shellcheck"], capture_output=True).returncode == 0:
        r = subprocess.run(["shellcheck", "-S", "warning", "-s", "bash", str(datei)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


EXIM_DA = subprocess.run(["which", "exim"], capture_output=True).returncode == 0


def _exim_konfig(tmp_path, zusatz=""):
    makros = tmp_path / "fv-makros.conf"
    makros.write_text("FV_DOMAIN = verein.example\nFV_HOST = mail.verein.example\n"
                      "FV_DKIM_SELEKTOR = fv2026\nFV_SRS_GEHEIMNIS = geheim\n"
                      f"FV_ZUSATZ = {zusatz}\n")
    konfig = tmp_path / "exim4.conf"
    konfig.write_text(_heredoc(MAIL, "EXIM").replace("/etc/exim4/fv-makros.conf", str(makros)))
    return konfig


@pytest.mark.skipif(not EXIM_DA, reason="exim nicht installiert")
def test_exim_konfiguration_gueltig(tmp_path):
    konfig = _exim_konfig(tmp_path)
    r = subprocess.run(["exim", "-C", str(konfig), "-bV"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    # SRS hin und zurück mit dem Geheimnis aus den Makros
    r = subprocess.run(["exim", "-C", str(konfig), "-be",
                        "${if inbound_srs{${local_part:${srs_encode{geheim}{a@b.example}{verein.example}}}}"
                        "{geheim}{$srs_recipient}{nein}}"], capture_output=True, text=True)
    assert r.stdout.strip() == "a@b.example", r.stdout + r.stderr


@pytest.mark.skipif(not EXIM_DA, reason="exim nicht installiert")
@pytest.mark.parametrize("zusatz", ["", "kurz.example : xn--frderverein-yrc.example"])
def test_exim_relay_und_anmeldung(tmp_path, zusatz):
    """Ohne Datenbank prüfbar: kein offenes Relay; Mailprogramm-Ports nur mit Anmeldung;
    weitere Domains (-A) gelten als eigene, Archiv bleibt auch dort gesperrt."""
    konfig = _exim_konfig(tmp_path, zusatz)

    def sitzung(port, ziel):
        r = subprocess.run(["exim", "-C", str(konfig), "-bh", "192.0.2.10", "-oMi", f"192.0.2.1.{port}"],
                           input=f"HELO t.example\r\nMAIL FROM:<x@extern.example>\r\nRCPT TO:<{ziel}>\r\nQUIT\r\n",
                           capture_output=True, text=True)
        return [z for z in r.stdout.splitlines() if re.match(r"^\d{3} ", z)]

    assert "550 Weiterleitung nicht erlaubt" in sitzung(25, "a@anders.example")
    assert "550 Bitte zuerst anmelden" in sitzung(587, "a@anders.example")
    assert "550 Unbekannte Adresse" in sitzung(25, "fv-archiv+vorstand@verein.example")
    if zusatz:
        assert "550 Weiterleitung nicht erlaubt" not in sitzung(25, "vera@kurz.example")
        assert "550 Unbekannte Adresse" in sitzung(25, "fv-archiv+vorstand@kurz.example")
    else:
        assert "550 Weiterleitung nicht erlaubt" in sitzung(25, "vera@kurz.example")


@pytest.mark.skipif(subprocess.run(["which", "rspamadm"], capture_output=True).returncode != 0,
                    reason="rspamd nicht installiert")
def test_rspamd_force_actions_syntax(tmp_path):
    datei = tmp_path / "force_actions.conf"
    m = re.search(r"cat > /etc/rspamd/local.d/force_actions.conf <<'RSPAMD'\n(.*?)\nRSPAMD\n", MAIL, re.S)
    assert m
    datei.write_text(m.group(1))
    assert 'action = "reject"' in m.group(1) and "MIME_BAD_EXTENSION" in m.group(1)


# ------------------------------------------------------- Einstellungsdatei (-f)

def _aufruf(tmp_path, *argumente, umgebung=None):
    """Skript mit einem ssh, das immer scheitert: läuft bis zur Verbindung, d. h.
    Optionen, Einstellungsdatei und Prüfungen werden echt ausgeführt."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "ssh").write_text("#!/bin/sh\nexit 255\n")
    (bindir / "ssh").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "MAIL_HOST"}
    env.update({"PATH": f"{bindir}:{os.environ['PATH']}", **(umgebung or {})})
    return subprocess.run(["bash", str(SKRIPT), *argumente, "-y"], cwd=tmp_path,
                          capture_output=True, text=True, env=env)


def _werte(datei):
    return dict(re.findall(r'^([A-Z_]+)="(.*)"$', datei.read_text(), re.M))


PUNY = "förderverein.example".encode("idna").decode()   # xn--frderverein-rfb.example


def test_einstellungsdatei_merkt_sich_optionen(tmp_path):
    datei = tmp_path / "kreuzau.env"
    _aufruf(tmp_path, "-f", str(datei), "-H", "203.0.113.10", "-d", "verein.example",
            "-W", "-M", "-P", "betreuung@example.org", "-B", "sftp://u@h:23/fv")
    w = _werte(datei)
    assert w["SERVER"] == "203.0.113.10" and w["DOMAIN"] == "verein.example"
    assert w["WITH_WWW"] == "1" and w["WITH_MAIL"] == "1"
    assert w["POSTMASTER"] == "betreuung@example.org" and w["BACKUP_REPO"] == "sftp://u@h:23/fv"
    assert w["MAIL_HOST"] == ""                     # Standard mail.<domain> wird nicht festgeschrieben
    # weitere Domains: mehrfach, Umlaut als Punycode, ohne Doppelte, kommen dazu
    r = _aufruf(tmp_path, "-f", str(datei), "-A", "Förderverein.example", "-A", "kurz.example",
                "-A", "kurz.example")
    assert _werte(datei)["ZUSATZ_DOMAINS"] == f"{PUNY} kurz.example"
    _aufruf(tmp_path, "-f", str(datei), "-A", "noch.example")
    assert _werte(datei)["ZUSATZ_DOMAINS"] == f"{PUNY} kurz.example noch.example"
    r = _aufruf(tmp_path, "-f", str(datei), "-A", "verein.example")
    assert r.returncode == 2 and "gleich der Domain" in r.stderr
    datei.write_text(datei.read_text().replace(" noch.example", ""))
    # später nur -U: nichts geht verloren, Datei bleibt gleich
    vorher = datei.read_text()
    r = _aufruf(tmp_path, "-f", str(datei), "-U")
    assert datei.read_text() == vorher
    assert "Einstellungen aktualisiert" not in r.stdout
    # Änderung per Option wird gemeldet und gespeichert
    r = _aufruf(tmp_path, "-f", str(datei), "-X", "smtp.verein.example")
    assert 'geändert: MAIL_HOST "" → "smtp.verein.example"' in r.stdout
    assert _werte(datei)["MAIL_HOST"] == "smtp.verein.example"
    # -c ändert die Datei nicht
    vorher = datei.read_text()
    _aufruf(tmp_path, "-f", str(datei), "-t", "UTC", "-c")
    assert datei.read_text() == vorher


def test_einstellungsdatei_wird_geprueft(tmp_path):
    datei = tmp_path / "x.env"
    datei.write_text('SERVER="203.0.113.10"\nDOMAIN="verein.example"\nWITH_WWW="ja"\n')
    r = _aufruf(tmp_path, "-f", str(datei))
    assert r.returncode == 2 and "WITH_WWW muss 0 oder 1 sein" in r.stderr
    datei.write_text('SERVER="203.0.113.10"\nDOMAIN="verein.example"\nRM="$(rm -rf /)"\n')
    r = _aufruf(tmp_path, "-f", str(datei))
    assert r.returncode == 2 and "unbekannte Einstellung RM" in r.stderr
    datei.write_text('SERVER="203.0.113.10"\nDOMAIN="$(touch boese)"\n')
    _aufruf(tmp_path, "-f", str(datei))
    assert not (tmp_path / "boese").exists()        # Datei wird gelesen, nicht ausgeführt


def test_vorhandenes_www_bleibt_erhalten():
    """Ohne -W wird ein auf dem Server eingerichtetes www nicht stillschweigend entfernt."""
    assert "grep -q '^WITH_WWW=\"1\"' /etc/fv-web/deploy.env" in TEXT
    assert "bleibt erhalten (wie -W)" in TEXT


# ------------------------------------------------------------ Überwachung (/health)

def test_fv_web_status_eingerichtet(tmp_path):
    werkzeug = zwischen(REMOTE, "phase_tool() {\n", "# --------------------------------------------------------------- Phase app")
    assert 'set_kv "$ENVF" FV_STATUS_DATEI "/var/lib/fv-web-status/status.json"' in werkzeug
    assert "fv-web-status.timer" in werkzeug and "OnUnitActiveSec=5min" in werkzeug
    assert "/var/lib/fv-web-status/sicherung" in BACKUP       # Marke der letzten Sicherung
    datei = tmp_path / "fv-web-status"
    datei.write_text(_heredoc(REMOTE, "STATUS"))
    r = subprocess.run(["bash", "-n", str(datei)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if subprocess.run(["which", "shellcheck"], capture_output=True).returncode == 0:
        r = subprocess.run(["shellcheck", "-S", "warning", "-s", "bash", str(datei)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout

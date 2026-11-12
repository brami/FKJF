"""Strukturprüfungen für das Installationsskript (ergänzend zu shellcheck).

shellcheck kann nicht erkennen, wenn das Skript auf dem Server eine Funktion aufruft,
die nur im eingebetteten Befehl fv-web-update definiert ist – genau so ein Fehler
hätte einmal die Erstinstallation abgebrochen.
"""

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
@pytest.mark.parametrize("modus", ["app", "platzhalter"])
def test_caddyfile_gueltig_und_mit_wartungsseite(tmp_path, modus):
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

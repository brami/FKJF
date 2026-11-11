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

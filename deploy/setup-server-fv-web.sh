#!/usr/bin/env bash
# =============================================================================
#  setup-server-fv-web.sh – Einrichtung des Webservers des Fördervereins KF/JF Kreuzau
#
#  Läuft auf DEINEM Rechner und richtet den vServer per SSH ein.
#  Ziel: Debian 13 (trixie), Grundinstallation. Das Skript kann allein liegen;
#  ein ausgechecktes Repository ist nur für -L nötig.
#  Reproduzierbar: Jeder Schritt prüft, ob er schon erledigt ist, und kann
#  beliebig oft erneut ausgeführt werden.
#
#  Aufbau auf dem Server (nur Debian-Pakete, kein Docker)
#    PostgreSQL 17      Datenbank "fvweb", Anmeldung über den Unix-Socket (ohne Passwort)
#    Python 3.13        Anwendung in einer virtuellen Umgebung je Version
#    gunicorn           Dienst fv-web.service als Benutzer "fvweb"
#    Newsletter         Dienst fv-web-newsletter.service (Versand im Hintergrund)
#    Caddy              HTTPS mit automatischem Zertifikat, statische Dateien
#    restic             tägliche, verschlüsselte Datensicherung
#    fv-web-update      holt die Anwendung von GitHub und installiert sie –
#                       auch ohne dieses Skript: ssh … sudo fv-web-update
#  Mit -M zusätzlich der Mailserver
#    Exim               SMTP (25, 465, 587), Adressen/Verteiler aus der Datenbank
#    Dovecot            IMAP (993), Sieve (4190), Speichergrenze, Archive der Verteiler
#    rspamd, Redis      Spam, Greylisting, unzulässige Anhänge
#    unbound            eigener DNS-Resolver mit DNSSEC; certbot für mail.<domain>
#    fv-mail            Abgleich mit der Webseite: sudo fv-mail status | dns | sync
#
#  Verzeichnisse
#    /srv/fv-web/releases/<zeit>-<commit> installierte Versionen (die letzten 3)
#    /srv/fv-web/current                  Verweis auf die aktive Version
#    /etc/fv-web/env                      Einstellungen der Anwendung
#    /etc/fv-web/deploy.env               Repository, Domain (nur root)
#    /etc/fv-web/backup.env               Datensicherung (nur root)
#    /var/lib/fv-web/private              Anhänge (nur für die Anwendung lesbar)
#    /var/lib/fv-web/static               CSS, JavaScript, Editor (liefert Caddy aus)
#    /var/lib/fv-web/mails                E-Mails, solange kein Mailserver eingetragen ist
#    /var/backups/fv-web                  Datenbank-Dumps (7 Tage)
#    /var/vmail                           Postfächer und Archive (mit -M)
#    /etc/fv-mail                         Mailserver: Einstellungen, DKIM, Zertifikat (mit -M)
#
#  Was das Skript macht
#    1. Verbindung, Ports 80/443 (anderer Webserver?) und DNS prüfen
#    2. System aktualisieren, Zeitzone, Hostname, automatische Sicherheitsupdates,
#       Admin-Benutzer mit SSH-Schlüssel und sudo, Firewall, fail2ban,
#       PostgreSQL, Caddy, Python, Dienstbenutzer, Einstellungen, Dienst, Sicherung
#    3. Anmeldung als Admin-Benutzer testen – erst DANACH SSH härten
#    4. fv-web-update einrichten bzw. aktualisieren, Zugriff auf GitHub prüfen
#       (privates Repository: Deploy-Schlüssel wird angezeigt)
#    5. Anwendung installieren: Der SERVER holt den Stand von GitHub
#       (Standard: main). Mit -L wird stattdessen der Stand des lokalen
#       Repositorys hochgeladen (z. B. noch nicht gepushte Commits testen).
#    6. Optional: Vorstandskonto anlegen (-a, -m)
#    7. Zusammenfassung
#
#  Protokolle
#    lokal:    logs/setup-<server>-<zeitstempel>.log (neben dem Skript)
#    Server:   /var/log/fv-web-setup/<zeitstempel>.log, /var/log/fv-web-update.log
#
#  Einstellungsdatei (-f): empfohlen
#    Alle dauerhaften Einstellungen eines Servers (Server, Domain, www, Mailserver,
#    Backup-Ziel …) stehen in einer Datei, z. B. kreuzau.env. Das Skript liest sie,
#    Optionen beim Aufruf ändern sie, und das Skript schreibt sie zurück. So geht
#    bei späteren Aufrufen keine Einstellung verloren:
#      ./setup-server-fv-web.sh -f kreuzau.env -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -W -M
#      ./setup-server-fv-web.sh -f kreuzau.env -U          # später: alles wie gespeichert
#    Einmalige Optionen (-c -U -N -L -r -a -m -y) werden nicht gespeichert.
#    Abschalten (z. B. www): in der Datei auf 0 setzen.
#
#  Beispiele
#    Nur prüfen (ändert nichts):
#      ./setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -W -c
#    Erstinstallation mit Vorstandskonto:
#      ./setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -W \
#                               -n fv-web -a michael.bramer -m adresse@example.org
#    Neue Version (main) einspielen – mit diesem Skript oder direkt auf dem Server:
#      ./setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -U
#      ssh fkjs@203.0.113.10 sudo fv-web-update
#    Lokalen, noch nicht gepushten Stand testen (im Repository):
#      deploy/setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -U -L
# =============================================================================
set -Eeuo pipefail

# ----------------------------- Voreinstellungen ------------------------------
ADMIN_USER="fkjs"
TIMEZONE="Europe/Berlin"
SSH_PORT="22"
NEW_HOSTNAME=""
SERVER=""
DOMAIN=""
WITH_WWW=0
ACME_EMAIL=""
BACKUP_REPO=""
GIT_REF=""                                  # leer: Server nimmt main; mit -L: HEAD
REPO_URL=""                                 # leer: bisheriger Eintrag bzw. Standard
REPO_URL_DEFAULT="https://github.com/brami/FreiVerein.git"
LOCAL_UPLOAD=0
SKIP_HARDEN=0
ASSUME_YES=0
CHECK_ONLY=0
UPDATE_ONLY=0
NO_APP=0
APP_ADMIN=""
APP_ADMIN_MAIL=""
WITH_MAIL=0
ZUSATZ_DOMAINS=""                           # weitere Domains (Leerzeichen-getrennt, ASCII/Punycode)
MAIL_HOST="${MAIL_HOST:-}"                  # leer: mail.<domain>
POSTMASTER=""

usage() {
  cat <<HILFE
Aufruf: $0 -H <server> -d <domain> [Optionen]

Einstellungsdatei (empfohlen):
  -f <datei>      Einstellungen dieses Servers lesen und – mit den Änderungen aus den
                  übrigen Optionen – zurückschreiben (wird beim ersten Mal angelegt).
                  Dauerhaft gespeichert: -H -d -A -W -M -X -P -e -B -R -u -n -t -p -S. Nicht gespeichert: -c -U -N -L -r -a -m -y.

Pflicht (ohne -f bzw. beim ersten Aufruf mit -f):
  -H <server>     IP-Adresse oder Name des vServers
  -d <domain>     Domain der Webseite, z. B. foerderverein-kf-jf-kreuzau.de

Anwendung:
  -r <ref>        Git-Stand (Branch, Tag oder Commit). Standard: main
                  (mit -L: HEAD des lokalen Repositorys)
  -R <url>        Repository, aus dem der Server holt. Standard beim ersten
                  Lauf: $REPO_URL_DEFAULT
                  Privates Repository per SSH: git@github.com:brami/FreiVerein.git
                  (der Server zeigt dann seinen Deploy-Schlüssel an)
  -L              Lokalen Stand hochladen statt vom Server holen lassen
                  (nur im ausgecheckten Repository; nur eingecheckter Code)
  -U              Nur die Anwendung installieren/aktualisieren (Grundeinrichtung
                  und SSH-Härtung überspringen; Server muss eingerichtet sein)
  -N              Keine Anwendung installieren (nur Server einrichten)
  -a <benutzer>   Vorstandskonto mit Verwaltungsrechten anlegen bzw. ergänzen,
  -m <e-mail>     z. B. -a michael.bramer -m adresse@example.org. Ausgegeben wird
                  ein Link zum Setzen des Passworts (7 Tage gültig).

Weitere Domains:
  -A <domain>     zusätzliche Domain, mehrfach möglich, auch mit Umlaut
                  (z. B. -A förderverein-kf-jf-kreuzau.de -A fv-kf-jf-kreuzau.de).
                  Webseite: leitet auf <domain> um (mit -W auch www.).
                  Mail (mit -M): jede Adresse gilt auch unter dieser Domain und
                  landet im selben Postfach; verschickt wird nur mit <domain>.
                  Entfernen: in der Einstellungsdatei (-f) aus ZUSATZ_DOMAINS löschen.

Mailserver:
  -M              Mailserver einrichten bzw. aktualisieren (Exim, Dovecot, rspamd);
                  Rechnername mail.<domain> (anders: -X).
                  Braucht die installierte Anwendung; mit -U nur Anwendung + Mail.
  -X <name>       anderer Rechnername für den Mailserver (Standard: mail.<domain>)
  -P <e-mail>     Betreuung: Ziel für postmaster@, abuse@, root@ …
                  (Standard: erste Adresse aus FV_ADMINS)

Optional:
  -W              www.<domain> zusätzlich einrichten (leitet auf <domain> um)
  -e <email>      Kontakt-E-Mail für die Zertifikatsstelle (nicht nötig)
  -B <ziel>       Backup-Ziel (restic-Repository). Standard: lokal
                  /var/backups/fv-web-restic. Extern z. B.
                  sftp://u12345@u12345.your-storagebox.de:23/fv-web
                  Ohne Angabe bleibt ein bereits eingetragenes Ziel erhalten.
  -u <benutzer>   Admin-Benutzer des Servers (Standard: $ADMIN_USER)
  -n <hostname>   Interner Rechnername des Servers (Standard: unverändert)
  -t <zeitzone>   Zeitzone (Standard: $TIMEZONE)
  -p <port>       SSH-Port (Standard: $SSH_PORT)
  -c              Nur prüfen: SSH, Ports, DNS – ändert nichts
  -S              SSH-Härtung überspringen (root-Login bleibt erlaubt)
  -y              Keine Rückfrage vor dem Start
  -h              Diese Hilfe
HILFE
}

# Einstellungen, die in der Datei (-f) gespeichert werden
DAUERHAFT=(SERVER DOMAIN ZUSATZ_DOMAINS WITH_WWW WITH_MAIL MAIL_HOST POSTMASTER ACME_EMAIL BACKUP_REPO
           REPO_URL ADMIN_USER NEW_HOSTNAME TIMEZONE SSH_PORT SKIP_HARDEN)
EINSTELLUNGEN=""
declare -A AUS_DATEI=()     # so beim Start in der Datei
declare -A GESPEICHERT=()   # zuletzt geschrieben (für die Anzeige der Änderungen)

einstellungen_lesen() {  # nur bekannte Schlüssel, Format KEY="wert" (kein source: keine Ausführung)
  local zeile key wert k
  while IFS= read -r zeile || [[ -n "$zeile" ]]; do
    [[ "$zeile" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "$zeile" =~ ^([A-Z_]+)=(.*)$ ]] || { echo "FEHLER: $EINSTELLUNGEN: Zeile nicht lesbar: $zeile" >&2; exit 2; }
    key="${BASH_REMATCH[1]}"; wert="${BASH_REMATCH[2]}"
    wert="${wert%\"}"; wert="${wert#\"}"
    for k in "${DAUERHAFT[@]}"; do
      # leerer MAIL_HOST = Standard mail.<domain>; dann gilt ggf. die Umgebungsvariable
      if [[ "$k" == "$key" && "$key" == MAIL_HOST && -z "$wert" ]]; then AUS_DATEI[$key]=""; GESPEICHERT[$key]=""; continue 2; fi
      if [[ "$k" == "$key" ]]; then printf -v "$key" '%s' "$wert"; AUS_DATEI[$key]="$wert"; GESPEICHERT[$key]="$wert"; continue 2; fi
    done
    echo "FEHLER: $EINSTELLUNGEN: unbekannte Einstellung $key" >&2; exit 2
  done < "$EINSTELLUNGEN"
}

einstellungen_schreiben() {
  local tmp k alt neu geaendert=0
  tmp="$(mktemp)"
  {
    echo "# Einstellungen für setup-server-fv-web.sh -f $(basename "$EINSTELLUNGEN")"
    echo "# Wird vom Skript geschrieben; Änderungen per Option oder hier von Hand."
    echo "# Schalter: 1 = an, 0 = aus. Enthält keine Passwörter."
    for k in "${DAUERHAFT[@]}"; do printf '%s="%s"\n' "$k" "${!k}"; done
  } > "$tmp"
  for k in "${DAUERHAFT[@]}"; do
    alt="${GESPEICHERT[$k]-}"; neu="${!k}"
    if [[ ! -v "GESPEICHERT[$k]" ]]; then
      [[ -f "$EINSTELLUNGEN" ]] && { echo "  neu:      $k=\"$neu\""; geaendert=1; }
    elif [[ "$alt" != "$neu" ]]; then
      echo "  geändert: $k \"$alt\" → \"$neu\""; geaendert=1
    fi
  done
  for k in "${DAUERHAFT[@]}"; do GESPEICHERT[$k]="${!k}"; done
  if [[ ! -f "$EINSTELLUNGEN" ]]; then
    mv "$tmp" "$EINSTELLUNGEN"; echo "Einstellungen gespeichert in $EINSTELLUNGEN"
  elif [[ $geaendert -eq 1 ]]; then
    mv "$tmp" "$EINSTELLUNGEN"; echo "Einstellungen aktualisiert: $EINSTELLUNGEN"
  else
    rm -f "$tmp"
  fi
}

OPTSTRING=":f:H:d:A:r:R:a:m:e:B:u:n:t:p:P:X:LWUNMcSyh"
while getopts "$OPTSTRING" opt; do
  case "$opt" in
    f) EINSTELLUNGEN="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) ;;
  esac
done
if [[ -n "$EINSTELLUNGEN" && -f "$EINSTELLUNGEN" ]]; then einstellungen_lesen; fi
OPTIND=1

ZUSATZ_NEU=()
while getopts "$OPTSTRING" opt; do
  case "$opt" in
    f) ;;
    H) SERVER="$OPTARG" ;;
    A) ZUSATZ_NEU+=("$OPTARG") ;;
    d) DOMAIN="$OPTARG" ;;
    r) GIT_REF="$OPTARG" ;;
    R) REPO_URL="$OPTARG" ;;
    L) LOCAL_UPLOAD=1 ;;
    a) APP_ADMIN="$OPTARG" ;;
    m) APP_ADMIN_MAIL="$OPTARG" ;;
    e) ACME_EMAIL="$OPTARG" ;;
    B) BACKUP_REPO="$OPTARG" ;;
    u) ADMIN_USER="$OPTARG" ;;
    n) NEW_HOSTNAME="$OPTARG" ;;
    t) TIMEZONE="$OPTARG" ;;
    p) SSH_PORT="$OPTARG" ;;
    W) WITH_WWW=1 ;;
    M) WITH_MAIL=1 ;;
    P) POSTMASTER="$OPTARG" ;;
    X) MAIL_HOST="$OPTARG" ;;
    U) UPDATE_ONLY=1 ;;
    N) NO_APP=1 ;;
    c) CHECK_ONLY=1 ;;
    S) SKIP_HARDEN=1 ;;
    y) ASSUME_YES=1 ;;
    h) usage; exit 0 ;;
    :) echo "Option -$OPTARG braucht einen Wert." >&2; usage; exit 2 ;;
    *) echo "Unbekannte Option: -$OPTARG" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$SERVER" && -n "$DOMAIN" ]] || { usage; exit 2; }
[[ "$ADMIN_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "Ungültiger Benutzername: $ADMIN_USER" >&2; exit 2; }
[[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$DOMAIN" == *.* ]] \
  || { echo "Ungültige Domain: $DOMAIN" >&2; exit 2; }
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || { echo "Ungültiger SSH-Port: $SSH_PORT" >&2; exit 2; }
[[ -z "$GIT_REF" || "$GIT_REF" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "Ungültiger Git-Stand: $GIT_REF" >&2; exit 2; }
if [[ -n "$APP_ADMIN$APP_ADMIN_MAIL" ]]; then
  [[ -n "$APP_ADMIN" && -n "$APP_ADMIN_MAIL" ]] || { echo "-a und -m nur zusammen angeben." >&2; exit 2; }
  [[ "$APP_ADMIN" =~ ^[a-z0-9][a-z0-9._-]{0,149}$ ]] || { echo "Ungültiger Benutzername für -a: $APP_ADMIN" >&2; exit 2; }
  [[ "$APP_ADMIN_MAIL" =~ ^[^@[:space:]\"\$\`]+@[^@[:space:]\"\$\`]+\.[^@[:space:]\"\$\`]+$ ]] \
    || { echo "Ungültige E-Mail-Adresse für -m: $APP_ADMIN_MAIL" >&2; exit 2; }
fi
[[ $UPDATE_ONLY -eq 1 && $NO_APP -eq 1 ]] && { echo "-U und -N schließen sich aus." >&2; exit 2; }
[[ $LOCAL_UPLOAD -eq 1 && $NO_APP -eq 1 ]] && { echo "-L und -N schließen sich aus." >&2; exit 2; }
# Domains mit Umlaut in ASCII (Punycode) umwandeln; so stehen sie auch in DNS, Caddy, Exim
ascii_domain() {
  local d="${1,,}"; d="${d%.}"
  if [[ "$d" == *[![:ascii:]]* ]]; then
    if command -v idn2 >/dev/null; then d="$(idn2 --quiet -- "$d")" || return 1
    elif [[ "$d" == *ß* ]]; then echo "Domains mit ß brauchen idn2 (apt install idn2)." >&2; return 1
    elif command -v python3 >/dev/null; then d="$(python3 -c 'import sys; print(sys.argv[1].encode("idna").decode())' "$d")" || return 1
    else echo "Für Domains mit Umlaut wird idn2 oder python3 benötigt." >&2; return 1; fi
  fi
  printf '%s' "$d"
}
gueltige_domain() { [[ "$1" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$1" == *.* ]]; }
ZUSATZ_LISTE=""
for d in ${ZUSATZ_DOMAINS} "${ZUSATZ_NEU[@]}"; do
  a="$(ascii_domain "$d")" || { echo "Domain nicht umwandelbar: $d" >&2; exit 2; }
  gueltige_domain "$a" || { echo "Ungültige Zusatzdomain: $d" >&2; exit 2; }
  [[ "$a" != "$DOMAIN" && "$a" != "www.$DOMAIN" ]] || { echo "Zusatzdomain gleich der Domain: $d" >&2; exit 2; }
  [[ " $ZUSATZ_LISTE " == *" $a "* ]] || ZUSATZ_LISTE="${ZUSATZ_LISTE:+$ZUSATZ_LISTE }$a"
  [[ "$a" == "${d,,}" ]] || echo "Zusatzdomain $d → $a"
done
ZUSATZ_DOMAINS="${ZUSATZ_LISTE:-}"

MAIL_HOST="${MAIL_HOST:-mail.$DOMAIN}"
[[ "$MAIL_HOST" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$MAIL_HOST" == *.* ]] \
  || { echo "Ungültiger Mail-Rechnername: $MAIL_HOST" >&2; exit 2; }
[[ -z "$POSTMASTER" || "$POSTMASTER" =~ ^[^@[:space:]\"\$\`]+@[^@[:space:]\"\$\`]+\.[^@[:space:]\"\$\`]+$ ]] \
  || { echo "Ungültige E-Mail-Adresse für -P: $POSTMASTER" >&2; exit 2; }
for v in "$ACME_EMAIL" "$BACKUP_REPO" "$TIMEZONE" "$NEW_HOSTNAME" "$REPO_URL"; do
  [[ "$v" != *[\"\$\`\\[:space:]]* ]] || { echo "Unzulässige Zeichen in einer Option: $v" >&2; exit 2; }
done
for v in WITH_WWW WITH_MAIL SKIP_HARDEN; do
  [[ "${!v}" == 0 || "${!v}" == 1 ]] || { echo "$v muss 0 oder 1 sein (ist: ${!v})." >&2; exit 2; }
done
if [[ -n "$EINSTELLUNGEN" ]]; then
  if [[ $CHECK_ONLY -eq 1 ]]; then echo "Nur prüfen (-c): $EINSTELLUNGEN bleibt unverändert."
  else
    # Standard-Mailname nicht festschreiben (folgt sonst einer geänderten Domain nicht)
    [[ "$MAIL_HOST" == "mail.$DOMAIN" ]] && MAIL_HOST=""
    einstellungen_schreiben
    MAIL_HOST="${MAIL_HOST:-mail.$DOMAIN}"
  fi
fi

# ----------------------------- Lokale Voraussetzungen ------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR=""
if [[ $LOCAL_UPLOAD -eq 1 ]]; then
  if [[ -f "$SCRIPT_DIR/../manage.py" ]] && git -C "$SCRIPT_DIR/.." rev-parse --git-dir >/dev/null 2>&1; then
    REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
  else
    echo "FEHLER: -L geht nur, wenn das Skript im ausgecheckten Repository liegt (deploy/)." >&2; exit 2
  fi
  GIT_REF="${GIT_REF:-HEAD}"
fi

check_local_tools() {
  local missing=() t
  if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4) )); then
    echo "FEHLER: Bash $BASH_VERSION ist zu alt, benötigt wird Bash 4.4 oder neuer." >&2
    echo "        macOS: brew install bash, dann: /opt/homebrew/bin/bash $0 ..." >&2
    exit 2
  fi
  for t in ssh curl tee awk sed grep tr wc head cut paste date; do
    command -v "$t" >/dev/null 2>&1 || missing+=("$t")
  done
  if [[ $LOCAL_UPLOAD -eq 1 ]] && ! command -v git >/dev/null 2>&1; then missing+=("git"); fi
  if (( ${#missing[@]} > 0 )); then
    echo "FEHLER: Folgende Programme fehlen auf diesem Rechner: ${missing[*]}" >&2
    exit 2
  fi
  command -v dig >/dev/null 2>&1 || echo "HINWEIS: 'dig' fehlt – die DNS-Vorabprüfung wird übersprungen (Debian: apt install bind9-dnsutils)." >&2
  if ! ssh-add -l >/dev/null 2>&1 && ! ls ~/.ssh/id_* >/dev/null 2>&1; then
    echo "WARNUNG: Kein SSH-Schlüssel gefunden (weder im ssh-agent noch unter ~/.ssh/id_*)." >&2
  fi
}
check_local_tools

# ----------------------------- Lokales Protokoll -----------------------------
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOCAL_LOG="$LOG_DIR/setup-${SERVER}-${STAMP}.log"
exec > >(tee -a "$LOCAL_LOG") 2>&1

log()  { printf '%s [lokal] %s\n' "$(date '+%F %T')" "$*"; }
fail() { log "FEHLER: $*"; exit 1; }
trap 'log "Abbruch in Zeile $LINENO (Exit-Code $?). Protokoll: $LOCAL_LOG"' ERR

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30
          -o StrictHostKeyChecking=accept-new -p "$SSH_PORT")

MODE="Einrichtung"
[[ $UPDATE_ONLY -eq 1 ]] && MODE="nur Anwendung"
[[ $CHECK_ONLY -eq 1 ]] && MODE="nur Prüfung"
[[ $WITH_MAIL -eq 1 ]] && MODE="$MODE + Mailserver ($MAIL_HOST)"
log "Start ($MODE)"
log "Server: $SERVER | Domain: $DOMAIN$([[ $WITH_WWW -eq 1 ]] && echo " + www.$DOMAIN") | Admin: $ADMIN_USER | Zeitzone: $TIMEZONE | Hostname: ${NEW_HOSTNAME:-unverändert}"
log "Lokales Protokoll: $LOCAL_LOG"

# ----------------------------- Lokaler Git-Stand (-L) ------------------------
APP_COMMIT=""; APP_DESC=""
if [[ $LOCAL_UPLOAD -eq 1 ]]; then
  APP_COMMIT="$(git -C "$REPO_DIR" rev-parse --verify --quiet "$GIT_REF^{commit}")" \
    || fail "Git-Stand '$GIT_REF' nicht gefunden."
  APP_DESC="$(git -C "$REPO_DIR" log -1 --format='%h %s (%ad)' --date=short "$APP_COMMIT")"
  log "Anwendung: lokaler Stand $APP_DESC (wird hochgeladen)"
  if [[ "$GIT_REF" == HEAD && -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]]; then
    log "HINWEIS: Es gibt nicht eingecheckte Änderungen – übertragen wird nur der letzte Commit."
  fi
  for f in manage.py requirements.txt config/settings.py; do
    git -C "$REPO_DIR" cat-file -e "$APP_COMMIT:$f" 2>/dev/null || fail "$f fehlt im Git-Stand $GIT_REF."
  done
elif [[ $NO_APP -eq 0 ]]; then
  log "Anwendung: Der Server holt ${GIT_REF:-main} aus ${REPO_URL:-dem eingetragenen Repository (Standard $REPO_URL_DEFAULT)}"
fi

# ----------------------------- Verbindung wählen -----------------------------
TARGET=""; SUDO=""
if ssh "${SSH_OPTS[@]}" "root@$SERVER" true 2>/dev/null; then
  TARGET="root@$SERVER"; SUDO=""
  log "Verbindung als root steht."
elif ssh "${SSH_OPTS[@]}" "$ADMIN_USER@$SERVER" 'sudo -n true' 2>/dev/null; then
  TARGET="$ADMIN_USER@$SERVER"; SUDO="sudo -n"
  log "root-Login nicht (mehr) möglich – verwende $ADMIN_USER mit sudo (erneuter Lauf)."
else
  fail "Keine SSH-Verbindung als root oder $ADMIN_USER mit sudo möglich (Port $SSH_PORT)."
fi

# ----------------------------- Server-Voraussetzungen ------------------------
# shellcheck disable=SC2016  # wird auf dem Server ausgewertet
REMOTE_CHECK=$(ssh "${SSH_OPTS[@]}" "$TARGET" "$SUDO bash -s" <<'CHECK' 2>/dev/null || true
. /etc/os-release 2>/dev/null; echo "os=${ID:-?} ${VERSION_ID:-?}"
for t in apt-get systemctl; do command -v $t >/dev/null || echo "fehlt=$t"; done
[ -d /run/systemd/system ] || echo "fehlt=systemd (läuft nicht)"
timeout 10 bash -c "exec 3<>/dev/tcp/deb.debian.org/80" 2>/dev/null || echo "fehlt=Internetzugang (deb.debian.org:80)"
[ -f /etc/fv-web/env ] && echo "eingerichtet=ja"
grep -q '^WITH_WWW="1"' /etc/fv-web/deploy.env 2>/dev/null && echo "www=1"
[ -f /etc/fv-mail/mail.env ] && echo "mail=ja"
# Andere Programme auf Port 80/443 (z. B. Apache des bisherigen Drupal)?
if command -v ss >/dev/null; then
  ss -Hltnp '( sport = :80 or sport = :443 )' 2>/dev/null \
    | grep -o 'users:(("[^"]*"' | cut -d'"' -f2 | sort -u | grep -vx caddy | sed 's/^/belegt=/'
fi
CHECK
)
OS="$(grep '^os=' <<<"$REMOTE_CHECK" | cut -d= -f2 || true)"
log "Server: ${OS:-unbekannt}"
[[ "$OS" == "debian 13" ]] || log "WARNUNG: Das Skript ist für Debian 13 geschrieben (gefunden: ${OS:-unbekannt})."
if grep -q '^fehlt=' <<<"$REMOTE_CHECK"; then
  fail "Auf dem Server fehlt: $(grep '^fehlt=' <<<"$REMOTE_CHECK" | cut -d= -f2 | paste -sd ', ')"
fi
if grep -q '^belegt=' <<<"$REMOTE_CHECK"; then
  log "Port 80/443 ist belegt von: $(grep '^belegt=' <<<"$REMOTE_CHECK" | cut -d= -f2 | paste -sd ', ')"
  [[ $CHECK_ONLY -eq 1 ]] || fail "Ein anderer Webserver läuft bereits (z. B. für Drupal). Bitte zuerst beenden: systemctl disable --now <dienst>"
fi
if [[ $UPDATE_ONLY -eq 1 ]] && ! grep -q '^eingerichtet=ja' <<<"$REMOTE_CHECK"; then
  fail "-U: Der Server ist noch nicht eingerichtet (/etc/fv-web/env fehlt). Bitte zuerst ohne -U ausführen."
fi
# Vorhandene Einrichtung nicht versehentlich zurückbauen (vergessene Option)
if grep -q '^www=1' <<<"$REMOTE_CHECK" && [[ $WITH_WWW -eq 0 ]]; then
  if [[ -v "AUS_DATEI[WITH_WWW]" ]]; then
    log "HINWEIS: www.$DOMAIN ist eingerichtet, laut $EINSTELLUNGEN aber abgeschaltet – wird entfernt."
  else
    WITH_WWW=1
    log "www.$DOMAIN ist auf dem Server eingerichtet – bleibt erhalten (wie -W)."
    if [[ -n "$EINSTELLUNGEN" && $CHECK_ONLY -eq 0 ]]; then
      [[ "$MAIL_HOST" == "mail.$DOMAIN" ]] && MAIL_HOST=""
      einstellungen_schreiben; MAIL_HOST="${MAIL_HOST:-mail.$DOMAIN}"
    fi
  fi
fi
if grep -q '^mail=ja' <<<"$REMOTE_CHECK" && [[ $WITH_MAIL -eq 0 ]]; then
  log "HINWEIS: Der Mailserver ist eingerichtet; ohne -M bleibt seine Konfiguration unverändert."
fi
log "Server-Voraussetzungen geprüft."

# ----------------------------- DNS-Vorabprüfung ------------------------------
DNS_RESOLVER="${DNS_RESOLVER:-1.1.1.1}"
DNS_TTL=3600
DNS_PROBLEMS=0
DNS_FIXES=()
q() { dig +short +time=3 +tries=2 "@$DNS_RESOLVER" "$1" "$2" 2>/dev/null | sed 's/\.$//'; }

dns_preflight() {
  log "DNS-Vorabprüfung (Resolver: $DNS_RESOLVER)"
  command -v dig >/dev/null || { log "WARNUNG: 'dig' fehlt – DNS-Prüfung übersprungen."; return 0; }
  local ip4 ip6 d a_list aaaa_list name caa
  if [[ "$SERVER" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then ip4="$SERVER"
  else ip4=$(q A "$SERVER" | grep -E '^[0-9.]+$' | head -n1 || true); fi
  # shellcheck disable=SC2016
  ip6=$(ssh "${SSH_OPTS[@]}" "$TARGET" \
        'ip -6 -o addr show scope global 2>/dev/null | awk "{print \$4}" | cut -d/ -f1 | grep -v "^f[cd]" | head -n1' 2>/dev/null || true)
  log "Server: IPv4 ${ip4:-unbekannt} | IPv6 ${ip6:-keine}"
  local domains=("$DOMAIN") z; [[ $WITH_WWW -eq 1 ]] && domains+=("www.$DOMAIN")
  for z in $ZUSATZ_DOMAINS; do domains+=("$z"); [[ $WITH_WWW -eq 1 ]] && domains+=("www.$z"); done
  for d in "${domains[@]}"; do
    a_list=$(q A "$d" | grep -E '^[0-9.]+$' || true)
    aaaa_list=$(q AAAA "$d" | grep ':' || true)
    if [[ -z "$a_list" ]]; then
      log "  FEHLT   $d: kein A-Eintrag"; DNS_PROBLEMS=$((DNS_PROBLEMS+1))
      [[ -n "$ip4" ]] && DNS_FIXES+=("$d.  $DNS_TTL  IN  A     $ip4      ; neu anlegen")
    elif [[ -n "$ip4" ]] && ! grep -qx "$ip4" <<<"$a_list"; then
      log "  FALSCH  $d: A zeigt auf $(tr '\n' ' ' <<<"$a_list")statt auf $ip4"; DNS_PROBLEMS=$((DNS_PROBLEMS+1))
      DNS_FIXES+=("$d.  $DNS_TTL  IN  A     $ip4      ; bestehenden A-Eintrag ersetzen")
    else
      log "  OK      $d: A -> $(tr '\n' ' ' <<<"$a_list")"
    fi
    if [[ -n "$aaaa_list" ]]; then
      if [[ -n "$ip6" ]] && grep -qix "$ip6" <<<"$aaaa_list"; then
        log "  OK      $d: AAAA -> $ip6"
      else
        log "  FALSCH  $d: AAAA zeigt auf $(tr '\n' ' ' <<<"$aaaa_list")– der Server hat ${ip6:-keine IPv6-Adresse}"
        DNS_PROBLEMS=$((DNS_PROBLEMS+1))
        if [[ -n "$ip6" ]]; then DNS_FIXES+=("$d.  $DNS_TTL  IN  AAAA  $ip6      ; bestehenden AAAA-Eintrag ersetzen")
        else DNS_FIXES+=("; $d: AAAA-Eintrag löschen (Server hat keine IPv6-Adresse)"); fi
      fi
    elif [[ -n "$ip6" ]]; then
      log "  HINWEIS $d: kein AAAA-Eintrag (optional, Server hätte IPv6 $ip6)"
    fi
    name="$d"; caa=""
    while [[ "$name" == *.* ]]; do caa=$(q CAA "$name" || true); [[ -n "$caa" ]] && break; name="${name#*.}"; done
    if [[ -n "$caa" ]] && ! grep -qiE 'issue "?letsencrypt\.org' <<<"$caa"; then
      log "  FALSCH  $d: CAA bei $name erlaubt Let's Encrypt nicht"; DNS_PROBLEMS=$((DNS_PROBLEMS+1))
      DNS_FIXES+=("$name.  $DNS_TTL  IN  CAA   0 issue \"letsencrypt.org\"   ; ergänzen")
    fi
  done
  if [[ ${#DNS_FIXES[@]} -gt 0 ]]; then
    log "Vorgeschlagene DNS-Einträge (beim DNS-Anbieter eintragen):"
    printf '    %s\n' "${DNS_FIXES[@]}" | awk '!seen[$0]++'
  fi
  if [[ $DNS_PROBLEMS -eq 0 ]]; then log "DNS-Prüfung: alles in Ordnung."
  else log "DNS-Prüfung: $DNS_PROBLEMS Problem(e). Ohne Korrektur erhält Caddy kein Zertifikat."; fi
}
dns_preflight

if [[ $CHECK_ONLY -eq 1 ]]; then
  log "Nur Prüfung (-c): Am Server wurde nichts geändert."
  exit $(( DNS_PROBLEMS > 0 ? 1 : 0 ))
fi

if [[ $ASSUME_YES -ne 1 ]]; then
  [[ $DNS_PROBLEMS -gt 0 ]] && echo "Die Einrichtung funktioniert auch ohne korrektes DNS; nur das Zertifikat folgt erst danach."
  read -r -p "$MODE auf $SERVER starten? [j/N] " answer
  [[ "$answer" =~ ^[jJyY]$ ]] || { log "Vom Benutzer abgebrochen."; exit 0; }
fi

REMOTE_TAR=""
run_remote() {  # $1 = Phase, Skript kommt über stdin
  local envs
  envs=$(printf 'PHASE=%q ADMIN_USER=%q TIMEZONE=%q NEW_HOSTNAME=%q DOMAIN=%q WITH_WWW=%q ACME_EMAIL=%q BACKUP_REPO=%q STAMP=%q SSH_PORT=%q REPO_URL=%q REPO_URL_DEFAULT=%q GIT_REF=%q NO_APP=%q LOCAL_UPLOAD=%q REMOTE_TAR=%q APP_COMMIT=%q APP_DESC=%q APP_ADMIN=%q APP_ADMIN_MAIL=%q WITH_MAIL=%q MAIL_HOST=%q POSTMASTER=%q ZUSATZ_DOMAINS=%q' \
    "$1" "$ADMIN_USER" "$TIMEZONE" "$NEW_HOSTNAME" "$DOMAIN" "$WITH_WWW" "$ACME_EMAIL" "$BACKUP_REPO" "$STAMP" "$SSH_PORT" \
    "$REPO_URL" "$REPO_URL_DEFAULT" "$GIT_REF" "$NO_APP" "$LOCAL_UPLOAD" "$REMOTE_TAR" "$APP_COMMIT" "$APP_DESC" "$APP_ADMIN" "$APP_ADMIN_MAIL" "$WITH_MAIL" "$MAIL_HOST" "$POSTMASTER" "$ZUSATZ_DOMAINS")
  # shellcheck disable=SC2029  # Variablen sollen lokal expandiert werden
  ssh "${SSH_OPTS[@]}" "$TARGET" "$SUDO env $envs bash -s"
}

# ============================== Remote-Skript ================================
REMOTE_SCRIPT=$(cat <<'REMOTE'
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
umask 022

LOG_DIR=/var/log/fv-web-setup
mkdir -p "$LOG_DIR"; chmod 750 "$LOG_DIR"
REMOTE_LOG="$LOG_DIR/$STAMP.log"
exec > >(tee -a "$REMOTE_LOG") 2>&1

log()  { printf '%s [%s] %s\n' "$(date '+%F %T')" "$(hostname)" "$*"; }
step() { printf '\n%s [%s] ===== %s =====\n' "$(date '+%F %T')" "$(hostname)" "$*"; }
trap 'log "FEHLER in Zeile $LINENO (Exit-Code $?)"' ERR
apt_install() { apt-get install -y -q --no-install-recommends "$@"; }

SVC=fvweb                       # Dienstbenutzer und Datenbank
BASE=/srv/fv-web
DATA=/var/lib/fv-web
ETC=/etc/fv-web
ENVF=$ETC/env
BENV=$ETC/backup.env
DENV=$ETC/deploy.env

rnd() { python3 -c "import secrets,sys; print(secrets.token_urlsafe(int(sys.argv[1])))" "$1"; }
# Einstellungsdateien im Format KEY="WERT" (lesbar für systemd und bash)
ensure_kv() {  # ensure_kv DATEI KEY WERT  -> nur setzen, wenn KEY fehlt
  grep -q "^$2=" "$1" || { printf '%s="%s"\n' "$2" "$3" >> "$1"; log "$(basename "$1"): $2 neu angelegt."; }
}
set_kv() {
  if grep -q "^$2=" "$1"; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$2" -v v="$3" 'BEGIN{FS=OFS="="} $1==k {print k "=\"" v "\""; next} {print}' "$1" > "$tmp"
    cat "$tmp" > "$1"; rm -f "$tmp"
  else
    printf '%s="%s"\n' "$2" "$3" >> "$1"
  fi
}
getkv() { grep -m1 "^$2=" "$1" | cut -d= -f2- | sed 's/^"//; s/"$//'; }
app_installed() { [[ -e "$BASE/current/manage.py" ]]; }

# --------------------------------------------------------------- Phase base
phase_base() {
  step "Systeminformationen"
  . /etc/os-release
  log "System: $PRETTY_NAME | Kernel: $(uname -r)"

  step "System aktualisieren und Pakete installieren"
  apt-get update -q
  apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade
  apt_install ca-certificates curl sudo dbus ufw fail2ban python3-systemd \
              unattended-upgrades apt-listchanges jq bind9-dnsutils rsync restic git \
              python3 python3-venv postgresql caddy
  log "Python $(python3 -V | cut -d' ' -f2) | PostgreSQL $(runuser -u postgres -- psql -tAc 'SHOW server_version' | cut -d' ' -f1) | $(caddy version | cut -d' ' -f1)"

  step "Zeitzone und Hostname"
  timedatectl set-timezone "$TIMEZONE"
  log "Zeitzone: $(timedatectl show -p Timezone --value)"
  if [[ -n "$NEW_HOSTNAME" && "$(hostnamectl --static)" != "$NEW_HOSTNAME" ]]; then
    hostnamectl set-hostname "$NEW_HOSTNAME"
    grep -q "127.0.1.1 $NEW_HOSTNAME" /etc/hosts || echo "127.0.1.1 $NEW_HOSTNAME" >> /etc/hosts
    log "Hostname gesetzt: $NEW_HOSTNAME"
  fi

  step "Automatische Sicherheitsupdates"
  cat > /etc/apt/apt.conf.d/20auto-upgrades <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
  systemctl enable --now unattended-upgrades >/dev/null
  log "unattended-upgrades aktiv (auch für PostgreSQL und Caddy; Neustarts NICHT automatisch)."

  step "Admin-Benutzer $ADMIN_USER"
  id "$ADMIN_USER" >/dev/null 2>&1 || { useradd -m -s /bin/bash "$ADMIN_USER"; log "Benutzer angelegt (ohne Passwort)."; }
  usermod -aG sudo "$ADMIN_USER"
  install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
  local ak="/home/$ADMIN_USER/.ssh/authorized_keys"
  touch "$ak"
  if [[ -s /root/.ssh/authorized_keys ]]; then
    sort -u "$ak" /root/.ssh/authorized_keys | grep -v '^\s*$' > "$ak.tmp"; mv "$ak.tmp" "$ak"
    log "SSH-Schlüssel von root übernommen ($(wc -l < "$ak") Schlüssel)."
  fi
  chown "$ADMIN_USER:$ADMIN_USER" "$ak"; chmod 600 "$ak"
  [[ -s "$ak" ]] || { log "FEHLER: $ADMIN_USER hat keinen SSH-Schlüssel."; exit 1; }
  echo "$ADMIN_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$ADMIN_USER"
  chmod 440 "/etc/sudoers.d/90-$ADMIN_USER"
  visudo -cf "/etc/sudoers.d/90-$ADMIN_USER" >/dev/null

  step "Firewall (ufw) und fail2ban"
  ufw default deny incoming >/dev/null
  ufw default allow outgoing >/dev/null
  ufw allow "$SSH_PORT/tcp" comment 'SSH' >/dev/null
  ufw allow 80/tcp  comment 'HTTP (Zertifikat, Weiterleitung)' >/dev/null
  ufw allow 443/tcp comment 'HTTPS' >/dev/null
  ufw allow 443/udp comment 'HTTP/3' >/dev/null
  ufw --force enable >/dev/null
  ufw status | sed 's/^/    /'
  cat > /etc/fail2ban/jail.d/fv-web.local <<EOF
[sshd]
enabled  = true
port     = $SSH_PORT
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
  systemctl enable fail2ban >/dev/null; systemctl restart fail2ban
  log "fail2ban aktiv für SSH."

  step "Dienstbenutzer, Verzeichnisse"
  id "$SVC" >/dev/null 2>&1 || { useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin "$SVC"; log "Dienstbenutzer $SVC angelegt."; }
  install -d -o root -g "$SVC" -m 750 "$BASE" "$BASE/releases"
  install -d -o root -g "$SVC" -m 750 "$DATA"
  install -d -o "$SVC" -g "$SVC" -m 700 "$DATA/private" "$DATA/mails"
  install -d -o "$SVC" -g "$SVC" -m 750 "$DATA/static"
  install -d -o root -g root -m 755 "$DATA/platzhalter"
  install -d -o root -g "$SVC" -m 750 "$ETC"
  install -d -o caddy -g caddy -m 750 /var/log/caddy
  # Caddy darf den Socket von gunicorn und die statischen Dateien lesen – nicht die Anhänge (700)
  usermod -aG "$SVC" caddy
  cat > "$DATA/platzhalter/index.html" <<'EOF'
<!doctype html><html lang="de"><meta charset="utf-8"><title>Förderverein KF/JF Kreuzau</title>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem">
<h1>Förderverein KF/JF Kreuzau</h1><p>Die neue Webseite wird gerade eingerichtet.</p></body></html>
EOF

  step "Einstellungen ($ENVF)"
  [[ -f "$ENVF" ]] || { ( umask 027; echo "# Webseite Förderverein – Einstellungen (NICHT ins Git-Repository!)" > "$ENVF" ); log "$ENVF angelegt."; }
  chown root:"$SVC" "$ENVF"; chmod 640 "$ENVF"
  # Geheimnisse und Standardwerte nur setzen, wenn sie fehlen
  ensure_kv "$ENVF" FV_SECRET_KEY "$(rnd 50)"
  ensure_kv "$ENVF" FV_DB_NAME "$SVC"
  ensure_kv "$ENVF" FV_DB_USER "$SVC"
  ensure_kv "$ENVF" FV_PRIVATE_MEDIA_ROOT "$DATA/private"
  ensure_kv "$ENVF" FV_STATIC_ROOT "$DATA/static"
  ensure_kv "$ENVF" FV_ADMIN_PFAD "verwaltung/"
  ensure_kv "$ENVF" FV_MAIL "datei"
  ensure_kv "$ENVF" FV_MAIL_DATEIEN "$DATA/mails"
  ensure_kv "$ENVF" FV_MAIL_ABSENDER "webmaster@$DOMAIN"   # Absendername = Name der Webseite
  ensure_kv "$ENVF" FV_ADMINS ""                         # Fehlermails an (Komma-getrennt)
  ensure_kv "$ENVF" FV_ADMINS_BETREFF "[$DOMAIN]"        # Betreff-Anfang der Fehlermails
  ensure_kv "$ENVF" FV_SMTP_HOST ""
  ensure_kv "$ENVF" FV_SMTP_PORT "587"
  ensure_kv "$ENVF" FV_SMTP_USER ""
  ensure_kv "$ENVF" FV_SMTP_PASSWORD ""
  ensure_kv "$ENVF" FV_SMTP_TLS "starttls"
  ensure_kv "$ENVF" FV_ADMINS ""
  # Domainabhängige Werte setzt die Phase "tool" (läuft auch mit -U, z. B. bei Domainwechsel)
  log "E-Mail-Versand: $(getkv "$ENVF" FV_MAIL)$([[ "$(getkv "$ENVF" FV_MAIL)" == datei ]] && echo " (nichts wird verschickt; Mails liegen in $DATA/mails)")"

  step "PostgreSQL"
  systemctl enable --now postgresql >/dev/null
  if [[ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$SVC'")" != 1 ]]; then
    runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole "$SVC"
    log "Datenbankbenutzer $SVC angelegt (Anmeldung nur lokal über den Socket, ohne Passwort)."
  fi
  if [[ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$SVC'")" != 1 ]]; then
    runuser -u postgres -- createdb --owner "$SVC" --encoding UTF8 --locale C.UTF-8 --template template0 "$SVC"
    log "Datenbank $SVC angelegt."
  fi
  # Rolle für den Mailserver (Dovecot): Anmeldung nur lokal per Socket als Systembenutzer
  # "dovecot"; Leserecht ausschließlich auf die Sicht dovecot_benutzer (vergibt fv-web-update)
  if [[ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='dovecot'")" != 1 ]]; then
    runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole dovecot
    log "Datenbankrolle dovecot angelegt (für die Passwortprüfung des Mailservers)."
  fi
  log "PostgreSQL lauscht nur lokal: $(runuser -u postgres -- psql -tAc 'SHOW listen_addresses')"

  step "Dienst fv-web (gunicorn)"
  cat > /etc/systemd/system/fv-web.service <<EOF
[Unit]
Description=Webseite Förderverein KF/JF Kreuzau (gunicorn)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=$SVC
Group=$SVC
WorkingDirectory=$BASE/current
EnvironmentFile=$ENVF
ExecStart=$BASE/current/.venv/bin/gunicorn config.wsgi:application \\
    --bind unix:/run/fv-web/gunicorn.sock --umask 007 \\
    --workers 3 --timeout 120 --access-logfile - --error-logfile -
RuntimeDirectory=fv-web
RuntimeDirectoryMode=0750
UMask=0027
Restart=on-failure
RestartSec=5
# Härtung
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=$DATA/private $DATA/mails

[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/fv-web-newsletter.service <<EOF
[Unit]
Description=Newsletter-Versand der Webseite
After=network.target postgresql.service fv-web.service
Requires=postgresql.service
# wird mit fv-web gestartet, gestoppt und neu gestartet
PartOf=fv-web.service

[Service]
User=$SVC
Group=$SVC
WorkingDirectory=$BASE/current
EnvironmentFile=$ENVF
ExecStart=$BASE/current/.venv/bin/python manage.py newsletter_dienst
UMask=0027
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=$DATA/mails

[Install]
WantedBy=fv-web.service
EOF
  cat > /usr/local/sbin/fv-manage <<EOF
#!/usr/bin/env bash
# Django-Befehle der Webseite ausführen, z. B.:  sudo fv-manage vorstand_anlegen …
set -euo pipefail
[[ -e $BASE/current/manage.py ]] || { echo "Anwendung nicht installiert." >&2; exit 1; }
exec runuser -u $SVC -- bash -c 'set -a; . $ENVF; set +a; cd $BASE/current; exec .venv/bin/python manage.py "\$@"' fv-manage "\$@"
EOF
  chmod 750 /usr/local/sbin/fv-manage
  systemctl daemon-reload
  app_installed && systemctl enable fv-web fv-web-newsletter >/dev/null 2>&1
  log "Dienste fv-web und fv-web-newsletter eingerichtet; Befehle: sudo fv-manage <befehl>"

  step "Caddy"
  systemctl enable caddy >/dev/null
  systemctl restart caddy   # neue Gruppenzugehörigkeit übernehmen
  log "Caddyfile schreibt fv-web-update (nächste Phase)."

  step "Datensicherung"
  [[ -f "$BENV" ]] || { ( umask 077; echo "# Datensicherung – Einstellungen (nur root)" > "$BENV" ); }
  chown root:root "$BENV"; chmod 600 "$BENV"
  ensure_kv "$BENV" RESTIC_PASSWORD "$(rnd 32)"
  ensure_kv "$BENV" RESTIC_REPOSITORY "/var/backups/fv-web-restic"
  ensure_kv "$BENV" BACKUP_KEEP_DAYS "30"
  ensure_kv "$BENV" BACKUP_KEEP_MONTHS "12"
  ensure_kv "$BENV" BACKUP_LOCAL_DAYS "7"
  ensure_kv "$BENV" BACKUP_PING_URL ""
  [[ -n "$BACKUP_REPO" ]] && set_kv "$BENV" RESTIC_REPOSITORY "$BACKUP_REPO"
  log "Backup-Ziel: $(getkv "$BENV" RESTIC_REPOSITORY)"
  install -d -m 700 /var/backups/fv-web /root/.ssh
  [[ -f /root/.ssh/fv-web-backup ]] || ssh-keygen -q -t ed25519 -N "" -C "fv-web-backup@$(hostnamectl --static)" -f /root/.ssh/fv-web-backup

  cat > /usr/local/sbin/fv-web-backup <<'BACKUP'
#!/usr/bin/env bash
# fv-web-backup – Datensicherung der Webseite (angelegt von setup-server-fv-web.sh)
# Täglich über fv-web-backup.timer; manuell: sudo fv-web-backup
#  1. Datenbank fvweb als pg_dump nach /var/backups/fv-web (BACKUP_LOCAL_DAYS Tage)
#  2. restic: Dump, Anhänge (/var/lib/fv-web/private), /etc/fv-web und – mit Mailserver –
#     /var/vmail, /etc/fv-mail, /etc/letsencrypt verschlüsselt
#     nach RESTIC_REPOSITORY (BACKUP_KEEP_DAYS tägliche, BACKUP_KEEP_MONTHS monatliche Stände)
set -Eeuo pipefail
DIR=/var/backups/fv-web; KEY=/root/.ssh/fv-web-backup; BENV=/etc/fv-web/backup.env
getkv() { grep -m1 "^$1=" "$BENV" | cut -d= -f2- | sed 's/^"//; s/"$//'; }
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
ping_url() { local u; u="$(getkv BACKUP_PING_URL)"; [[ -n "$u" ]] && curl -fsS -m 10 --retry 3 -o /dev/null "$u$1" || true; }
trap 'log "FEHLER in Zeile $LINENO – Sicherung unvollständig"; ping_url /fail' ERR
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
exec 9>/run/fv-web-backup.lock; flock -n 9 || { log "Es läuft bereits eine Sicherung."; exit 0; }
ping_url /start
STAMP="$(date +%Y%m%d-%H%M%S)"
f="$DIR/$STAMP-fvweb.dump"
runuser -u postgres -- pg_dump --format=custom --compress=9 fvweb > "$f.part"
runuser -u postgres -- pg_restore --list "$f.part" >/dev/null
mv "$f.part" "$f"; chmod 600 "$f"
log "Dump: $f ($(du -h "$f" | cut -f1))"
find "$DIR" -maxdepth 1 -name '*-fvweb.dump' -mtime +"$(getkv BACKUP_LOCAL_DAYS)" -print -delete | sed 's/^/gelöscht: /'
find "$DIR" -maxdepth 1 -name '*.part' -delete
export RESTIC_REPOSITORY RESTIC_PASSWORD
RESTIC_REPOSITORY="$(getkv RESTIC_REPOSITORY)"; RESTIC_PASSWORD="$(getkv RESTIC_PASSWORD)"
R=(restic); [[ "$RESTIC_REPOSITORY" == sftp:* ]] && R+=(-o "sftp.args=-i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new")
[[ "$RESTIC_REPOSITORY" == /* ]] && install -d -m 700 "$RESTIC_REPOSITORY"
rc=0; "${R[@]}" cat config >/dev/null 2>&1 || rc=$?
if [[ $rc -eq 10 ]]; then log "Repository wird angelegt."; "${R[@]}" init
elif [[ $rc -ne 0 ]]; then log "FEHLER: Backup-Ziel nicht erreichbar (restic Exit-Code $rc)."; false; fi
# mit Mailserver auch Postfächer, Archive, DKIM-Schlüssel und Zertifikat (Schlüssel für DANE)
ZIELE=("$f" /var/lib/fv-web/private /etc/fv-web)
for d in /var/vmail /etc/fv-mail /etc/letsencrypt; do [[ -d "$d" && -e /etc/fv-mail/mail.env ]] && ZIELE+=("$d"); done
"${R[@]}" backup --quiet --host fv-web --tag fv-web "${ZIELE[@]}"
"${R[@]}" forget --quiet --host fv-web --keep-daily "$(getkv BACKUP_KEEP_DAYS)" --keep-monthly "$(getkv BACKUP_KEEP_MONTHS)" --prune
[[ "$(date +%u)" == 7 ]] && "${R[@]}" check --read-data-subset=5%
log "Gesichert in $RESTIC_REPOSITORY ($("${R[@]}" snapshots --host fv-web --json | jq length) Stände)"
[[ "$RESTIC_REPOSITORY" == /* ]] && log "HINWEIS: Ziel liegt auf diesem Server – schützt nicht bei Ausfall des Servers."
ping_url ""
install -d -m 755 /var/lib/fv-web-status && date +%s > /var/lib/fv-web-status/sicherung   # für /health
log "Sicherung erfolgreich."
BACKUP

  cat > /usr/local/sbin/fv-web-restore <<'RESTORE'
#!/usr/bin/env bash
# fv-web-restore – Wiederherstellung (angelegt von setup-server-fv-web.sh)
#   sudo fv-web-restore -l                  Sicherungen anzeigen
#   sudo fv-web-restore -t                  neuesten Stand in die Test-Datenbank fvweb_test
#                                           einspielen (gefahrloser Wiederherstellungstest)
#   sudo fv-web-restore -r <snapshot|latest> -E
#                                           Produktion ERSETZEN: Datenbank fvweb und Anhänge
#                                           (mit Rückfrage; vorher automatische Sicherung)
#   sudo fv-web-restore -r <snapshot> -d <datei> [-d <datei> …]
#                                           einzelne Dateien (Anhänge) zurücklegen, z. B. für
#                                           fv-manage seite_wiederherstellen
set -Eeuo pipefail
BENV=/etc/fv-web/backup.env; KEY=/root/.ssh/fv-web-backup
getkv() { grep -m1 "^$1=" "$BENV" | cut -d= -f2- | sed 's/^"//; s/"$//'; }
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
SNAP=latest; MODE=""; DATEIEN=()
while getopts ":lr:tEd:" o; do
  case "$o" in l) MODE=liste ;; r) SNAP="$OPTARG" ;; t) MODE="test" ;; E) MODE="echt" ;;
    d) MODE="dateien"; DATEIEN+=("$OPTARG") ;;
    *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;; esac
done
[[ -n "$MODE" ]] || { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
export RESTIC_REPOSITORY RESTIC_PASSWORD
RESTIC_REPOSITORY="$(getkv RESTIC_REPOSITORY)"; RESTIC_PASSWORD="$(getkv RESTIC_PASSWORD)"
R=(restic); [[ "$RESTIC_REPOSITORY" == sftp:* ]] && R+=(-o "sftp.args=-i $KEY -o BatchMode=yes")
if [[ "$MODE" == liste ]]; then
  echo "Lokale Dumps:"; ls -lh /var/backups/fv-web/*.dump 2>/dev/null | awk '{print "  "$5"  "$9}' || echo "  keine"
  echo "restic ($RESTIC_REPOSITORY):"; "${R[@]}" snapshots --host fv-web; exit 0
fi
if [[ "$MODE" == dateien ]]; then
  for d in "${DATEIEN[@]}"; do
    [[ "$d" == /var/lib/fv-web/private/* && "$d" != *..* ]] || { echo "Nur Dateien unter /var/lib/fv-web/private: $d" >&2; exit 1; }
  done
  inc=(); for d in "${DATEIEN[@]}"; do inc+=(--include "$d"); done
  "${R[@]}" restore "$SNAP" --host fv-web --target / "${inc[@]}"
  for d in "${DATEIEN[@]}"; do
    if [[ -f "$d" ]]; then chown fvweb:fvweb "$d"; chmod 600 "$d"; log "zurück: $d"
    else log "NICHT im Stand $SNAP: $d"; fi
  done
  exit 0
fi
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
"${R[@]}" restore "$SNAP" --host fv-web --target "$TMP"
DUMP="$(find "$TMP" -name '*-fvweb.dump' | sort | tail -n1)"
[[ -f "$DUMP" ]] || { echo "Kein Datenbank-Dump im Stand $SNAP." >&2; exit 1; }
pg() { runuser -u postgres -- "$@"; }
if [[ "$MODE" == test ]]; then
  pg dropdb --if-exists fvweb_test; pg createdb --owner fvweb fvweb_test
  pg pg_restore --no-owner --role=fvweb -d fvweb_test < "$DUMP"
  log "Test-Datenbank fvweb_test: $(pg psql -tAc "SELECT count(*) FROM seiten_seite" fvweb_test) Seiten, $(pg psql -tAc "SELECT count(*) FROM seiten_anhang" fvweb_test) Anhänge."
  log "Anhänge im Stand: $(find "$TMP/var/lib/fv-web/private" -type f | wc -l) Dateien. Test erfolgreich."
  pg dropdb fvweb_test; exit 0
fi
echo "ACHTUNG: Datenbank fvweb und alle Anhänge werden durch den Stand $SNAP ERSETZT."
read -r -p "Zum Fortfahren 'ersetzen' eintippen: " a; [[ "$a" == ersetzen ]] || { echo "Abgebrochen."; exit 1; }
/usr/local/sbin/fv-web-backup
systemctl stop fv-web
pg dropdb fvweb; pg createdb --owner fvweb --encoding UTF8 --locale C.UTF-8 --template template0 fvweb
pg pg_restore --no-owner --role=fvweb -d fvweb < "$DUMP"
rsync -a --delete "$TMP/var/lib/fv-web/private/" /var/lib/fv-web/private/
chown -R fvweb:fvweb /var/lib/fv-web/private
systemctl start fv-web
log "Wiederhergestellt aus Stand $SNAP."
RESTORE
  chmod 750 /usr/local/sbin/fv-web-backup /usr/local/sbin/fv-web-restore

  cat > /etc/systemd/system/fv-web-backup.service <<'EOF'
[Unit]
Description=Webseite Förderverein: Datensicherung
After=postgresql.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/fv-web-backup
Nice=10
IOSchedulingClass=idle
EOF
  cat > /etc/systemd/system/fv-web-backup.timer <<'EOF'
[Unit]
Description=Webseite Förderverein: tägliche Datensicherung

[Timer]
OnCalendar=*-*-* 03:30
RandomizedDelaySec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now fv-web-backup.timer >/dev/null
  log "Sicherung täglich ~03:30. Erste Sicherung zur Kontrolle …"
  if systemctl start fv-web-backup.service; then
    journalctl -u fv-web-backup -n 4 --no-pager -o cat | sed 's/^/    /'
  else
    journalctl -u fv-web-backup -n 15 --no-pager -o cat | sed 's/^/    /'
    log "WARNUNG: Erste Sicherung fehlgeschlagen (siehe oben). Einrichtung läuft weiter."
  fi
}

# ------------------------------------------------------------- Phase harden
phase_harden() {
  step "SSH härten"
  local conf=/etc/ssh/sshd_config.d/10-fv-web-hardening.conf
  cat > "$conf" <<EOF
# SSH-Härtung (angelegt von setup-server-fv-web.sh)
Port $SSH_PORT
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers $ADMIN_USER
X11Forwarding no
MaxAuthTries 4
LoginGraceTime 30
EOF
  chmod 644 "$conf"
  if sshd -t; then
    systemctl reload ssh 2>/dev/null || systemctl restart ssh
    sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication|allowusers|port) ' | sed 's/^/    /'
  else
    rm -f "$conf"; log "FEHLER: sshd-Konfiguration ungültig – Änderung zurückgenommen."; exit 1
  fi
}

# --------------------------------------------------------------- Phase tool
# fv-web-update einrichten bzw. aktualisieren (läuft bei jedem Aufruf, auch mit -U)
phase_tool() {
  step "fv-web-update einrichten"
  [[ -f "$DENV" ]] || ( umask 077; echo "# Bereitstellung – Repository und Domain (nur root)" > "$DENV" )
  chown root:root "$DENV"; chmod 600 "$DENV"
  if [[ -n "$REPO_URL" ]]; then set_kv "$DENV" REPO_URL "$REPO_URL"
  else ensure_kv "$DENV" REPO_URL "$REPO_URL_DEFAULT"; fi
  # Repository umbenannt (FKJF → FreiVerein): alte Adresse auf vorhandenen Servern ersetzen
  case "$(getkv "$DENV" REPO_URL)" in
    https://github.com/brami/FKJF.git|https://github.com/brami/FKJF)
      set_kv "$DENV" REPO_URL "https://github.com/brami/FreiVerein.git"; log "Repository-Adresse auf brami/FreiVerein umgestellt." ;;
    git@github.com:brami/FKJF.git)
      set_kv "$DENV" REPO_URL "git@github.com:brami/FreiVerein.git"; log "Repository-Adresse auf brami/FreiVerein umgestellt." ;;
  esac
  ensure_kv "$DENV" DEFAULT_REF "main"
  set_kv "$DENV" DOMAIN "$DOMAIN"
  set_kv "$DENV" WITH_WWW "$WITH_WWW"
  set_kv "$DENV" ZUSATZ_DOMAINS "$ZUSATZ_DOMAINS"
  set_kv "$DENV" ACME_EMAIL "$ACME_EMAIL"

  # Domain in den Einstellungen der Anwendung (bei jedem Lauf, auch mit -U)
  local hosts="$DOMAIN" vorher
  [[ "$WITH_WWW" == 1 ]] && hosts="$DOMAIN,www.$DOMAIN"
  vorher="$(getkv "$ENVF" FV_BASIS_URL)"
  set_kv "$ENVF" FV_ALLOWED_HOSTS "$hosts"
  set_kv "$ENVF" FV_CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
  set_kv "$ENVF" FV_BASIS_URL "https://$DOMAIN"
  if [[ -n "$vorher" && "$vorher" != "https://$DOMAIN" ]]; then
    log "Domain geändert: $vorher -> https://$DOMAIN"
    if app_installed; then systemctl restart fv-web; log "Anwendung mit neuer Domain neu gestartet."; fi
    log "Hinweis: Angemeldete Personen müssen sich unter der neuen Adresse neu anmelden;"
    log "         bereits verschickte Einladungs-Links zeigen noch auf die alte Adresse."
  fi
  log "Repository: $(getkv "$DENV" REPO_URL) (Standard-Stand: $(getkv "$DENV" DEFAULT_REF))"
  install -d -m 700 /root/.ssh
  if [[ ! -f /root/.ssh/fv-web-deploy ]]; then
    ssh-keygen -q -t ed25519 -N "" -C "fv-web-deploy@$(hostnamectl --static)" -f /root/.ssh/fv-web-deploy
    log "Deploy-Schlüssel erzeugt (nur nötig für ein privates Repository)."
  fi

  cat > /usr/local/sbin/fv-web-update <<'UPDATE'
#!/usr/bin/env bash
# =============================================================================
#  fv-web-update – Anwendung der Webseite installieren und aktualisieren
#  (angelegt von setup-server-fv-web.sh; Einstellungen in /etc/fv-web/deploy.env)
#
#  sudo fv-web-update                 Stand von main (DEFAULT_REF) holen und installieren
#  sudo fv-web-update <ref>           bestimmten Branch, Tag oder Commit installieren
#  sudo fv-web-update -f [<ref>]      auch installieren, wenn der Commit schon aktiv ist
#  sudo fv-web-update --zurueck       vorige installierte Version wieder aktivieren
#  sudo fv-web-update --status        installierte Versionen anzeigen
#  sudo fv-web-update --pruefen       Zugriff auf das Repository prüfen
#
#  Intern (vom Einrichtungsskript):
#    --paket <datei.tar.gz> --commit <hash> --beschreibung <text>
#                                     hochgeladenen lokalen Stand installieren
#    --caddy                          Caddyfile schreiben (Anwendung oder Platzhalter)
#
#  Ablauf einer Installation: holen → Python-Umgebung → Prüfung → Sicherung →
#  Migration → statische Dateien → umschalten → Neustart → Statusprüfung.
#  Startet die neue Version nicht, wird die vorige wieder aktiviert.
#  Protokoll: /var/log/fv-web-update.log
# =============================================================================
set -Eeuo pipefail
umask 022

SVC=fvweb
BASE=/srv/fv-web
DATA=/var/lib/fv-web
ETC=/etc/fv-web
ENVF=$ETC/env
DENV=$ETC/deploy.env
KEY=/root/.ssh/fv-web-deploy
LOGF=/var/log/fv-web-update.log

[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
[[ -f "$DENV" ]] || { echo "$DENV fehlt – Server mit setup-server-fv-web.sh einrichten." >&2; exit 1; }

getkv() { grep -m1 "^$2=" "$1" | cut -d= -f2- | sed 's/^"//; s/"$//'; }
REPO_URL="$(getkv "$DENV" REPO_URL)"
DEFAULT_REF="$(getkv "$DENV" DEFAULT_REF)"
DOMAIN="$(getkv "$DENV" DOMAIN)"
WITH_WWW="$(getkv "$DENV" WITH_WWW)"
ACME_EMAIL="$(getkv "$DENV" ACME_EMAIL)"
ZUSATZ_DOMAINS="$(getkv "$DENV" ZUSATZ_DOMAINS || true)"   # leiten auf $DOMAIN um (-A)
MAIL_HOST="$(getkv "$DENV" MAIL_HOST || true)"   # nur mit Mailserver (-M)
MAIL_WEB="$(getkv "$DENV" MAIL_WEB || true)"     # z. B. mta-sts.<domain>, wenn DNS stimmt

log()  { printf '%s [update] %s\n' "$(date '+%F %T')" "$*"; }
step() { printf '\n%s [update] ===== %s =====\n' "$(date '+%F %T')" "$*"; }
app_installed() { [[ -e "$BASE/current/manage.py" ]]; }

# Zugriff per SSH-URL über den Deploy-Schlüssel (nur Lesezugriff auf dieses Repository)
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
export GIT_TERMINAL_PROMPT=0

manage_in() {  # manage.py als Dienstbenutzer; $1 = Code-Verzeichnis
  local dir="$1"; shift
  runuser -u "$SVC" -- bash -c 'set -a; . "$0"; set +a; cd "$1"; shift; exec .venv/bin/python manage.py "$@"' \
    "$ENVF" "$dir" "$@"
}

wartungsseite() {  # statische Seite, die Caddy zeigt, solange die Anwendung nicht antwortet
  install -d -o root -g root -m 755 "$DATA/wartung"
  cat > "$DATA/wartung/index.html" <<'HTML'
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <meta http-equiv="refresh" content="30">
  <title>Wartung</title>
  <link rel="stylesheet" href="/static/css/fv.css">
</head>
<body>
  <main id="inhalt" class="rahmen">
    <h1>Die Webseite wird gerade aktualisiert</h1>
    <p>In wenigen Minuten ist sie wieder erreichbar. Diese Seite lädt sich alle 30 Sekunden
      von selbst neu.</p>
  </main>
</body>
</html>
HTML
}

write_caddyfile() {  # $1 = app | platzhalter
  local tmp; tmp="$(mktemp)"
  [[ "$1" == app ]] && wartungsseite
  {
    if [[ -n "$ACME_EMAIL" ]]; then printf '{\n\temail %s\n}\n\n' "$ACME_EMAIL"; fi
    cat <<CADDY
# Webseite Förderverein KF/JF Kreuzau (angelegt von setup-server-fv-web.sh)
(sicherheit) {
	encode zstd gzip
	# Die Anwendung setzt diese Kopfzeilen selbst; "?" ergänzt sie nur, wo sie
	# fehlen (statische Dateien, Platzhalter)
	header {
		?Strict-Transport-Security "max-age=31536000"
		?X-Content-Type-Options "nosniff"
		-Server
	}
}

$DOMAIN {
	import sicherheit
	log {
		output file /var/log/caddy/fv-web.log {
			roll_size 10MiB
			roll_keep 10
		}
	}
CADDY
    if [[ "$1" == app && -n "$MAIL_HOST" ]]; then
      cat <<'CADDY'
	# Einstellungen für Thunderbird & Co. (Mailserver)
	handle_path /.well-known/autoconfig/* {
		root * /var/lib/fv-mail/www/autoconfig
		file_server
	}
CADDY
    fi
    if [[ "$1" == app ]]; then
      cat <<'CADDY'
	# Mehrere Anhänge à 20 MB in einem Formular
	request_body {
		max_size 150MB
	}
	handle_path /static/* {
		root * /var/lib/fv-web/static
		header Cache-Control "public, max-age=3600"
		file_server
	}
	handle {
		reverse_proxy unix//run/fv-web/gunicorn.sock
	}
	# Anwendung antwortet nicht (Update, Neustart, Ausfall): Wartungsseite statt leerer Fehlerseite
	handle_errors {
		@ausfall expression `{err.status_code} in [502, 503, 504]`
		handle @ausfall {
			root * /var/lib/fv-web/wartung
			rewrite * /index.html
			header Retry-After 60
			header Cache-Control no-store
			file_server
		}
	}
}
CADDY
    else
      cat <<'CADDY'
	# Platzhalter bis zur Installation der Anwendung
	root * /var/lib/fv-web/platzhalter
	file_server
}
CADDY
    fi
    if [[ "$WITH_WWW" == 1 ]]; then
      printf '\nwww.%s {\n\tredir https://%s{uri} permanent\n}\n' "$DOMAIN" "$DOMAIN"
    fi
    local z
    for z in $ZUSATZ_DOMAINS; do
      # weitere Domains (z. B. mit Umlaut) leiten auf die Hauptdomain um
      if [[ "$WITH_WWW" == 1 ]]; then
        printf '\n%s, www.%s {\n\tredir https://%s{uri} permanent\n}\n' "$z" "$z" "$DOMAIN"
      else
        printf '\n%s {\n\tredir https://%s{uri} permanent\n}\n' "$z" "$DOMAIN"
      fi
    done
    if [[ -n "$MAIL_HOST" ]]; then
      # Zertifikat des Mailservers: certbot legt die Antwort in /var/lib/fv-mail/acme ab
      printf '\nhttp://%s {\n\thandle /.well-known/acme-challenge/* {\n\t\troot * /var/lib/fv-mail/acme\n\t\tfile_server\n\t}\n\thandle {\n\t\tredir https://%s{uri}\n\t}\n}\n' "$MAIL_HOST" "$DOMAIN"
    fi
    if [[ " $MAIL_WEB " == *" mta-sts.$DOMAIN "* ]]; then
      printf '\nmta-sts.%s {\n\timport sicherheit\n\troot * /var/lib/fv-mail/www/mta-sts\n\tfile_server\n}\n' "$DOMAIN"
    fi
  } > "$tmp"
  if caddy validate --adapter caddyfile --config "$tmp" >/dev/null 2>&1; then
    install -m 644 "$tmp" /etc/caddy/Caddyfile; rm -f "$tmp"
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
    log "Caddyfile geschrieben ($1) und geladen."
  else
    caddy validate --adapter caddyfile --config "$tmp" 2>&1 | tail -5 || true
    rm -f "$tmp"; log "FEHLER: Caddyfile ungültig – unverändert gelassen."; exit 1
  fi
}

gesund() {
  [[ "$(curl -s --max-time 5 --unix-socket /run/fv-web/gunicorn.sock \
          -H "Host: $DOMAIN" -H 'X-Forwarded-Proto: https' http://localhost/gesund/ || true)" == ok ]]
}

warte_gesund() {
  local _
  for _ in $(seq 1 20); do gesund && return 0; sleep 1; done
  return 1
}

aktiviere() {  # aktiviere <release-verzeichnis>
  ln -sfn "$1" "$BASE/current.neu" && mv -T "$BASE/current.neu" "$BASE/current"
  systemctl daemon-reload
  systemctl enable fv-web >/dev/null
  systemctl enable fv-web-newsletter >/dev/null 2>&1 || true
  systemctl restart fv-web
  systemctl restart fv-web-newsletter 2>/dev/null || true
}

pruefen() {
  if git ls-remote --exit-code "$REPO_URL" HEAD >/dev/null 2>&1; then
    log "Repository erreichbar: $REPO_URL"
    return 0
  fi
  log "FEHLER: Kein Zugriff auf $REPO_URL"
  if [[ "$REPO_URL" == git@* || "$REPO_URL" == ssh://* ]]; then
    log "Deploy-Schlüssel bei GitHub eintragen: Repository → Settings → Deploy keys → Add deploy key"
    log "(Titel z. B. \"Webserver\", \"Allow write access\" NICHT anhaken):"
    sed 's/^/    /' "$KEY.pub"
  else
    log "Ist das Repository privat? Dann per SSH-URL und Deploy-Schlüssel holen:"
    log "    setup-server-fv-web.sh … -R git@github.com:<besitzer>/<repo>.git"
  fi
  return 1
}

status() {
  if app_installed; then
    echo "Aktiv:"; sed 's/^/  /' "$BASE/current/.release"
  else
    echo "Keine Anwendung installiert."
  fi
  echo "Installierte Versionen (neueste zuerst):"
  ls -1t "$BASE/releases" 2>/dev/null | sed 's/^/  /' || true
  echo "Repository: $REPO_URL (Standard: $DEFAULT_REF)"
}

installiere() {  # installiere <tar.gz> <commit> <beschreibung>
  local tarball="$1" commit="$2" desc="$3"
  local rel prev=""
  rel="$BASE/releases/$(date +%Y%m%d-%H%M%S)-${commit:0:7}"
  [[ -L "$BASE/current" ]] && prev="$(readlink -f "$BASE/current")"

  step "Entpacken: $desc"
  install -d -m 750 -o root -g "$SVC" "$rel"
  tar -xzf "$tarball" -C "$rel" --strip-components=1 --no-same-owner
  for f in manage.py requirements.txt config/settings.py; do
    [[ -f "$rel/$f" ]] || { log "FEHLER: $f fehlt im Paket."; rm -rf "$rel"; exit 1; }
  done
  printf 'Commit:      %s\nStand:       %s\nQuelle:      %s\nInstalliert: %s\n' \
    "$commit" "$desc" "$SOURCE" "$(date '+%F %T')" > "$rel/.release"

  step "Python-Umgebung"
  python3 -m venv "$rel/.venv"
  "$rel/.venv/bin/pip" install -q --no-cache-dir --disable-pip-version-check -r "$rel/requirements.txt"
  # Code gehört root und ist für den Dienst nur lesbar
  chown -R root:"$SVC" "$rel"; chmod -R g+rX,g-w,o-rwx "$rel"
  log "$("$rel/.venv/bin/python" -c 'import django; print("Django", django.get_version())')"

  step "Prüfung"
  manage_in "$rel" check --deploy --fail-level ERROR

  step "Datensicherung vor dem Update"
  if app_installed && systemctl cat fv-web-backup.service >/dev/null 2>&1; then
    if systemctl start fv-web-backup.service; then log "Sicherung erstellt."
    else log "WARNUNG: Sicherung fehlgeschlagen – Update läuft trotzdem weiter."; fi
  else
    log "Erstinstallation – keine Sicherung nötig."
  fi

  step "Datenbank migrieren, statische Dateien"
  manage_in "$rel" migrate --noinput
  manage_in "$rel" createcachetable
  # Mailserver: Leserecht nur auf die Sichten für Dovecot und Exim (wie phase_mail)
  runuser -u postgres -- psql -d fvweb -v ON_ERROR_STOP=1 -qtA >/dev/null <<'SQL'
DO $$ DECLARE s text; BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dovecot') THEN
    GRANT CONNECT ON DATABASE fvweb TO dovecot;
    FOR s IN SELECT viewname FROM pg_views WHERE schemaname = 'public'
             AND viewname IN ('dovecot_benutzer') LOOP
      EXECUTE format('GRANT SELECT ON %I TO dovecot', s);
    END LOOP;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'Debian-exim') THEN
    GRANT CONNECT ON DATABASE fvweb TO "Debian-exim";
    FOR s IN SELECT viewname FROM pg_views WHERE schemaname = 'public'
             AND viewname IN ('exim_adressen', 'exim_verteiler', 'exim_absender',
                              'exim_plus_gesperrt', 'mail_archive') LOOP
      EXECUTE format('GRANT SELECT ON %I TO "Debian-exim"', s);
    END LOOP;
  END IF;
END $$;
SQL
  manage_in "$rel" collectstatic --noinput --clear -v0
  log "Statische Dateien: $(find "$DATA/static" -type f | wc -l)"

  step "Aktivieren und starten"
  aktiviere "$rel"
  if ! warte_gesund; then
    journalctl -u fv-web -n 40 --no-pager -o cat | sed 's/^/    /' || true
    if [[ -n "$prev" && -d "$prev" ]]; then
      aktiviere "$prev"
      rm -rf "$rel"   # defekte Version entfernen, damit --zurueck sie nicht wählt
      if warte_gesund; then
        log "FEHLER: Neue Version startet nicht – vorige Version $(basename "$prev") wieder aktiv."
      else
        log "FEHLER: Neue Version startet nicht, und auch die vorige Version $(basename "$prev") antwortet nicht!"
      fi
      log "        Datenbank-Migrationen der neuen Version wurden NICHT zurückgenommen."
    else
      rm -rf "$rel"
      rm -f "$BASE/current"
      systemctl stop fv-web 2>/dev/null || true
      log "FEHLER: Anwendung startet nicht (Protokoll siehe oben). Es bleibt bei der Platzhalterseite."
    fi
    exit 1
  fi
  log "Anwendung läuft: $desc"
  write_caddyfile app

  # die letzten drei Versionen behalten
  ls -1dt "$BASE"/releases/*/ | tail -n +4 | xargs -r rm -rf
  log "Versionen: $(ls -1t "$BASE/releases" | paste -sd ' ')"

  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/gesund/" || true)
  if [[ "$code" == 200 ]]; then log "https://$DOMAIN/gesund/: in Ordnung."
  else log "HINWEIS: https://$DOMAIN noch nicht erreichbar (HTTP ${code:-–}). Meist fehlt noch das Zertifikat (DNS prüfen)."; fi
}

zurueck() {
  app_installed || { log "Keine Anwendung installiert."; exit 1; }
  local cur prev
  cur="$(readlink -f "$BASE/current")"
  prev="$(ls -1dt "$BASE"/releases/*/ | sed 's:/$::' | grep -vx "$cur" | head -n1 || true)"
  [[ -n "$prev" ]] || { log "Keine vorige Version vorhanden."; exit 1; }
  step "Zurück auf $(basename "$prev")"
  log "Achtung: Datenbank-Migrationen der aktuellen Version werden NICHT zurückgenommen."
  aktiviere "$prev"
  if warte_gesund; then log "Vorige Version aktiv: $(grep '^Stand' "$prev/.release" | cut -d: -f2- | xargs)"
  else
    journalctl -u fv-web -n 30 --no-pager -o cat | sed 's/^/    /' || true
    aktiviere "$cur"; log "FEHLER: Vorige Version startet nicht – aktuelle Version wieder aktiv."; exit 1
  fi
}

# ----------------------------------------------------------------- Aufruf
MODE=holen; REF=""; FORCE=0; PAKET=""; COMMIT=""; DESC=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --status) MODE=status ;;
    --pruefen) MODE=pruefen ;;
    --zurueck) MODE=zurueck ;;
    --caddy) MODE=caddy ;;
    --paket) MODE=paket; PAKET="${2:?}"; shift ;;
    --commit) COMMIT="${2:?}"; shift ;;
    --beschreibung) DESC="${2:?}"; shift ;;
    -f|--erzwingen) FORCE=1 ;;
    -h|--hilfe) sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    *) REF="$1" ;;
  esac
  shift
done

case "$MODE" in
  status)  status; exit 0 ;;
  pruefen) pruefen; exit $? ;;
  caddy)   if app_installed; then write_caddyfile app; else write_caddyfile platzhalter; fi; exit 0 ;;
esac

# Ab hier ändert sich etwas: sperren und protokollieren
exec 9>/run/fv-web-update.lock
flock -n 9 || { echo "Es läuft bereits ein Update." >&2; exit 1; }
touch "$LOGF"; chmod 640 "$LOGF"
exec > >(tee -a "$LOGF") 2>&1
trap 'log "FEHLER in Zeile $LINENO (Exit-Code $?)"' ERR
log "Start: fv-web-update $MODE ${REF:-}"

case "$MODE" in
  zurueck) zurueck ;;
  paket)
    [[ -f "$PAKET" ]] || { log "FEHLER: Paket fehlt: $PAKET"; exit 1; }
    SOURCE="hochgeladen (lokaler Stand)"
    installiere "$PAKET" "${COMMIT:-unbekannt}" "${DESC:-lokaler Stand}"
    rm -f "$PAKET" ;;
  holen)
    REF="${REF:-$DEFAULT_REF}"
    [[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || { log "FEHLER: Ungültiger Git-Stand: $REF"; exit 1; }
    pruefen || exit 1
    WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
    step "Hole $REF aus $REPO_URL"
    git -C "$WORK" init -q
    git -C "$WORK" fetch -q --depth 1 "$REPO_URL" "$REF" || { log "FEHLER: $REF nicht gefunden."; exit 1; }
    COMMIT="$(git -C "$WORK" rev-parse FETCH_HEAD)"
    DESC="$(git -C "$WORK" log -1 --format='%h %s (%ad)' --date=short FETCH_HEAD)"
    log "Stand: $DESC"
    if [[ $FORCE -eq 0 ]] && app_installed && grep -q "^Commit: *$COMMIT$" "$BASE/current/.release" && gesund; then
      log "Dieser Stand ist bereits installiert – nichts zu tun (erneut installieren mit -f)."
      exit 0
    fi
    git -C "$WORK" archive --format=tar.gz --prefix=fv-web/ FETCH_HEAD > "$WORK/paket.tar.gz"
    SOURCE="$REPO_URL ($REF)"
    installiere "$WORK/paket.tar.gz" "$COMMIT" "$DESC" ;;
esac
log "Fertig."
UPDATE
  chmod 750 /usr/local/sbin/fv-web-update
  log "fv-web-update installiert: sudo fv-web-update [<ref>|--status|--zurueck|--pruefen]"
  /usr/local/sbin/fv-web-update --caddy

  step "Überwachung (fv-web-status für /health)"
  install -d -m 755 /var/lib/fv-web-status
  set_kv "$ENVF" FV_STATUS_DATEI "/var/lib/fv-web-status/status.json"
  cat > /usr/local/sbin/fv-web-status <<'STATUS'
#!/usr/bin/env bash
# =============================================================================
#  fv-web-status – Zustand des Servers für https://<domain>/health
#  (angelegt von setup-server-fv-web.sh; läuft alle 5 Minuten, fv-web-status.timer)
#
#  Schreibt /var/lib/fv-web-status/status.json: {"zeit", "probleme", "hinweise"}.
#  Die Webseite ergänzt Datenbank und Newsletter-Dienst und antwortet mit 200 oder 503.
#  sudo fv-web-status       prüfen und Ergebnis anzeigen
# =============================================================================
set -uo pipefail
DIR=/var/lib/fv-web-status
install -d -m 755 "$DIR"
DOMAIN="$(grep -m1 '^DOMAIN=' /etc/fv-web/deploy.env 2>/dev/null | cut -d= -f2- | tr -d '"')"
jetzt="$(date +%s)"
probleme=(); hinweise=()
problem() { probleme+=("$1"); }
hinweis() { hinweise+=("$1"); }
dienst() { systemctl is-active --quiet "$1" || problem "Dienst $2 läuft nicht"; }
laeuft_ab() {  # laeuft_ab <zertifikat> <name>
  [[ -r "$1" ]] || { problem "Zertifikat $2 fehlt"; return; }
  openssl x509 -checkend $((14 * 86400)) -noout -in "$1" >/dev/null 2>&1 \
    || problem "Zertifikat $2 läuft in weniger als 14 Tagen ab"
}

# --- Webseite
dienst postgresql "Datenbank (PostgreSQL)"
dienst caddy "Webserver (Caddy)"
if [[ -e /srv/fv-web/current/manage.py ]]; then
  dienst fv-web "Webseite"
  dienst fv-web-newsletter "Newsletter-Versand"
fi
if [[ -n "$DOMAIN" ]]; then
  zert="$(find /var/lib/caddy -name "$DOMAIN.crt" -path '*certificates*' 2>/dev/null | head -n1)"
  if [[ -n "$zert" ]]; then laeuft_ab "$zert" "der Webseite"
  else hinweis "Zertifikat der Webseite noch nicht vorhanden"; fi
fi

# --- Datensicherung: letzte erfolgreiche (Marke von fv-web-backup, sonst neuester Dump)
if [[ -f "$DIR/sicherung" ]]; then t="$(cat "$DIR/sicherung")"
else t="$(stat -c %Y "$(ls -1t /var/backups/fv-web/*.dump 2>/dev/null | head -n1)" 2>/dev/null || echo 0)"; fi
[[ "$t" =~ ^[0-9]+$ ]] || t=0
if (( t == 0 )); then problem "Noch keine erfolgreiche Datensicherung"
elif (( jetzt - t > 26 * 3600 )); then problem "Letzte erfolgreiche Datensicherung vor $(( (jetzt - t) / 3600 )) Stunden"; fi
systemctl is-failed --quiet fv-web-backup.service && problem "Letzte Datensicherung fehlgeschlagen"
grep -q '^RESTIC_REPOSITORY="\{0,1\}/' /etc/fv-web/backup.env 2>/dev/null \
  && hinweis "Datensicherung liegt nur auf diesem Server"

# --- Speicherplatz (ab 90 % belegt)
while read -r belegt ziel; do
  belegt="${belegt%\%}"
  [[ "$belegt" =~ ^[0-9]+$ ]] && (( belegt >= 90 )) && problem "Speicherplatz $ziel zu $belegt % belegt"
done < <(df --output=pcent,target -x tmpfs -x devtmpfs -x overlay -x squashfs 2>/dev/null | tail -n +2)

# --- System
[[ -f /run/reboot-required ]] && hinweis "Neustart nötig (Updates)"

# --- Mailserver (nur wenn eingerichtet)
if [[ -f /etc/fv-mail/mail.env ]]; then
  dienst exim4 "Mailserver (Exim)"
  dienst dovecot "Postfächer (Dovecot)"
  dienst rspamd "Spamfilter (rspamd)"
  dienst redis-server "Redis"
  dienst unbound "DNS-Resolver (unbound)"
  laeuft_ab /etc/fv-mail/tls/fullchain.pem "des Mailservers"
  if [[ -r /etc/fv-mail/tls/fullchain.pem ]] && [[ "$(openssl x509 -in /etc/fv-mail/tls/fullchain.pem -noout -subject -nameopt compat)" == \
       "$(openssl x509 -in /etc/fv-mail/tls/fullchain.pem -noout -issuer -nameopt compat | sed 's/^issuer=/subject=/')" ]]; then
    problem "Mailserver hat nur ein vorläufiges (selbst signiertes) Zertifikat"
  fi
  alt="$(exiqgrep -o 3600 -c 2>/dev/null | awk '{print $1}')"
  [[ "$alt" =~ ^[0-9]+$ ]] && (( alt > 20 )) && problem "$alt Mails warten länger als eine Stunde in der Warteschlange"
  eingefroren="$(exiqgrep -z -c 2>/dev/null | awk '{print $1}')"
  [[ "$eingefroren" =~ ^[0-9]+$ ]] && (( eingefroren > 0 )) && hinweis "$eingefroren eingefrorene Mail(s) in der Warteschlange"
  systemctl is-failed --quiet fv-mail-sync.service && problem "Abgleich Mailserver – Webseite fehlgeschlagen"
  systemctl is-failed --quiet fv-mail-taeglich.service && problem "Tägliche Aufgaben des Mailservers fehlgeschlagen"
fi

liste() { if (( $# )); then printf '%s\n' "$@" | jq -R . | jq -s -c .; else echo '[]'; fi; }
tmp="$(mktemp "$DIR/.status.XXXXXX")"
jq -n --argjson zeit "$jetzt" --argjson p "$(liste "${probleme[@]}")" --argjson h "$(liste "${hinweise[@]}")" \
  '{zeit: $zeit, probleme: $p, hinweise: $h}' > "$tmp"
chmod 644 "$tmp"; mv "$tmp" "$DIR/status.json"
if [[ -t 1 ]]; then
  if (( ${#probleme[@]} )); then printf 'Problem:  %s\n' "${probleme[@]}"; else echo "Keine Probleme."; fi
  (( ${#hinweise[@]} )) && printf 'Hinweis:  %s\n' "${hinweise[@]}"
fi
exit 0
STATUS
  chmod 755 /usr/local/sbin/fv-web-status
  cat > /etc/systemd/system/fv-web-status.service <<'EOF'
[Unit]
Description=Zustand des Servers für /health prüfen

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/fv-web-status
Nice=10
EOF
  cat > /etc/systemd/system/fv-web-status.timer <<'EOF'
[Unit]
Description=Zustand des Servers alle 5 Minuten prüfen

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now fv-web-status.timer >/dev/null
  /usr/local/sbin/fv-web-status >/dev/null
  log "Überwachung: https://$DOMAIN/health (Gesamtzustand) und /health/live (Lebenszeichen)"

  if [[ "$NO_APP" != 1 && "$LOCAL_UPLOAD" != 1 ]]; then
    step "Zugriff auf das Repository"
    if ! /usr/local/sbin/fv-web-update --pruefen; then
      log "Anwendung wird nicht installiert. Nach dem Eintragen des Schlüssels erneut mit -U aufrufen"
      log "oder direkt auf dem Server: sudo fv-web-update"
      exit 1
    fi
  fi
}

# --------------------------------------------------------------- Phase app
phase_app() {
  if [[ "$LOCAL_UPLOAD" == 1 ]]; then
    /usr/local/sbin/fv-web-update --paket "$REMOTE_TAR" --commit "$APP_COMMIT" --beschreibung "$APP_DESC"
  elif [[ -n "$GIT_REF" ]]; then
    /usr/local/sbin/fv-web-update "$GIT_REF"
  else
    /usr/local/sbin/fv-web-update
  fi
}

# ------------------------------------------------------------- Phase admin
phase_admin() {
  step "Vorstandskonto $APP_ADMIN"
  /usr/local/sbin/fv-manage vorstand_anlegen "$APP_ADMIN" "$APP_ADMIN_MAIL" --admin
  log "Den Link nur an $APP_ADMIN weitergeben. Er ist nach dem Setzen des Passworts verbraucht."
}

# --------------------------------------------------------------- Phase mail
# Mailserver: Exim (SMTP), Dovecot (IMAP, Sieve), rspamd (Spam, Greylisting, Anhänge),
# unbound (DNSSEC), certbot (Zertifikat für den Mail-Rechnernamen, Schlüssel bleibt für DANE).
# Adressen, Postfächer, Verteiler und Rechte kommen aus der Datenbank der Webseite.
MENV=/etc/fv-mail/mail.env

vorlage() {  # vorlage ZIEL MODUS BESITZER:GRUPPE < Text  (ersetzt @DOMAIN@, @HOST@ …)
  local tmp; tmp="$(mktemp)"
  sed -e "s|@DOMAIN@|$MAIL_DOMAIN|g" -e "s|@HOST@|$MAIL_HOST|g" -e "s|@VMAIL_UID@|${VMAIL_UID:-}|g" \
      -e "s|@QUOTA@|${QUOTA:-5}|g" -e "s|@ZUSATZ@|${ZUSATZ_DOMAINS// / : }|g" -e "s|@LISTEN@|${LISTEN:-*}|g" > "$tmp"
  install -m "$2" -o "${3%:*}" -g "${3#*:}" "$tmp" "$1"; rm -f "$tmp"
}

mail_rechte_sql() {  # Leserechte der Mailserver-Rollen auf die Sichten (wie in fv-web-update)
  runuser -u postgres -- psql -d fvweb -v ON_ERROR_STOP=1 -qtA >/dev/null <<'SQL'
DO $$ DECLARE s text; BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dovecot') THEN
    GRANT CONNECT ON DATABASE fvweb TO dovecot;
    FOR s IN SELECT viewname FROM pg_views WHERE schemaname = 'public'
             AND viewname IN ('dovecot_benutzer') LOOP
      EXECUTE format('GRANT SELECT ON %I TO dovecot', s);
    END LOOP;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'Debian-exim') THEN
    GRANT CONNECT ON DATABASE fvweb TO "Debian-exim";
    FOR s IN SELECT viewname FROM pg_views WHERE schemaname = 'public'
             AND viewname IN ('exim_adressen', 'exim_verteiler', 'exim_absender',
                              'exim_plus_gesperrt', 'mail_archive') LOOP
      EXECUTE format('GRANT SELECT ON %I TO "Debian-exim"', s);
    END LOOP;
  END IF;
END $$;
SQL
}

dns_a() { dig +short +time=3 +tries=2 @1.1.1.1 "$2" "$1" 2>/dev/null | grep -v '\.$' || true; }

phase_mail() {
  app_installed || { log "FEHLER: Der Mailserver braucht die installierte Anwendung (Datenbanksichten). Zuerst ohne -N ausführen."; exit 1; }
  MAIL_DOMAIN="$DOMAIN"
  local ip4 ip6 ptr4 ptr6 nur_ipv4=0 pw tmp policy alt

  step "Mailserver: Einstellungen ($MENV)"
  install -d -m 755 /etc/fv-mail
  [[ -f "$MENV" ]] || ( umask 077; echo "# Mailserver – Einstellungen (nur root)" > "$MENV" )
  chown root:root "$MENV"; chmod 600 "$MENV"
  set_kv "$MENV" MAIL_DOMAIN "$MAIL_DOMAIN"
  set_kv "$MENV" MAIL_HOST "$MAIL_HOST"
  set_kv "$MENV" ZUSATZ_DOMAINS "$ZUSATZ_DOMAINS"
  ensure_kv "$MENV" DKIM_SELECTOR "fv$(date +%Y)"
  ensure_kv "$MENV" SRS_SECRET "$(rnd 32)"
  ensure_kv "$MENV" RSPAMD_PASSWORT "$(rnd 18)"
  ensure_kv "$MENV" MTA_STS_MODE "testing"
  ensure_kv "$MENV" MTA_STS_ID ""
  ensure_kv "$MENV" POSTMASTER ""
  [[ -n "$POSTMASTER" ]] && set_kv "$MENV" POSTMASTER "$POSTMASTER"
  if [[ -z "$(getkv "$MENV" POSTMASTER)" ]]; then
    set_kv "$MENV" POSTMASTER "$(getkv "$ENVF" FV_ADMINS | cut -d, -f1 | xargs)"
  fi
  [[ -n "$(getkv "$MENV" POSTMASTER)" ]] \
    || { log "FEHLER: Keine Adresse für postmaster@/abuse@ (Betreuung). Bitte mit -P <adresse> angeben."; exit 1; }
  QUOTA="$(getkv "$ENVF" FV_MAIL_QUOTA_GB || true)"; QUOTA="${QUOTA:-5}"
  [[ "$QUOTA" =~ ^[0-9]+$ ]] || QUOTA=5
  set_kv "$DENV" MAIL_HOST "$MAIL_HOST"
  log "Mail-Domain $MAIL_DOMAIN, Rechnername $MAIL_HOST, Betreuung (postmaster@): $(getkv "$MENV" POSTMASTER)"

  step "Mailserver: Pakete"
  apt_install exim4-daemon-heavy dovecot-core dovecot-imapd dovecot-lmtpd dovecot-pgsql \
              dovecot-sieve dovecot-managesieved rspamd redis-server unbound certbot openssl
  log "$(exim -bV | head -n1 | cut -d' ' -f1-3) | Dovecot $(dovecot --version | cut -d' ' -f1) | rspamd $(rspamd --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -n1)"

  step "Mailserver: Netz, Reverse-DNS"
  ip4="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="src") print $(i+1)}' | head -n1)"
  ip6="$(ip -6 route get 2606:4700:4700::1111 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="src") print $(i+1)}' | head -n1)"
  [[ "$ip6" == f[cd]* || "$ip6" == fe80* ]] && ip6=""
  set_kv "$MENV" MAIL_IPV4 "$ip4"
  ptr4="$(dig +short -x "$ip4" @1.1.1.1 2>/dev/null | sed 's/\.$//' | head -n1 || true)"
  if [[ "$ptr4" == "$MAIL_HOST" ]]; then log "PTR $ip4 -> $ptr4: in Ordnung."
  else log "WARNUNG: PTR von $ip4 ist '${ptr4:-leer}', erwartet $MAIL_HOST – beim Server-Anbieter eintragen (sonst landen Mails im Spam)."; fi
  if [[ -n "$ip6" ]]; then
    ptr6="$(dig +short -x "$ip6" @1.1.1.1 2>/dev/null | sed 's/\.$//' | head -n1 || true)"
    if [[ "$ptr6" == "$MAIL_HOST" ]]; then
      log "PTR $ip6 -> $ptr6: in Ordnung, Mails werden auch über IPv6 verschickt."
    else
      nur_ipv4=1
      log "HINWEIS: Kein passender PTR für IPv6 $ip6 – der Mailserver verwendet nur IPv4."
      log "         Nach dem Eintragen ($ip6 -> $MAIL_HOST) erneut mit -M ausführen."
    fi
  fi
  [[ $nur_ipv4 -eq 1 ]] && ip6=""
  set_kv "$MENV" MAIL_IPV6 "$ip6"
  if timeout 8 bash -c 'exec 3<>/dev/tcp/gmail-smtp-in.l.google.com/25' 2>/dev/null; then
    log "Ausgehende Verbindungen auf Port 25: möglich."
  else
    log "WARNUNG: Ausgehender Port 25 scheint gesperrt (Anbieter fragen) – Mails nach außen bleiben sonst in der Warteschlange."
  fi

  step "Mailserver: Benutzer, Verzeichnisse, Datenbank"
  id vmail >/dev/null 2>&1 || { useradd --system --home-dir /var/vmail --shell /usr/sbin/nologin vmail; log "Systembenutzer vmail angelegt."; }
  VMAIL_UID="$(id -u vmail)"
  install -d -o vmail -g vmail -m 750 /var/vmail /var/vmail/konten /var/vmail/archiv
  install -d -o root -g root -m 755 /var/lib/fv-mail /var/lib/fv-mail/acme /var/lib/fv-mail/www \
             /usr/local/lib/fv-mail /usr/local/lib/fv-mail/sieve-pipe
  install -d -o root -g Debian-exim -m 750 /etc/fv-mail/dkim /etc/fv-mail/tls
  if [[ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='Debian-exim'")" != 1 ]]; then
    runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole Debian-exim
    log "Datenbankrolle Debian-exim angelegt (Exim liest Adressen, nur über den Socket)."
  fi
  mail_rechte_sql
  log "Leserechte auf die Sichten vergeben (dovecot, Debian-exim)."

  step "Mailserver: DNS-Resolver (unbound, DNSSEC)"
  cat > /etc/unbound/unbound.conf.d/fv-mail.conf <<'EOF'
# eigener DNS-Resolver für den Mailserver (DNSSEC für DANE; DNS-Sperrlisten lehnen
# Anfragen über öffentliche Resolver ab) – angelegt von setup-server-fv-web.sh
server:
    interface: 127.0.0.1
    access-control: 127.0.0.0/8 allow
    hide-identity: yes
    hide-version: yes
    qname-minimisation: yes
    prefetch: yes
EOF
  unbound-checkconf >/dev/null
  systemctl enable unbound >/dev/null; systemctl restart unbound; sleep 1
  if dig +dnssec +time=5 @127.0.0.1 debian.org SOA 2>/dev/null | grep -q 'flags:.* ad'; then
    if ! grep -qx 'nameserver 127.0.0.1' /etc/resolv.conf 2>/dev/null; then
      [[ -e /etc/resolv.conf.fv-vorher ]] || cp -P /etc/resolv.conf /etc/resolv.conf.fv-vorher 2>/dev/null || true
      rm -f /etc/resolv.conf
      printf '# angelegt von setup-server-fv-web.sh: lokaler Resolver (unbound)\n# vorher: /etc/resolv.conf.fv-vorher\nnameserver 127.0.0.1\noptions edns0 trust-ad\n' > /etc/resolv.conf
      if [[ -d /etc/dhcp/dhclient-enter-hooks.d ]]; then
        printf '# fv-mail: resolv.conf nicht überschreiben (lokaler Resolver unbound)\nmake_resolv_conf() { :; }\n' \
          > /etc/dhcp/dhclient-enter-hooks.d/fv-unbound
      fi
      log "/etc/resolv.conf zeigt auf unbound (127.0.0.1)."
    fi
    log "unbound antwortet und prüft DNSSEC."
  else
    log "WARNUNG: unbound liefert keine DNSSEC-geprüften Antworten – /etc/resolv.conf bleibt unverändert."
  fi

  step "Mailserver: DKIM-Schlüssel"
  local sel; sel="$(getkv "$MENV" DKIM_SELECTOR)"
  if [[ ! -f "/etc/fv-mail/dkim/$sel.key" ]]; then
    ( umask 027; openssl genpkey -quiet -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "/etc/fv-mail/dkim/$sel.key" )
    log "DKIM-Schlüssel $sel erzeugt (öffentlicher Teil: sudo fv-mail dns)."
  fi
  chown root:Debian-exim "/etc/fv-mail/dkim/$sel.key"; chmod 640 "/etc/fv-mail/dkim/$sel.key"

  step "Mailserver: Webseiten-Teile (Zertifikat, MTA-STS, Autoconfig)"
  policy="$(printf 'version: STSv1\nmode: %s\nmx: %s\nmax_age: 604800\n' "$(getkv "$MENV" MTA_STS_MODE)" "$MAIL_HOST")"
  install -d -m 755 /var/lib/fv-mail/www/mta-sts/.well-known /var/lib/fv-mail/www/autoconfig/mail
  alt="$(cat /var/lib/fv-mail/www/mta-sts/.well-known/mta-sts.txt 2>/dev/null || true)"
  if [[ "$alt" != "$policy" || -z "$(getkv "$MENV" MTA_STS_ID)" ]]; then
    printf '%s\n' "$policy" > /var/lib/fv-mail/www/mta-sts/.well-known/mta-sts.txt
    set_kv "$MENV" MTA_STS_ID "$(date +%Y%m%d%H%M%S)"
  fi
  vorlage /var/lib/fv-mail/www/autoconfig/mail/config-v1.1.xml 644 root:root <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<clientConfig version="1.1">
  <emailProvider id="@DOMAIN@">
    <domain>@DOMAIN@</domain>
    <displayName>@DOMAIN@</displayName>
    <displayShortName>@DOMAIN@</displayShortName>
    <incomingServer type="imap">
      <hostname>@HOST@</hostname>
      <port>993</port>
      <socketType>SSL</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>@HOST@</hostname>
      <port>465</port>
      <socketType>SSL</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </outgoingServer>
  </emailProvider>
</clientConfig>
XML
  # mta-sts.<domain> nur, wenn der Name schon auf diesen Server zeigt (sonst scheitert das Zertifikat)
  if [[ -n "$ip4" ]] && dns_a A "mta-sts.$MAIL_DOMAIN" | grep -qx "$ip4"; then
    set_kv "$DENV" MAIL_WEB "mta-sts.$MAIL_DOMAIN"
  else
    set_kv "$DENV" MAIL_WEB ""
    log "HINWEIS: mta-sts.$MAIL_DOMAIN zeigt noch nicht auf diesen Server – MTA-STS folgt nach dem DNS-Eintrag (erneut -M)."
  fi
  /usr/local/sbin/fv-web-update --caddy

  step "Mailserver: Zertifikat für $MAIL_HOST"
  install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
  cat > /etc/letsencrypt/renewal-hooks/deploy/fv-mail <<'HOOK'
#!/bin/sh
# Zertifikat des Mailservers nach /etc/fv-mail/tls kopieren (angelegt von setup-server-fv-web.sh)
set -e
[ "${RENEWED_LINEAGE##*/}" = fv-mail ] || exit 0
install -m 644 -o root -g Debian-exim "$RENEWED_LINEAGE/fullchain.pem" /etc/fv-mail/tls/fullchain.pem
install -m 640 -o root -g Debian-exim "$RENEWED_LINEAGE/privkey.pem" /etc/fv-mail/tls/privkey.pem
systemctl reload dovecot 2>/dev/null || true
HOOK
  chmod 755 /etc/letsencrypt/renewal-hooks/deploy/fv-mail
  local acme_mail=(--register-unsafely-without-email)
  [[ -n "$ACME_EMAIL" ]] && acme_mail=(--email "$ACME_EMAIL")
  if [[ -n "$ip4" ]] && dns_a A "$MAIL_HOST" | grep -qx "$ip4"; then
    # --reuse-key: der Schlüssel bleibt bei Verlängerungen gleich (TLSA-Eintrag für DANE)
    if certbot certonly --non-interactive --agree-tos "${acme_mail[@]}" --cert-name fv-mail \
         --webroot -w /var/lib/fv-mail/acme -d "$MAIL_HOST" \
         --key-type rsa --rsa-key-size 3072 --reuse-key --keep-until-expiring >/dev/null; then
      RENEWED_LINEAGE=/etc/letsencrypt/live/fv-mail /etc/letsencrypt/renewal-hooks/deploy/fv-mail
      log "Zertifikat: $(openssl x509 -in /etc/fv-mail/tls/fullchain.pem -noout -enddate | cut -d= -f2) (Verlängerung automatisch, certbot.timer)"
    else
      log "WARNUNG: Zertifikat konnte nicht geholt werden (Protokoll: /var/log/letsencrypt/letsencrypt.log)."
    fi
  else
    log "HINWEIS: $MAIL_HOST zeigt noch nicht auf $ip4 – kein Zertifikat. Nach dem DNS-Eintrag erneut mit -M ausführen."
  fi
  if [[ ! -s /etc/fv-mail/tls/fullchain.pem ]]; then
    openssl req -x509 -newkey rsa:3072 -nodes -days 30 -subj "/CN=$MAIL_HOST" -addext "subjectAltName=DNS:$MAIL_HOST" \
      -keyout /etc/fv-mail/tls/privkey.pem -out /etc/fv-mail/tls/fullchain.pem 2>/dev/null
    chown root:Debian-exim /etc/fv-mail/tls/*.pem; chmod 640 /etc/fv-mail/tls/privkey.pem; chmod 644 /etc/fv-mail/tls/fullchain.pem
    log "Vorläufig selbst signiertes Zertifikat (Mailprogramme warnen, bis das echte Zertifikat da ist)."
  fi

  step "Mailserver: Exim (SMTP)"
  ( umask 027
    { echo "# Werte für /etc/exim4/exim4.conf (angelegt von setup-server-fv-web.sh, nur root/Exim)"
      echo "FV_DOMAIN = $MAIL_DOMAIN"
      echo "FV_HOST = $MAIL_HOST"
      echo "FV_DKIM_SELEKTOR = $sel"
      echo "FV_SRS_GEHEIMNIS = $(getkv "$MENV" SRS_SECRET)"
      # weitere Domains: nur Empfang, gleiche Adressen wie FV_DOMAIN (Liste mit ":")
      echo "FV_ZUSATZ = ${ZUSATZ_DOMAINS// / : }"
      if [[ $nur_ipv4 -eq 1 ]]; then echo "FV_NUR_IPV4 = 1"; fi
    } > /etc/exim4/fv-makros.conf )
  chown root:Debian-exim /etc/exim4/fv-makros.conf; chmod 640 /etc/exim4/fv-makros.conf
  local pm; pm="$(getkv "$MENV" POSTMASTER)"
  printf '# Systemadressen an die Betreuung (wenn nicht als Adresse in der Webseite angelegt)\n' > /etc/fv-mail/aliases
  for a in postmaster abuse hostmaster webmaster root mailer-daemon nobody; do printf '%s: %s\n' "$a" "$pm"; done >> /etc/fv-mail/aliases
  chmod 644 /etc/fv-mail/aliases
  vorlage /etc/exim4/fv-filter 644 root:root <<'FILTER'
# Exim filter
# Systemfilter (angelegt von setup-server-fv-web.sh): Mails, die eine angemeldete Person
# mit einem Verteiler als Absender verschickt, landen auch im Archiv des Verteilers.
if $authenticated_id is not "" and
   "${lookup pgsql{SELECT 1 FROM mail_archive WHERE aktiv AND verteiler = '${quote_pgsql:${lc:${sg{$sender_address_local_part}{[+].*}{}}}@${if inlisti{$sender_address_domain}{@ZUSATZ@}{@DOMAIN@}{${lc:$sender_address_domain}}}}'}{ja}{nein}}" is "ja"
then
  unseen deliver "fv-archiv+${sg{${lc:${sg{$sender_address_local_part}{[+].*}{}}}}{[^a-z0-9-]}{-}}@@DOMAIN@"
endif
FILTER
  vorlage /etc/exim4/exim4.conf.neu 640 root:Debian-exim <<'EXIM'
# =============================================================================
#  Exim – Mailserver des Vereins (angelegt von setup-server-fv-web.sh)
#  Nicht von Hand ändern: Ein erneuter Lauf mit -M überschreibt diese Datei.
#  Werte (Domain, Rechnername, DKIM, SRS) stehen in /etc/exim4/fv-makros.conf.
#  Adressen, Verteiler, Aliase, Sperren kommen aus der Datenbank der Webseite
#  (Sichten exim_*; nur Leserecht, Anmeldung per Unix-Socket als Debian-exim).
# =============================================================================
.include /etc/exim4/fv-makros.conf

primary_hostname = FV_HOST
qualify_domain = FV_DOMAIN
# weitere Domains (-A): Adressen gelten dort genauso, landen im selben Postfach
domainlist fv_zusatz = FV_ZUSATZ
domainlist local_domains = FV_DOMAIN : FV_HOST : +fv_zusatz
hostlist relay_from_hosts = <; 127.0.0.1 ; ::1

.ifdef FV_NUR_IPV4
disable_ipv6 = true
.endif

daemon_smtp_ports = 25 : 465 : 587
tls_on_connect_ports = 465
tls_advertise_hosts = *
tls_certificate = /etc/fv-mail/tls/fullchain.pem
tls_privatekey = /etc/fv-mail/tls/privkey.pem
# Port 25 (andere Mailserver): alles ab NORMAL; Mailprogramme (465/587): TLS 1.2 und 1.3
tls_require_ciphers = ${if eq{$received_port}{25}{NORMAL}{NORMAL:-VERS-ALL:+VERS-TLS1.3:+VERS-TLS1.2}}
# Anmeldung nur verschlüsselt und nur auf den Ports für Mailprogramme
auth_advertise_hosts = ${if and{{def:tls_in_cipher}{!eq{$received_port}{25}}}{*}{}}

hide pgsql_servers = (/var/run/postgresql/.s.PGSQL.5432)/fvweb/Debian-exim/

acl_smtp_rcpt = acl_check_rcpt
acl_smtp_data = acl_check_data

spamd_address = 127.0.0.1 11333 variant=rspamd
system_filter = /etc/exim4/fv-filter
system_filter_user = Debian-exim

dns_dnssec_ok = 1
host_lookup = *
rfc1413_hosts =
never_users = root
deliver_drop_privilege = true
local_from_check = false
keep_environment =
add_environment = <; PATH=/usr/sbin:/usr/bin:/sbin:/bin

message_size_limit = 25M
recipients_max = 200
smtp_accept_max = 50
smtp_accept_max_per_host = 10
check_spool_space = 100M
ignore_bounce_errors_after = 2d
timeout_frozen_after = 7d
freeze_tell = postmaster
smtp_banner = $smtp_active_hostname ESMTP
log_file_path = /var/log/exim4/%slog
# Betreff wird nicht protokolliert (Datenschutz)
log_selector = +tls_cipher +smtp_protocol_error +smtp_syntax_error +incoming_port -host_lookup_failed

# Adresse ohne Plus-Zusatz, klein geschrieben, für SQL (ACLs sehen den vollen Teil vor @)
# Domain für Abfragen: weitere Domains zählen als FV_DOMAIN
FV_DOM = ${if match_domain{$domain}{+fv_zusatz}{FV_DOMAIN}{${lc:$domain}}}
FV_ADR = ${quote_pgsql:${lc:${sg{$local_part}{[+].*}{}}}@FV_DOM}
# in Routern ist der Zusatz (+…) schon abgetrennt
FV_RCPT = ${quote_pgsql:${lc:$local_part@$domain}}
# Absender ohne Plus-Zusatz; weitere Domains (-A) zählen als FV_DOMAIN, dürfen also auch senden
FV_ABSENDER = ${quote_pgsql:${lc:${sg{$sender_address_local_part}{[+].*}{}}}@${if match_domain{$sender_address_domain}{+fv_zusatz}{FV_DOMAIN}{${lc:$sender_address_domain}}}}
FV_FROM_DOM = ${lc:${domain:${address:$h_From:}}}
FV_AUTH = ${quote_pgsql:${lc:$authenticated_id}}

begin acl

acl_check_rcpt:
  # lokal eingelieferte Mails (Cron, Abwesenheitsnotizen, Quota-Hinweise)
  accept  hosts = :
          control = dkim_disable_verify

  deny    domains = +local_domains
          local_parts = ^[.] : ^.*[@%!/|]
          message = Ungültige Adresse

  # Archivpostfach nimmt nur intern weitergeleitete Mails an
  deny    domains = +local_domains
          local_parts = ^fv-archiv
          message = Unbekannte Adresse

  # die Webseite (Newsletter, Benachrichtigungen) auf diesem Server
  accept  hosts = +relay_from_hosts
          control = submission/sender_retain
          control = dkim_disable_verify

  # angemeldete Personen: nur eigene Adressen, Aliase und eigene Verteiler als Absender
  deny    authenticated = *
          condition = ${lookup pgsql{SELECT 1 FROM exim_absender WHERE benutzer = 'FV_AUTH' AND adresse = 'FV_ABSENDER'}{false}{true}}
          message = Absender <$sender_address> ist für $authenticated_id nicht erlaubt
  deny    authenticated = *
          ratelimit = 100 / 1h / per_rcpt / leaky / $authenticated_id
          message = Zu viele Empfänger in kurzer Zeit (höchstens $sender_rate_limit je Stunde)
  deny    authenticated = *
          domains = +local_domains
          !verify = recipient
  accept  authenticated = *
          control = submission/sender_retain
          control = dkim_disable_verify

  # Ports für Mailprogramme nur mit Anmeldung
  deny    condition = ${if or{{eq{$received_port}{465}}{eq{$received_port}{587}}}}
          message = Bitte zuerst anmelden

  # von außen: nur an Adressen des Vereins
  require message = Weiterleitung nicht erlaubt
          domains = +local_domains

  deny    dnslists = zen.spamhaus.org=127.0.0.2,127.0.0.3,127.0.0.4,127.0.0.9,127.0.0.10,127.0.0.11
          message = Abgelehnt: $sender_host_address steht in $dnslist_domain

  deny    condition = ${lookup pgsql{SELECT 1 FROM exim_plus_gesperrt WHERE adresse = '${quote_pgsql:${lc:$local_part}@FV_DOM}'}{true}{false}}
          message = Diese Adresse nimmt keine E-Mails mehr an

  deny    condition = ${lookup pgsql{SELECT 1 FROM exim_adressen WHERE adresse = 'FV_ADR' AND art = 'gesperrt'}{true}{false}}
          message = Diese Adresse ist nicht (mehr) vergeben

  # geschlossene Verteiler: nur Mitglieder dürfen schreiben
  deny    condition = ${lookup pgsql{SELECT 1 FROM exim_adressen WHERE adresse = 'FV_ADR' AND art = 'verteiler' AND NOT offen}{true}{false}}
          condition = ${lookup pgsql{SELECT 1 FROM exim_verteiler WHERE verteiler = 'FV_ADR' AND empfaenger = 'FV_ABSENDER'}{false}{true}}
          message = Dieser Verteiler nimmt nur E-Mails seiner Mitglieder an

  require verify = recipient

  # volles Postfach: gleich hier ablehnen statt später eine Fehlermeldung zu schicken
  warn    set acl_m_quota = ${readsocket{/run/dovecot/quota-status}{request=smtpd_access_policy\nrecipient=${lc:$local_part}@FV_DOM\nsize=$message_size\n\n}{5s}{}{action=DUNNO}}
  deny    condition = ${if match{$acl_m_quota}{^action=55}}
          message = Das Postfach ist voll

  accept

acl_check_data:
  accept  hosts = : +relay_from_hosts

  # angemeldet: auch die sichtbare Absenderzeile (From) muss erlaubt sein
  deny    authenticated = *
          condition = ${lookup pgsql{SELECT 1 FROM exim_absender WHERE benutzer = 'FV_AUTH' AND adresse = '${quote_pgsql:${lc:${sg{${local_part:${address:$h_From:}}}{[+].*}{}}}@${if match_domain{FV_FROM_DOM}{+fv_zusatz}{FV_DOMAIN}{FV_FROM_DOM}}}'}{false}{true}}
          message = Absender (From) ist für $authenticated_id nicht erlaubt
  accept  authenticated = *

  deny    !verify = header_syntax
          message = Fehlerhafte Kopfzeilen

  # Kopfzeilen von außen nicht übernehmen, die wir selbst setzen
  warn    remove_header = X-Spam : X-Spam-Score
  # Prüfung durch rspamd (Spam, Greylisting, unzulässige Anhänge)
  warn    spam = nobody:true/defer_ok
          add_header = X-Spam-Score: $spam_score
  defer   condition = ${if eq{$spam_action}{soft reject}}
          message = Bitte später erneut versuchen (Greylisting)
  deny    condition = ${if eq{$spam_action}{reject}}
          message = Nachricht abgelehnt (Spamverdacht oder unzulässiger Anhang). $spam_report
  warn    condition = ${if or{{eq{$spam_action}{add header}}{eq{$spam_action}{rewrite subject}}}}
          set acl_m_spam = 1
          add_header = X-Spam: Yes
  accept

begin routers

# Rückläufer an weitergeleitete Mails (SRS-Adressen) zurückübersetzen
inbound_srs:
  driver = redirect
  senders = :
  domains = +local_domains
  condition = ${if inbound_srs{$local_part}{FV_SRS_GEHEIMNIS}}
  data = $srs_recipient

inbound_srs_failure:
  driver = redirect
  senders = :
  domains = +local_domains
  condition = ${if inbound_srs{$local_part}{}}
  allow_fail
  data = :fail: Ungültige SRS-Adresse

# weitere Domains: auf dieselbe Adresse der Hauptdomain umschreiben (Zusatz +… bleibt)
fv_zusatzdomain:
  driver = redirect
  domains = +fv_zusatz
  local_part_suffix = +*
  local_part_suffix_optional
  data = ${quote_local_part:$local_part$local_part_suffix}@FV_DOMAIN

dnslookup:
  driver = dnslookup
  domains = ! +local_domains
  transport = remote_smtp
  ignore_target_hosts = 0.0.0.0 : 127.0.0.0/8 : ::1
  dnssec_request_domains = *
  no_more

fv_gesperrt:
  driver = redirect
  domains = FV_DOMAIN
  local_part_suffix = +*
  local_part_suffix_optional
  condition = ${lookup pgsql{SELECT 1 FROM exim_adressen WHERE adresse = 'FV_RCPT' AND art = 'gesperrt'}{true}{false}}
  allow_fail
  data = :fail: Diese Adresse ist nicht (mehr) vergeben

# Kopie für das Archiv eines Verteilers (nicht bei Spam)
fv_archiv_kopie:
  driver = redirect
  domains = FV_DOMAIN
  local_part_suffix = +*
  local_part_suffix_optional
  unseen
  no_verify
  condition = ${if and{{!eq{$acl_m_spam}{1}}{eq{${lookup pgsql{SELECT 1 FROM mail_archive WHERE aktiv AND verteiler = 'FV_RCPT'}}}{1}}}}
  data = fv-archiv+${sg{${lc:$local_part}}{[^a-z0-9-]}{-}}@FV_DOMAIN

fv_verteiler:
  driver = redirect
  domains = FV_DOMAIN
  local_part_suffix = +*
  local_part_suffix_optional
  condition = ${lookup pgsql{SELECT 1 FROM exim_adressen WHERE adresse = 'FV_RCPT' AND art = 'verteiler'}{true}{false}}
  data = ${lookup pgsql{SELECT empfaenger FROM exim_verteiler WHERE verteiler = 'FV_RCPT'}}
  headers_add = List-Id: <${sg{${lc:$local_part}}{[^a-z0-9-]}{-}}.FV_DOMAIN>
  forbid_file
  forbid_pipe
  forbid_filter_reply

fv_alias:
  driver = redirect
  domains = FV_DOMAIN
  local_part_suffix = +*
  local_part_suffix_optional
  data = ${lookup pgsql{SELECT ziel FROM exim_adressen WHERE adresse = 'FV_RCPT' AND art = 'alias'}}
  forbid_file
  forbid_pipe

fv_postfach:
  driver = accept
  domains = FV_DOMAIN
  local_part_suffix = +*
  local_part_suffix_optional
  condition = ${lookup pgsql{SELECT 1 FROM exim_adressen WHERE adresse = 'FV_RCPT' AND art = 'postfach'}{true}{false}}
  transport = dovecot_lmtp

fv_archiv:
  driver = accept
  domains = FV_DOMAIN
  local_parts = fv-archiv
  local_part_suffix = +*
  transport = dovecot_lmtp

# postmaster, abuse, root … an die Betreuung (nur wenn nicht in der Datenbank)
system_aliases:
  driver = redirect
  domains = +local_domains
  data = ${lookup{${lc:$local_part}}lsearch{/etc/fv-mail/aliases}}
  forbid_file
  forbid_pipe

begin transports

remote_smtp:
  driver = smtp
  helo_data = FV_HOST
  hosts_try_dane = *
  # weitergeleitete Mails fremder Absender (Verteiler): Rückweg über SRS
  return_path = ${if and{{!eq{$return_path}{}}{!match_domain{$sender_address_domain}{+local_domains}}}{${srs_encode{FV_SRS_GEHEIMNIS}{$return_path}{FV_DOMAIN}}}fail}
  # DKIM-Signatur für Mails mit Absender aus der eigenen Domain oder einer weiteren (-A);
  # alle nutzen denselben Schlüssel und Selektor
  dkim_domain = ${if match_domain{FV_FROM_DOM}{FV_DOMAIN : +fv_zusatz}{FV_FROM_DOM}{FV_DOMAIN}}
  dkim_selector = FV_DKIM_SELEKTOR
  dkim_private_key = ${if match_domain{FV_FROM_DOM}{FV_DOMAIN : +fv_zusatz}{/etc/fv-mail/dkim/FV_DKIM_SELEKTOR.key}{0}}
  dkim_canon = relaxed

dovecot_lmtp:
  driver = lmtp
  socket = /run/dovecot/lmtp
  rcpt_include_affixes
  batch_max = 200

begin retry

*   *   F,2h,15m; G,16h,1h,1.5; F,4d,6h

begin rewrite

begin authenticators

dovecot_plain:
  driver = dovecot
  public_name = PLAIN
  server_socket = /run/dovecot/auth-exim
  server_set_id = $auth1

dovecot_login:
  driver = dovecot
  public_name = LOGIN
  server_socket = /run/dovecot/auth-exim
  server_set_id = $auth1
EXIM
  if exim -C /etc/exim4/exim4.conf.neu -bV >/dev/null 2>&1; then
    mv /etc/exim4/exim4.conf.neu /etc/exim4/exim4.conf
  else
    exim -C /etc/exim4/exim4.conf.neu -bV 2>&1 | tail -5 | sed 's/^/    /'
    rm -f /etc/exim4/exim4.conf.neu
    log "FEHLER: Exim-Konfiguration ungültig – bisherige bleibt aktiv."; exit 1
  fi
  echo "$MAIL_HOST" > /etc/mailname
  systemctl enable exim4 >/dev/null; systemctl restart exim4
  log "Exim läuft (Ports 25, 465, 587): $(systemctl is-active exim4)"

  step "Mailserver: rspamd (Spam, Greylisting, Anhänge)"
  install -d -m 755 /etc/rspamd/local.d
  cat > /etc/rspamd/local.d/options.inc <<'RSPAMD'
# eigener Resolver (unbound, prüft DNSSEC) – öffentliche Resolver werden von DNS-Sperrlisten abgewiesen
dns {
  nameserver = ["127.0.0.1:53"];
}
RSPAMD
  cat > /etc/rspamd/local.d/redis.conf <<'RSPAMD'
servers = "127.0.0.1:6379";
RSPAMD
  cat > /etc/rspamd/local.d/actions.conf <<'RSPAMD'
# Punktgrenzen: ab 4 Greylisting, ab 6 als Spam markiert (Ordner Junk), ab 15 abgelehnt
reject = 15;
add_header = 6;
greylist = 4;
RSPAMD
  cat > /etc/rspamd/local.d/greylist.conf <<'RSPAMD'
# erneuter Zustellversuch frühestens nach 5 Minuten; bekannte Absender 30 Tage ohne Wartezeit
timeout = 5min;
expire = 30d;
RSPAMD
  cat > /etc/rspamd/local.d/classifier-bayes.conf <<'RSPAMD'
backend = "redis";
autolearn = true;
RSPAMD
  cat > /etc/rspamd/local.d/mime_types.conf <<'RSPAMD'
# Anhänge, die Schadsoftware enthalten können, werden nicht angenommen (siehe force_actions)
bad_extensions = {
  exe = 10; scr = 10; bat = 10; cmd = 10; com = 10; pif = 10; js = 10; jse = 10;
  vbs = 10; vbe = 10; wsf = 10; ps1 = 10; jar = 10; msi = 10; lnk = 10; hta = 10;
  cpl = 10; reg = 10; docm = 10; xlsm = 10; pptm = 10; iso = 10; img = 10; vhd = 10;
  vhdx = 10; appx = 10;
}
RSPAMD
  cat > /etc/rspamd/local.d/force_actions.conf <<'RSPAMD'
rules {
  FV_ANHANG {
    action = "reject";
    expression = "MIME_BAD_EXTENSION | MIME_DOUBLE_BAD_EXTENSION | MIME_ARCHIVE_IN_ARCHIVE";
    message = "Anhang dieses Typs wird nicht angenommen (bitte z. B. als PDF oder über einen Link senden)";
  }
}
RSPAMD
  cat > /etc/rspamd/local.d/dkim_signing.conf <<'RSPAMD'
# signiert Exim selbst
enabled = false;
RSPAMD
  cat > /etc/rspamd/local.d/arc.conf <<'RSPAMD'
enabled = false;
RSPAMD
  cat > /etc/rspamd/local.d/milter_headers.conf <<'RSPAMD'
# Kopfzeilen setzt Exim
use = [];
RSPAMD
  pw="$(rspamadm pw -q -p "$(getkv "$MENV" RSPAMD_PASSWORT)" 2>/dev/null || rspamadm pw -p "$(getkv "$MENV" RSPAMD_PASSWORT)")"
  ( umask 027; printf '# Weboberfläche nur über SSH-Tunnel: ssh -L 11334:127.0.0.1:11334 …\npassword = "%s";\n' "$pw" \
      > /etc/rspamd/local.d/worker-controller.inc )
  chgrp _rspamd /etc/rspamd/local.d/worker-controller.inc 2>/dev/null || true
  rspamadm configtest >/dev/null || { rspamadm configtest 2>&1 | tail -5 | sed 's/^/    /'; log "FEHLER: rspamd-Konfiguration ungültig."; exit 1; }
  systemctl enable redis-server rspamd >/dev/null; systemctl restart redis-server rspamd
  log "rspamd läuft: $(systemctl is-active rspamd) (Passwort der Weboberfläche: sudo grep RSPAMD $MENV)"

  step "Mailserver: Dovecot (IMAP, Sieve, Speichergrenze, Archive)"
  LISTEN="*"; [[ -n "$ip6" ]] && LISTEN="*, ::"
  install -d -m 755 /etc/dovecot/sieve
  vorlage /etc/dovecot/dovecot.conf.neu 644 root:root <<'DOVECOT'
# =============================================================================
#  Dovecot 2.4 – Postfächer des Vereins (angelegt von setup-server-fv-web.sh)
#  Nicht von Hand ändern: Ein erneuter Lauf mit -M überschreibt diese Datei.
#  Prüfen: doveconf -n
# =============================================================================
dovecot_config_version = 2.4.0
dovecot_storage_version = 2.4.0

protocols = imap lmtp sieve
listen = @LISTEN@
log_path = syslog
auth_verbose = yes
hostname = @HOST@
postmaster_address = postmaster@@DOMAIN@

# ------------------------------------------------------------------- TLS
ssl = required
ssl_server_cert_file = /etc/fv-mail/tls/fullchain.pem
ssl_server_key_file = /etc/fv-mail/tls/privkey.pem
ssl_min_protocol = TLSv1.2

# ------------------------------------------------------------- Anmeldung
# Benutzer und Passwörter aus der Datenbank der Webseite (Sicht dovecot_benutzer;
# Anmeldung bei PostgreSQL per Unix-Socket als Systembenutzer dovecot, nur Leserecht)
auth_mechanisms = plain login
auth_allow_cleartext = no
auth_username_format = %{user | lower}

sql_driver = pgsql
pgsql /var/run/postgresql {
  parameters {
    dbname = fvweb
    user = dovecot
  }
}

passdb sql {
  query = SELECT benutzer AS "user", passwort AS password FROM dovecot_benutzer \
    WHERE benutzer = '%{user}' AND aktiv AND passwort IS NOT NULL
}

# Archivpostfach der Verteiler (nur für die Zustellung, keine Anmeldung)
userdb archiv {
  driver = passwd-file
  passwd_file_path = /etc/dovecot/fv-archiv.passwd
}

userdb sql {
  query = SELECT benutzer AS "user", home FROM dovecot_benutzer WHERE benutzer = '%{user}'
  iterate_query = SELECT benutzer AS "user" FROM dovecot_benutzer WHERE aktiv
}

# ------------------------------------------------------------- Postfächer
mail_uid = vmail
mail_gid = vmail
first_valid_uid = @VMAIL_UID@
last_valid_uid = @VMAIL_UID@
mail_driver = maildir
mail_path = ~/Maildir
recipient_delimiter = +
lmtp_save_to_detail_mailbox = no

mail_plugins {
  quota = yes
  acl = yes
}

namespace inbox {
  separator = /
  inbox = yes
  mailbox Drafts {
    special_use = \Drafts
    auto = subscribe
  }
  mailbox Sent {
    special_use = \Sent
    auto = subscribe
  }
  mailbox Archive {
    special_use = \Archive
    auto = subscribe
  }
  mailbox Junk {
    special_use = \Junk
    auto = subscribe
    autoexpunge = 90d
  }
  mailbox Trash {
    special_use = \Trash
    auto = subscribe
    autoexpunge = 90d
  }
}

# Archive der Verteiler: für die jeweiligen Empfänger nur lesbar (Rechte in dovecot-acl,
# schreibt fv-mail-sync); Nachrichten liegen bereits als gelesen darin
namespace archiv {
  type = public
  separator = /
  prefix = Archiv/
  mail_driver = maildir
  mail_path = /var/vmail/archiv/Maildir
  subscriptions = no
  list = children
}

acl_driver = vfile

# --------------------------------------------------------- Speichergrenze
quota "Postfach" {
  driver = count
  storage_size = @QUOTA@G
  warning warn-95 {
    quota_storage_percentage = 95
    execute quota-warning {
      args = 95 %{user}
    }
  }
  warning warn-90 {
    quota_storage_percentage = 90
    execute quota-warning {
      args = 90 %{user}
    }
  }
}
quota_status_success = DUNNO
quota_status_nouser = DUNNO
quota_status_overquota = "552 5.2.2 Das Postfach ist voll"

# ------------------------------------------------------------------ Sieve
sieve_max_redirects = 0
sieve_plugins = sieve_imapsieve sieve_extprograms
sieve_pipe_bin_dir = /usr/local/lib/fv-mail/sieve-pipe
sieve_global_extensions {
  vnd.dovecot.pipe = yes
}

# zuerst: als Spam markierte Mails in den Ordner Junk
sieve_script fv-spam {
  type = before
  path = /etc/dovecot/sieve/fv-spam.sieve
}
# Abwesenheitsnotiz aus der Webseite (schreibt fv-mail-sync)
sieve_script fv-abwesenheit {
  type = before
  path = ~/fv/abwesenheit.sieve
}
# eigene Regeln der Person (ManageSieve, Port 4190)
sieve_script personal {
  driver = file
  path = ~/sieve
  active_path = ~/.dovecot.sieve
}

# Spam lernen: in Junk verschoben = Spam, aus Junk heraus = kein Spam
mailbox Junk {
  sieve_script spam-lernen {
    type = before
    cause = copy
    path = /etc/dovecot/sieve/spam-lernen.sieve
  }
}
imapsieve_from Junk {
  sieve_script ham-lernen {
    type = before
    cause = copy
    path = /etc/dovecot/sieve/ham-lernen.sieve
  }
}

# --------------------------------------------------------------- Dienste
protocol imap {
  mail_plugins {
    imap_quota = yes
    imap_acl = yes
    imap_sieve = yes
  }
  mail_max_userip_connections = 30
}

protocol lmtp {
  mail_plugins {
    sieve = yes
  }
}

service imap-login {
  inet_listener imap {
    port = 0
  }
  inet_listener imaps {
    port = 993
    ssl = yes
  }
}

service managesieve-login {
  inet_listener sieve {
    port = 4190
  }
}

service lmtp {
  unix_listener lmtp {
    mode = 0600
    user = Debian-exim
  }
}

service auth {
  unix_listener auth-exim {
    mode = 0600
    user = Debian-exim
  }
}

service auth-worker {
  user = dovecot
}

service quota-status {
  executable = quota-status -p postfix
  unix_listener quota-status {
    mode = 0600
    user = Debian-exim
  }
  client_limit = 1
}

service quota-warning {
  executable = script /usr/local/lib/fv-mail/quota-warnung
  user = dovecot
  unix_listener quota-warning {
    mode = 0600
    user = vmail
  }
}
DOVECOT
  if doveconf -c /etc/dovecot/dovecot.conf.neu -n >/dev/null 2>&1; then
    [[ -e /etc/dovecot/dovecot.conf.debian ]] || cp /etc/dovecot/dovecot.conf /etc/dovecot/dovecot.conf.debian
    mv /etc/dovecot/dovecot.conf.neu /etc/dovecot/dovecot.conf
  else
    doveconf -c /etc/dovecot/dovecot.conf.neu -n 2>&1 | grep -i -m5 'error\|fatal' | sed 's/^/    /' || true
    log "FEHLER: Dovecot-Konfiguration ungültig – bisherige bleibt aktiv (neue: /etc/dovecot/dovecot.conf.neu)."; exit 1
  fi
  printf 'fv-archiv@%s::%s:%s::/var/vmail/archiv::\n' "$MAIL_DOMAIN" "$VMAIL_UID" "$(id -g vmail)" > /etc/dovecot/fv-archiv.passwd
  chmod 644 /etc/dovecot/fv-archiv.passwd
  cat > /etc/dovecot/sieve/fv-spam.sieve <<'SIEVE'
# Als Spam markierte Mails (rspamd, Kopfzeile X-Spam) in den Ordner Junk
require ["fileinto", "mailbox"];
if header :is "X-Spam" "Yes" {
  fileinto :create "Junk";
  stop;
}
SIEVE
  cat > /etc/dovecot/sieve/spam-lernen.sieve <<'SIEVE'
# in Junk verschoben: rspamd lernt „Spam“
require ["vnd.dovecot.pipe", "copy", "imapsieve"];
pipe :copy "rspamd-lernen" ["spam"];
SIEVE
  cat > /etc/dovecot/sieve/ham-lernen.sieve <<'SIEVE'
# aus Junk heraus verschoben (nicht in den Papierkorb): rspamd lernt „kein Spam“
require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];
if environment :matches "imap.mailbox" "*" { set "ziel" "${1}"; }
if string :is "${ziel}" "Trash" { stop; }
pipe :copy "rspamd-lernen" ["ham"];
SIEVE
  cat > /usr/local/lib/fv-mail/sieve-pipe/rspamd-lernen <<'PIPE'
#!/bin/sh
# von Dovecot (IMAPSieve) aufgerufen: $1 = spam | ham, Nachricht auf stdin
case "$1" in spam|ham) exec /usr/bin/rspamc -h 127.0.0.1:11334 "learn_$1" >/dev/null ;; esac
PIPE
  vorlage /usr/local/lib/fv-mail/quota-warnung 755 root:root <<'QUOTA'
#!/bin/sh
# Hinweis an die Person, wenn ihr Postfach fast voll ist (von Dovecot aufgerufen: <prozent> <adresse>)
PROZENT="$1"; BENUTZER="$2"
case "$BENUTZER" in *[!a-z0-9@._+-]*|"") exit 0 ;; esac
/usr/sbin/sendmail -f '<>' -- "$BENUTZER" <<EOF
From: Postmaster <postmaster@@DOMAIN@>
To: <$BENUTZER>
Subject: Ihr Postfach ist zu $PROZENT % gefüllt
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: 8bit
Auto-Submitted: auto-generated

Hallo,

Ihr Postfach $BENUTZER ist zu $PROZENT % gefüllt. Ist es voll, werden neue
E-Mails abgewiesen.

Bitte löschen Sie nicht mehr benötigte E-Mails (vor allem mit großen Anhängen)
und leeren Sie den Papierkorb. Die aktuelle Belegung steht auf der Webseite unter
„Konto“.

Diese Nachricht wurde automatisch erzeugt.
EOF
QUOTA
  chmod 755 /usr/local/lib/fv-mail/sieve-pipe/rspamd-lernen
  sievec /etc/dovecot/sieve/fv-spam.sieve
  sievec /etc/dovecot/sieve/spam-lernen.sieve
  sievec /etc/dovecot/sieve/ham-lernen.sieve
  # Archivpostfach: legt jede Kopie als gelesen im Ordner des Verteilers ab
  install -d -o vmail -g vmail -m 750 /var/vmail/archiv/sieve
  cat > /var/vmail/archiv/sieve/archiv.sieve <<'SIEVE'
# Kopie für das Archiv eines Verteilers: Ordner = Zusatz der Adresse (fv-archiv+<ordner>@…)
require ["fileinto", "mailbox", "envelope", "subaddress", "variables", "imap4flags"];
set "ordner" "unbekannt";
if envelope :detail :matches "to" "?*" { set "ordner" "${1}${2}"; }
fileinto :create :flags "\\Seen" "${ordner}";
SIEVE
  chown vmail:vmail /var/vmail/archiv/sieve/archiv.sieve
  ln -sfn sieve/archiv.sieve /var/vmail/archiv/.dovecot.sieve; chown -h vmail:vmail /var/vmail/archiv/.dovecot.sieve
  systemctl enable dovecot >/dev/null; systemctl restart dovecot
  log "Dovecot läuft (IMAPS 993, ManageSieve 4190): $(systemctl is-active dovecot)"
  if doveadm user "fv-archiv@$MAIL_DOMAIN" >/dev/null 2>&1 && doveadm user -m '*' >/dev/null 2>&1; then
    log "Datenbankzugriff von Dovecot: in Ordnung ($(doveadm user '*' 2>/dev/null | grep -c . || true) Postfächer)."
  else
    log "WARNUNG: Dovecot findet die Postfächer nicht – Protokoll: journalctl -u dovecot"
  fi

  step "Mailserver: Firewall, fail2ban, Protokolle"
  ufw allow 25/tcp comment 'SMTP (Mailserver)' >/dev/null
  ufw allow 465/tcp comment 'SMTPS (Mailprogramme)' >/dev/null
  ufw allow 587/tcp comment 'Submission (Mailprogramme)' >/dev/null
  ufw allow 993/tcp comment 'IMAPS' >/dev/null
  ufw allow 4190/tcp comment 'ManageSieve' >/dev/null
  cat > /etc/fail2ban/jail.d/fv-mail.local <<'EOF'
# angelegt von setup-server-fv-web.sh: falsche Passwörter beim Mailserver
[exim]
enabled  = true
port     = smtp,465,submission
backend  = auto
logpath  = /var/log/exim4/mainlog
maxretry = 10
findtime = 10m
bantime  = 10m
bantime.increment = true

[dovecot]
enabled  = true
port     = imaps,4190
backend  = systemd
maxretry = 10
findtime = 10m
bantime  = 10m
bantime.increment = true
EOF
  systemctl restart fail2ban
  # Protokolle 14 Tage
  sed -i 's/^\(\s*rotate\s\+\)[0-9]\+/\114/' /etc/logrotate.d/exim4-base /etc/logrotate.d/exim4-paniclog 2>/dev/null || true
  install -d -m 755 /etc/systemd/journald.conf.d
  printf '[Journal]\nMaxRetentionSec=14day\n' > /etc/systemd/journald.conf.d/fv-mail.conf
  systemctl restart systemd-journald
  log "Ports 25, 465, 587, 993, 4190 offen; fail2ban für Exim und Dovecot; Protokolle 14 Tage."

  step "Mailserver: Abgleich mit der Webseite (fv-mail)"
  cat > /usr/local/sbin/fv-mail <<'FVMAIL'
#!/usr/bin/env bash
# =============================================================================
#  fv-mail – Mailserver mit der Webseite abgleichen (angelegt von setup-server-fv-web.sh)
#
#  sudo fv-mail sync         Abwesenheitsnotizen, Archiv-Rechte, Belegung, Plus-Adressen
#                            (alle 5 Minuten über fv-mail-sync.timer)
#  sudo fv-mail taeglich     Erinnerungen und Löschungen gesperrter Postfächer,
#                            Aufbewahrungsfrist der Archive (täglich, fv-mail-taeglich.timer)
#  sudo fv-mail import <maildir> <adresse>
#                            vorhandene Mails (Maildir) in ein Postfach übernehmen
#  sudo fv-mail status       Dienste, Warteschlange, Zertifikat, Postfächer
#  sudo fv-mail dns          DNS-Einträge anzeigen und prüfen
# =============================================================================
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
MENV=/etc/fv-mail/mail.env
[[ -f "$MENV" ]] || { echo "$MENV fehlt – Mailserver mit setup-server-fv-web.sh … -M einrichten." >&2; exit 1; }
getkv() { grep -m1 "^$1=" "$MENV" | cut -d= -f2- | sed 's/^"//; s/"$//'; }
DOMAIN="$(getkv MAIL_DOMAIN)"; HOST="$(getkv MAIL_HOST)"; SELEKTOR="$(getkv DKIM_SELECTOR)"
ZUSATZ="$(getkv ZUSATZ_DOMAINS || true)"
ARCHIV=/var/vmail/archiv/Maildir
ARCHIV_BENUTZER="fv-archiv@$DOMAIN"
STAND=/var/lib/fv-mail
log() { printf '%s [fv-mail] %s\n' "$(date '+%F %T')" "$*"; }
sql() { runuser -u postgres -- psql -d fvweb -XAtq -F $'\t' -c "$1"; }
manage() { /usr/local/sbin/fv-manage "$@"; }
# Ordnername im Archiv: Teil vor @, klein, nur a-z 0-9 - (wie im Exim-Router fv_archiv_kopie)
ordner() { local lp="${1%@*}"; lp="${lp,,}"; printf '%s' "$lp" | tr -c 'a-z0-9-' '-'; }

abwesenheit() {
  local quelle="$STAND/sieve" f nr ziel
  install -d -o fvweb -g fvweb -m 700 "$quelle"
  manage mail_sieve --ziel "$quelle" >/dev/null
  for f in "$quelle"/*.sieve; do
    [[ -e "$f" ]] || continue
    nr="$(basename "$f" .sieve)"; [[ "$nr" =~ ^[0-9]+$ ]] || continue
    ziel="/var/vmail/konten/$nr/fv/abwesenheit.sieve"
    cmp -s "$f" "$ziel" 2>/dev/null && continue
    install -d -o vmail -g vmail -m 700 "/var/vmail/konten/$nr" "/var/vmail/konten/$nr/fv"
    install -o vmail -g vmail -m 600 "$f" "$ziel"
    rm -f "${ziel%.sieve}.svbin"
  done
  for ziel in /var/vmail/konten/*/fv/abwesenheit.sieve; do
    [[ -e "$ziel" ]] || continue
    nr="$(basename "$(dirname "$(dirname "$ziel")")")"
    [[ -e "$quelle/$nr.sieve" ]] || rm -f "$ziel" "${ziel%.sieve}.svbin"
  done
}

archiv_rechte() {
  local verteiler leser name datei neu
  install -d -o vmail -g vmail -m 750 /var/vmail/archiv "$ARCHIV"
  # Wurzel: nur das Archivpostfach selbst
  neu="user=$ARCHIV_BENUTZER lrwstipekxa"
  [[ "$(cat "$ARCHIV/dovecot-acl" 2>/dev/null)" == "$neu" ]] \
    || { printf '%s\n' "$neu" > "$ARCHIV/dovecot-acl"; chown vmail:vmail "$ARCHIV/dovecot-acl"; }
  declare -A rechte=()
  while IFS=$'\t' read -r verteiler _; do
    [[ -n "$verteiler" ]] && rechte["$(ordner "$verteiler")"]=""
  done < <(sql "SELECT verteiler, aktiv FROM mail_archive")
  while IFS=$'\t' read -r verteiler leser; do
    [[ -n "$verteiler" && "$leser" =~ ^[a-z0-9._+-]+@[a-z0-9.-]+$ ]] || continue
    name="$(ordner "$verteiler")"
    rechte["$name"]+="user=$leser lr"$'\n'
  done < <(sql "SELECT verteiler, benutzer FROM dovecot_archiv_leser ORDER BY 1, 2")
  # auch Ordner abgeschalteter Archive: nur noch für das Archivpostfach
  for datei in "$ARCHIV"/.*/; do
    name="$(basename "$datei")"; name="${name#.}"
    [[ "$name" == "" || "$name" == "." || "$name" == ".." ]] && continue
    [[ -v "rechte[$name]" ]] || rechte["$name"]=""
  done
  for name in "${!rechte[@]}"; do
    [[ -d "$ARCHIV/.$name" ]] || doveadm mailbox create -u "$ARCHIV_BENUTZER" "$name" 2>/dev/null || true
    [[ -d "$ARCHIV/.$name" ]] || continue
    neu="user=$ARCHIV_BENUTZER lrwstipekxa"$'\n'"${rechte[$name]}"
    if [[ "$(cat "$ARCHIV/.$name/dovecot-acl" 2>/dev/null)"$'\n' != "$neu" ]]; then
      printf '%s' "$neu" > "$ARCHIV/.$name/dovecot-acl"
      chown vmail:vmail "$ARCHIV/.$name/dovecot-acl"; chmod 600 "$ARCHIV/.$name/dovecot-acl"
      log "Archiv $name: $(grep -c ' lr$' "$ARCHIV/.$name/dovecot-acl" || true) Leser"
    fi
  done
}

belegung() {
  doveadm -f flow quota get -A 2>/dev/null | manage mail_belegung >/dev/null
}

# zugestellte Plus-Adressen aus dem Exim-Protokoll (nur neue Zeilen seit dem letzten Lauf)
plusadressen() {
  local log=/var/log/exim4/mainlog pos="$STAND/mainlog.pos" ino alt_ino=0 alt_off=0 groesse
  [[ -f "$log" ]] || return 0
  [[ -f "$pos" ]] && read -r alt_ino alt_off < "$pos"
  ino="$(stat -c %i "$log")"; groesse="$(stat -c %s "$log")"
  {
    if [[ "$ino" != "$alt_ino" ]]; then
      # rotiert: Rest der alten Datei, dann die neue von vorn
      [[ -f "$log.1" && "$(stat -c %i "$log.1")" == "$alt_ino" ]] && tail -c +"$((alt_off + 1))" "$log.1"
      head -c "$groesse" "$log"
    elif (( groesse > alt_off )); then
      tail -c +"$((alt_off + 1))" "$log" | head -c "$((groesse - alt_off))"
    fi
  } | awk -v d="$DOMAIN" -v z="$ZUSATZ" '
      BEGIN { n = split(z, liste, " "); for (i = 1; i <= n; i++) weitere[liste[i]] = 1 }
      $4 == "=>" || $4 == "->" {
        a = $5; if ($6 ~ /^</) { a = $6; gsub(/[<>]/, "", a) }
        a = tolower(a); at = index(a, "@"); if (!at) next
        lp = substr(a, 1, at - 1); dom = substr(a, at + 1)
        if (dom in weitere) dom = d                 # weitere Domains zählen als Hauptdomain
        if (dom == d && lp ~ /\+/ && lp !~ /^fv-archiv\+/) print lp "@" dom
      }' | manage mail_plusadressen >/dev/null
  printf '%s %s\n' "$ino" "$groesse" > "$pos"
}

abgleich() {
  exec 9>/run/fv-mail-sync.lock; flock -n 9 || exit 0
  [[ -e /srv/fv-web/current/manage.py ]] || { log "Anwendung nicht installiert."; exit 0; }
  abwesenheit; archiv_rechte; belegung; plusadressen
}

taeglich() {
  exec 9>/run/fv-mail-sync.lock; flock 9
  local nr faellig=() verteiler frist
  manage mail_aufraeumen | sed 's/^/  /'
  while read -r nr; do
    [[ "$nr" =~ ^[0-9]+$ ]] || continue
    doveadm kick "$(sql "SELECT benutzer FROM dovecot_benutzer WHERE nummer = $nr")" >/dev/null 2>&1 || true
    rm -rf --one-file-system "/var/vmail/konten/$nr"
    faellig+=("$nr"); log "Postfach $nr gelöscht (Löschfrist abgelaufen)."
  done < <(manage mail_aufraeumen --faellig)
  (( ${#faellig[@]} == 0 )) || manage mail_aufraeumen --geloescht "${faellig[@]}" | sed 's/^/  /'
  # Archive mit Aufbewahrungsfrist
  while IFS=$'\t' read -r verteiler frist; do
    [[ "$frist" =~ ^[1-9][0-9]*$ ]] || continue
    doveadm expunge -u "$ARCHIV_BENUTZER" mailbox "$(ordner "$verteiler")" savedbefore "${frist}d" 2>/dev/null || true
  done < <(sql "SELECT verteiler, coalesce(frist_tage, 0) FROM mail_archive")
}

uebernehmen() {
  local quelle="${1:?Maildir-Verzeichnis fehlt}" adresse="${2:?Adresse fehlt}" nr ziel
  adresse="${adresse,,}"
  [[ "$adresse" =~ ^[a-z0-9._+-]+@[a-z0-9.-]+$ ]] || { echo "Ungültige Adresse: $adresse" >&2; exit 2; }
  [[ -d "$quelle/cur" || -d "$quelle/new" ]] || { echo "$quelle ist kein Maildir (cur/, new/ fehlen)." >&2; exit 2; }
  nr="$(sql "SELECT nummer FROM dovecot_benutzer WHERE benutzer = '$adresse'")"
  [[ "$nr" =~ ^[0-9]+$ ]] || { echo "Kein Postfach mit der Adresse $adresse." >&2; exit 1; }
  ziel="/var/vmail/konten/$nr/Maildir"
  install -d -o vmail -g vmail -m 700 "/var/vmail/konten/$nr" "$ziel"
  log "Übernehme $quelle nach $adresse ($ziel) – vorhandene Mails bleiben erhalten."
  rsync -a --ignore-existing --exclude 'dovecot*' --exclude 'subscriptions' --exclude 'courier*' "$quelle/" "$ziel/"
  chown -R vmail:vmail "/var/vmail/konten/$nr"
  doveadm force-resync -u "$adresse" '*'
  doveadm quota recalc -u "$adresse" || true
  doveadm mailbox list -u "$adresse" | sed 's/^/  /'
  doveadm -f flow quota get -u "$adresse" | sed 's/^/  /'
}

status() {
  local d
  for d in exim4 dovecot rspamd redis-server unbound; do printf '%-13s %s\n' "$d" "$(systemctl is-active "$d" || true)"; done
  echo "Warteschlange: $(exim -bpc) Nachricht(en)"
  openssl x509 -in /etc/fv-mail/tls/fullchain.pem -noout -subject -issuer -enddate | sed 's/^/Zertifikat:   /'
  echo "Postfächer:   $(sql "SELECT count(*) FROM dovecot_benutzer WHERE aktiv") aktiv, $(sql "SELECT count(*) FROM dovecot_benutzer WHERE NOT aktiv") gesperrt"
  echo "Belegung:     $(du -sh /var/vmail 2>/dev/null | cut -f1) in /var/vmail"
}

dns() {
  local ip4 ip6 dkim tlsa
  ip4="$(getkv MAIL_IPV4)"; ip6="$(getkv MAIL_IPV6)"
  dkim="$(openssl pkey -in "/etc/fv-mail/dkim/$SELEKTOR.key" -pubout -outform DER 2>/dev/null | base64 -w0)"
  tlsa="$(openssl x509 -in /etc/fv-mail/tls/fullchain.pem -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1)"
  cat <<EOF
Beim DNS-Anbieter einzutragen (Zone $DOMAIN, TTL z. B. 3600):

$HOST.                      A      $ip4
$( [[ -n "$ip6" ]] && echo "$HOST.                      AAAA   $ip6" )
$DOMAIN.                    MX     10 $HOST.
$DOMAIN.                    TXT    "v=spf1 mx -all"
$HOST.                      TXT    "v=spf1 a -all"
$SELEKTOR._domainkey.$DOMAIN.  TXT  $(printf '%s' "v=DKIM1; k=rsa; p=$dkim" | fold -w 250 | sed 's/.*/"&"/' | paste -sd ' ')
_dmarc.$DOMAIN.             TXT    "v=DMARC1; p=none; rua=mailto:postmaster@$DOMAIN"
_mta-sts.$DOMAIN.           TXT    "v=STSv1; id=$(getkv MTA_STS_ID)"
mta-sts.$DOMAIN.            A      $ip4      (Richtlinie liefert Caddy aus)
_smtp._tls.$DOMAIN.         TXT    "v=TLSRPTv1; rua=mailto:postmaster@$DOMAIN"
_submissions._tcp.$DOMAIN.  SRV    0 1 465 $HOST.
_imaps._tcp.$DOMAIN.        SRV    0 1 993 $HOST.
_submission._tcp.$DOMAIN.   SRV    0 0 0 .
_imap._tcp.$DOMAIN.         SRV    0 0 0 .
_pop3._tcp.$DOMAIN.         SRV    0 0 0 .
_pop3s._tcp.$DOMAIN.        SRV    0 0 0 .

Nur mit DNSSEC (sonst wirkungslos):
_25._tcp.$HOST.             TLSA   3 1 1 $tlsa

$(for z in $ZUSATZ; do cat <<ZONE
Weitere Domain $z (Webseite leitet um; Mail empfangen und senden; Zone $z):
$z.          A      $ip4
$z.          MX     10 $HOST.
$z.          TXT    "v=spf1 mx -all"
$SELEKTOR._domainkey.$z.  TXT  (derselbe Wert wie bei $DOMAIN)
_dmarc.$z.   TXT    "v=DMARC1; p=none; rua=mailto:postmaster@$z"

ZONE
done)
Beim Server-Anbieter (Reverse-DNS, PTR):
$ip4  ->  $HOST
$( [[ -n "$ip6" ]] && echo "$ip6  ->  $HOST" )
EOF
  echo
  echo "Prüfung (Resolver 1.1.1.1):"
  pruefe() { local soll="$3" ist; ist="$(dig +short +time=3 +tries=2 @1.1.1.1 "$2" "$1" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"
    if [[ "$ist" == *"$soll"* && -n "$ist" ]]; then echo "  OK      $1 $2"; else echo "  FEHLT   $1 $2 (gefunden: ${ist:-nichts})"; fi; }
  pruefe "$HOST" A "$ip4"
  pruefe "$DOMAIN" MX "$HOST"
  pruefe "$DOMAIN" TXT "v=spf1"
  pruefe "$SELEKTOR._domainkey.$DOMAIN" TXT "${dkim:0:40}"
  pruefe "_dmarc.$DOMAIN" TXT "v=DMARC1"
  pruefe "_mta-sts.$DOMAIN" TXT "v=STSv1"
  pruefe "_smtp._tls.$DOMAIN" TXT "v=TLSRPTv1"
  pruefe "$(awk -F. '{print $4"."$3"."$2"."$1".in-addr.arpa"}' <<<"$ip4")" PTR "$HOST"
  local z
  for z in $ZUSATZ; do
    pruefe "$z" MX "$HOST"
    pruefe "$z" TXT "v=spf1"
    pruefe "$SELEKTOR._domainkey.$z" TXT "${dkim:0:40}"
    pruefe "_dmarc.$z" TXT "v=DMARC1"
  done
}

case "${1:-}" in
  sync) abgleich ;;
  taeglich) taeglich ;;
  import) shift; uebernehmen "$@" ;;
  status) status ;;
  dns) dns ;;
  *) sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
FVMAIL
  chmod 750 /usr/local/sbin/fv-mail
  cat > /etc/systemd/system/fv-mail-sync.service <<'EOF'
[Unit]
Description=Mailserver: Abgleich mit der Webseite (Abwesenheit, Archive, Belegung, Plus-Adressen)
After=postgresql.service dovecot.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/fv-mail sync
Nice=10
EOF
  cat > /etc/systemd/system/fv-mail-sync.timer <<'EOF'
[Unit]
Description=Mailserver: Abgleich alle 5 Minuten

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
  cat > /etc/systemd/system/fv-mail-taeglich.service <<'EOF'
[Unit]
Description=Mailserver: Löschfristen der Postfächer und Archive
After=postgresql.service dovecot.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/fv-mail taeglich
Nice=10
EOF
  cat > /etc/systemd/system/fv-mail-taeglich.timer <<'EOF'
[Unit]
Description=Mailserver: tägliche Aufgaben

[Timer]
OnCalendar=*-*-* 04:15
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now fv-mail-sync.timer fv-mail-taeglich.timer >/dev/null
  if /usr/local/sbin/fv-mail sync; then log "Erster Abgleich erfolgreich."
  else log "WARNUNG: Erster Abgleich fehlgeschlagen (sudo fv-mail sync)."; fi

  step "Mailserver: Webseite verschickt über den eigenen Mailserver"
  set_kv "$ENVF" FV_MAIL "smtp"
  set_kv "$ENVF" FV_SMTP_HOST "127.0.0.1"
  set_kv "$ENVF" FV_SMTP_PORT "25"
  set_kv "$ENVF" FV_SMTP_USER ""
  set_kv "$ENVF" FV_SMTP_PASSWORD ""
  set_kv "$ENVF" FV_SMTP_TLS "aus"
  set_kv "$ENVF" FV_MAIL_DOMAIN "$MAIL_DOMAIN"
  set_kv "$ENVF" FV_MAIL_SERVER "$MAIL_HOST"
  systemctl restart fv-web
  log "FV_MAIL=smtp über 127.0.0.1:25; Vereinsadressen @$MAIL_DOMAIN, Server $MAIL_HOST."

  grep -q /var/vmail /usr/local/sbin/fv-web-backup \
    || log "HINWEIS: Die Datensicherung kennt die Postfächer noch nicht – einmal ohne -U ausführen."

  step "Mailserver: DNS-Einträge"
  /usr/local/sbin/fv-mail dns || true
}

# ------------------------------------------------------------ Phase summary
phase_summary() {
  step "Zusammenfassung"
  . /etc/os-release
  log "System:       $PRETTY_NAME, Kernel $(uname -r), Hostname $(hostnamectl --static)"
  log "Admin:        $ADMIN_USER | Firewall: $(ufw status | head -n1) | fail2ban: $(systemctl is-active fail2ban)"
  /usr/local/sbin/fv-web-status >/dev/null 2>&1 || true
  log "Zustand:      $(curl -s --max-time 10 -H "Host: $DOMAIN" -H 'X-Forwarded-Proto: https' http://localhost/health 2>/dev/null || echo 'nicht erreichbar') (https://$DOMAIN/health)"
  log "Dienste:      fv-web $(systemctl is-active fv-web 2>/dev/null || true) | newsletter $(systemctl is-active fv-web-newsletter 2>/dev/null || true) | caddy $(systemctl is-active caddy) | postgresql $(systemctl is-active postgresql)"
  if app_installed; then
    log "Anwendung:    $(grep '^Stand' "$BASE/current/.release" | cut -d: -f2- | xargs)"
    log "              Verwaltung: https://$DOMAIN/$(getkv "$ENVF" FV_ADMIN_PFAD)"
  else
    log "Anwendung:    noch nicht installiert (Platzhalterseite)"
  fi
  log "Updates:      sudo fv-web-update            (holt $(getkv "$DENV" DEFAULT_REF) aus $(getkv "$DENV" REPO_URL))"
  log "              sudo fv-web-update --zurueck  (vorige Version)"
  if [[ -f /etc/fv-mail/mail.env ]]; then
    log "Mailserver:   exim4 $(systemctl is-active exim4 || true) | dovecot $(systemctl is-active dovecot || true) | rspamd $(systemctl is-active rspamd || true) | unbound $(systemctl is-active unbound || true)"
    log "              $(getkv /etc/fv-mail/mail.env MAIL_HOST), Warteschlange $(exim -bpc 2>/dev/null || echo ?) | sudo fv-mail status | sudo fv-mail dns"
  else
    log "E-Mail:       FV_MAIL=$(getkv "$ENVF" FV_MAIL) – eigener Mailserver mit -M, oder in $ENVF eintragen"
    log "              (FV_MAIL=smtp, FV_SMTP_*), danach: sudo systemctl restart fv-web"
  fi
  log "Backup:       täglich ~03:30 nach $(getkv "$BENV" RESTIC_REPOSITORY)"
  log "              Wiederherstellungstest: sudo fv-web-restore -t"
  if [[ "$(getkv "$BENV" RESTIC_REPOSITORY)" == /* ]]; then
    log "              HINWEIS: Ziel liegt auf diesem Server – später extern sichern (-B)."
  fi
  log "Öffentlicher Schlüssel für ein SFTP-Backup-Ziel:"
  sed 's/^/    /' /root/.ssh/fv-web-backup.pub
  log "WICHTIG: RESTIC_PASSWORD getrennt vom Server verwahren (Passwort-Manager):"
  log "         sudo grep RESTIC_PASSWORD $BENV"
  local newest; newest="$(ls /boot/vmlinuz-* 2>/dev/null | sed 's|/boot/vmlinuz-||' | sort -V | tail -n1)"
  if [[ -n "$newest" && "$newest" != "$(uname -r)" ]]; then
    log "HINWEIS: Neustart erforderlich (Kernel-Update). Bitte zu passender Zeit: sudo reboot"
  fi
  log "Server-Protokoll: $REMOTE_LOG"
}

case "$PHASE" in
  base)    phase_base ;;
  harden)  phase_harden ;;
  tool)    phase_tool ;;
  app)     phase_app ;;
  admin)   phase_admin ;;
  mail)    phase_mail ;;
  summary) phase_summary ;;
  *) echo "Unbekannte Phase: $PHASE"; exit 2 ;;
esac
REMOTE
)

# ============================== Ablauf (lokal) ===============================
if [[ $UPDATE_ONLY -eq 1 ]]; then
  log "Grundeinrichtung und SSH-Härtung übersprungen (-U)."
else
  log "Phase 1: Grundeinrichtung"
  run_remote base <<<"$REMOTE_SCRIPT"

  log "Phase 2: Anmeldung als $ADMIN_USER testen"
  ssh "${SSH_OPTS[@]}" "$ADMIN_USER@$SERVER" 'sudo -n true' \
    || fail "Anmeldung als $ADMIN_USER fehlgeschlagen – SSH wird NICHT gehärtet, root-Login bleibt möglich."
  log "Anmeldung als $ADMIN_USER mit sudo funktioniert."
  TARGET="$ADMIN_USER@$SERVER"; SUDO="sudo -n"

  if [[ $SKIP_HARDEN -eq 1 ]]; then
    log "Phase 3: SSH-Härtung übersprungen (-S)."
  else
    log "Phase 3: SSH härten"
    run_remote harden <<<"$REMOTE_SCRIPT"
    ssh "${SSH_OPTS[@]}" "$ADMIN_USER@$SERVER" true \
      || fail "Anmeldung nach Härtung fehlgeschlagen! Bestehende SSH-Sitzung offen halten und Konfiguration prüfen."
    if ssh "${SSH_OPTS[@]}" "root@$SERVER" true 2>/dev/null; then log "WARNUNG: root-Login ist noch möglich."
    else log "root-Login ist gesperrt (erwartet)."; fi
  fi
fi

log "Phase 4: fv-web-update einrichten"
run_remote tool <<<"$REMOTE_SCRIPT"

if [[ $NO_APP -eq 1 ]]; then
  log "Phase 5: Anwendung übersprungen (-N)."
else
  if [[ $LOCAL_UPLOAD -eq 1 ]]; then
    log "Phase 5: Anwendung installieren (lokaler Stand $APP_DESC)"
    TMP_TAR="$(mktemp)"
    git -C "$REPO_DIR" archive --format=tar.gz --prefix=fv-web/ "$APP_COMMIT" > "$TMP_TAR"
    TAR_KB=$(( $(wc -c < "$TMP_TAR") / 1024 ))
    REMOTE_TAR="/tmp/fv-web-$STAMP.tar.gz"
    # shellcheck disable=SC2029
    ssh "${SSH_OPTS[@]}" "$TARGET" "umask 077; cat > '$REMOTE_TAR'" < "$TMP_TAR" || fail "Hochladen fehlgeschlagen."
    rm -f "$TMP_TAR"
    log "Paket hochgeladen (${TAR_KB} KB)."
  else
    log "Phase 5: Anwendung installieren (Server holt ${GIT_REF:-den Standard-Stand} von GitHub)"
  fi
  run_remote app <<<"$REMOTE_SCRIPT"
fi

if [[ -n "$APP_ADMIN" ]]; then
  log "Phase 6: Vorstandskonto"
  run_remote admin <<<"$REMOTE_SCRIPT"
fi

if [[ $WITH_MAIL -eq 1 ]]; then
  log "Phase 7: Mailserver ($MAIL_HOST)"
  run_remote mail <<<"$REMOTE_SCRIPT"
fi

log "Phase 8: Zusammenfassung"
run_remote summary <<<"$REMOTE_SCRIPT"

if curl -fsS --max-time 15 -o /dev/null "https://$DOMAIN/"; then
  log "HTTPS-Test https://$DOMAIN: erreichbar."
else
  log "HTTPS-Test https://$DOMAIN: noch nicht erreichbar (DNS/Zertifikat prüfen; Caddy versucht es automatisch erneut)."
fi
log "Fertig. Anmeldung künftig: ssh -p $SSH_PORT $ADMIN_USER@$SERVER"
log "Neue Version einspielen: ssh -p $SSH_PORT $ADMIN_USER@$SERVER sudo fv-web-update"
log "Lokales Protokoll: $LOCAL_LOG"

#!/usr/bin/env bash
# =============================================================================
#  setup-server-fv-web.sh – Einrichtung des Webservers des Fördervereins KF/JF Kreuzau
#
#  Läuft auf DEINEM Rechner und richtet den vServer per SSH ein.
#  Ziel: Debian 13 (trixie), Grundinstallation.
#
#  Zwei Arten des Aufrufs
#    im Repository:  deploy/setup-server-fv-web.sh …   (nimmt den lokalen Git-Stand)
#    eigenständig:   ./setup-server-fv-web.sh …        (Skript liegt allein irgendwo;
#                    holt den Stand per git von GitHub, Standard: Branch main.
#                    Nötig ist nur Lesezugriff auf das Repository, z. B. über
#                    die eigenen GitHub-Zugangsdaten oder einen SSH-Schlüssel.)
#  Reproduzierbar: Jeder Schritt prüft, ob er schon erledigt ist, und kann
#  beliebig oft erneut ausgeführt werden.
#
#  Aufbau auf dem Server (nur Debian-Pakete, kein Docker)
#    PostgreSQL 17      Datenbank "fvweb", Anmeldung über den Unix-Socket (ohne Passwort)
#    Python 3.13        Anwendung in einer virtuellen Umgebung je Version
#    gunicorn           Dienst fv-web.service als Benutzer "fvweb"
#    Caddy              HTTPS mit automatischem Zertifikat, statische Dateien
#    restic             tägliche, verschlüsselte Datensicherung
#
#  Verzeichnisse
#    /srv/fv-web/releases/<zeitstempel>   installierte Versionen (die letzten 3)
#    /srv/fv-web/current                  Verweis auf die aktive Version
#    /etc/fv-web/env                      Einstellungen der Anwendung
#    /etc/fv-web/backup.env               Einstellungen der Datensicherung (nur root)
#    /var/lib/fv-web/private              Anhänge (nur für die Anwendung lesbar)
#    /var/lib/fv-web/static               CSS, JavaScript, Editor (liefert Caddy aus)
#    /var/lib/fv-web/mails                E-Mails, solange kein Mailserver eingetragen ist
#    /var/backups/fv-web                  Datenbank-Dumps (7 Tage)
#
#  Was das Skript macht
#    1. Verbindung und DNS prüfen, Ports 80/443 auf andere Webserver prüfen
#    2. System aktualisieren, Zeitzone, Hostname, automatische Sicherheitsupdates
#    3. Admin-Benutzer mit SSH-Schlüssel und sudo, Firewall, fail2ban
#    4. PostgreSQL, Caddy, Python; Dienstbenutzer, Verzeichnisse, Einstellungen,
#       systemd-Dienst, Datensicherung
#    5. Anmeldung als Admin-Benutzer testen – erst DANACH SSH härten
#    6. Anwendung aus dem Git-Repository (git archive, ohne Zugangsdaten auf
#       dem Server) hochladen, installieren, Datenbank migrieren, starten.
#       Vorher automatische Datensicherung; schlägt der Start fehl, wird die
#       vorherige Version wieder aktiviert.
#    7. Optional: Vorstandskonto anlegen (-a, -m) – gibt einen Link zum Setzen
#       des Passworts aus
#    8. Zusammenfassung
#
#  Protokolle
#    lokal:    deploy/logs/setup-<server>-<zeitstempel>.log
#    Server:   /var/log/fv-web-setup/<zeitstempel>.log
#
#  Beispiele
#    Nur prüfen (ändert nichts):
#      deploy/setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -W -c
#    Erstinstallation mit Vorstandskonto:
#      deploy/setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -W \
#                                    -n fv-web -a michael.bramer -m adresse@example.org
#    Neue Version einspielen (aktueller Stand von main):
#      deploy/setup-server-fv-web.sh -H 203.0.113.10 -d foerderverein-kf-jf-kreuzau.de -U -r main
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
GIT_REF=""            # leer: HEAD (im Repository) bzw. main (eigenständig)
REPO_URL="https://github.com/brami/FKJF.git"
SKIP_HARDEN=0
ASSUME_YES=0
CHECK_ONLY=0
UPDATE_ONLY=0
NO_APP=0
APP_ADMIN=""
APP_ADMIN_MAIL=""

usage() {
  cat <<EOF
Aufruf: $0 -H <server> -d <domain> [Optionen]

Pflicht:
  -H <server>     IP-Adresse oder Name des vServers
  -d <domain>     Domain der Webseite, z. B. foerderverein-kf-jf-kreuzau.de

Anwendung:
  -r <ref>        Git-Stand, der installiert wird (Branch, Tag oder Commit).
                  Im Repository Standard: HEAD (nur eingecheckter Code).
                  Eigenständig Standard: main.
  -R <url>        Repository, aus dem eigenständig geholt wird
                  (Standard: $REPO_URL, per SSH z. B.
                  git@github.com:brami/FKJF.git)
  -U              Nur die Anwendung installieren/aktualisieren (Grundeinrichtung
                  und SSH-Härtung überspringen; Server muss eingerichtet sein)
  -N              Keine Anwendung installieren (nur Server einrichten)
  -a <benutzer>   Vorstandskonto mit Verwaltungsrechten anlegen bzw. ergänzen,
  -m <e-mail>     z. B. -a michael.bramer -m adresse@example.org. Ausgegeben wird
                  ein Link zum Setzen des Passworts (7 Tage gültig).

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
  -c              Nur prüfen: SSH, Ports, DNS, Git-Stand – ändert nichts
  -S              SSH-Härtung überspringen (root-Login bleibt erlaubt)
  -y              Keine Rückfrage vor dem Start
  -h              Diese Hilfe
EOF
}

while getopts ":H:d:r:R:a:m:e:B:u:n:t:p:WUNcSyh" opt; do
  case "$opt" in
    H) SERVER="$OPTARG" ;;
    d) DOMAIN="$OPTARG" ;;
    r) GIT_REF="$OPTARG" ;;
    R) REPO_URL="$OPTARG" ;;
    a) APP_ADMIN="$OPTARG" ;;
    m) APP_ADMIN_MAIL="$OPTARG" ;;
    e) ACME_EMAIL="$OPTARG" ;;
    B) BACKUP_REPO="$OPTARG" ;;
    u) ADMIN_USER="$OPTARG" ;;
    n) NEW_HOSTNAME="$OPTARG" ;;
    t) TIMEZONE="$OPTARG" ;;
    p) SSH_PORT="$OPTARG" ;;
    W) WITH_WWW=1 ;;
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
if [[ -n "$APP_ADMIN$APP_ADMIN_MAIL" ]]; then
  [[ -n "$APP_ADMIN" && -n "$APP_ADMIN_MAIL" ]] || { echo "-a und -m nur zusammen angeben." >&2; exit 2; }
  [[ "$APP_ADMIN" =~ ^[a-z0-9][a-z0-9._-]{0,149}$ ]] || { echo "Ungültiger Benutzername für -a: $APP_ADMIN" >&2; exit 2; }
  [[ "$APP_ADMIN_MAIL" =~ ^[^@[:space:]\"\$\`]+@[^@[:space:]\"\$\`]+\.[^@[:space:]\"\$\`]+$ ]] \
    || { echo "Ungültige E-Mail-Adresse für -m: $APP_ADMIN_MAIL" >&2; exit 2; }
fi
[[ $UPDATE_ONLY -eq 1 && $NO_APP -eq 1 ]] && { echo "-U und -N schließen sich aus." >&2; exit 2; }
for v in "$ACME_EMAIL" "$BACKUP_REPO" "$TIMEZONE" "$NEW_HOSTNAME"; do
  [[ "$v" != *[\"\$\`\\]* ]] || { echo "Unzulässige Zeichen in einer Option: $v" >&2; exit 2; }
done

# ----------------------------- Lokale Voraussetzungen ------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Liegt das Skript im Repository (deploy/), wird der lokale Stand verwendet,
# sonst wird das Repository in ein temporäres Verzeichnis geholt.
REPO_DIR=""; STANDALONE=1
if [[ -f "$SCRIPT_DIR/../manage.py" ]] && git -C "$SCRIPT_DIR/.." rev-parse --git-dir >/dev/null 2>&1; then
  REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"; STANDALONE=0
fi
[[ -n "$GIT_REF" ]] || { [[ $STANDALONE -eq 1 ]] && GIT_REF="main" || GIT_REF="HEAD"; }

check_local_tools() {
  local missing=() t
  if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4) )); then
    echo "FEHLER: Bash $BASH_VERSION ist zu alt, benötigt wird Bash 4.4 oder neuer." >&2
    echo "        macOS: brew install bash, dann: /opt/homebrew/bin/bash $0 ..." >&2
    exit 2
  fi
  for t in ssh git curl tee awk sed grep tr wc head cut paste date gzip; do
    command -v "$t" >/dev/null 2>&1 || missing+=("$t")
  done
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
log "Start ($MODE)"
log "Server: $SERVER | Domain: $DOMAIN$([[ $WITH_WWW -eq 1 ]] && echo " + www.$DOMAIN") | Admin: $ADMIN_USER | Zeitzone: $TIMEZONE | Hostname: ${NEW_HOSTNAME:-unverändert}"
log "Lokales Protokoll: $LOCAL_LOG"
if [[ $STANDALONE -eq 1 ]]; then log "Aufruf eigenständig – Code aus $REPO_URL ($GIT_REF)"
else log "Aufruf im Repository $REPO_DIR ($GIT_REF)"; fi

# ----------------------------- Git-Stand -------------------------------------
APP_COMMIT=""; APP_DESC=""
FETCH_DIR=""
cleanup_fetch() { [[ -n "$FETCH_DIR" ]] && rm -rf "$FETCH_DIR"; return 0; }
trap cleanup_fetch EXIT
if [[ $NO_APP -eq 0 && $STANDALONE -eq 1 ]]; then
  # Eigenständig: nur den gewünschten Stand holen (flach, ohne Verlauf)
  FETCH_DIR="$(mktemp -d)"
  log "Hole $GIT_REF aus $REPO_URL …"
  git -C "$FETCH_DIR" init -q
  if ! git -C "$FETCH_DIR" fetch -q --depth 1 "$REPO_URL" "$GIT_REF"; then
    fail "Konnte $GIT_REF nicht aus $REPO_URL holen. Zugriff prüfen (privates Repository: GitHub-Anmeldung bzw. SSH-Schlüssel, -R git@github.com:brami/FKJF.git)."
  fi
  REPO_DIR="$FETCH_DIR"; GIT_REF="FETCH_HEAD"
fi
if [[ $NO_APP -eq 0 ]]; then
  APP_COMMIT="$(git -C "$REPO_DIR" rev-parse --verify --quiet "$GIT_REF^{commit}")" \
    || fail "Git-Stand '$GIT_REF' nicht gefunden (git fetch vergessen?)."
  APP_DESC="$(git -C "$REPO_DIR" log -1 --format='%h %s (%ad)' --date=short "$APP_COMMIT")"
  log "Anwendung: $APP_DESC"
  if [[ $STANDALONE -eq 0 && "$GIT_REF" == HEAD && -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]]; then
    log "HINWEIS: Es gibt nicht eingecheckte Änderungen – übertragen wird nur der Stand des letzten Commits."
  fi
  for f in manage.py requirements.txt config/settings.py; do
    git -C "$REPO_DIR" cat-file -e "$APP_COMMIT:$f" 2>/dev/null || fail "$f fehlt im Git-Stand $GIT_REF."
  done
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
[ -e /srv/fv-web/current/manage.py ] && echo "anwendung=ja"
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
  local domains=("$DOMAIN"); [[ $WITH_WWW -eq 1 ]] && domains+=("www.$DOMAIN")
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

RELEASE="$STAMP"
REMOTE_TAR=""
APP_SHA=""
run_remote() {  # $1 = Phase, Skript kommt über stdin
  local envs
  envs=$(printf 'PHASE=%q ADMIN_USER=%q TIMEZONE=%q NEW_HOSTNAME=%q DOMAIN=%q WITH_WWW=%q ACME_EMAIL=%q BACKUP_REPO=%q STAMP=%q SSH_PORT=%q REMOTE_TAR=%q APP_SHA=%q APP_COMMIT=%q APP_DESC=%q RELEASE=%q APP_ADMIN=%q APP_ADMIN_MAIL=%q' \
    "$1" "$ADMIN_USER" "$TIMEZONE" "$NEW_HOSTNAME" "$DOMAIN" "$WITH_WWW" "$ACME_EMAIL" "$BACKUP_REPO" "$STAMP" "$SSH_PORT" \
    "$REMOTE_TAR" "$APP_SHA" "$APP_COMMIT" "$APP_DESC" "$RELEASE" "$APP_ADMIN" "$APP_ADMIN_MAIL")
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

# manage.py als Dienstbenutzer mit den Einstellungen ausführen; $1 = Code-Verzeichnis
manage_in() {
  local dir="$1"; shift
  runuser -u "$SVC" -- bash -c 'set -a; . "$0"; set +a; cd "$1"; shift; exec .venv/bin/python manage.py "$@"' \
    "$ENVF" "$dir" "$@"
}

write_caddyfile() {  # $1 = app | platzhalter
  local tmp; tmp="$(mktemp)"
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

# --------------------------------------------------------------- Phase base
phase_base() {
  step "Systeminformationen"
  . /etc/os-release
  log "System: $PRETTY_NAME | Kernel: $(uname -r)"

  step "System aktualisieren und Pakete installieren"
  apt-get update -q
  apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade
  apt_install ca-certificates curl sudo dbus ufw fail2ban python3-systemd \
              unattended-upgrades apt-listchanges jq bind9-dnsutils rsync restic \
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
  ensure_kv "$ENVF" FV_MAIL_ABSENDER "Förderverein KF/JF Kreuzau <webmaster@$DOMAIN>"
  ensure_kv "$ENVF" FV_SMTP_HOST ""
  ensure_kv "$ENVF" FV_SMTP_PORT "587"
  ensure_kv "$ENVF" FV_SMTP_USER ""
  ensure_kv "$ENVF" FV_SMTP_PASSWORD ""
  ensure_kv "$ENVF" FV_SMTP_TLS "starttls"
  ensure_kv "$ENVF" FV_ADMINS ""
  # Domainabhängige Werte bei jedem Lauf setzen
  local hosts="$DOMAIN"; [[ "$WITH_WWW" == 1 ]] && hosts="$DOMAIN,www.$DOMAIN"
  set_kv "$ENVF" FV_ALLOWED_HOSTS "$hosts"
  set_kv "$ENVF" FV_CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
  set_kv "$ENVF" FV_BASIS_URL "https://$DOMAIN"
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
  cat > /usr/local/sbin/fv-manage <<EOF
#!/usr/bin/env bash
# Django-Befehle der Webseite ausführen, z. B.:  sudo fv-manage vorstand_anlegen …
set -euo pipefail
[[ -e $BASE/current/manage.py ]] || { echo "Anwendung nicht installiert." >&2; exit 1; }
exec runuser -u $SVC -- bash -c 'set -a; . $ENVF; set +a; cd $BASE/current; exec .venv/bin/python manage.py "\$@"' fv-manage "\$@"
EOF
  chmod 750 /usr/local/sbin/fv-manage
  systemctl daemon-reload
  app_installed && systemctl enable fv-web >/dev/null
  log "Dienst fv-web eingerichtet; Befehle: sudo fv-manage <befehl>"

  step "Caddy"
  systemctl enable caddy >/dev/null
  systemctl restart caddy   # neue Gruppenzugehörigkeit übernehmen
  if app_installed; then write_caddyfile app; else write_caddyfile platzhalter; fi

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
#  2. restic: Dump, Anhänge (/var/lib/fv-web/private) und /etc/fv-web verschlüsselt
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
"${R[@]}" backup --quiet --host fv-web --tag fv-web "$f" /var/lib/fv-web/private /etc/fv-web
"${R[@]}" forget --quiet --host fv-web --keep-daily "$(getkv BACKUP_KEEP_DAYS)" --keep-monthly "$(getkv BACKUP_KEEP_MONTHS)" --prune
[[ "$(date +%u)" == 7 ]] && "${R[@]}" check --read-data-subset=5%
log "Gesichert in $RESTIC_REPOSITORY ($("${R[@]}" snapshots --host fv-web --json | jq length) Stände)"
[[ "$RESTIC_REPOSITORY" == /* ]] && log "HINWEIS: Ziel liegt auf diesem Server – schützt nicht bei Ausfall des Servers."
ping_url ""
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
set -Eeuo pipefail
BENV=/etc/fv-web/backup.env; KEY=/root/.ssh/fv-web-backup
getkv() { grep -m1 "^$1=" "$BENV" | cut -d= -f2- | sed 's/^"//; s/"$//'; }
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
SNAP=latest; MODE=""
while getopts ":lr:tE" o; do
  case "$o" in l) MODE=liste ;; r) SNAP="$OPTARG" ;; t) MODE="test" ;; E) MODE="echt" ;;
    *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;; esac
done
[[ -n "$MODE" ]] || { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
export RESTIC_REPOSITORY RESTIC_PASSWORD
RESTIC_REPOSITORY="$(getkv RESTIC_REPOSITORY)"; RESTIC_PASSWORD="$(getkv RESTIC_PASSWORD)"
R=(restic); [[ "$RESTIC_REPOSITORY" == sftp:* ]] && R+=(-o "sftp.args=-i $KEY -o BatchMode=yes")
if [[ "$MODE" == liste ]]; then
  echo "Lokale Dumps:"; ls -lh /var/backups/fv-web/*.dump 2>/dev/null | awk '{print "  "$5"  "$9}' || echo "  keine"
  echo "restic ($RESTIC_REPOSITORY):"; "${R[@]}" snapshots --host fv-web; exit 0
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

# --------------------------------------------------------------- Phase app
phase_app() {
  step "Anwendung: Paket prüfen"
  [[ -f "$ENVF" ]] || { log "FEHLER: $ENVF fehlt – Server zuerst ohne -U einrichten."; exit 1; }
  [[ -f "$REMOTE_TAR" ]] || { log "FEHLER: Hochgeladenes Paket fehlt: $REMOTE_TAR"; exit 1; }
  [[ "$(sha256sum "$REMOTE_TAR" | cut -d' ' -f1)" == "$APP_SHA" ]] \
    || { log "FEHLER: Prüfsumme stimmt nicht – Übertragung fehlerhaft."; exit 1; }

  local rel="$BASE/releases/$RELEASE" prev=""
  [[ -L "$BASE/current" ]] && prev="$(readlink -f "$BASE/current")"
  step "Anwendung: entpacken (Version $RELEASE, Commit ${APP_COMMIT:0:10})"
  rm -rf "$rel"; install -d -m 750 -o root -g "$SVC" "$rel"
  tar -xzf "$REMOTE_TAR" -C "$rel" --strip-components=1 --no-same-owner
  rm -f "$REMOTE_TAR"
  printf 'Version:  %s\nCommit:   %s\nStand:    %s\nInstalliert: %s\n' \
    "$RELEASE" "$APP_COMMIT" "$APP_DESC" "$(date '+%F %T')" > "$rel/.release"

  step "Anwendung: Python-Umgebung"
  python3 -m venv "$rel/.venv"
  "$rel/.venv/bin/pip" install -q --no-cache-dir --disable-pip-version-check -r "$rel/requirements.txt"
  # Code gehört root und ist für den Dienst nur lesbar
  chown -R root:"$SVC" "$rel"; chmod -R g+rX,g-w,o-rwx "$rel"
  log "$("$rel/.venv/bin/python" -c 'import django; print("Django", django.get_version())')"

  step "Anwendung: Prüfung"
  manage_in "$rel" check --deploy --fail-level ERROR

  step "Anwendung: Datensicherung vor dem Update"
  if app_installed && systemctl cat fv-web-backup.service >/dev/null 2>&1; then
    systemctl start fv-web-backup.service && log "Sicherung erstellt." \
      || log "WARNUNG: Sicherung fehlgeschlagen – Update läuft trotzdem weiter."
  else
    log "Erstinstallation – keine Sicherung nötig."
  fi

  step "Anwendung: Datenbank migrieren, statische Dateien"
  manage_in "$rel" migrate --noinput
  manage_in "$rel" collectstatic --noinput --clear -v0
  log "Statische Dateien: $(find "$DATA/static" -type f | wc -l) Dateien."

  step "Anwendung: aktivieren und starten"
  ln -sfn "$rel" "$BASE/current.neu" && mv -T "$BASE/current.neu" "$BASE/current"
  systemctl daemon-reload
  systemctl enable fv-web >/dev/null
  systemctl restart fv-web
  local ok=0
  for _ in $(seq 1 20); do
    if [[ "$(curl -s --max-time 5 --unix-socket /run/fv-web/gunicorn.sock \
               -H "Host: $DOMAIN" -H 'X-Forwarded-Proto: https' http://localhost/gesund/ || true)" == ok ]]; then
      ok=1; break
    fi
    sleep 1
  done
  if [[ $ok -ne 1 ]]; then
    journalctl -u fv-web -n 40 --no-pager -o cat | sed 's/^/    /'
    if [[ -n "$prev" && -d "$prev" ]]; then
      ln -sfn "$prev" "$BASE/current.neu" && mv -T "$BASE/current.neu" "$BASE/current"
      systemctl restart fv-web
      log "FEHLER: Neue Version startet nicht – vorherige Version $(basename "$prev") wieder aktiv."
      log "        Achtung: Datenbank-Migrationen der neuen Version wurden NICHT zurückgenommen."
    else
      log "FEHLER: Anwendung startet nicht (Protokoll siehe oben)."
    fi
    exit 1
  fi
  log "Anwendung läuft (gunicorn, $(systemctl show fv-web -p MainPID --value))."
  write_caddyfile app

  # die letzten drei Versionen behalten
  ls -1dt "$BASE"/releases/*/ | tail -n +4 | xargs -r rm -rf
  log "Versionen: $(ls -1 "$BASE/releases" | paste -sd ' ')"

  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/gesund/" || true)
  if [[ "$code" == 200 ]]; then log "https://$DOMAIN/gesund/: in Ordnung."
  else log "HINWEIS: https://$DOMAIN noch nicht erreichbar (HTTP ${code:-–}). Meist fehlt noch das Zertifikat (DNS prüfen)."; fi
}

# ------------------------------------------------------------- Phase admin
phase_admin() {
  step "Vorstandskonto $APP_ADMIN"
  /usr/local/sbin/fv-manage vorstand_anlegen "$APP_ADMIN" "$APP_ADMIN_MAIL" --admin
  log "Den Link nur an $APP_ADMIN weitergeben. Er ist nach dem Setzen des Passworts verbraucht."
}

# ------------------------------------------------------------ Phase summary
phase_summary() {
  step "Zusammenfassung"
  . /etc/os-release
  log "System:       $PRETTY_NAME, Kernel $(uname -r), Hostname $(hostnamectl --static)"
  log "Admin:        $ADMIN_USER | Firewall: $(ufw status | head -n1) | fail2ban: $(systemctl is-active fail2ban)"
  log "Dienste:      fv-web $(systemctl is-active fv-web 2>/dev/null || true) | caddy $(systemctl is-active caddy) | postgresql $(systemctl is-active postgresql)"
  if app_installed; then
    log "Anwendung:    $(grep '^Stand' "$BASE/current/.release" | cut -d: -f2- | xargs)"
    log "              Verwaltung: https://$DOMAIN/$(getkv "$ENVF" FV_ADMIN_PFAD)"
  else
    log "Anwendung:    noch nicht installiert (Platzhalterseite)"
  fi
  log "E-Mail:       FV_MAIL=$(getkv "$ENVF" FV_MAIL) – Mailserver später in $ENVF eintragen (FV_MAIL=smtp, FV_SMTP_*)"
  log "              und mit -U neu starten bzw.: sudo systemctl restart fv-web"
  log "Backup:       täglich ~03:30 nach $(getkv "$BENV" RESTIC_REPOSITORY)"
  log "              Wiederherstellungstest: sudo fv-web-restore -t"
  [[ "$(getkv "$BENV" RESTIC_REPOSITORY)" == /* ]] && log "              HINWEIS: Ziel liegt auf diesem Server – später extern sichern (-B)."
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
  app)     phase_app ;;
  admin)   phase_admin ;;
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

if [[ $NO_APP -eq 1 ]]; then
  log "Phase 4: Anwendung übersprungen (-N)."
else
  log "Phase 4: Anwendung installieren ($APP_DESC)"
  TMP_TAR="$(mktemp)"
  git -C "$REPO_DIR" archive --format=tar.gz --prefix=fv-web/ "$APP_COMMIT" > "$TMP_TAR"
  if command -v sha256sum >/dev/null; then APP_SHA="$(sha256sum "$TMP_TAR" | cut -d' ' -f1)"
  else APP_SHA="$(shasum -a 256 "$TMP_TAR" | cut -d' ' -f1)"; fi
  REMOTE_TAR="/tmp/fv-web-$STAMP.tar.gz"
  TAR_KB=$(( $(wc -c < "$TMP_TAR") / 1024 ))
  # shellcheck disable=SC2029
  ssh "${SSH_OPTS[@]}" "$TARGET" "umask 077; cat > '$REMOTE_TAR'" < "$TMP_TAR" || fail "Hochladen fehlgeschlagen."
  rm -f "$TMP_TAR"
  log "Paket hochgeladen (${TAR_KB} KB, SHA-256 ${APP_SHA:0:16}…)"
  run_remote app <<<"$REMOTE_SCRIPT"
fi

if [[ -n "$APP_ADMIN" ]]; then
  log "Phase 5: Vorstandskonto"
  run_remote admin <<<"$REMOTE_SCRIPT"
fi

log "Phase 6: Zusammenfassung"
run_remote summary <<<"$REMOTE_SCRIPT"

if curl -fsS --max-time 15 -o /dev/null "https://$DOMAIN/"; then
  log "HTTPS-Test https://$DOMAIN: erreichbar."
else
  log "HTTPS-Test https://$DOMAIN: noch nicht erreichbar (DNS/Zertifikat prüfen; Caddy versucht es automatisch erneut)."
fi
log "Fertig. Anmeldung künftig: ssh -p $SSH_PORT $ADMIN_USER@$SERVER"
log "Neue Version einspielen: $0 -H $SERVER -d $DOMAIN -U$([[ $STANDALONE -eq 0 ]] && echo ' -r main')"
log "Lokales Protokoll: $LOCAL_LOG"

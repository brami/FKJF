#!/usr/bin/env bash
# =============================================================================
#  drupal-export.sh – bisherige Drupal-Seite sichern und Inhalte auflisten
#
#  Auf dem Drupal-Server als root ausführen:
#      sudo bash drupal-export.sh                 (Drupal-Verzeichnis wird gesucht)
#      sudo bash drupal-export.sh -r /var/www/drupal
#
#  Das Skript ÄNDERT NICHTS an Drupal: Es liest nur (SELECT, mysqldump, tar).
#  Ergebnis in /root/drupal-export-<zeitstempel>/:
#
#    sicherung/          VOLLSTÄNDIGE Sicherung zum Aufbewahren – NICHT weitergeben
#                        (enthält Benutzerkonten, Passwort-Hashes, Zugangsdaten):
#      datenbank.sql.gz    kompletter Datenbank-Dump
#      dateien.tar.gz      sites/default/files (ohne erzeugte Caches)
#      settings.php        Konfiguration
#    uebersicht.txt      Bericht: Seiten, Adressen, Dateien, Menü, Felder
#    inhalte/            nur ÖFFENTLICHE Inhalte für die Übernahme:
#      seiten.tsv          nid, Typ, veröffentlicht, erstellt, geändert, Titel
#      adressen.tsv        Systempfad (/node/5) -> Adresse (/satzung)
#      dateien.tsv         Dateien mit Zuordnung zu Seiten
#      menue.tsv           Menüeinträge
#      weiterleitungen.tsv vorhandene Weiterleitungen (Modul "redirect")
#      node-<nid>.html     Text jeder Seite
#      dateien/            die von Seiten verwendeten öffentlichen Dateien
#
#  Zum Weitergeben (für die Übernahme) nur:  uebersicht.txt und inhalte/
#  (das Skript erstellt dafür am Ende inhalte.tar.gz)
#
#  Voraussetzungen auf dem Server: php (CLI), mysql/mariadb-Client, mysqldump, tar
# =============================================================================
set -Eeuo pipefail

DRUPAL_ROOT=""
SITE="sites/default"
while getopts ":r:s:h" opt; do
  case "$opt" in
    r) DRUPAL_ROOT="$OPTARG" ;;
    s) SITE="$OPTARG" ;;
    h) sed -n '3,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unbekannte Option. Hilfe: $0 -h" >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen (sudo)." >&2; exit 1; }
for t in php tar gzip; do
  command -v "$t" >/dev/null || { echo "Programm fehlt: $t" >&2; exit 1; }
done
MYSQL="$(command -v mariadb || command -v mysql || true)"
DUMP="$(command -v mariadb-dump || command -v mysqldump || true)"
[[ -n "$MYSQL" && -n "$DUMP" ]] || { echo "mysql/mariadb-Client oder mysqldump fehlt." >&2; exit 1; }

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

# ----------------------------------------------------------- Drupal finden
if [[ -z "$DRUPAL_ROOT" ]]; then
  kandidat="$(find /var/www /srv /opt /home -maxdepth 5 -path '*/core/lib/Drupal.php' -print -quit 2>/dev/null || true)"
  [[ -n "$kandidat" ]] && DRUPAL_ROOT="$(dirname "$(dirname "$(dirname "$kandidat")")")"
fi
[[ -n "$DRUPAL_ROOT" && -f "$DRUPAL_ROOT/core/lib/Drupal.php" ]] \
  || { echo "Drupal nicht gefunden. Bitte mit -r <verzeichnis> angeben (das Verzeichnis mit core/)." >&2; exit 1; }
SETTINGS="$DRUPAL_ROOT/$SITE/settings.php"
[[ -f "$SETTINGS" ]] || { echo "$SETTINGS nicht gefunden (anderes Site-Verzeichnis? -s sites/<name>)." >&2; exit 1; }
VERSION="$(grep -m1 "const VERSION" "$DRUPAL_ROOT/core/lib/Drupal.php" | grep -o "'[^']*'" | tr -d "'" || true)"
log "Drupal ${VERSION:-?} in $DRUPAL_ROOT ($SITE)"

# ------------------------------------------------- Datenbank-Zugang lesen
# settings.php mit PHP auswerten (ohne Drupal zu starten)
DB_JSON="$(cd "$DRUPAL_ROOT" && php -r '
  $app_root = getcwd(); $site_path = $argv[1]; $settings = []; $config = []; $databases = [];
  $class_loader = null;
  @include $argv[1] . "/settings.php";
  echo json_encode($databases["default"]["default"] ?? null);
' "$SITE" 2>/dev/null || true)"
feld() { php -r '$d = json_decode($argv[1], true); echo $d[$argv[2]] ?? "";' "$DB_JSON" "$1"; }
DRIVER="$(feld driver)"
[[ "$DRIVER" == mysql ]] || { echo "Datenbanktreiber '${DRIVER:-unbekannt}' wird nicht unterstützt (nur MySQL/MariaDB)." >&2; exit 1; }
DB_NAME="$(feld database)"; DB_PREFIX="$(feld prefix)"

AUS="/root/drupal-export-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$AUS" "$AUS/sicherung" "$AUS/inhalte" "$AUS/inhalte/dateien"
ZUGANG="$(mktemp)"; chmod 600 "$ZUGANG"
trap 'rm -f "$ZUGANG"' EXIT
{
  echo "[client]"
  echo "user=$(feld username)"
  echo "password=$(feld password)"
  host="$(feld host)"; port="$(feld port)"
  [[ -n "$host" ]] && echo "host=$host"
  [[ -n "$port" ]] && echo "port=$port"
  echo "default-character-set=utf8mb4"
} > "$ZUGANG"

sql() { "$MYSQL" --defaults-extra-file="$ZUGANG" --batch --raw --skip-column-names "$DB_NAME" -e "$1"; }
sql_kopf() { "$MYSQL" --defaults-extra-file="$ZUGANG" --batch --raw "$DB_NAME" -e "$1"; }
t() { printf '%s%s' "$DB_PREFIX" "$1"; }   # Tabellenname mit Präfix
gibt_tabelle() {
  [[ "$(sql "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$(t "$1")'")" == 1 ]]
}
sql "SELECT 1" >/dev/null || { echo "Anmeldung an der Datenbank $DB_NAME fehlgeschlagen." >&2; exit 1; }
log "Datenbank: $DB_NAME (Präfix: ${DB_PREFIX:-keins})"

# ---------------------------------------------------------- 1. Sicherung
log "Sicherung der Datenbank …"
"$DUMP" --defaults-extra-file="$ZUGANG" --single-transaction --quick --routines --triggers \
        --hex-blob "$DB_NAME" | gzip -9 > "$AUS/sicherung/datenbank.sql.gz"
log "Sicherung der Dateien …"
DATEIEN_DIR="$DRUPAL_ROOT/$SITE/files"
if [[ -d "$DATEIEN_DIR" ]]; then
  tar -czf "$AUS/sicherung/dateien.tar.gz" -C "$DRUPAL_ROOT/$SITE" \
      --exclude='files/css' --exclude='files/js' --exclude='files/php' --exclude='files/styles' files
fi
cp -p "$SETTINGS" "$AUS/sicherung/settings.php"
chmod -R go-rwx "$AUS/sicherung"

# --------------------------------------------------- 2. Inhalte auflisten
log "Inhalte auslesen (nur lesend) …"
sql_kopf "SELECT nid, type AS typ, status AS veroeffentlicht,
                 FROM_UNIXTIME(created) AS erstellt, FROM_UNIXTIME(changed) AS geaendert, title AS titel
          FROM $(t node_field_data) WHERE default_langcode = 1 ORDER BY created" > "$AUS/inhalte/seiten.tsv"

if gibt_tabelle path_alias; then
  sql_kopf "SELECT path AS systempfad, alias AS adresse, status FROM $(t path_alias) ORDER BY path" \
    > "$AUS/inhalte/adressen.tsv"
fi
if gibt_tabelle redirect; then
  sql_kopf "SELECT redirect_source__path AS von, redirect_redirect__uri AS nach, status_code
            FROM $(t redirect)" > "$AUS/inhalte/weiterleitungen.tsv"
fi
if gibt_tabelle menu_link_content_data; then
  sql_kopf "SELECT menu_name AS menue, title AS titel, link__uri AS ziel, enabled AS aktiv, weight AS reihenfolge
            FROM $(t menu_link_content_data) ORDER BY menu_name, weight" > "$AUS/inhalte/menue.tsv"
fi
sql_kopf "SELECT f.fid, f.filename AS dateiname, f.uri, f.filemime AS typ, f.filesize AS bytes,
                 u.type AS verwendet_von, u.id AS nid
          FROM $(t file_managed) f LEFT JOIN $(t file_usage) u ON u.fid = f.fid
          ORDER BY u.id, f.fid" > "$AUS/inhalte/dateien.tsv"

# Text jeder Seite
anzahl_texte=0
if gibt_tabelle node__body; then
  for nid in $(sql "SELECT entity_id FROM $(t node__body) WHERE deleted = 0 AND delta = 0"); do
    sql "SELECT body_value FROM $(t node__body) WHERE entity_id = $nid AND deleted = 0 AND delta = 0 LIMIT 1" \
      > "$AUS/inhalte/node-$nid.html"
    anzahl_texte=$((anzahl_texte + 1))
  done
fi

# Von Seiten verwendete öffentliche Dateien kopieren (private:// bleibt außen vor)
anzahl_dateien=0
while IFS=$'\t' read -r fid uri; do
  [[ "$uri" == public://* ]] || continue
  quelle="$DATEIEN_DIR/${uri#public://}"
  [[ -f "$quelle" ]] || continue
  ziel="$AUS/inhalte/dateien/$fid-$(basename "$quelle")"
  cp -p "$quelle" "$ziel"
  anzahl_dateien=$((anzahl_dateien + 1))
done < <(sql "SELECT DISTINCT f.fid, f.uri FROM $(t file_managed) f
              JOIN $(t file_usage) u ON u.fid = f.fid WHERE u.type = 'node'")

# -------------------------------------------------------------- 3. Bericht
{
  echo "Drupal-Export $(date '+%F %T') – Drupal ${VERSION:-?}, Datenbank $DB_NAME"
  echo
  echo "== Seiten nach Typ (veröffentlicht/gesamt)"
  sql "SELECT type, SUM(status), COUNT(*) FROM $(t node_field_data) WHERE default_langcode=1 GROUP BY type" \
    | awk -F'\t' '{printf "  %-20s %s/%s\n", $1, $2, $3}'
  echo
  echo "== Alle Seiten"
  sql "SELECT n.nid, n.type, IF(n.status=1,'öffentlich','ENTWURF'), DATE(FROM_UNIXTIME(n.created)), n.title
       FROM $(t node_field_data) n WHERE n.default_langcode=1 ORDER BY n.created" \
    | awk -F'\t' '{printf "  %5s  %-12s %-10s %s  %s\n", $1, $2, $3, $4, $5}'
  if [[ -f "$AUS/inhalte/adressen.tsv" ]]; then
    echo
    echo "== Adressen (für Weiterleitungen)"
    tail -n +2 "$AUS/inhalte/adressen.tsv" | awk -F'\t' '{printf "  %-20s -> %s\n", $1, $2}'
  fi
  if [[ -f "$AUS/inhalte/menue.tsv" ]]; then
    echo
    echo "== Menü"
    tail -n +2 "$AUS/inhalte/menue.tsv" | awk -F'\t' '{printf "  %-12s %-30s %s\n", $1, $2, $3}'
  fi
  echo
  echo "== Felder an Seiten (Tabellen node__*)"
  sql "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()
       AND table_name LIKE '$(t node__)%' ORDER BY table_name" | sed 's/^/  /'
  echo
  echo "== Dateien: $(tail -n +2 "$AUS/inhalte/dateien.tsv" | cut -f1 | sort -u | wc -l) insgesamt, $anzahl_dateien von Seiten verwendet und kopiert"
  echo "== Texte:   $anzahl_texte"
  echo "== Benutzerkonten in Drupal: $(sql "SELECT COUNT(*) FROM $(t users_field_data) WHERE uid > 0" 2>/dev/null || echo '?') (werden NICHT exportiert)"
} > "$AUS/uebersicht.txt"

tar -czf "$AUS/inhalte.tar.gz" -C "$AUS" uebersicht.txt inhalte
chmod -R go-rwx "$AUS"

cat "$AUS/uebersicht.txt"
echo
log "Fertig: $AUS"
log "  sicherung/        vollständige Sicherung – aufbewahren, NICHT weitergeben"
log "  inhalte.tar.gz    öffentliche Inhalte + Übersicht – für die Übernahme"
log "Größen: $(du -sh "$AUS/sicherung" | cut -f1) Sicherung, $(du -sh "$AUS/inhalte.tar.gz" | cut -f1) Inhalte"

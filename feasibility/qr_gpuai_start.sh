#!/usr/bin/env bash
# =============================================================================
# QR-MASSENGENERIERUNG auf gpu.ai (oder jeder anderen Linux-Box) - CPU-only.
#
# Nach den Konventionen von gpuai_start.sh aus dem Vollscan-Projekt gebaut:
# alles über Drive (rclone), kein AWS noetig, POD/PODS-Streifen fuer mehrere
# Pods, Positivkontrolle vor dem Fan-out, Kostenuhr-Warnung am Ende.
#
# WICHTIG - anders als beim Vollscan wird die GPU hier NICHT benutzt. Die
# QR-Erzeugung ist reine CPU-Arbeit; auf einer B300 rechnet nur die Host-CPU,
# das Blackwell-Silizium liegt brach. Sinnvoll also nur, wenn der Pod ohnehin
# laeuft oder Credits da sind - sonst ist eine CPU-Instanz ~3-5x guenstiger
# (siehe QR_CODE_MACHBARKEIT.md, Abschnitt 7). Das Skript misst zuerst den
# echten Durchsatz dieser Maschine und zeigt Laufzeit- und Kostenprojektion,
# BEVOR die lange Rechnung beginnt.
#
# Aufruf:   bash qr_gpuai_start.sh [POD] [PODS] [LAUFNAME]
#   1 Pod:  bash qr_gpuai_start.sh
#   2 Pods: Pod A: bash qr_gpuai_start.sh 0 2 qr_20260812
#           Pod B: bash qr_gpuai_start.sh 1 2 qr_20260812
#   Die Pods teilen sich die Daten-Shards im Streifen (Shard i -> Pod i%PODS);
#   jeder Pod ist unabhaengig, es gibt keine Zusammenfuehr-Phase.
#
# Umgebungsvariablen (alle optional):
#   QR_DRIVE_ZIEL   rclone-Ziel, z. B. gdrive:QR_Runs  (leer = nur lokal;
#                   dann bleiben ALLE Artefakte auf der Platte - beim vollen
#                   Datensatz ~0,44 TB!)
#   QR_DATEN        vorhandenes data/-Verzeichnis des Domains-Repos
#                   (sonst wird das Repo geklont, git-lfs-Pull ~4,6 GB)
#   QR_REPO_URL     Klon-Quelle (Standard: tb0hdan/domains)
#   QR_CODES_JE_TASK  Codes je Task/Artefakt (Standard 200000, ~14 min/vCPU)
#   QR_LIMIT_SHARDS   nur die ersten N Shards dieses Pods (Uebungsmodus)
#   QR_TEST_ZEILEN    nur die ersten N Zeilen je Shard (Uebungsmodus)
#   QR_PREIS_H        Maschinenpreis USD/h fuer die Projektion (Standard 7.76)
#
# Wiederaufsetzen: einfach denselben Befehl erneut ausfuehren. Fertige Shards
# (Drive-Marker) werden uebersprungen, fertige Artefakte (lokal oder schon in
# Drive) ebenfalls - ein Abbruch kostet hoechstens einen angefangenen Task.
# =============================================================================
set -uo pipefail

POD="${1:-0}"
PODS="${2:-1}"
LAUFNAME="${3:-qr_$(date +%Y%m%d-%H%M%S)}"
DRIVE_ZIEL="${QR_DRIVE_ZIEL:+${QR_DRIVE_ZIEL}/$LAUFNAME}"
CPT="${QR_CODES_JE_TASK:-200000}"
PREIS_H="${QR_PREIS_H:-7.76}"
NPROC="$(nproc)"
GESAMT_DATENSATZ=1766025618

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPE="$HERE/qr_pipeline.py"
ARBEIT="${QR_ARBEIT:-/workspace/qr-lauf}"
[ -d /workspace ] || ARBEIT="${QR_ARBEIT:-$HOME/qr-lauf}"
OUT="$ARBEIT/out"; LOGS="$ARBEIT/logs"; MARKER="$ARBEIT/marker"
mkdir -p "$OUT" "$LOGS" "$MARKER"

status(){ printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$ARBEIT/STATUS.txt"; }
fail(){ status "ABBRUCH: $*"; final_sync; exit 1; }

final_sync(){
  [ -n "$DRIVE_ZIEL" ] || return 0
  rclone move "$OUT" "$DRIVE_ZIEL/artefakte" --include '*.tar.xz' -q || true
  rclone copy "$ARBEIT/STATUS.txt" "$DRIVE_ZIEL/pod$POD/" -q || true
  rclone copy "$LOGS" "$DRIVE_ZIEL/pod$POD/logs" -q || true
}
trap final_sync EXIT

echo "== Pod $POD von $PODS | Lauf: $LAUFNAME | $NPROC vCPUs | $CPT Codes/Task"
[ -n "$DRIVE_ZIEL" ] && echo "== Ziel: $DRIVE_ZIEL" \
  || echo "== KEIN Drive-Ziel (QR_DRIVE_ZIEL leer) - Artefakte bleiben lokal in $OUT"

# --------------------------------------------------------------------------
status "Werkzeuge pruefen/installieren"
command -v xz >/dev/null || { apt-get update -qq && apt-get install -y -qq xz-utils >/dev/null; }
python3 -c 'import segno' 2>/dev/null || python3 -m pip install -q segno
python3 -c 'import cv2'   2>/dev/null || python3 -m pip install -q opencv-python-headless || true
if [ -n "$DRIVE_ZIEL" ]; then
  command -v rclone >/dev/null || { curl -fsS https://rclone.org/install.sh | bash >/dev/null; }
  rclone lsd "${DRIVE_ZIEL%%:*}:" >/dev/null \
    || fail "rclone.conf fehlt/kaputt (~/.config/rclone/rclone.conf)"
fi
[ -f "$PIPE" ] || fail "qr_pipeline.py fehlt neben diesem Skript"

# --------------------------------------------------------------------------
status "Daten bereitstellen"
if [ -n "${QR_DATEN:-}" ]; then
  DATEN="$QR_DATEN"
else
  DATEN="$ARBEIT/domains/data"
  if [ ! -d "$DATEN" ]; then
    command -v git-lfs >/dev/null || { apt-get update -qq && apt-get install -y -qq git-lfs >/dev/null; }
    status "Klone Domains-Repo (LFS ~4,6 GB - dauert ein paar Minuten)"
    GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 \
      "${QR_REPO_URL:-https://github.com/tb0hdan/domains.git}" "$ARBEIT/domains" \
      || fail "git clone fehlgeschlagen"
    ( cd "$ARBEIT/domains" && git lfs install --skip-smudge && git lfs pull ) \
      || fail "git lfs pull fehlgeschlagen"
  fi
fi
[ -d "$DATEN" ] || fail "Datenverzeichnis $DATEN existiert nicht"

# Shard-Liste: sortiert, dann Streifen fuer diesen Pod (Shard i -> Pod i%PODS)
mapfile -t ALLE < <(find "$DATEN" -name '*.txt.xz' | sort)
SHARDS=(); UEBERSPRUNGEN=0
for i in "${!ALLE[@]}"; do
  [ $(( i % PODS )) -eq "$POD" ] || continue
  # Git-LFS-Zeiger (nicht gepullte Dateien) erkennen und auslassen
  if head -c 40 "${ALLE[$i]}" | grep -q 'git-lfs'; then
    UEBERSPRUNGEN=$((UEBERSPRUNGEN+1)); continue
  fi
  SHARDS+=("${ALLE[$i]}")
done
[ -n "${QR_LIMIT_SHARDS:-}" ] && SHARDS=("${SHARDS[@]:0:$QR_LIMIT_SHARDS}")
[ "${#SHARDS[@]}" -gt 0 ] || fail "keine (gepullten) Shards fuer Pod $POD gefunden"
[ "$UEBERSPRUNGEN" -gt 0 ] && status "WARNUNG: $UEBERSPRUNGEN Shards sind LFS-Zeiger (nicht gepullt) - werden ausgelassen"
status "${#SHARDS[@]} Shards fuer diesen Pod"

# Erledigt-Listen: Drive-Artefakte + Drive-Marker (Wiederaufsetzen)
DONE_ART="$ARBEIT/done_artefakte.txt"; DONE_MARK="$ARBEIT/done_marker.txt"
refresh_done(){
  if [ -n "$DRIVE_ZIEL" ]; then
    rclone lsf "$DRIVE_ZIEL/artefakte" 2>/dev/null > "$DONE_ART" || : > "$DONE_ART"
    rclone lsf "$DRIVE_ZIEL/marker"    2>/dev/null > "$DONE_MARK" || : > "$DONE_MARK"
  else : > "$DONE_ART"; : > "$DONE_MARK"; fi
}
refresh_done
art_fertig(){ [ -f "$OUT/$1" ] || grep -qxF "$1" "$DONE_ART"; }

# Hintergrund-Verschieber: fertige Artefakte alle 120 s nach Drive
# (atomar: die Pipeline schreibt .tmp und benennt erst am Ende um)
MOVER=""
if [ -n "$DRIVE_ZIEL" ]; then
  ( while :; do
      rclone move "$OUT" "$DRIVE_ZIEL/artefakte" --include '*.tar.xz' -q || true
      sleep 120
    done ) & MOVER=$!
  trap '[ -n "$MOVER" ] && kill "$MOVER" 2>/dev/null; final_sync' EXIT
fi

# --------------------------------------------------------------------------
# Ein Task: Pipeline aufrufen, Log ablegen
task_lauf(){ # $1=input $2=taskcount $3=index $4=lines $5=prefix
  python3 "$PIPE" run --input "$1" --output-dir "$OUT" --task-count "$2" \
    --task-index "$3" --total-lines "$4" --prefix "$5" \
    >> "$LOGS/$5-$(printf '%05d' "$3").log" 2>&1
}
export -f task_lauf; export PIPE OUT LOGS

PC_OFFEN=1   # Positivkontrolle: erster Task laeuft allein und wird verifiziert
for SHARD in "${SHARDS[@]}"; do
  PREFIX="$(basename "$SHARD" .txt.xz)"
  grep -qxF "$PREFIX.FERTIG" "$DONE_MARK" && { status "$PREFIX: schon fertig (Marker)"; continue; }
  [ -f "$MARKER/$PREFIX.FERTIG" ] && { status "$PREFIX: schon fertig (lokal)"; continue; }

  TMP="$ARBEIT/$PREFIX.txt"
  xz -dc "$SHARD" > "$TMP" || fail "$PREFIX: xz-Entpacken fehlgeschlagen"
  [ -n "${QR_TEST_ZEILEN:-}" ] && { head -n "$QR_TEST_ZEILEN" "$TMP" > "$TMP.k" && mv "$TMP.k" "$TMP"; }
  LINES="$(wc -l < "$TMP")"
  [ "$LINES" -eq 0 ] && { rm -f "$TMP"; touch "$MARKER/$PREFIX.FERTIG"; continue; }
  T=$(( (LINES + CPT - 1) / CPT ))

  # ---- Positivkontrolle + Projektion (einmal, vor dem Fan-out) ----
  if [ "$PC_OFFEN" -eq 1 ]; then
    status "Positivkontrolle: $PREFIX Task 0 laeuft allein"
    task_lauf "$TMP" "$T" 0 "$LINES" "$PREFIX" || fail "Positivkontrolle: Task 0 abgebrochen"
    ART0="$OUT/$PREFIX-00000.tar.xz"
    python3 "$PIPE" verify "$ART0" --sample 25 > "$LOGS/pc_verify.json" 2>&1 \
      || fail "Positivkontrolle: Verifikation gescheitert (siehe logs/pc_verify.json)"
    RATE="$(grep -h '"event": "done"' "$LOGS/$PREFIX-00000.log" | tail -1 \
            | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["codes_per_sec"])')"
    status "Positivkontrolle bestanden - $RATE Codes/s je Prozess"
    python3 - "$RATE" "$NPROC" "$GESAMT_DATENSATZ" "$PREIS_H" <<'PY'
import sys
rate, nproc, total, preis = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
flotte = rate * nproc * 0.93          # gemessener Parallelisierungsverlust ~7 %
std = total / flotte / 3600
print(f"          PROJEKTION dieser Maschine ({nproc} vCPUs):")
print(f"          {flotte:,.0f} Codes/s -> Gesamtdatensatz in ~{std:.1f} h "
      f"-> ~{std*preis:,.0f} USD bei {preis} USD/h")
print(f"          (Zum Vergleich: AWS-Spot-Flotte ~26 USD, s. Abschnitt 7 der Doku.)")
PY
    PC_OFFEN=0
  fi

  # ---- Fan-out mit bis zu 3 Runden (Muster aus dem Vollscan-Runner) ----
  for RUNDE in 1 2 3; do
    refresh_done
    JOBS="$ARBEIT/jobs.txt"; : > "$JOBS"
    for (( i=0; i<T; i++ )); do
      art_fertig "$PREFIX-$(printf '%05d' "$i").tar.xz" || echo "$i" >> "$JOBS"
    done
    [ -s "$JOBS" ] || break
    status "$PREFIX: Runde $RUNDE - $(wc -l < "$JOBS")/$T Tasks offen, $NPROC parallel"
    xargs -a "$JOBS" -P "$NPROC" -I{} bash -c \
      'task_lauf "$1" "$2" "$3" "$4" "$5"' _ "$TMP" "$T" {} "$LINES" "$PREFIX" || true
  done
  refresh_done
  OFFEN=0
  for (( i=0; i<T; i++ )); do
    art_fertig "$PREFIX-$(printf '%05d' "$i").tar.xz" || OFFEN=$((OFFEN+1))
  done
  [ "$OFFEN" -eq 0 ] || fail "$PREFIX: nach 3 Runden noch $OFFEN Tasks offen (Logs in $LOGS)"

  rm -f "$TMP"
  touch "$MARKER/$PREFIX.FERTIG"
  [ -n "$DRIVE_ZIEL" ] && rclone copyto "$MARKER/$PREFIX.FERTIG" \
      "$DRIVE_ZIEL/marker/$PREFIX.FERTIG" -q || true
  status "$PREFIX: fertig ($T Artefakte)"
done

[ -n "$MOVER" ] && kill "$MOVER" 2>/dev/null || true
final_sync
echo ""
echo "================================================================="
echo "FERTIG (Pod $POD): alle ${#SHARDS[@]} Shards dieses Pods komplett."
[ -n "$DRIVE_ZIEL" ] && echo "Artefakte in: $DRIVE_ZIEL/artefakte" \
  || echo "Artefakte lokal in: $OUT"
echo ">>> JETZT DEN POD IN DER GPU.AI-OBERFLAECHE STOPPEN (Kostenuhr!) <<<"
echo "================================================================="

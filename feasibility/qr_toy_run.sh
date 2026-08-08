#!/usr/bin/env bash
#
# Trockenübung für den scharfen AWS-Lauf.
#
# Simuliert einen AWS-Batch-Array-Job lokal: mehrere Tasks laufen parallel
# über eine kleine Eingabe, danach werden die Artefakte verifiziert, die
# Idempotenz und der Spot-Abbruch geprobt und die Messwerte auf die volle
# Flotte hochgerechnet.
#
# Sinn der Übung: ein Fehler kostet hier Sekunden — im scharfen Lauf
# 500 vCPU-Stunden.
#
# Aufruf:
#   ./qr_toy_run.sh                                  # 50k synthetische Domains
#   TOY_INPUT=data/austria/domain2multi-at00.txt ./qr_toy_run.sh
#   TOY_DOMAINS=200000 TOY_TASKS=8 ./qr_toy_run.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE="${HERE}/qr_pipeline.py"

TOY_DOMAINS="${TOY_DOMAINS:-50000}"       # Domains in der Übungseingabe
TOY_TASKS="${TOY_TASKS:-4}"               # simulierte Array-Job-Tasks
WORKDIR="${TOY_WORKDIR:-${TMPDIR:-/tmp}/qr-toy-run}"
INPUT="${TOY_INPUT:-}"

# Kennzahlen des scharfen Laufs (siehe QR_CODE_MACHBARKEIT.md)
FULL_DATASET="${FULL_DATASET:-1766025618}"   # Domains im Gesamtdatensatz
FLEET_VCPUS="${FLEET_VCPUS:-512}"            # geplante Flottengröße
VCPU_USD_HOUR="${VCPU_USD_HOUR:-0.03625}"    # c7g on-demand: 0,145 USD / 4 vCPU

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFEHLGESCHLAGEN: %s\033[0m\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
say "0. Vorbedingungen"
python3 -c 'import segno' 2>/dev/null || fail "segno fehlt: pip install segno"
if python3 -c 'import cv2' 2>/dev/null; then
  echo "   Decoder vorhanden — die Verifikation dekodiert echte Codes."
else
  echo "   Kein Decoder (pip install opencv-python-headless) —"
  echo "   die Verifikation prüft dann nur Prüfsummen."
fi
echo "   Arbeitsverzeichnis: ${WORKDIR}"
rm -rf "${WORKDIR}"
mkdir -p "${WORKDIR}/out"

# --------------------------------------------------------------------------
say "1. Übungseingabe vorbereiten"
if [[ -z "${INPUT}" ]]; then
  SHARD="$(find "${HERE}/.." -path '*/data/*' -name '*.txt' -size +1M 2>/dev/null | head -1)"
  INPUT="${WORKDIR}/input.txt"
  if [[ -n "${SHARD}" ]]; then
    echo "   Quelle: ${SHARD} (erste ${TOY_DOMAINS} Zeilen)"
    head -n "${TOY_DOMAINS}" "${SHARD}" > "${INPUT}"
  else
    echo "   Kein entpackter Shard gefunden — erzeuge synthetische Domains."
    echo "   Für realistische Längen: git lfs pull && xz -dk data/<land>/*.xz"
    python3 - "${INPUT}" "${TOY_DOMAINS}" <<'PY'
import random, sys
path, count = sys.argv[1], int(sys.argv[2])
random.seed(7)
alphabet = "abcdefghijklmnopqrstuvwxyz0123456789-"
tlds = ["at", "de", "com", "net", "org", "io"]
with open(path, "w") as handle:
    for i in range(count):
        label = "".join(random.choices(alphabet, k=random.randint(4, 24)))
        handle.write(f"{label.strip('-') or 'x'}{i}.{random.choice(tlds)}\n")
PY
  fi
fi
TOTAL_LINES="$(wc -l < "${INPUT}")"
echo "   Eingabe: ${INPUT} (${TOTAL_LINES} Zeilen)"

# --------------------------------------------------------------------------
say "2. Array-Job simulieren: ${TOY_TASKS} Tasks parallel"
WALL_START="$(date +%s.%N)"
pids=()
for ((i = 0; i < TOY_TASKS; i++)); do
  # AWS_BATCH_JOB_ARRAY_INDEX setzt Batch im scharfen Lauf genauso.
  AWS_BATCH_JOB_ARRAY_INDEX="${i}" python3 "${PIPELINE}" run \
    --input "${INPUT}" --output-dir "${WORKDIR}/out" \
    --task-count "${TOY_TASKS}" --total-lines "${TOTAL_LINES}" \
    > "${WORKDIR}/task-${i}.log" 2>&1 &
  pids+=($!)
done
for pid in "${pids[@]}"; do
  wait "${pid}" || fail "ein Task ist abgebrochen — siehe ${WORKDIR}/task-*.log"
done
WALL="$(python3 -c "print(f'{$(date +%s.%N) - ${WALL_START}:.2f}')")"
echo "   Alle ${TOY_TASKS} Tasks fertig in ${WALL}s Wanduhrzeit."

PRODUCED="$(find "${WORKDIR}/out" -name '*.tar.xz' | wc -l)"
[[ "${PRODUCED}" -eq "${TOY_TASKS}" ]] \
  || fail "${PRODUCED} Artefakte statt ${TOY_TASKS}"
find "${WORKDIR}/out" -name '*.tmp' | grep -q . \
  && fail "Reste von .tmp-Dateien — Atomarität verletzt"

# --------------------------------------------------------------------------
say "3. Artefakte verifizieren (Prüfsumme + Decodierung einer Stichprobe)"
for artifact in "${WORKDIR}/out"/*.tar.xz; do
  if OUTPUT="$(python3 "${PIPELINE}" verify "${artifact}" --sample 10)"; then
    STATUS="OK"
  else
    STATUS="PROBLEM"
  fi
  DETAIL="$(printf '%s' "${OUTPUT}" | tr -d ' \n' \
    | grep -o '"checksum_ok":[^,]*,"decoded":"[^"]*"' || true)"
  printf '   %-8s %-22s %s\n' "${STATUS}" "$(basename "${artifact}")" "${DETAIL}"
  [[ "${STATUS}" == "OK" ]] || { printf '%s\n' "${OUTPUT}"; fail "Verifikation"; }
done

# --------------------------------------------------------------------------
say "4. Idempotenz: ein erneuter Lauf darf nichts neu rechnen"
REDO="$(AWS_BATCH_JOB_ARRAY_INDEX=0 python3 "${PIPELINE}" run \
  --input "${INPUT}" --output-dir "${WORKDIR}/out" \
  --task-count "${TOY_TASKS}" --total-lines "${TOTAL_LINES}" 2>&1)"
grep -q '"event": "skip"' <<<"${REDO}" \
  || fail "Task 0 hat erneut gerechnet statt zu überspringen"
echo "   Task 0 übersprungen — ein Retry nach Teilausfall kostet nichts."

# --------------------------------------------------------------------------
say "5. Spot-Abbruch proben (SIGTERM mitten im Lauf)"
INTERRUPT_DIR="${WORKDIR}/interrupted"
AWS_BATCH_JOB_ARRAY_INDEX=0 python3 "${PIPELINE}" run \
  --input "${INPUT}" --output-dir "${INTERRUPT_DIR}" \
  --task-count 1 --total-lines "${TOTAL_LINES}" \
  > "${WORKDIR}/interrupt.log" 2>&1 &
VICTIM=$!
python3 -c 'import time; time.sleep(2)'
if kill -0 "${VICTIM}" 2>/dev/null; then
  kill -TERM "${VICTIM}"
  set +e; wait "${VICTIM}"; RC=$?; set -e
  [[ "${RC}" -eq 75 ]] \
    || fail "Exit-Code ${RC} statt 75 (EX_TEMPFAIL) — Batch plante nicht neu ein"
  grep -q '"event": "interrupted"' "${WORKDIR}/interrupt.log" \
    || fail "Abbruch wurde nicht protokolliert"
  find "${INTERRUPT_DIR}" -name '*.tar.xz' | grep -q . \
    && fail "halbes Artefakt überlebt — ein Retry erzeugte Datenmüll"
  find "${INTERRUPT_DIR}" -name '*.tmp' | grep -q . \
    && fail ".tmp-Datei nicht aufgeräumt"
  echo "   SIGTERM → Exit 75, kein halbes Artefakt, kein .tmp-Rest."
  AWS_BATCH_JOB_ARRAY_INDEX=0 python3 "${PIPELINE}" run \
    --input "${INPUT}" --output-dir "${INTERRUPT_DIR}" \
    --task-count 1 --total-lines "${TOTAL_LINES}" > /dev/null 2>&1 \
    || fail "Wiederholung nach Abbruch schlug fehl"
  python3 "${PIPELINE}" verify "${INTERRUPT_DIR}"/*.tar.xz --sample 5 > /dev/null \
    || fail "Artefakt nach Wiederholung ist defekt"
  echo "   Wiederholung liefert ein vollständiges, verifiziertes Artefakt."
else
  echo "   Task war vor dem Signal fertig — für die Probe TOY_DOMAINS erhöhen."
fi

# --------------------------------------------------------------------------
say "6. Bilanz und Hochrechnung auf den scharfen Lauf"
python3 "${PIPELINE}" report --log-dir "${WORKDIR}" --wall "${WALL}" \
  --expect-tasks "${TOY_TASKS}" --expect-lines "${TOTAL_LINES}" \
  --fleet-vcpus "${FLEET_VCPUS}" --dataset-size "${FULL_DATASET}" \
  --usd-per-vcpu-hour "${VCPU_USD_HOUR}" \
  || fail "Bilanz stimmt nicht — nicht jede Eingabezeile wurde verarbeitet"

say "Probelauf bestanden"
echo "Artefakte und Logs liegen in ${WORKDIR} — aufräumen mit:"
echo "  rm -rf ${WORKDIR}"

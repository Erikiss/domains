#!/usr/bin/env python3
"""QR-Massengenerierung: Worker-Skript für einen Array-Job-Task.

Ein Prozess = ein Task = ein Artefakt. Die Parallelität liefert der
Orchestrator (AWS Batch Array Job, lokal simuliert von qr_toy_run.sh), nicht
dieses Skript — genau so läuft es auch im scharfen Lauf.

Eigenschaften, die den scharfen Lauf überlebensfähig machen:

* **Idempotent** — ein fertiges Artefakt wird nicht neu berechnet; ein Retry
  nach Abbruch wiederholt den Task sauber von vorn.
* **Atomar** — geschrieben wird in eine `.tmp`-Datei, die erst nach
  vollständigem Durchlauf umbenannt wird. Es gibt keine halben Artefakte.
* **Spot-fest** — SIGTERM (Spot-Interruption, 2 Minuten Vorlauf) wird
  abgefangen, der Task räumt auf und beendet sich mit Code 75 (EX_TEMPFAIL),
  woraufhin der Orchestrator ihn neu einplant.
* **Gebündelt** — Ausgabe ist ein `tar.xz` statt Millionen Einzeldateien.
  Das vermeidet die S3-Request-Kostenfalle und den Inode-Overhead.
* **Selbstbeschreibend** — jedes Artefakt enthält `_manifest.json` mit
  Kennzahlen, Prüfsumme und Parametern.

Beispiele:

    # Task 3 von 16 über einen Shard, Ausgabe nach ./out
    python3 qr_pipeline.py run --input domains.txt --task-index 3 \\
        --task-count 16 --output-dir out

    # Auf AWS Batch: --task-index entfällt, kommt aus der Umgebung
    python3 qr_pipeline.py run --input domains.txt --task-count 16 \\
        --output-dir /mnt/out

    # Artefakt stichprobenartig dekodieren und gegen das Manifest prüfen
    python3 qr_pipeline.py verify out/qr-00003.tar.xz --sample 50
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import os
import signal
import sys
import tarfile
import time
from pathlib import Path

import segno

# Exit-Code für "temporärer Fehler, bitte erneut einplanen" (sysexits.h).
EX_TEMPFAIL = 75

# Bei der Verifikation um das Bild gelegter weißer Rand (Pixel). Die von der
# Norm geforderte Ruhezone von 4 Modulen ist spec-konform und für echte
# Scanner ausreichend, OpenCVs Detektor brauchte im Test aber mehr Weißraum.
# Gepolstert wird nur die Prüfkopie, das gespeicherte Artefakt bleibt
# unverändert.
VERIFY_PAD_PX = 32

_interrupted = False


def _handle_termination(signum, _frame):
    """Spot-Interruption/SIGTERM: Flag setzen, Hauptschleife räumt auf."""
    global _interrupted
    _interrupted = True
    print(json.dumps({"event": "signal", "signal": signum,
                      "action": "draining"}), flush=True)


def normalize_domain(raw: bytes) -> str | None:
    """Domain-Zeile zu einem ASCII-Hostnamen normalisieren.

    Gibt None zurück, wenn die Zeile unbrauchbar ist (defekte Kodierung,
    nicht IDNA-kodierbar). Der Datensatz enthält vereinzelt beides; ein
    QR-Code für eine kaputte URL wäre schlimmer als gar keiner.
    """
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    if text.isascii():
        return text
    try:
        return text.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def iter_slice(path: Path, start: int, end: int):
    """Zeilen [start, end) der Datei als normalisierte Domains liefern.

    Streamt die Datei, hält also nur eine Zeile im Speicher. Unbrauchbare
    Zeilen kommen als None durch, damit der Aufrufer Ausschuss zählen kann.
    """
    with open(path, "rb") as handle:
        for line_no, raw in enumerate(handle):
            if line_no < start:
                continue
            if line_no >= end:
                break
            domain = normalize_domain(raw)
            yield domain


def count_lines(path: Path) -> int:
    with open(path, "rb") as handle:
        return sum(1 for _ in handle)


def resolve_task_index(explicit: int | None) -> int:
    """Task-Index aus dem Argument oder der Orchestrator-Umgebung ziehen."""
    if explicit is not None:
        return explicit
    for env_var in ("AWS_BATCH_JOB_ARRAY_INDEX", "SLURM_ARRAY_TASK_ID",
                    "JOB_COMPLETION_INDEX"):
        value = os.environ.get(env_var)
        if value is not None:
            return int(value)
    raise SystemExit(
        "Kein Task-Index: --task-index setzen oder das Skript unter einem "
        "Array-Job laufen lassen (AWS_BATCH_JOB_ARRAY_INDEX)."
    )


def slice_bounds(total: int, task_index: int, task_count: int) -> tuple[int, int]:
    """Zusammenhängenden Bereich für diesen Task berechnen.

    Der Rest wird auf die ersten Tasks verteilt, damit kein Task leer ausgeht
    und die Last gleichmäßig bleibt.
    """
    if not 0 <= task_index < task_count:
        raise SystemExit(f"task-index {task_index} liegt außerhalb von "
                         f"0..{task_count - 1}")
    base, remainder = divmod(total, task_count)
    start = task_index * base + min(task_index, remainder)
    end = start + base + (1 if task_index < remainder else 0)
    return start, end


def run(args: argparse.Namespace) -> int:
    task_index = resolve_task_index(args.task_index)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"{args.prefix}-{task_index:05d}.tar.xz"
    staging = artifact.with_suffix(".tmp")

    if artifact.exists() and not args.force:
        print(json.dumps({"event": "skip", "task": task_index,
                          "artifact": str(artifact),
                          "reason": "already complete"}), flush=True)
        return 0

    signal.signal(signal.SIGTERM, _handle_termination)
    signal.signal(signal.SIGINT, _handle_termination)

    total = args.total_lines or count_lines(Path(args.input))
    start, end = slice_bounds(total, task_index, args.task_count)
    print(json.dumps({"event": "start", "task": task_index,
                      "lines": [start, end], "artifact": str(artifact)}),
          flush=True)

    versions: dict[int, int] = {}
    payload_digest = hashlib.sha256()
    written = skipped = 0
    began = time.perf_counter()
    last_report = began

    staging.unlink(missing_ok=True)
    try:
        with lzma.open(staging, "wb", preset=args.xz_preset) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for domain in iter_slice(Path(args.input), start, end):
                    if _interrupted:
                        raise KeyboardInterrupt
                    if domain is None:
                        skipped += 1
                        continue

                    url = f"{args.scheme}://{domain}"
                    # micro=False ist Pflicht: für sehr kurze URLs würde segno
                    # sonst einen Micro-QR-Code (M1-M4) erzeugen, den viele
                    # Kamera-Apps nicht lesen.
                    qr = segno.make(url, error=args.ecc, boost_error=False,
                                    micro=False)
                    buffer = io.BytesIO()
                    qr.save(buffer, kind=args.format, scale=args.scale,
                            border=args.border)
                    blob = buffer.getvalue()

                    versions[qr.version] = versions.get(qr.version, 0) + 1
                    payload_digest.update(blob)

                    info = tarfile.TarInfo(f"{domain}.{args.format}")
                    info.size = len(blob)
                    info.mtime = 0  # reproduzierbare Artefakte
                    tar.addfile(info, io.BytesIO(blob))
                    written += 1

                    now = time.perf_counter()
                    if now - last_report >= args.report_interval:
                        print(json.dumps({
                            "event": "progress", "task": task_index,
                            "written": written,
                            "codes_per_sec": round(written / (now - began)),
                        }), flush=True)
                        last_report = now

                manifest = {
                    "task_index": task_index,
                    "task_count": args.task_count,
                    "input": str(args.input),
                    "line_range": [start, end],
                    "written": written,
                    "skipped": skipped,
                    "qr_versions": dict(sorted(versions.items())),
                    "payload_sha256": payload_digest.hexdigest(),
                    "params": {
                        "scheme": args.scheme, "format": args.format,
                        "ecc": args.ecc, "scale": args.scale,
                        "border": args.border, "xz_preset": args.xz_preset,
                    },
                }
                blob = json.dumps(manifest, indent=2).encode()
                info = tarfile.TarInfo("_manifest.json")
                info.size = len(blob)
                info.mtime = 0
                tar.addfile(info, io.BytesIO(blob))
    except KeyboardInterrupt:
        staging.unlink(missing_ok=True)
        print(json.dumps({"event": "interrupted", "task": task_index,
                          "written_before_abort": written,
                          "action": "artifact discarded, task is retryable"}),
              flush=True)
        return EX_TEMPFAIL
    except Exception:
        staging.unlink(missing_ok=True)
        raise

    # Erst jetzt wird das Artefakt sichtbar — vorher gibt es nichts Halbes.
    os.replace(staging, artifact)

    elapsed = time.perf_counter() - began
    print(json.dumps({
        "event": "done", "task": task_index, "written": written,
        "skipped": skipped, "seconds": round(elapsed, 2),
        "codes_per_sec": round(written / elapsed) if elapsed else None,
        "artifact_bytes": artifact.stat().st_size,
        "bytes_per_code": round(artifact.stat().st_size / written, 1)
        if written else None,
    }), flush=True)
    return 0


def _decode(png_bytes: bytes) -> str | None:
    """QR-Code aus PNG-Bytes dekodieren; None, wenn kein Decoder da ist."""
    try:
        import cv2
        import numpy
        from PIL import Image
    except ImportError:
        return None
    image = numpy.array(Image.open(io.BytesIO(png_bytes)).convert("L"))
    padded = numpy.pad(image, VERIFY_PAD_PX, constant_values=255)
    value, _, _ = cv2.QRCodeDetector().detectAndDecode(padded)
    return value


def verify(args: argparse.Namespace) -> int:
    """Artefakt gegen sein Manifest prüfen und Stichprobe dekodieren."""
    artifact = Path(args.artifact)
    digest = hashlib.sha256()
    manifest = None
    members = []

    with tarfile.open(artifact, mode="r:xz") as tar:
        for info in tar:
            data = tar.extractfile(info).read()
            if info.name == "_manifest.json":
                manifest = json.loads(data)
                continue
            digest.update(data)
            if len(members) < args.sample:
                members.append((info.name, data))

    if manifest is None:
        print(f"FEHLER: {artifact} enthält kein _manifest.json")
        return 1

    problems = []
    if digest.hexdigest() != manifest["payload_sha256"]:
        problems.append("Prüfsumme der Nutzdaten weicht vom Manifest ab")

    scheme = manifest["params"]["scheme"]
    suffix = "." + manifest["params"]["format"]
    decoded_ok = decoded_tested = 0
    for name, data in members:
        expected = f"{scheme}://{name[: -len(suffix)]}"
        value = _decode(data)
        if value is None:
            break  # kein Decoder installiert
        decoded_tested += 1
        if value == expected:
            decoded_ok += 1
        else:
            problems.append(f"{name}: dekodiert zu {value!r}, "
                            f"erwartet {expected!r}")

    print(json.dumps({
        "artifact": str(artifact),
        "written": manifest["written"],
        "skipped": manifest["skipped"],
        "checksum_ok": digest.hexdigest() == manifest["payload_sha256"],
        "decoded": f"{decoded_ok}/{decoded_tested}" if decoded_tested
        else "übersprungen (kein Decoder: pip install opencv-python-headless)",
        "qr_versions": manifest["qr_versions"],
        "problems": problems,
    }, indent=2, ensure_ascii=False))
    return 1 if problems else 0


def report(args: argparse.Namespace) -> int:
    """Task-Logs auswerten, Bilanz prüfen und auf die Flotte hochrechnen."""
    rows = []
    for log in sorted(Path(args.log_dir).glob("*.log")):
        for line in log.read_text().splitlines():
            if '"event": "done"' in line:
                rows.append(json.loads(line))

    if not rows:
        print(f"FEHLER: keine abgeschlossenen Tasks in {args.log_dir}")
        return 1

    for row in sorted(rows, key=lambda r: r["task"]):
        print("   Task {task:>2}: {written:>8} Codes  {seconds:>7.2f}s  "
              "{codes_per_sec:>5} Codes/s  {bytes_per_code:>6.1f} B/Code"
              .format(**row))

    written = sum(row["written"] for row in rows)
    skipped = sum(row["skipped"] for row in rows)
    per_task_rate = sum(row["codes_per_sec"] for row in rows) / len(rows)
    bytes_per_code = sum(row["artifact_bytes"] for row in rows) / written

    problems = []
    if args.expect_tasks is not None and len(rows) != args.expect_tasks:
        problems.append(f"{len(rows)} Tasks fertig, erwartet {args.expect_tasks}")
    if args.expect_lines is not None and written + skipped != args.expect_lines:
        problems.append(f"Zeilenbilanz: {written} verarbeitet + {skipped} "
                        f"übersprungen != {args.expect_lines} Eingabezeilen")

    print(f"\n   Summe: {written} Codes, {skipped} übersprungen, "
          f"{len(rows)} Artefakte")
    if args.wall:
        print(f"   Wanduhr der Übung: {args.wall:.2f}s "
              f"({written / args.wall:,.0f} Codes/s auf {len(rows)} Tasks)")

    fleet_rate = per_task_rate * args.fleet_vcpus
    hours = args.dataset_size / fleet_rate / 3600
    artifacts = -(-args.dataset_size // args.codes_per_artifact)
    print(f"\n   Hochrechnung auf {args.fleet_vcpus} vCPUs "
          f"(gemessen: {per_task_rate:.0f} Codes/s je Task):")
    print(f"     Durchsatz:      {fleet_rate:>12,.0f} Codes/s")
    print(f"     Gesamtdatensatz ({args.dataset_size:,} Domains): "
          f"{hours:.1f} h Wanduhr")
    print(f"     Rechenkosten:   {args.fleet_vcpus * hours * args.usd_per_vcpu_hour:>12,.0f} USD")
    print(f"     Ausgabemenge:   {args.dataset_size * bytes_per_code / 1e12:>12,.2f} TB "
          f"in {artifacts:,} Artefakten")
    print(f"     S3-PUT-Kosten:  {artifacts / 1000 * 0.005:>12,.2f} USD "
          f"(gebündelt; einzeln wären es "
          f"{args.dataset_size / 1000 * 0.005:,.0f} USD)")

    for problem in problems:
        print(f"\nFEHLER: {problem}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="QR-Massengenerierung für Array-Jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Beispiele:")[-1],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    runner = sub.add_parser("run", help="einen Array-Task abarbeiten")
    runner.add_argument("--input", required=True,
                        help="Textdatei mit einer Domain pro Zeile")
    runner.add_argument("--output-dir", required=True)
    runner.add_argument("--task-count", type=int, required=True,
                        help="Gesamtzahl der Tasks im Array-Job")
    runner.add_argument("--task-index", type=int, default=None,
                        help="Index dieses Tasks; ohne Angabe aus "
                             "AWS_BATCH_JOB_ARRAY_INDEX")
    runner.add_argument("--total-lines", type=int, default=None,
                        help="Zeilenzahl der Eingabe (spart den Vorlauf-Scan)")
    runner.add_argument("--prefix", default="qr")
    runner.add_argument("--scheme", default="https")
    runner.add_argument("--format", default="png", choices=["png", "svg"])
    runner.add_argument("--ecc", default="m", choices=["l", "m", "q", "h"])
    runner.add_argument("--scale", type=int, default=4)
    runner.add_argument("--border", type=int, default=4,
                        help="Ruhezone in Modulen (Norm: 4)")
    runner.add_argument("--xz-preset", type=int, default=1,
                        help="xz-Kompressionsstufe (1 = schnell, reicht)")
    runner.add_argument("--report-interval", type=float, default=30.0)
    runner.add_argument("--force", action="store_true",
                        help="vorhandenes Artefakt überschreiben")
    runner.set_defaults(func=run)

    checker = sub.add_parser("verify", help="Artefakt prüfen")
    checker.add_argument("artifact")
    checker.add_argument("--sample", type=int, default=25,
                         help="wie viele Codes dekodiert werden")
    checker.set_defaults(func=verify)

    reporter = sub.add_parser("report",
                              help="Task-Logs auswerten und hochrechnen")
    reporter.add_argument("--log-dir", required=True)
    reporter.add_argument("--wall", type=float, default=None,
                          help="Wanduhrzeit des Übungslaufs in Sekunden")
    reporter.add_argument("--expect-tasks", type=int, default=None)
    reporter.add_argument("--expect-lines", type=int, default=None)
    reporter.add_argument("--fleet-vcpus", type=int, default=512)
    reporter.add_argument("--dataset-size", type=int, default=1_766_025_618)
    reporter.add_argument("--codes-per-artifact", type=int, default=200_000,
                          help="Codes je Task/Artefakt. Klein halten: ein "
                               "Spot-Abbruch kostet höchstens einen Task. "
                               "AWS Batch deckelt Array-Jobs bei 10.000.")
    reporter.add_argument("--usd-per-vcpu-hour", type=float, default=0.03625,
                          help="c7g on-demand: 0,145 USD je 4 vCPU")
    reporter.set_defaults(func=report)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

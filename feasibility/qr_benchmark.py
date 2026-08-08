#!/usr/bin/env python3
"""Empirical benchmark: QR code generation from URLs (Domains Project dataset).

Measures per-code generation time and output size for several libraries and
output formats, single-core and multi-core, using real domains as input.
Prints a JSON report to stdout.
"""
import io
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time

SAMPLE_FILE = os.environ.get(
    "DOMAINS_SAMPLE",
    "/tmp/claude-0/-home-user-domains/bb66d645-c723-58a5-9861-b3d1c8b2f14b/scratchpad/domains-sample.txt",
)
N_TIMING = 2000          # codes per timing run
N_MULTICORE = 40000      # codes for the multi-core throughput run
RNG_SEED = 42


def load_urls():
    with open(SAMPLE_FILE, "r", encoding="utf-8", errors="replace") as f:
        domains = [line.strip() for line in f if line.strip()]
    random.seed(RNG_SEED)
    sample = random.sample(domains, min(200000, len(domains)))
    urls = ["https://" + d for d in sample]
    lengths = [len(u) for u in urls]
    stats = {
        "n_domains_in_file": len(domains),
        "url_len_mean": round(statistics.mean(lengths), 1),
        "url_len_median": statistics.median(lengths),
        "url_len_p95": sorted(lengths)[int(0.95 * len(lengths))],
        "url_len_max": max(lengths),
    }
    return urls, stats


def bench(fn, urls, n):
    """Time fn over n urls; return per-code microseconds and avg output bytes."""
    subset = urls[:n]
    sizes = []
    t0 = time.perf_counter()
    for u in subset:
        out = fn(u)
        if out is not None:
            sizes.append(out)
    dt = time.perf_counter() - t0
    return {
        "per_code_us": round(dt / len(subset) * 1e6, 1),
        "codes_per_sec_1core": round(len(subset) / dt),
        "avg_output_bytes": round(statistics.mean(sizes)) if sizes else None,
    }


def segno_matrix(u):
    import segno
    segno.make(u, error="m")
    return None


def segno_png(u):
    import segno
    buf = io.BytesIO()
    segno.make(u, error="m").save(buf, kind="png", scale=4)
    return buf.getbuffer().nbytes


def segno_svg(u):
    import segno
    buf = io.BytesIO()
    segno.make(u, error="m").save(buf, kind="svg", scale=4)
    return buf.getbuffer().nbytes


def qrcode_pil_png(u):
    import qrcode
    buf = io.BytesIO()
    qrcode.make(u).save(buf, format="PNG")
    return buf.getbuffer().nbytes


def worker_chunk(chunk):
    import segno
    t0 = time.perf_counter()
    for u in chunk:
        buf = io.BytesIO()
        segno.make(u, error="m").save(buf, kind="png", scale=4)
    return time.perf_counter() - t0, len(chunk)


def multicore_bench(urls, n, ncpu):
    subset = urls[:n]
    chunks = [subset[i::ncpu] for i in range(ncpu)]
    t0 = time.perf_counter()
    with mp.Pool(ncpu) as pool:
        pool.map(worker_chunk, chunks)
    wall = time.perf_counter() - t0
    return {
        "n_codes": n,
        "n_procs": ncpu,
        "wall_seconds": round(wall, 2),
        "codes_per_sec_total": round(n / wall),
    }


def qr_version_info(urls):
    import segno
    from collections import Counter
    versions = Counter()
    for u in urls[:5000]:
        versions[segno.make(u, error="m").version] += 1
    return dict(sorted(versions.items()))


def main():
    urls, url_stats = load_urls()
    ncpu = os.cpu_count() or 1
    report = {
        "environment": {
            "python": sys.version.split()[0],
            "cpus": ncpu,
        },
        "input": url_stats,
        "timing_n_codes": N_TIMING,
        "results": {
            "segno_matrix_only": bench(segno_matrix, urls, N_TIMING),
            "segno_png_scale4": bench(segno_png, urls, N_TIMING),
            "segno_svg": bench(segno_svg, urls, N_TIMING),
            "qrcode_pil_png": bench(qrcode_pil_png, urls, N_TIMING),
        },
        "multicore_segno_png": multicore_bench(urls, N_MULTICORE, ncpu),
        "qr_versions_ecc_M": qr_version_info(urls),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

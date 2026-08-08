#!/usr/bin/env python3
"""Cross-validate ISO/IEC 18004 byte-mode capacities with two independent
implementations (segno, qrcode).

For each (version, ECC) pair the largest byte payload that still fits is
determined per library via binary search and compared against the table in
QR_CODE_MACHBARKEIT.md. Exits non-zero on any disagreement.
"""
import sys

import qrcode
import qrcode.constants
import segno
from qrcode.exceptions import DataOverflowError

EXPECTED = {
    1: {"L": 17, "M": 14, "Q": 11, "H": 7},
    2: {"L": 32, "M": 26, "Q": 20, "H": 14},
    3: {"L": 53, "M": 42, "Q": 32, "H": 24},
    4: {"L": 78, "M": 62, "Q": 46, "H": 34},
    5: {"L": 106, "M": 84, "Q": 60, "H": 44},
    8: {"L": 192, "M": 152, "Q": 108, "H": 84},
    40: {"L": 2953, "M": 2331, "Q": 1663, "H": 1273},
}

QRCODE_ECC = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}


def fits_segno(n, version, ecc):
    try:
        segno.make(b"a" * n, mode="byte", error=ecc.lower(),
                   version=version, boost_error=False)
        return True
    except (segno.DataOverflowError, ValueError):
        return False


def fits_qrcode(n, version, ecc):
    qr = qrcode.QRCode(version=version, error_correction=QRCODE_ECC[ecc])
    qr.add_data(b"a" * n)
    try:
        qr.make(fit=False)
        return True
    except (DataOverflowError, ValueError):
        return False


def max_bytes(fits, version, ecc):
    lo, hi = 0, 3500
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid, version, ecc):
            lo = mid
        else:
            hi = mid - 1
    return lo


def module_count(version):
    return segno.make(b"a", mode="byte", error="l", version=version,
                      boost_error=False).symbol_size(scale=1, border=0)[0]


def main():
    failures = 0
    print(f"{'Version':>7} {'Module':>9} {'ECC':>4} {'erwartet':>9} "
          f"{'segno':>7} {'qrcode':>7}")
    for version, row in EXPECTED.items():
        modules = module_count(version)
        expected_modules = 21 + 4 * (version - 1)
        if modules != expected_modules:
            print(f"FEHLER: Version {version}: {modules} Module, "
                  f"erwartet {expected_modules}")
            failures += 1
        for ecc, expected in row.items():
            got_segno = max_bytes(fits_segno, version, ecc)
            got_qrcode = max_bytes(fits_qrcode, version, ecc)
            mark = "" if got_segno == got_qrcode == expected else "  <-- FEHLER"
            if mark:
                failures += 1
            print(f"{version:>7} {modules:>4}x{modules:<4} {ecc:>4} "
                  f"{expected:>9} {got_segno:>7} {got_qrcode:>7}{mark}")
    if failures:
        print(f"\n{failures} Abweichung(en) gefunden.")
        return 1
    print("\nAlle Werte von beiden Bibliotheken bestätigt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

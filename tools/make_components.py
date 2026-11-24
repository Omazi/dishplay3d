#!/usr/bin/env python3
"""Write compliance/components.csv: one row per component, with its version, the licence it declares and the
project's decision.   python tools/make_components.py [--check]

The rows of the calculator's Python packages come from backend/requirements.lock and from the metadata of the
packages as installed (run it with backend/.venv, where exactly the lock is installed). The few rows that are
not Python packages (Apple's SDKs, the FFmpeg inside the OpenCV wheel, the depth model's weights, build tools)
are kept from the file as it is, or added from MANUAL below.

The project's rule: permissive licences only (MIT, BSD, Apache-2.0 or equivalent). MPL-2.0 is tolerated for
packages that are neither modified nor redistributed. Anything else must be decided by hand: the tool writes
"TO DECIDE" and the test fails.
"""
from __future__ import annotations

import csv
import importlib.metadata as md
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "compliance" / "components.csv"
LOCK = ROOT / "backend" / "requirements.lock"
HEADER = ["component", "version", "provenance", "licence (declared metadata)", "usage", "distribution", "decision"]
PYPI = "PyPI wheel"
CALCULATOR_ONLY = "calculator only (not shipped in the iOS app)"
PERMISSIVE = ("mit", "bsd", "apache", "isc", "psf", "python software foundation", "zlib", "hpnd", "unlicense", "cc0", "boost", "bsl-1.0")
OK, TOLERATED, TO_DECIDE = "ok (permissive)", "tolerated (MPL-2.0: neither modified nor redistributed)", "TO DECIDE"

# Components that are not packages of the lock. Added when the file has no row of that name.
MANUAL = [
    ["Depth Anything V2 Small (ONNX weights, onnx-community export)", "revision 4472b73", "downloaded at the calculator's first start, not in the repository",
     "Apache-2.0", "fills what stereo cannot measure", CALCULATOR_ONLY, OK],
    ["GitHub actions: checkout, upload-artifact, setup-python", "pinned by commit", "GitHub", "MIT", "automatic checks only", "not distributed", OK],
]


def locked() -> list[tuple[str, str]]:
    out = []
    for line in LOCK.read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            out.append((name.strip(), version.split(";")[0].strip()))
    return out


def key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(name: str) -> str:
    """The licence the installed package declares: its SPDX expression, else its classifiers, else its licence field."""
    meta = md.distribution(name).metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"].strip()
    classifiers = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    if classifiers:
        return " / ".join(dict.fromkeys(classifiers))
    first = (meta.get("License") or "").strip().splitlines()[0].strip() if (meta.get("License") or "").strip() else ""
    return first if first and first != "UNKNOWN" and len(first) <= 60 else "UNKNOWN"


def family(licence: str) -> str:
    """"permissive", "mpl" (tolerated) or "other", for a declared licence that may combine several."""
    def one(part: str) -> str:
        p = part.strip().lower()
        if any(word in p for word in PERMISSIVE):
            return "permissive"
        return "mpl" if "mpl" in p or "mozilla" in p else "other"

    alternatives = [a for a in re.split(r"\s+OR\s+", licence) if a.strip()]
    best = "other"
    for alt in alternatives:                      # "A OR B": the most permissive alternative may be chosen
        parts = [one(p) for p in re.split(r"\s+AND\s+|\s*/\s*|\s*,\s*", alt) if p.strip()]
        kind = "other" if not parts or "other" in parts else ("mpl" if "mpl" in parts else "permissive")
        if kind == "permissive" or (kind == "mpl" and best == "other"):
            best = kind
        if best == "permissive":
            break
    return best


def decision(licence: str) -> str:
    return {"permissive": OK, "mpl": TOLERATED, "other": TO_DECIDE}[family(licence)]


def build() -> str:
    old = list(csv.reader(io.StringIO(CSV.read_text(), newline=""))) if CSV.exists() else [HEADER]
    kept = {key(r[0]): r for r in old[1:] if len(r) == len(HEADER)}
    rows = []
    for name, version in sorted(locked(), key=lambda nv: key(nv[0])):
        before = kept.get(key(name))
        licence = declared(name)
        known = before is not None and before[2] == PYPI       # what a person wrote about it is kept
        rows.append([before[0] if known else name, version, PYPI, licence, before[4] if known else "transitive",
                     before[5] if known else CALCULATOR_ONLY, decision(licence)])
    names = {key(r[0]) for r in rows}
    manual = [r for r in old[1:] if len(r) == len(HEADER) and r[2] != PYPI]
    manual += [r for r in MANUAL if key(r[0]) not in {key(m[0]) for m in manual}]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n" if CSV.exists() and b"\r\n" in CSV.read_bytes() else "\n")
    w.writerow(HEADER)
    w.writerows(rows + [r for r in manual if key(r[0]) not in names])
    return out.getvalue()


def main() -> None:
    text = build()
    if "--check" in sys.argv:
        if not CSV.exists() or CSV.read_bytes().decode() != text:
            sys.exit("compliance/components.csv is out of date: run backend/.venv/bin/python tools/make_components.py")
        print("inventory up to date")
        return
    CSV.write_bytes(text.encode())
    undecided = [line.split(",")[0] for line in text.splitlines() if line.endswith(TO_DECIDE)]
    print(f"written {CSV} ({len(text.splitlines()) - 1} components)" + (f"; TO DECIDE: {', '.join(undecided)}" if undecided else ""))


if __name__ == "__main__":
    main()

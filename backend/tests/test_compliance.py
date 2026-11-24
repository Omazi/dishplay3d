"""The owner's rule: only components under a permissive licence. The inventory (compliance/components.csv) said
it was complete while three installed packages were missing from it; and a video encoder under GPL was asked
for by the neural trial without appearing anywhere. Both can no longer happen without this file failing."""
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import make_components  # noqa: E402


def rows():
    return list(csv.DictReader(io.StringIO((ROOT / "compliance" / "components.csv").read_text(), newline="")))


def test_the_inventory_is_the_one_made_from_what_is_installed():
    """Every package of backend/requirements.lock has its row, with its version and the licence its installed
    metadata declares; nothing is listed that is no longer installed."""
    assert (ROOT / "compliance" / "components.csv").read_bytes().decode() == make_components.build(), \
        "run backend/.venv/bin/python tools/make_components.py"
    listed = {make_components.key(r["component"]): r for r in rows() if r["provenance"] == make_components.PYPI}
    locked = dict((make_components.key(n), v) for n, v in make_components.locked())
    assert len(locked) > 90
    assert set(listed) == set(locked)
    assert all(listed[k]["version"] == v for k, v in locked.items())


def test_every_component_is_permissive_or_explicitly_tolerated():
    undecided = [r["component"] for r in rows() if "TO DECIDE" in r["decision"] or not r["decision"].strip()]
    assert undecided == [], f"a licence outside the rule needs a decision: {undecided}"
    for r in rows():
        if r["provenance"] != make_components.PYPI:
            continue
        kind = make_components.family(r["licence (declared metadata)"])
        assert kind != "other", r
        assert r["decision"].startswith("tolerated") == (kind == "mpl"), r     # MPL is tolerated, never called permissive
    tolerated = sorted(r["component"] for r in rows() if r["decision"].startswith("tolerated"))
    assert tolerated == ["certifi", "tqdm"]                                     # a third one must be looked at, not waved through


def test_licence_families_are_told_apart():
    f = make_components.family
    for text in ("MIT", "MIT License", "BSD-3-Clause", "3-Clause BSD License", "Apache-2.0", "Apache Software License", "Apache 2.0",
                 "ISC License (ISCL)", "PSF-2.0", "Python Software Foundation License", "MIT-CMU", "MIT-0", "Apache-2.0 OR BSD-3-Clause",
                 "GPL-3.0-only OR MIT", "BSD License / MIT License"):
        assert f(text) == "permissive", text
    for text in ("MPL-2.0", "Mozilla Public License 2.0 (MPL 2.0)", "MPL-2.0 AND MIT"):
        assert f(text) == "mpl", text
    for text in ("GPL-3.0-only", "GNU General Public License v3 (GPLv3)", "AGPL-3.0", "LGPL-2.1-or-later", "CC-BY-NC-4.0", "CC-BY-SA-4.0",
                 "MIT AND GPL-2.0-only", "UNKNOWN", "", "Proprietary", "Stability AI Community License"):
        assert f(text) == "other", text


def test_no_code_asks_for_the_gpl_video_encoder_again():
    """x264 is under GPL and only exists in GPL builds of FFmpeg; imageio-ffmpeg ships such a build."""
    code = [p for folder in ("backend/app", "backend/reconstruction", "tools") for p in (ROOT / folder).glob("*.py")]
    assert len(code) > 30
    for p in code:
        text = p.read_text()
        assert "libx264" not in text and "imageio_ffmpeg" not in text, p
        if p.name != "photo_express.py":          # (its header explains why imageio-ffmpeg is NOT installed)
            assert "imageio-ffmpeg" not in text, p

#!/usr/bin/env python3
"""The app's colour palette in one table.

  python tools/ios_colors.py          write the colour sets of the asset catalog from the table below
  python tools/ios_colors.py --check  verify that every colour named in the Swift code exists in the catalog

Each role has a light and a dark value (0xRRGGBB). The Swift side only knows the role names
(ios/App/DesignSystem/Theme.swift); changing a colour of the app means changing one line here and running
this script. The values are those of the dishplay website (paper, ink, blue).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "ios" / "App" / "Assets.xcassets"

#         role             light     dark
PALETTE = {
    "Canvas":        (0xF8F8F2, 0x0E0F0D),   # behind a whole screen
    "Surface":       (0xFFFFFF, 0x1A1B18),   # cards
    "SurfaceSunken": (0xEDEDE5, 0x262823),   # fields, wells, quiet buttons
    "Stage":         (0x151613, 0x151613),   # the dark stage 3D content sits on, in both appearances
    "TextOnStage":   (0xF8F8F2, 0xF8F8F2),
    "TextPrimary":   (0x252824, 0xF4F4EE),
    "TextSecondary": (0x6B6E66, 0xA5A89F),
    "Hairline":      (0xE2E4DA, 0x2D2F2A),
    "AccentColor":   (0x2254E7, 0x7E99FF),   # the one action colour (also the app's global tint)
    "OnAccent":      (0xFFFFFF, 0x0B0C0A),   # text on a filled action or status colour
    "Good":          (0x2F7150, 0x62CD93),
    "Warn":          (0x9A5B06, 0xF3C552),
    "Bad":           (0xBF3329, 0xFF6F61),
    "LaunchBackground": (0xF8F8F2, 0x0E0F0D),
}
AT_ROOT = {"AccentColor", "LaunchBackground"}   # names the project settings and Info.plist refer to


def _components(rgb: int) -> dict:
    return {"alpha": "1.000", "red": f"{((rgb >> 16) & 255) / 255:.3f}", "green": f"{((rgb >> 8) & 255) / 255:.3f}",
            "blue": f"{(rgb & 255) / 255:.3f}"}


def colorset(light: int, dark: int) -> dict:
    colors = [{"color": {"color-space": "srgb", "components": _components(light)}, "idiom": "universal"}]
    if dark != light:
        colors.append({"appearances": [{"appearance": "luminosity", "value": "dark"}],
                       "color": {"color-space": "srgb", "components": _components(dark)}, "idiom": "universal"})
    return {"colors": colors, "info": {"author": "xcode", "version": 1}}


def write() -> None:
    group = CATALOG / "Colors"
    group.mkdir(parents=True, exist_ok=True)
    (group / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    for name, (light, dark) in PALETTE.items():
        d = (CATALOG if name in AT_ROOT else group) / f"{name}.colorset"
        d.mkdir(parents=True, exist_ok=True)
        (d / "Contents.json").write_text(json.dumps(colorset(light, dark), indent=2) + "\n")
    print(f"{len(PALETTE)} colour sets written under {CATALOG.relative_to(ROOT)}")


def check() -> int:
    on_disk = {p.name.removesuffix(".colorset") for p in CATALOG.rglob("*.colorset")}
    used = set()
    for f in (ROOT / "ios").rglob("*.swift"):
        used |= set(re.findall(r'Color\("([A-Za-z]+)"\)', f.read_text()))
    missing, unused = sorted(used - on_disk), sorted(on_disk - used - AT_ROOT)
    for name in missing:
        print(f"MISSING in the asset catalog: {name}")
    for name in unused:
        print(f"not used by the Swift code: {name}")
    stale = sorted(n for n in on_disk if n not in PALETTE)
    for name in stale:
        print(f"in the catalog but not in the table: {name}")
    print(f"{len(used)} colours used, {len(on_disk)} in the catalog, {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else write())

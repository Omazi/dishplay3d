"""Chooses the simulator of the screen check.

Reads `xcrun simctl list devices available -j` on standard input and prints the identifier of one device.

    pick-simulator.py [ios major version] [device name]

Without arguments: the newest iOS installed and a current standard-size iPhone. With a major version (`18`), the
newest iOS of that version; an empty string means "the newest". With a name (`iPhone 16e`), that model only.
A name that ends with a star (`iPad*`) means any model whose name starts so, an iPad of the usual size first:
the names of the iPads change with each generation. The choice goes to standard error, for the log.
"""
import json
import re
import sys

PREFERRED = ["iPhone 17 Pro", "iPhone 17", "iPhone 16 Pro", "iPhone 16", "iPhone 15 Pro", "iPhone 15"]
# Within a family asked with a star: how the names of the usual sizes start ("iPad (A16)", "iPad Air 11-inch (M3)").
PREFERRED_START = ["iPad (", "iPad Air 11", "iPad Pro 11"]


def main() -> None:
    major = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    wanted = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    family = wanted[:-1] if wanted and wanted.endswith("*") else None
    best = None
    for runtime, entries in json.load(sys.stdin)["devices"].items():
        found = re.search(r"iOS-(\d+)-(\d+)", runtime)
        if not found:
            continue
        version = (int(found.group(1)), int(found.group(2)))
        if major is not None and version[0] != major:
            continue
        for device in entries:
            name = device.get("name", "")
            if not device.get("isAvailable", True):
                continue
            if family is not None:
                if not name.startswith(family):
                    continue
                rank = next((i for i, start in enumerate(PREFERRED_START) if name.startswith(start)), len(PREFERRED_START))
                key = (version, -rank, name)    # the name settles a tie, so that the choice does not depend on the order of the list
            else:
                if (name != wanted) if wanted is not None else (not name.startswith("iPhone")):
                    continue   # not the model asked for; without a wish, only iPhones
                rank = PREFERRED.index(name) if name in PREFERRED else len(PREFERRED)
                key = (version, -rank)
            if best is None or key > best[0]:
                best = (key, device["udid"], f"{name}, iOS {version[0]}.{version[1]}")
    if best is None:
        sys.exit(f"no simulator installed for {wanted or 'an iPhone'}" + (f" with iOS {major}" if major else ""))
    print(best[2], file=sys.stderr)
    print(best[1])


if __name__ == "__main__":
    main()

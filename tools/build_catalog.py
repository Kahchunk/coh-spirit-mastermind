"""Build editor/catalog.json: every name the editor can offer, read from your installed client.

usage: python tools/build_catalog.py ["C:/Users/<you>/AppData/Local/Thunderspy Gaming/Sweet Tea"]

Reads the base bin.pigg, then Rebirth's z_rebirth_bin.pigg on top (Rebirth's copy wins,
same as the game). Nothing in the install is modified.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pigg import bin_source_files, bin_strings, read_pigg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CLIENT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Thunderspy Gaming", "Sweet Tea")
WANTED = {"powers.bin", "powersets.bin", "VillainDef.bin", "VillainCostume.bin", "fxinfo.bin",
          "villain_classes.bin"}

IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,}$")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
POWER = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
POWERSET = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")


def load_bins(client):
    bins = {}
    for archive in (os.path.join(client, "piggs", "bin.pigg"),
                    os.path.join(client, "rebirth", "z_rebirth_bin.pigg")):
        if not os.path.exists(archive):
            print(f"skip (missing): {archive}")
            continue
        for name, blob in read_pigg(archive):
            base = name.split("/")[-1]
            if base in WANTED:
                bins[base] = blob
    return bins


def build(client):
    bins = load_bins(client)
    s = {k: bin_strings(v) for k, v in bins.items()}

    # Neighbouring length bytes are sometimes printable and glue onto a name, so split on them.
    def idents(strings):
        return {w for x in strings for w in WORD.findall(x)}
    costumes = sorted(idents(s["VillainCostume.bin"]) & idents(s["VillainDef.bin"]))

    villains = sorted({s["VillainDef.bin"][i - 1] for i, x in enumerate(s["VillainDef.bin"])
                       if x.startswith("Class_") and i and IDENT.match(s["VillainDef.bin"][i - 1])})

    powers = sorted({x for x in s["powers.bin"] if POWER.match(x)})
    powersets = sorted({x for x in s["powersets.bin"] if POWERSET.match(x)})
    icons = sorted({x for x in s["powers.bin"] if x.lower().endswith(".tga") and " " not in x})
    fx = sorted({f for f in bin_source_files(bins["fxinfo.bin"])})
    classes = sorted({x for x in s["villain_classes.bin"] if x.startswith("Class_")})
    ai = sorted({x for x in s["VillainDef.bin"] if re.match(r"^Pets_[A-Za-z]+$", x)})

    catalog = {
        "source": client,
        "costumes": costumes,
        "villains": villains,
        "powers": powers,
        "powersets": powersets,
        "icons": icons,
        "fx": fx,
        "classes": classes,
        "ai_configs": ai,
    }
    out = os.path.join(ROOT, "editor", "catalog.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=0)
    for k, v in catalog.items():
        if isinstance(v, list):
            print(f"{k:12} {len(v)}")
    print(f"wrote {out}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CLIENT)

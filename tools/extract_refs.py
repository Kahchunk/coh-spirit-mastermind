"""Pull reference art out of your installed client into art/reference/ (gitignored).

usage:
  python tools/extract_refs.py textures "Croatoa/Ghosts"        # .texture -> .png
  python tools/extract_refs.py geo "player_library/MALE_SHIRT"  # .geo -> .obj per file
  python tools/extract_refs.py list "Croatoa"                    # just list matching entries

Game assets stay on your machine; never commit art/reference/.
Models export in their T-pose bind position with UVs and normals (decoder follows GetVrml's
compressDeltas). Bone weights are not written to the OBJ.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pigg import read_pigg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Thunderspy Gaming", "Sweet Tea")
OUT = os.path.join(ROOT, "art", "reference")


def archives():
    base = sorted(glob.glob(os.path.join(CLIENT, "piggs", "*.pigg")))
    rebirth = sorted(glob.glob(os.path.join(CLIENT, "rebirth", "*.pigg")))
    # Rebirth's archives load last so their copy of a file wins, as in the game.
    return [p for p in base + rebirth if not os.path.basename(p).startswith(("sound", "maps"))]


def matches(kind, pattern):
    pat = re.compile(pattern, re.I)
    ext = {"textures": ".texture", "geo": ".geo"}.get(kind)
    found = {}
    for arc in archives():
        for name, blob in read_pigg(arc):
            if pat.search(name) and (ext is None or name.lower().endswith(ext)):
                found[name] = (os.path.basename(arc), blob)
    return found


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("textures", "geo", "list"):
        print(__doc__)
        return 2
    kind, pattern = sys.argv[1], sys.argv[2]
    found = matches(kind, pattern)
    if not found:
        print("no matches")
        return 1
    for name, (arc, blob) in sorted(found.items()):
        if kind == "list":
            print(f"{arc}: {name} ({len(blob)} bytes)")
            continue
        stem = os.path.splitext(name)[0]
        dest = os.path.join(OUT, *stem.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if kind == "textures":
            from texture import texture_to_png
            size = texture_to_png(blob, dest + ".png")
            print(f"{name} -> {dest}.png {size}")
        else:
            import tempfile
            import geo
            with tempfile.NamedTemporaryFile(suffix=".geo", delete=False) as tmp:
                tmp.write(blob)
            try:
                models = geo.read_geo(tmp.name)
            finally:
                os.unlink(tmp.name)
            lod0 = lambda m: not re.search(r"_LOD\d$", m.name)
            geo.write_obj(models, dest + ".obj", include=lod0)
            print(f"{name} -> {dest}.obj ({sum(1 for m in models if lod0(m))} meshes, LOD0 only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

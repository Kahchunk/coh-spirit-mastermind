"""Inspect 3ds Max .max files without opening Max: metadata + a scan for known scene-script worms.

usage: python tools/max_inspect.py <file-or-folder> [...] [--json out.json]

Reads the OLE property streams Max writes (version, mesh totals, plug-ins, linked files) and greps
the raw file for markers of the MAXScript worms that spread through shared scenes (ALC, CRP, ADSL,
PhysXPluginMfx and similar). A hit means: don't open it in Max until Autodesk's Security Tools clean it.
"""
import json
import os
import re
import sys

import olefile

WORM_MARKERS = [
    rb"ALC_betaA", rb"ALC2", rb"CRP_BScript", rb"CRP_AScript", rb"ADSL_BScript", rb"ADSL_AScript",
    rb"PhysXPluginMfx", rb"PhysXPluginStup", rb"vrdematcleanbeta", rb"CleanBeta", rb"AutodeskLicSerStuckCleanBeta",
    rb"persistent global", rb"callbacks.addScript", rb"filein", rb"deleteFile",
]


def ole_strings(ole, stream):
    if not ole.exists(stream):
        return []
    raw = ole.openstream(stream).read()
    out = []
    for enc, pat in (("utf-16-le", rb"(?:[\x20-\x7e]\x00){3,}"), ("latin-1", rb"[\x20-\x7e]{3,}")):
        out += [m.group().decode(enc) for m in re.finditer(pat, raw)]
    return out


def inspect(path):
    info = {"file": path, "size_mb": round(os.path.getsize(path) / 2**20, 1)}
    with open(path, "rb") as f:
        raw = f.read()
    hits = sorted({m.decode() for m in WORM_MARKERS if m in raw})
    # Generic MAXScript terms appear in harmless scenes too; only the named worm markers are alarming.
    named = [h for h in hits if h not in ("persistent global", "callbacks.addScript", "filein", "deleteFile")]
    info["worm_markers"] = named
    info["script_terms"] = [h for h in hits if h not in named]
    try:
        ole = olefile.OleFileIO(path)
    except OSError as e:
        info["error"] = f"not an OLE .max: {e}"
        return info
    info["streams"] = ["/".join(s) for s in ole.listdir()][:20]
    doc = ole_strings(ole, "\x05DocumentSummaryInformation")
    summ = ole_strings(ole, "\x05SummaryInformation")
    info["summary"] = summ[:12]
    text = "\n".join(doc)
    info["saved_with"] = next((s for s in doc if re.search(r"3ds ?max|Max Version|\b(20\d\d|[789])\b", s, re.I)), None)
    info["doc_props"] = doc[:120]
    deps = [s for s in doc if re.search(r"\.(tga|psd|jpg|png|dds|bmp|tif)$", s, re.I)]
    info["linked_textures"] = deps[:60]
    info["linked_texture_count"] = len(deps)
    ole.close()
    return info


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    if out_json in args:
        args.remove(out_json)
    files = []
    for a in args:
        if os.path.isdir(a):
            for root, _d, fs in os.walk(a):
                files += [os.path.join(root, f) for f in fs if f.lower().endswith(".max")]
        else:
            files.append(a)
    results = [inspect(f) for f in sorted(files)]
    for r in results:
        flag = "WORM MARKERS: " + ", ".join(r["worm_markers"]) if r["worm_markers"] else "clean"
        print(f"{r['size_mb']:8.1f} MB  {flag:20}  textures:{r.get('linked_texture_count', '?'):>4}  {os.path.relpath(r['file'])}")
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
        print("wrote", out_json)


if __name__ == "__main__":
    main()

"""CoH Art Bridge: Photoshop -> Blender live preview without typing commands.

Leave it running (double-click "CoH Art Bridge" on the desktop, or `python tools/art_bridge.py`).
  - Switch to a part's .psd in Photoshop and Blender opens that part's model.
  - Save in Photoshop and the preview textures are re-exported; Blender reloads them.

Parts live in art/work/<name>/:
  <name>.psd     your texture, organized in layer groups:
                   Color  - grayscale detail (or full color for NPC-only pieces)
                   Mask   - black = Color1, white = Color2 (optional)
                   Bump, Spec - exported later for the game; ignored by the preview
                   "UV guide" layer - your paint guide; never exported
  <name>.obj     the mesh
  part.json      preview settings (tint colors)
  .preview/      generated PNGs the Blender preview watches (don't edit)

Make a new part from any game mesh:
  python tools/art_bridge.py new spirit_chest --game "player_library/MALE_SHIRT.geo" --mesh GEO_Chest_Tight
  python tools/art_bridge.py new my_piece --obj path/to/model.obj
Make the two example parts:
  python tools/art_bridge.py examples
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import Group, PixelLayer

sys.path.insert(0, os.path.dirname(__file__))
import geo  # noqa: E402
from uv_overlay import uv_overlay  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "art", "work")
BLENDER = os.environ.get("BLENDER_EXE", r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe")
PREVIEW_SCRIPT = os.path.join(ROOT, "tools", "blender", "coh_live_preview.py")
NOT_COLOR = {"mask", "bump", "spec", "uv guide"}
POLL_SECONDS = 1.0


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(os.path.join(WORK, "bridge.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------- parts ----------

class Part:
    def __init__(self, folder):
        self.folder = folder
        self.name = os.path.basename(folder)
        self.psd = os.path.join(folder, self.name + ".psd")
        self.mesh = next((os.path.join(folder, f) for f in os.listdir(folder)
                          if f.lower().endswith(".obj")), None)
        cfg_path = os.path.join(folder, "part.json")
        self.cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
        self.preview = os.path.join(folder, ".preview")

    @property
    def color_png(self):
        return os.path.join(self.preview, "color.png")

    @property
    def mask_png(self):
        return os.path.join(self.preview, "mask.png")

    @property
    def sheet_png(self):
        return os.path.join(self.preview, "sheet.png")

    @property
    def cfg_path(self):
        return os.path.join(self.folder, "part.json")

    def read_cfg(self):
        try:
            return json.load(open(self.cfg_path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def find_parts():
    if not os.path.isdir(WORK):
        return []
    parts = []
    for d in sorted(os.listdir(WORK)):
        folder = os.path.join(WORK, d)
        if os.path.isdir(folder) and os.path.exists(os.path.join(folder, d + ".psd")):
            parts.append(Part(folder))
    return parts


# ---------- PSD export ----------

def _stack(psd, layers):
    """Normal-blend the given pixel layers bottom-to-top. psd-tools' compositor returns blank
    images for layers it created itself, so new starter PSDs need this until Photoshop resaves them."""
    canvas = Image.new("RGBA", psd.size, (0, 0, 0, 0))
    for lay in layers:
        img = lay.topil()
        if img is None:
            continue
        img = img.convert("RGBA")
        if lay.opacity < 255:
            img.putalpha(img.getchannel("A").point(lambda a: a * lay.opacity // 255))
        canvas.alpha_composite(img, dest=lay.offset)
    return canvas


def _composite(psd, members, force=False):
    img = psd.composite(force=force, layer_filter=lambda l: id(l) in members)
    if img is None or (img.mode == "RGBA" and img.getchannel("A").getextrema()[1] == 0):
        ordered = [l for l in psd.descendants() if id(l) in members and not l.is_group()
                   and (force or l.is_visible())]
        img = _stack(psd, ordered)
    return img


def _flatten(img, background=(0, 0, 0)):
    flat = Image.new("RGB", img.size, background)
    flat.paste(img, mask=img.getchannel("A") if img.mode == "RGBA" else None)
    return flat


def export_maps(part):
    """Write .preview/color.png (+ mask.png) from the PSD's layer groups."""
    psd = PSDImage.open(part.psd)
    top = list(psd)
    mask_group = next((l for l in top if l.name.strip().lower() == "mask"), None)
    excluded = {id(l) for l in top if l.name.strip().lower() in NOT_COLOR}
    for l in top:
        if id(l) in excluded and l.is_group():
            excluded |= {id(c) for c in l.descendants()}

    color_members = {id(l) for l in psd.descendants() if id(l) not in excluded}
    os.makedirs(part.preview, exist_ok=True)
    _save_atomic(_flatten(_composite(psd, color_members), (128, 128, 128)), part.color_png)

    has_mask = False
    if mask_group is not None and any(not c.is_group() for c in mask_group.descendants()):
        members = {id(c) for c in mask_group.descendants()} | {id(mask_group)}
        _save_atomic(_flatten(_composite(psd, members, force=True)), part.mask_png)
        has_mask = True
    if not has_mask and os.path.exists(part.mask_png):
        os.remove(part.mask_png)
    return has_mask


def _save_atomic(img, path):
    # Write then rename so Blender never reloads a half-written file.
    tmp = path + ".tmp.png"
    img.save(tmp)
    os.replace(tmp, path)


# ---------- Blender ----------

_blender = {}
BASE_BLEND = os.path.join(WORK, ".preview_base.blend")


def ensure_base_blend():
    """An empty scene file to open Blender with; created once, headless."""
    if not os.path.exists(BASE_BLEND):
        os.makedirs(WORK, exist_ok=True)
        expr = ("import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); "
                f"bpy.ops.wm.save_as_mainfile(filepath={BASE_BLEND!r})")
        subprocess.run([BLENDER, "-b", "--factory-startup", "--python-expr", expr],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return BASE_BLEND


def open_in_blender(part, has_mask):
    proc = _blender.get(part.name)
    if proc and proc.poll() is None:
        return
    if not part.mesh:
        log(f"{part.name}: no .obj in the folder, nothing to show")
        return
    # Opening a .blend (instead of starting empty) skips Blender's splash screen.
    args = [BLENDER, ensure_base_blend(), "--python", PREVIEW_SCRIPT, "--", "--obj", part.mesh, "--base", part.color_png,
            "--color1", part.cfg.get("color1", "#b0d8ff"), "--color2", part.cfg.get("color2", "#2a6f8f")]
    if has_mask:
        args += ["--mask", part.mask_png]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    _blender[part.name] = subprocess.Popen(args, creationflags=flags, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
    log(f"{part.name}: opened in Blender")


# ---------- 3ds Max (default backend) ----------

MAX_EXE = os.environ.get("COH_MAX_EXE", os.path.join(r"C:\Program Files", "Autodesk", "3ds Max 2015", "3dsmax.exe"))
MAX_SCRIPT = os.path.join(ROOT, "tools", "max", "coh_bridge.ms")
REQUEST = os.path.join(WORK, ".preview_request.txt")
BACKEND = os.environ.get("COH_BACKEND", "max")
_max_proc = None


def hex_to_rgb255(h):
    h = h.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def write_request(part):
    """Tell the Max-side script (tools/max/coh_bridge.ms) what to show and how to color it."""
    cfg = part.read_cfg()
    lines = {
        "part": part.name,
        "obj": part.mesh or "",
        "color": part.color_png,
        "mask": part.mask_png if os.path.exists(part.mask_png) else "",
        "sheet": part.sheet_png,
        "color1": hex_to_rgb255(cfg.get("color1", "#b0d8ff")),
        "color2": hex_to_rgb255(cfg.get("color2", "#2a6f8f")),
        "look": cfg.get("look", "FLAT"),
        "ghost_opacity": str(int(float(cfg.get("ghost_opacity", 0.55)) * 100)),
    }
    tmp = REQUEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(f"{k}={v}\n" for k, v in lines.items())
    os.replace(tmp, REQUEST)


def close_max_welcome():
    """Max 2015's Welcome Screen blocks rendering while it's open; close it if it shows up."""
    try:
        import win32con
        import win32gui
        hwnd = win32gui.FindWindow(None, "Welcome to 3ds Max")
        if hwnd and win32gui.IsWindowVisible(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            log("closed 3ds Max's Welcome Screen")
    except Exception:
        pass


def max_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq 3dsmax.exe", "/NH"], capture_output=True, text=True).stdout
    return "3dsmax.exe" in out


def open_in_max(part):
    global _max_proc
    if not part.mesh:
        log(f"{part.name}: no .obj in the folder, nothing to show")
        return
    write_request(part)
    if _max_proc and _max_proc.poll() is None:
        return
    if max_running():
        if _max_proc is None:
            log("3ds Max is already open. If the preview doesn't load, run MAXScript > Run Script > "
                "tools/max/coh_bridge.ms once in that Max.")
            _max_proc = False  # don't nag again
        return
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    _max_proc = subprocess.Popen([MAX_EXE, "-U", "MAXScript", MAX_SCRIPT], creationflags=flags,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("starting 3ds Max (first launch takes a minute)")


def open_preview(part):
    if BACKEND == "blender":
        open_in_blender(part, os.path.exists(part.mask_png))
    else:
        open_in_max(part)


# ---------- Photoshop ----------

def photoshop_active_doc():
    """Active document file name: full path via COM when Photoshop is free, else the window title."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        ps = win32com.client.GetActiveObject("Photoshop.Application")
        if ps.Documents.Count:
            return ps.ActiveDocument.FullName
    except Exception:
        pass  # Busy (dialog open), not running, or unsaved doc: fall back to the title.
    try:
        import win32gui
        found = []

        def cb(h, _):
            if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "Photoshop":
                found.append(win32gui.GetWindowText(h))
        win32gui.EnumWindows(cb, None)
        for title in found:
            m = re.match(r"^(.+?) @ \d", title)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def match_part(doc, parts):
    if not doc:
        return None
    base = os.path.basename(doc).lower()
    return next((p for p in parts if os.path.basename(p.psd).lower() == base), None)


# ---------- run loop ----------

def run():
    os.makedirs(WORK, exist_ok=True)
    log(f"watching {WORK}  (Ctrl+C to stop)")
    mtimes, last_doc, active, cfg_stamp = {}, None, None, None
    while True:
        parts = find_parts()
        for p in parts:
            try:
                m = os.path.getmtime(p.psd)
            except OSError:
                continue
            if mtimes.get(p.psd) != m:
                first = p.psd not in mtimes
                mtimes[p.psd] = m
                try:
                    has_mask = export_maps(p)
                    if not first:
                        log(f"{p.name}: saved -> preview updated")
                    p.cfg["_has_mask"] = has_mask
                except Exception as e:  # Photoshop may still be writing; retry next tick.
                    mtimes.pop(p.psd, None)
                    log(f"{p.name}: couldn't read the PSD yet ({type(e).__name__}), retrying")
        doc = photoshop_active_doc()
        part = match_part(doc, parts)
        if part and doc != last_doc:
            log(f"Photoshop: {os.path.basename(doc)}")
            open_preview(part)
            active = part
        last_doc = doc
        if BACKEND != "blender":
            close_max_welcome()
        # Colors/look edited in the Photoshop panel land in part.json; pass them on.
        if active and BACKEND != "blender":
            try:
                stamp = (os.path.getmtime(active.cfg_path), os.path.exists(active.mask_png))
            except OSError:
                stamp = None
            if stamp != cfg_stamp:
                cfg_stamp = stamp
                write_request(active)
        time.sleep(POLL_SECONDS)


# ---------- new parts ----------

def load_game_mesh(game_path, mesh_name):
    import extract_refs
    found = extract_refs.matches("geo", re.escape(game_path) + "$")
    if not found:
        raise SystemExit(f"{game_path} not found in the installed client")
    blob = next(iter(found.values()))[1]
    with tempfile.NamedTemporaryFile(suffix=".geo", delete=False) as tmp:
        tmp.write(blob)
    try:
        models = geo.read_geo(tmp.name)
    finally:
        os.unlink(tmp.name)
    hit = [m for m in models if m.name == mesh_name]
    if not hit:
        raise SystemExit(f"{mesh_name} not in {game_path}; meshes: {[m.name for m in models if 'LOD' not in m.name]}")
    return models, hit[0]


def build_psd(path, size, color_img=None, mask_img=None, uv_img=None):
    w, h = size
    psd = PSDImage.new("RGB", (w, h))

    def group(name, img, visible):
        g = Group.new(psd, name, open_folder=False)
        if img is not None:
            g.append(PixelLayer.frompil(img.convert("RGB").resize((w, h)), psd, name.lower(), 0, 0))
        g.visible = visible
        return g

    group("Spec", Image.new("RGB", (w, h), (0, 0, 0)), False)
    group("Bump", Image.new("RGB", (w, h), (128, 128, 128)), False)
    # Left empty unless given: an empty Mask group means "no tint" (full-color piece).
    group("Mask", mask_img, False)
    group("Color", color_img if color_img is not None else Image.new("RGB", (w, h), (180, 180, 180)), True)
    if uv_img is not None:
        guide = PixelLayer.frompil(uv_img.resize((w, h)), psd, "UV guide", 0, 0)
        guide.opacity = 160
        psd.append(guide)
    psd.save(path)


def new_part(name, obj=None, game=None, mesh=None, color=None, mask=None, size=512, color1=None, color2=None):
    folder = os.path.join(WORK, name)
    if os.path.exists(folder):
        raise SystemExit(f"{folder} already exists")
    os.makedirs(folder)
    if game:
        models, m = load_game_mesh(game, mesh)
        geo.write_obj(models, os.path.join(folder, name + ".obj"), include=lambda x: x is m)
        uv = uv_overlay(m, None, size)
    elif obj:
        shutil.copy(obj, os.path.join(folder, name + ".obj"))
        uv = None
    else:
        raise SystemExit("give --game/--mesh or --obj")
    color_img = Image.open(color) if color else None
    mask_img = Image.open(mask) if mask else None
    dims = color_img.size if color_img else (size, size)
    build_psd(os.path.join(folder, name + ".psd"), dims, color_img, mask_img, uv)
    cfg = {"color1": color1 or "#b0d8ff", "color2": color2 or "#2a6f8f"}
    json.dump(cfg, open(os.path.join(folder, "part.json"), "w"), indent=2)
    log(f"created {folder}")
    return folder


def examples():
    ref = os.path.join(ROOT, "art", "reference", "preview")
    if not os.path.isdir(ref):
        raise SystemExit("run the reference extraction first (art/reference/preview missing)")
    for name, kw in (
        ("example_rifle", dict(game="player_library/G_WepR_AssaultRifle_01.geo", mesh="GEO_Hips",
                               color=os.path.join(ref, "rifle01_base.png"), mask=os.path.join(ref, "rifle01_mask.png"),
                               color1="#c83232", color2="#e6c83c")),
        ("example_spirit_head", dict(game="player_library/MALE_HEAD.geo", mesh="GEO_Head_Masked_Bald",
                                     color=os.path.join(ref, "spirit_face.png"))),
    ):
        if not os.path.exists(os.path.join(WORK, name)):
            new_part(name, **kw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    n = sub.add_parser("new")
    n.add_argument("name")
    n.add_argument("--obj")
    n.add_argument("--game", help='e.g. "player_library/MALE_SHIRT.geo"')
    n.add_argument("--mesh", help="e.g. GEO_Chest_Tight")
    n.add_argument("--color", help="starting texture image")
    n.add_argument("--mask", help="starting mask image")
    n.add_argument("--size", type=int, default=512)
    sub.add_parser("examples")
    a = ap.parse_args()
    if a.cmd == "new":
        new_part(a.name, a.obj, a.game, a.mesh, a.color, a.mask, a.size)
    elif a.cmd == "examples":
        examples()
    else:
        run()


if __name__ == "__main__":
    main()

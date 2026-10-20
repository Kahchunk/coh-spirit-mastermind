"""Master turnaround sheet: the game's standard body, ready to draw a character over in Photoshop.

    python tools/master_sheet.py                 # male, female and huge
    python tools/master_sheet.py huge --scale 220

For each body type this assembles the base body (the plain chest, hips, gloves, boots and head pieces
every player and NPC costume builds on) on that body's rest skeleton, renders it front / right side /
back in orthographic views at one shared scale, and writes art/templates/<body>_master_sheet.psd:

  Your design       empty layer to draw on
  Guides            landmark lines (soles ... top of head), center lines, view and side labels
  Slot zones        which costume slot each area belongs to (head, chest + upper arms, gloves,
                    hips + upper legs, boots); a design should split along these seams
  Outline           silhouette and slot seams
  Body              shaded render of the base body
  Paper             background

plus <body>_master_sheet.json (scale, ground line, view centers, landmarks) so later tools can line the
drawing up with the skeleton in 3ds Max without any manual fitting, and a flattened .png preview.
Templates are made from the installed client's art, so they stay out of git (art/templates/).
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from psd_tools import PSDImage
from psd_tools.api.layers import Group, PixelLayer

sys.path.insert(0, os.path.dirname(__file__))
import art_bridge_app  # noqa: E402  (model index + mesh loading)
import skeleton  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "art", "templates")

# (geo file, mesh, bone it hangs from, slot). Pieces are stored relative to their bone.
BODIES = {
    "male": [
        ("player_library/MALE_SHIRT.geo", "GEO_Chest_Tight", "CHEST", "chest"),
        ("player_library/MALE_PANTS.geo", "GEO_Hips_Tight", "HIPS", "hips"),
        ("player_library/MALE_GLOVE.geo", "GEO_LarmL_Smooth", "LARML", "gloves"),
        ("player_library/MALE_GLOVE.geo", "GEO_LarmR_Smooth", "LARMR", "gloves"),
        ("player_library/MALE_BOOT.geo", "GEO_LlegL_Smooth", "LLEGL", "boots"),
        ("player_library/MALE_BOOT.geo", "GEO_LlegR_Smooth", "LLEGR", "boots"),
        ("player_library/MALE_HEAD.geo", "GEO_Head_Standard", "HEAD", "head"),
    ],
    "female": [
        ("player_library/fem_shirt.geo", "GEO_Chest_Tight", "CHEST", "chest"),
        ("player_library/fem_pants.geo", "GEO_Hips_Tight", "HIPS", "hips"),
        ("player_library/fem_GLOVE.geo", "GEO_LarmL_Smooth", "LARML", "gloves"),
        ("player_library/fem_GLOVE.geo", "GEO_LarmR_Smooth", "LARMR", "gloves"),
        ("player_library/fem_BOOT.geo", "GEO_LlegL_Smooth", "LLEGL", "boots"),
        ("player_library/fem_BOOT.geo", "GEO_LlegR_Smooth", "LLEGR", "boots"),
        ("player_library/fem_head.geo", "GEO_Head_Standard", "HEAD", "head"),
    ],
    "huge": [
        ("player_library/HUGE_SHIRT.geo", "GEO_Chest_Tight", "CHEST", "chest"),
        ("player_library/HUGE_PANTS.geo", "GEO_Hips_Tight", "HIPS", "hips"),
        ("player_library/N_Huge_Clubwear.geo", "GEO_LarmL_Smooth", "LARML", "gloves"),
        ("player_library/N_Huge_Clubwear.geo", "GEO_LarmR_Smooth", "LARMR", "gloves"),
        ("player_library/N_Huge_Clubwear.geo", "GEO_LlegL_Smooth", "LLEGL", "boots"),
        ("player_library/N_Huge_Clubwear.geo", "GEO_LlegR_Smooth", "LLEGR", "boots"),
        ("player_library/HUGE_HEAD.geo", "GEO_Head_Standard", "HEAD", "head"),
    ],
}

SLOTS = {  # slot: (label, RGB)
    "head": ("Head", (155, 110, 220)),
    "chest": ("Chest + upper arms", (70, 140, 230)),
    "gloves": ("Gloves (lower arms)", (60, 180, 120)),
    "hips": ("Hips + upper legs", (235, 150, 50)),
    "boots": ("Boots (lower legs)", (220, 80, 80)),
}
SLOT_IDS = list(SLOTS)

# Views of the body in right-handed space (game X negated, so the character's left is +X).
# forward = the direction the camera looks; screen right = forward x up.
VIEWS = [
    ("FRONT", (0.0, 0.0, -1.0)),
    ("RIGHT SIDE", (1.0, 0.0, 0.0)),
    ("BACK", (0.0, 0.0, 1.0)),
]
UP = np.array([0.0, 1.0, 0.0])

# Landmarks: name -> how to find its height (a bone, or the body's lowest/highest point).
LANDMARKS = [
    ("Top of head", "top"), ("Head", "HEAD"), ("Neck", "NECK"), ("Shoulders", "UARML"),
    ("Chest", "CHEST"), ("Waist", "WAIST"), ("Hips", "HIPS"), ("Crotch / upper legs", "ULEGL"),
    ("Knees", "LLEGL"), ("Ankles", "FOOTL"), ("Soles", "bottom"),
]

PAPER = (236, 236, 232)
INK = (40, 42, 48)


def assemble(body):
    """World-space body: verts, normals, tris and a slot id per triangle (right-handed: X negated)."""
    bones = skeleton.load_skeleton(body)
    index = art_bridge_app.build_index()
    verts, norms, tris, slots = [], [], [], []
    for geo_path, mesh, bone, slot in BODIES[body]:
        hit = [e for e in index if e["geo"] == geo_path and e["mesh"] == mesh]
        if not hit:
            raise SystemExit(f"{geo_path} / {mesh} not in the installed client")
        model = art_bridge_app.load_entry(hit[0])[1]
        origin = np.array(bones[bone])
        base = len(verts)
        verts += [tuple(np.array(v) + origin) for v in model.verts]
        norms += model.norms if model.norms else [(0.0, 0.0, 1.0)] * len(model.verts)
        tris += [(a + base, b + base, c + base) for a, b, c in model.tris]
        slots += [SLOT_IDS.index(slot)] * len(model.tris)
    flip = np.array([-1.0, 1.0, 1.0])
    bones_rh = {k: tuple(np.array(p) * flip) for k, p in bones.items()}
    return np.array(verts) * flip, np.array(norms) * flip, np.array(tris), np.array(slots), bones_rh


def render_view(v, n, tris, slots, forward, scale, cell_w, cell_h, ground_y, center_x):
    """Orthographic render: (shade RGB array, slot-id buffer with -1 = empty)."""
    f = np.array(forward)
    right = np.cross(f, UP)
    sx = center_x + scale * (v @ right)
    sy = ground_y - scale * (v @ UP)
    depth = -(v @ f)  # larger = closer to the camera
    light = -f * 0.8 + UP * 0.5 - right * 0.3
    light /= np.linalg.norm(light)
    shade_v = np.clip(n @ light, 0, 1)
    img = np.zeros((cell_h, cell_w), dtype=float)
    ids = np.full((cell_h, cell_w), -1, dtype=int)
    zbuf = np.full((cell_h, cell_w), -np.inf)
    for t, (a, b, c) in enumerate(tris):
        xs, ys = sx[[a, b, c]], sy[[a, b, c]]
        x0, x1 = int(max(np.floor(xs.min()), 0)), int(min(np.ceil(xs.max()), cell_w - 1))
        y0, y1 = int(max(np.floor(ys.min()), 0)), int(min(np.ceil(ys.max()), cell_h - 1))
        if x1 < x0 or y1 < y0:
            continue
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * depth[a] + w1 * depth[b] + w2 * depth[c]
        zr = zbuf[y0:y1 + 1, x0:x1 + 1]
        win = inside & (zz > zr)
        if not win.any():
            continue
        zr[win] = zz[win]
        s = w0 * shade_v[a] + w1 * shade_v[b] + w2 * shade_v[c]
        img[y0:y1 + 1, x0:x1 + 1][win] = s[win]
        ids[y0:y1 + 1, x0:x1 + 1][win] = slots[t]
    return img, ids


def edges(ids):
    """(silhouette mask, seam mask) from a slot-id buffer: body pixels next to empty space, and
    body pixels next to a different slot."""
    body = ids >= 0
    pad = np.pad(ids, 1, constant_values=-1)
    near_empty = np.zeros_like(body)
    near_other = np.zeros_like(body)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        nb = pad[1 + dy:1 + dy + ids.shape[0], 1 + dx:1 + dx + ids.shape[1]]
        near_empty |= nb < 0
        near_other |= (nb >= 0) & (nb != ids)
    silhouette = body & near_empty
    return silhouette, body & near_other & ~silhouette


def font(size, bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build(body, scale):
    v, n, tris, slots, bones = assemble(body)
    lo, hi = v.min(0), v.max(0)
    height = hi[1] - lo[1]
    span = max(hi[0] - lo[0], hi[2] - lo[2])
    margin = int(0.35 * scale)
    label_w = int(1.6 * scale)                       # left column for landmark names
    cell_w = int(span * scale) + 2 * margin
    head_h = int(0.9 * scale)                        # title band
    cell_h = int(height * scale) + 2 * margin
    width, total_h = label_w + cell_w * len(VIEWS), head_h + cell_h
    ground_y = head_h + cell_h - margin + int(lo[1] * scale)  # pixel row of world y = 0

    paper = Image.new("RGB", (width, total_h), PAPER)
    body_rgba = np.zeros((total_h, width, 4), dtype=np.uint8)
    zones = np.zeros((total_h, width, 4), dtype=np.uint8)
    outline = np.zeros((total_h, width, 4), dtype=np.uint8)
    views_meta = []
    for k, (name, forward) in enumerate(VIEWS):
        x0 = label_w + k * cell_w
        center = cell_w // 2
        shade, ids = render_view(v, n, tris, slots, forward, scale, cell_w, total_h, ground_y, center)
        mask = ids >= 0
        g = (150 + 95 * shade).clip(0, 255).astype(np.uint8)
        region = body_rgba[:, x0:x0 + cell_w]
        region[mask, 0], region[mask, 1], region[mask, 2], region[mask, 3] = g[mask], g[mask], g[mask] + 3, 255
        for sid, slot in enumerate(SLOT_IDS):
            m = ids == sid
            zones[:, x0:x0 + cell_w][m] = (*SLOTS[slot][1], 110)
        sil, seams = edges(ids)
        outline[:, x0:x0 + cell_w][seams] = (*INK, 150)
        outline[:, x0:x0 + cell_w][sil] = (*INK, 255)
        views_meta.append({"name": name, "forward": forward, "right": list(np.cross(forward, UP)),
                           "left_px": x0, "center_x_px": x0 + center, "width_px": cell_w})

    # Guides: landmark lines across every view, center lines, labels.
    guides = Image.new("RGBA", (width, total_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(guides)
    f_small, f_mid, f_big = font(max(12, scale // 9)), font(max(14, scale // 7), True), font(max(18, scale // 4), True)
    landmarks = {}
    for label, src in LANDMARKS:
        y_world = lo[1] if src == "bottom" else hi[1] if src == "top" else bones[src][1]
        y_px = int(round(ground_y - scale * y_world))
        landmarks[label] = {"y_units": round(float(y_world), 4), "y_px": y_px}
        major = src in ("top", "bottom", "HIPS", "UARML", "LLEGL")
        gd.line([(label_w - 8, y_px), (width, y_px)], fill=(200, 60, 60, 200) if major else (60, 110, 200, 150),
                width=2 if major else 1)
        gd.text((10, y_px - f_small.size // 2 - 1), label, font=f_small, fill=(*INK, 255))
    for vm in views_meta:
        cx = vm["center_x_px"]
        for yy in range(head_h, total_h, 12):  # dashed center line
            gd.line([(cx, yy), (cx, yy + 6)], fill=(60, 110, 200, 160), width=1)
        gd.text((vm["left_px"] + 14, 14), vm["name"], font=f_big, fill=(*INK, 255))
        gd.line([(vm["left_px"], head_h - 4), (vm["left_px"], total_h)], fill=(*INK, 60), width=1)
    # Which side is which, so a drawing can't come out mirrored.
    fy = head_h + int(0.2 * scale)
    front, back = views_meta[0], views_meta[2]
    for vm, left_word, right_word in ((front, "their RIGHT", "their LEFT"), (back, "their LEFT", "their RIGHT")):
        gd.text((vm["left_px"] + 14, fy), left_word, font=f_mid, fill=(200, 60, 60, 255))
        w = gd.textlength(right_word, font=f_mid)
        gd.text((vm["left_px"] + vm["width_px"] - 14 - w, fy), right_word, font=f_mid, fill=(200, 60, 60, 255))
    side = views_meta[1]
    gd.text((side["left_px"] + 14, fy), "back", font=f_mid, fill=(200, 60, 60, 255))
    w = gd.textlength("front", font=f_mid)
    gd.text((side["left_px"] + side["width_px"] - 14 - w, fy), "front", font=f_mid, fill=(200, 60, 60, 255))
    # Body type and scale in the label column; slot legend as a row in the title band.
    gd.text((10, 14), f"{body.upper()} body", font=f_mid, fill=(*INK, 255))
    gd.text((10, 14 + int(f_mid.size * 1.4)), f"1 unit = {scale}px", font=f_small, fill=(*INK, 200))
    lx, ly = label_w + 14, int(0.5 * scale)
    for slot, (label, rgb) in SLOTS.items():
        sw = f_small.size
        gd.rectangle([lx, ly + 2, lx + sw, ly + 2 + sw], fill=(*rgb, 255))
        gd.text((lx + sw + 6, ly), label, font=f_small, fill=(*INK, 255))
        lx += sw + 6 + int(gd.textlength(label, font=f_small)) + 28

    os.makedirs(OUT_DIR, exist_ok=True)
    stem = os.path.join(OUT_DIR, f"{body}_master_sheet")
    layers = {
        "Body": Image.fromarray(body_rgba, "RGBA"),
        "Outline": Image.fromarray(outline, "RGBA"),
        "Slot zones": Image.fromarray(zones, "RGBA"),
        "Guides": guides,
    }
    write_psd(stem + ".psd", paper, layers)
    flat = paper.convert("RGBA")
    for name in ("Body", "Slot zones", "Outline", "Guides"):
        flat = Image.alpha_composite(flat, layers[name])
    flat.convert("RGB").save(stem + ".png")
    meta = {
        "body": body, "units": "game units (about a foot each)", "scale_px_per_unit": scale,
        "ground_y_px": ground_y, "canvas": [width, total_h], "views": views_meta,
        "landmarks": landmarks, "bones": {k: [round(float(c), 4) for c in p] for k, p in bones.items()
                                           if not k.startswith("BONE_")},
        "coordinates": "right-handed, Y up, character faces +Z, its left side at +X (game X negated)",
        "pieces": [{"geo": g, "mesh": m, "bone": b, "slot": s} for g, m, b, s in BODIES[body]],
    }
    with open(stem + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"{body}: {stem}.psd ({width}x{total_h})")
    return stem


def write_psd(path, paper, layers):
    psd = PSDImage.new("RGB", paper.size, color=PAPER)
    psd.append(PixelLayer.frompil(paper, psd, "Paper", 0, 0))
    for name in ("Body", "Outline", "Slot zones"):
        layer = PixelLayer.frompil(layers[name], psd, name, 0, 0)
        if name == "Slot zones":
            layer.visible = False  # turn on when you want to see where each costume slot ends
        psd.append(layer)
    guides = Group.new(psd, "Guides", open_folder=False)
    guides.append(PixelLayer.frompil(layers["Guides"], psd, "Landmarks + labels", 0, 0))
    design = Group.new(psd, "Your design", open_folder=True)
    design.append(PixelLayer.frompil(Image.new("RGBA", paper.size, (0, 0, 0, 0)), psd, "Draw here", 0, 0))
    psd.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bodies", nargs="*", choices=list(BODIES), help="default: all three")
    ap.add_argument("--scale", type=int, default=180, help="pixels per game unit (default 180)")
    a = ap.parse_args()
    for body in a.bodies or list(BODIES):
        build(body, a.scale)


if __name__ == "__main__":
    main()

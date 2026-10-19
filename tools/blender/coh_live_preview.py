"""Live texture preview for CoH costume art in Blender.

Normally launched by the CoH Art Bridge (tools/art_bridge.py); it can also be run directly:
  blender <empty.blend> --python tools/blender/coh_live_preview.py -- --obj <mesh.obj> --base <color.png>
          [--mask <mask.png>] [--color1 #b0d8ff] [--color2 #2a6f8f] [--save <scene.blend>]

What it builds
- A "CoH Tint" material reproducing the game's two-color costume tint:
      color = base (grayscale detail) x mix(Color1, Color2, by mask)
  Without a mask the base is shown as-is (full-color NPC pieces like the Spirit face).
- A layout with one large isometric view and a Quad View (top, front, right, plus the opposite
  isometric corner), so all six sides show at once.
- A "CoH" tab in the 3D view sidebar (N): Color1/Color2 pickers and look presets:
    Flat         exactly the painted texture, no lighting
    Lit          approximate in-game lighting (key + fill + ambient)
    Ghostly      approximate Spirit look: translucent with a cool rim glow
    Croatoa dusk lit, under Croatoa's orange/purple zone light
  These approximate the game; the test server is the final check.
- A file watcher: images reload when their files change on disk.
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Euler

WATCH_SECONDS = 0.75

LOOKS = {
    # world color, world strength, flat amount, ghost amount, key light color, key energy
    "FLAT": ((0.12, 0.13, 0.16), 1.0, 1.0, 0.0, (1, 1, 1), 0.0),
    "LIT": ((0.35, 0.37, 0.42), 0.8, 0.0, 0.0, (1.0, 0.97, 0.92), 3.5),
    "GHOST": ((0.06, 0.08, 0.12), 0.6, 0.0, 1.0, (0.75, 0.9, 1.0), 2.0),
    "DUSK": ((0.30, 0.18, 0.28), 0.9, 0.0, 0.0, (1.0, 0.62, 0.32), 3.0),
}


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def load_image(path):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=True)
    # CoH texture alpha is a blend mask, never transparency.
    img.alpha_mode = "NONE"
    return img


def node(nt, kind, label, loc):
    n = nt.nodes.new(kind)
    n.label = label
    n.location = loc
    return n


def tint_material(base_path, mask_path, color1, color2):
    """Nodes are found later by label, so the sidebar controls can drive them."""
    mat = bpy.data.materials.new("CoH Tint")
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    mat.shadow_method = "HASHED"
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    out = nodes["Material Output"]
    nodes.remove(nodes["Principled BSDF"])
    out.location = (900, 0)

    base = node(nt, "ShaderNodeTexImage", "Base", (-1100, 300))
    base.image = load_image(base_path)
    color_socket = base.outputs["Color"]

    c1 = node(nt, "ShaderNodeRGB", "Color1", (-850, 520))
    c1.outputs[0].default_value = hex_rgb(color1) + (1.0,)
    c2 = node(nt, "ShaderNodeRGB", "Color2", (-850, 340))
    c2.outputs[0].default_value = hex_rgb(color2) + (1.0,)
    if mask_path:
        mask = node(nt, "ShaderNodeTexImage", "Mask", (-1100, 0))
        mask.image = load_image(mask_path)
        mask.image.colorspace_settings.name = "Non-Color"
        pick = node(nt, "ShaderNodeMix", "pick by mask", (-600, 420))
        pick.data_type = "RGBA"
        links.new(mask.outputs["Color"], pick.inputs["Factor"])
        links.new(c1.outputs[0], pick.inputs[6])
        links.new(c2.outputs[0], pick.inputs[7])
        mult = node(nt, "ShaderNodeMix", "x base", (-380, 380))
        mult.data_type = "RGBA"
        mult.blend_type = "MULTIPLY"
        mult.inputs["Factor"].default_value = 1.0
        links.new(pick.outputs[2], mult.inputs[6])
        links.new(base.outputs["Color"], mult.inputs[7])
        color_socket = mult.outputs[2]

    lit = node(nt, "ShaderNodeBsdfPrincipled", "Lit", (-150, 300))
    lit.inputs["Roughness"].default_value = 0.65
    links.new(color_socket, lit.inputs["Base Color"])
    flat = node(nt, "ShaderNodeEmission", "Flat", (-150, 0))
    links.new(color_socket, flat.inputs["Color"])
    flat_mix = node(nt, "ShaderNodeMixShader", "Flat amount", (150, 200))
    links.new(lit.outputs[0], flat_mix.inputs[1])
    links.new(flat.outputs[0], flat_mix.inputs[2])

    # Ghostly: fresnel rim glow added on top, then partial transparency.
    fres = node(nt, "ShaderNodeFresnel", "Rim", (-150, -250))
    fres.inputs["IOR"].default_value = 1.25
    rim = node(nt, "ShaderNodeEmission", "Rim glow", (100, -250))
    rim.inputs["Color"].default_value = (0.65, 0.9, 1.0, 1.0)
    rim_strength = node(nt, "ShaderNodeMath", "Rim strength", (-150, -420))
    rim_strength.operation = "MULTIPLY"
    links.new(fres.outputs[0], rim_strength.inputs[0])
    rim_strength.inputs[1].default_value = 0.0
    links.new(rim_strength.outputs[0], rim.inputs["Strength"])
    add = node(nt, "ShaderNodeAddShader", "+ rim", (380, 100))
    links.new(flat_mix.outputs[0], add.inputs[0])
    links.new(rim.outputs[0], add.inputs[1])
    clear = node(nt, "ShaderNodeBsdfTransparent", "Clear", (380, -100))
    ghost = node(nt, "ShaderNodeMixShader", "Opacity", (650, 0))
    ghost.inputs["Fac"].default_value = 1.0
    links.new(clear.outputs[0], ghost.inputs[1])
    links.new(add.outputs[0], ghost.inputs[2])
    links.new(ghost.outputs[0], out.inputs["Surface"])
    return mat


def mat_nodes():
    mat = bpy.data.materials.get("CoH Tint")
    return {n.label: n for n in mat.node_tree.nodes} if mat else {}


# ---------- sidebar controls ----------

def _set_color(label):
    def update(self, _ctx):
        n = mat_nodes().get(label)
        if n:
            n.outputs[0].default_value = tuple(getattr(self, "coh_" + label.lower())) + (1.0,)
    return update


def apply_look(scene, _ctx=None):
    world_color, world_strength, flat_amt, ghost_amt, key_color, key_energy = LOOKS[scene.coh_look]
    n = mat_nodes()
    if n:
        n["Flat amount"].inputs["Fac"].default_value = flat_amt
        n["Rim strength"].inputs[1].default_value = 2.5 * ghost_amt
        n["Opacity"].inputs["Fac"].default_value = 1.0 - ghost_amt * (1.0 - scene.coh_ghost_opacity)
    if scene.world:
        bg = scene.world.node_tree.nodes.get("Background")
        bg.inputs["Color"].default_value = world_color + (1.0,)
        bg.inputs["Strength"].default_value = world_strength
    key = bpy.data.objects.get("CoH Key")
    if key:
        key.data.color = key_color
        key.data.energy = key_energy


class COH_PT_preview(bpy.types.Panel):
    bl_label = "CoH Preview"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CoH"

    def draw(self, context):
        s = context.scene
        col = self.layout.column()
        col.prop(s, "coh_look", text="Look")
        if s.coh_look == "GHOST":
            col.prop(s, "coh_ghost_opacity", slider=True)
        col.separator()
        if "Mask" in mat_nodes():
            col.prop(s, "coh_color1")
            col.prop(s, "coh_color2")
        else:
            col.label(text="No mask: full-color piece")


def register_ui(color1, color2):
    S = bpy.types.Scene
    S.coh_color1 = bpy.props.FloatVectorProperty(name="Color1 (mask black)", subtype="COLOR", size=3,
                                                 min=0, max=1, default=hex_rgb(color1), update=_set_color("Color1"))
    S.coh_color2 = bpy.props.FloatVectorProperty(name="Color2 (mask white)", subtype="COLOR", size=3,
                                                 min=0, max=1, default=hex_rgb(color2), update=_set_color("Color2"))
    S.coh_look = bpy.props.EnumProperty(name="Look", items=[
        ("FLAT", "Flat (as painted)", "The texture exactly as painted, no lighting"),
        ("LIT", "Lit (game-like)", "Approximate in-game lighting"),
        ("GHOST", "Ghostly (Spirit FX)", "Translucent with a rim glow, like the Croatoa Spirits"),
        ("DUSK", "Croatoa dusk", "Lit under Croatoa's orange/purple light"),
    ], default="FLAT", update=apply_look)
    S.coh_ghost_opacity = bpy.props.FloatProperty(name="Ghost opacity", min=0.1, max=1.0, default=0.55,
                                                  update=apply_look)
    if not hasattr(bpy.types, "COH_PT_preview"):
        bpy.utils.register_class(COH_PT_preview)


# ---------- scene ----------

def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def first_window():
    wins = bpy.context.window_manager.windows
    return wins[0] if wins else None


def import_obj(path):
    window = first_window()
    if window is None:
        bpy.ops.wm.obj_import(filepath=path, forward_axis="NEGATIVE_Z", up_axis="Y")
        return
    # With the UI open, operators need a real window/area to run in.
    area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), window.screen.areas[0])
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.wm.obj_import(filepath=path, forward_axis="NEGATIVE_Z", up_axis="Y")


def build(args):
    if bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    else:
        # Keep the open UI; resetting factory settings here would tear down the window.
        clear_scene()
    import_obj(os.path.abspath(args.obj))
    mat = tint_material(args.base, args.mask, args.color1, args.color2)
    for o in bpy.context.scene.objects:
        o.select_set(False)
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(mat)
            for p in o.data.polygons:
                p.use_smooth = True
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.world = bpy.data.worlds.new("CoH preview")
    scene.world.use_nodes = True
    key = bpy.data.objects.new("CoH Key", bpy.data.lights.new("CoH Key", "SUN"))
    key.rotation_euler = Euler((math.radians(50), 0, math.radians(35)))
    scene.collection.objects.link(key)
    fill = bpy.data.objects.new("CoH Fill", bpy.data.lights.new("CoH Fill", "SUN"))
    fill.data.energy = 1.0
    fill.data.color = (0.75, 0.82, 1.0)
    fill.rotation_euler = Euler((math.radians(60), 0, math.radians(-145)))
    scene.collection.objects.link(fill)
    register_ui(args.color1, args.color2)
    apply_look(scene)
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save))


# ---------- layout ----------

def split(window, area, direction, factor):
    # Match areas by pointer, and redraw so the new sizes are real before anyone reads them.
    before = {a.as_pointer() for a in window.screen.areas}
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
        bpy.ops.screen.area_split(direction=direction, factor=factor)
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    new = [a for a in window.screen.areas if a.as_pointer() not in before]
    old = next(a for a in window.screen.areas if a.as_pointer() == area.as_pointer())
    if len(new) != 1:
        raise RuntimeError(f"area_split {direction}: {len(new)} new areas")
    return old, new[0]


def setup_view(window, area, axis=None, iso=False):
    space = area.spaces[0]
    space.shading.type = "MATERIAL"
    space.shading.use_scene_lights = True
    space.shading.use_scene_world = True
    space.overlay.show_floor = False
    space.overlay.show_axis_x = space.overlay.show_axis_y = False
    space.overlay.show_cursor = False
    space.overlay.show_extras = False          # hide light gizmo lines
    space.overlay.show_outline_selected = False
    space.show_gizmo_navigate = iso
    space.show_region_toolbar = False
    space.show_region_ui = iso
    if iso:
        for r in area.regions:
            if r.type == "UI":
                try:
                    r.active_panel_category = "CoH"
                except (AttributeError, TypeError):
                    pass
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=region):
        if axis:
            bpy.ops.view3d.view_axis(type=axis)
        bpy.ops.view3d.view_all(center=False)
    if iso:
        r3d = space.region_3d
        r3d.view_perspective = "ORTHO"
        r3d.view_rotation = ISO_FRONT.to_quaternion()
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.view3d.view_all(center=False)


ISO_FRONT = Euler((math.radians(54.7356), 0, math.radians(45)))      # sees top, front, right
ISO_BACK = Euler((math.radians(125.2644), 0, math.radians(225)))     # sees bottom, back, left


def build_layout():
    """Left: big isometric view. Right: Blender's Quad View (Top, Front, Right) whose fourth
    pane looks from the opposite corner, so all six sides are on screen at once."""
    window = first_window()
    main = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    a, b = split(window, main, "VERTICAL", 0.5)
    iso, quad = (a, b) if a.x < b.x else (b, a)
    setup_view(window, iso, iso=True)

    setup_view(window, quad)
    space = quad.spaces[0]
    region = next(r for r in quad.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=quad, region=region):
        bpy.ops.screen.region_quadview()
    r3d = space.region_3d
    r3d.view_perspective = "ORTHO"
    r3d.view_rotation = ISO_BACK.to_quaternion()
    for reg in quad.regions:
        if reg.type == "WINDOW":
            with bpy.context.temp_override(window=window, area=quad, region=reg):
                bpy.ops.view3d.view_all(center=False)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--obj", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--mask")
    ap.add_argument("--color1", default="#b0d8ff")
    ap.add_argument("--color2", default="#2a6f8f")
    ap.add_argument("--save")
    args = ap.parse_args(argv)
    if bpy.app.background:
        build(args)
        return

    # --python runs before Blender's window exists; build once the UI is up.
    def start():
        build(args)
        try:
            build_layout()
        except Exception as e:  # A layout hiccup shouldn't lose the preview itself.
            import traceback; traceback.print_exc()
            for a in first_window().screen.areas:
                if a.type == "VIEW_3D":
                    a.spaces[0].shading.type = "MATERIAL"
        bpy.app.timers.register(watch_images, persistent=True)
        return None

    bpy.app.timers.register(start, first_interval=0.5)


_mtimes = {}


def watch_images():
    for img in bpy.data.images:
        path = bpy.path.abspath(img.filepath) if img.filepath else ""
        if not path or not os.path.exists(path):
            continue
        try:
            m = os.path.getmtime(path)
        except OSError:
            continue
        if _mtimes.get(path) not in (None, m):
            img.reload()
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        _mtimes[path] = m
    return WATCH_SECONDS


if __name__ == "__main__":
    main()

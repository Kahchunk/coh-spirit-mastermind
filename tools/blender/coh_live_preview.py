"""Live texture preview for CoH costume art in Blender.

Paint in Photoshop, save, and the model in Blender updates within about a second.

Run (opens Blender with the scene set up):
  blender --python tools/blender/coh_live_preview.py -- --obj <mesh.obj> --base <base.png> [--mask <mask.png>]
          [--color1 #b0d8ff] [--color2 #2a6f8f] [--save <scene.blend>]

What it builds
- A "CoH Tint" material that reproduces the game's two-color costume tint:
      color = base (grayscale detail) x mix(Color1, Color2, by mask)
  Color1 / Color2 are plain color pickers on the material, so you can try player colors live.
  Without --mask the base texture is shown as-is (for full-color NPC pieces like the Spirit face).
- A file watcher: every image in the scene is reloaded when its file changes on disk.

Photoshop side: name the layer groups after files (e.g. "spirit_chest.png", "spirit_chest_mask.png")
and turn on File > Generate > Image Assets. Photoshop then rewrites those PNGs on every edit, and
this watcher picks them up.
"""
import argparse
import os
import sys

import bpy

WATCH_SECONDS = 0.75


def hex_rgba(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)


def load_image(path):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=True)
    # CoH texture alpha is a blend mask, never transparency.
    img.alpha_mode = "NONE"
    return img


def tint_material(base_path, mask_path, color1, color2):
    mat = bpy.data.materials.new("CoH Tint")
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.6

    base = nodes.new("ShaderNodeTexImage")
    base.label = "Base (grayscale detail)"
    base.image = load_image(base_path)
    base.location = (-900, 300)

    if not mask_path:
        links.new(base.outputs["Color"], bsdf.inputs["Base Color"])
        return mat

    mask = nodes.new("ShaderNodeTexImage")
    mask.label = "Mask (black=Color1, white=Color2)"
    mask.image = load_image(mask_path)
    mask.image.colorspace_settings.name = "Non-Color"
    mask.location = (-900, -50)

    c1 = nodes.new("ShaderNodeRGB")
    c1.label = "Color1"
    c1.outputs[0].default_value = hex_rgba(color1)
    c1.location = (-650, 450)
    c2 = nodes.new("ShaderNodeRGB")
    c2.label = "Color2"
    c2.outputs[0].default_value = hex_rgba(color2)
    c2.location = (-650, 250)

    pick = nodes.new("ShaderNodeMix")
    pick.data_type = "RGBA"
    pick.label = "pick color by mask"
    pick.location = (-400, 300)
    links.new(mask.outputs["Color"], pick.inputs["Factor"])
    links.new(c1.outputs[0], pick.inputs[6])
    links.new(c2.outputs[0], pick.inputs[7])

    mult = nodes.new("ShaderNodeMix")
    mult.data_type = "RGBA"
    mult.blend_type = "MULTIPLY"
    mult.label = "x base"
    mult.inputs["Factor"].default_value = 1.0
    mult.location = (-180, 300)
    links.new(pick.outputs[2], mult.inputs[6])
    links.new(base.outputs["Color"], mult.inputs[7])
    links.new(mult.outputs[2], bsdf.inputs["Base Color"])
    return mat


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


def build(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=os.path.abspath(args.obj), forward_axis="NEGATIVE_Z", up_axis="Y")
    mat = tint_material(args.base, args.mask, args.color1, args.color2)
    for o in bpy.context.scene.objects:
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(mat)
            for p in o.data.polygons:
                p.use_smooth = True
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    world = bpy.data.worlds.new("preview")
    world.color = (0.12, 0.13, 0.16)
    scene.world = world
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save))


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
    build(args)
    if not bpy.app.background:
        bpy.app.timers.register(watch_images, persistent=True)
        # Show the material in the viewport.
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces[0].shading.type = "MATERIAL"


if __name__ == "__main__":
    main()

"""Blender headless: render an OBJ with a texture applied, front and three-quarter views.

blender -b --factory-startup --python tools/render_textured.py -- <in.obj> <texture.png> <out_prefix>
"""
import math
import sys

import bpy
from mathutils import Vector

obj_path, tex_path, out = sys.argv[sys.argv.index("--") + 1:][:3]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=obj_path, forward_axis="NEGATIVE_Z", up_axis="Y")
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]

mat = bpy.data.materials.new("tex")
mat.use_nodes = True
nodes = mat.node_tree.nodes
bsdf = nodes["Principled BSDF"]
img = nodes.new("ShaderNodeTexImage")
img.image = bpy.data.images.load(tex_path)
# CoH texture alpha is a blend mask (skin tint), not transparency.
img.image.alpha_mode = "NONE"
mat.node_tree.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
for o in objs:
    o.data.materials.clear()
    o.data.materials.append(mat)
    for p in o.data.polygons:
        p.use_smooth = True

pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center, size = (lo + hi) / 2, max(hi - lo)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.render.resolution_x = scene.render.resolution_y = 640
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.12, 0.13, 0.16)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = size * 1.25
for label, direction in (("front", Vector((0, -1, 0))), ("threequarter", Vector((0.7, -0.7, 0.1)).normalized()), ("side", Vector((1, 0, 0)))):
    cam.location = center + direction * size * 4
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Z").to_euler()
    scene.render.filepath = f"{out}_{label}.png"
    bpy.ops.render.render(write_still=True)

"""Draw a mesh's UV layout over a texture: the paint guide you trace in Photoshop.

usage: python tools/uv_overlay.py <model.geo> <mesh name> <texture.png|-> <out.png> [size]
Pass "-" as the texture to get a bare UV template on transparent background.
"""
import sys

from PIL import Image, ImageDraw

import geo


def uv_overlay(mesh, texture=None, size=1024, color=(80, 220, 255, 255)):
    if texture is not None:
        base = texture.convert("RGBA").resize((size, size), Image.BILINEAR)
    else:
        base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    # v runs bottom-up; image rows run top-down.
    pts = [(u * size, (1 - v) * size) for u, v in mesh.sts]
    for a, b, c in mesh.tris:
        draw.polygon([pts[a], pts[b], pts[c]], outline=color)
    return base


def main():
    geo_path, name, tex, out = sys.argv[1:5]
    size = int(sys.argv[5]) if len(sys.argv) > 5 else 1024
    mesh = next(m for m in geo.read_geo(geo_path) if m.name == name)
    texture = None if tex == "-" else Image.open(tex)
    uv_overlay(mesh, texture, size).save(out)
    print(out, f"{len(mesh.tris)} triangles")


if __name__ == "__main__":
    main()

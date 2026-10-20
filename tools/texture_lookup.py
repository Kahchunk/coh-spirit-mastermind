"""Find the game texture a mesh uses, as images (read-only on the installed client).

A .geo names a texture per triangle range (geo.Model.textures). That name is either a plain texture
("Demon_Chest_Lieut.tga" -> texture_library/.../Demon_Chest_Lieut.texture) or a texture trick
("X_CustomWeapon_AssaultRifle_01"), which tricks.bin expands into a base, a _Mask and a _Bump texture.
"""
import os
import re

import extract_refs
import pigg
from texture import texture_to_image

_textures = None  # lowercased basename -> (archive, size, offset, packed)
_tricks = None    # tricks.bin bytes (Rebirth's copy when present)


def _texture_index():
    global _textures
    if _textures is None:
        _textures = {}
        # Later archives (Rebirth's) override earlier ones, as in the game.
        for arc in extract_refs.archives():
            for name, size, off, packed in pigg.pigg_entries(arc):
                if name.lower().endswith(".texture"):
                    key = os.path.splitext(os.path.basename(name))[0].lower()
                    _textures[key] = (arc, size, off, packed)
    return _textures


def _tricks_bin():
    global _tricks
    if _tricks is None:
        _tricks = b""
        for arc in extract_refs.archives():
            for name, size, off, packed in pigg.pigg_entries(arc):
                if name.lower() == "bin/tricks.bin":
                    _tricks = pigg.read_entry(arc, size, off, packed)
    return _tricks


def load_texture(name):
    """PIL image for a texture name (extension and folder ignored), or None."""
    key = os.path.splitext(os.path.basename(name))[0].lower()
    hit = _texture_index().get(key)
    if not hit:
        return None
    return texture_to_image(pigg.read_entry(*hit))


def expand_trick(name):
    """(base, mask) texture names for a layered-texture trick, or None if it isn't one."""
    blob = _tricks_bin()
    key = os.path.splitext(name)[0].encode("latin-1")
    for m in re.finditer(re.escape(key) + rb"\x00", blob):
        names = [s.decode("latin-1") for s in re.findall(rb"[\x20-\x7e]{3,}", blob[m.end():m.end() + 400])][:6]
        # Skip the trick's own name (it repeats), the helper maps (bump, mask, spec, reflection, normal),
        # "none" placeholders and the source path (all caps).
        own = key.decode("latin-1").lower()
        base = next((n for n in names if n.lower() != own and n.upper() != n
                     and not re.search(r"bump|mask|spec|reflect|normal|^none$", n, re.I)), None)
        mask = next((n for n in names if n.lower().endswith("_mask")), None)
        if base:
            return base, mask
    return None


def mesh_textures(model):
    """(color image, mask image or None, source description) for the mesh's main texture, or None.
    The main texture is the one covering the most triangles; "white" placeholders are skipped."""
    names = sorted((t for t in getattr(model, "textures", []) if not t[0].lower().startswith("white")),
                   key=lambda t: -t[1])
    for name, _count in names:
        img = load_texture(name)
        if img is not None:
            return img, None, name
        trick = expand_trick(name)
        if trick:
            base = load_texture(trick[0])
            if base is not None:
                mask = load_texture(trick[1]) if trick[1] else None
                return base, mask, f"{name} -> {trick[0]}" + (f" + {trick[1]}" if mask else "")
    return None

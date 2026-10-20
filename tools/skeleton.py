"""Read a body type's rest skeleton (the bone positions every costume piece is built around).

Each body type (male, female, huge) has a skel_*.anim in player_library/animations/<body>/. Format per
OuroDev's Common/seq/animtrack.h: a SkeletonAnimTrack header (header size, two 256-byte names,
hip displacement, length, then file offsets to the bone tracks and the bone hierarchy). Each bone
track's first position key is the bone's offset from its parent; walking the hierarchy gives the
rest pose. Rotations are identity in the rest pose, so the offsets simply add up.

Coordinates are the game's own: left-handed, Y up, the character faces +Z and its left side is at -X.
"""
import struct

import extract_refs
import pigg

SKELETONS = {
    "male": "player_library/animations/male/skel_ready2.anim",
    "female": "player_library/animations/fem/skel_ready2.anim",
    "huge": "player_library/animations/huge/Skel_ready.anim",
}

# BoneId order from OuroDev Common/seq/bones.h (the ones a body uses; extras keep their number).
BONE_NAMES = [
    "HIPS", "WAIST", "CHEST", "NECK", "HEAD", "COL_R", "COL_L", "UARMR", "UARML", "LARMR", "LARML",
    "HANDR", "HANDL", "F1_R", "F1_L", "F2_R", "F2_L", "T1_R", "T1_L", "T2_R", "T2_L", "T3_R", "T3_L",
    "ULEGR", "ULEGL", "LLEGR", "LLEGL", "FOOTR", "FOOTL", "TOER", "TOEL",
]

POSITION_UNCOMPRESSED = 1 << 3
POSITION_COMPRESSED_TO_6_BYTES = 1 << 4
BONES_ON_DISK = 100


def bone_name(bid):
    return BONE_NAMES[bid] if 0 <= bid < len(BONE_NAMES) else f"BONE_{bid}"


def parse_skeleton(blob):
    """{bone name: (x, y, z) rest position in world space} from a skel_*.anim file's bytes."""
    tracks_off, track_count = struct.unpack_from("<ii", blob, 0x20C)
    hier_off = struct.unpack_from("<i", blob, 0x21C)[0]
    local = {}
    for k in range(track_count):
        _rot, pos_idx, _rf, pos_full, _rc, _pc, bid, flags, _pad = struct.unpack_from("<iiHHHHbBH", blob, tracks_off + 20 * k)
        if not pos_full:
            continue
        if flags & POSITION_UNCOMPRESSED:
            local[bid] = struct.unpack_from("<3f", blob, pos_idx)
        elif flags & POSITION_COMPRESSED_TO_6_BYTES:
            local[bid] = tuple(v * 0.00003125 for v in struct.unpack_from("<3h", blob, pos_idx))
    root = struct.unpack_from("<i", blob, hier_off)[0]
    links = [struct.unpack_from("<3i", blob, hier_off + 4 + 12 * k) for k in range(BONES_ON_DISK)]  # child, next, id
    world = {}

    def walk(i, parent):
        while i != -1:
            child, nxt, bid = links[i]
            p = local.get(bid, (0.0, 0.0, 0.0))
            world[bid] = (parent[0] + p[0], parent[1] + p[1], parent[2] + p[2])
            if child != -1:
                walk(child, world[bid])
            i = nxt

    walk(root, (0.0, 0.0, 0.0))
    return {bone_name(b): p for b, p in world.items()}


def load_skeleton(body):
    """Rest skeleton for "male", "female" or "huge", read from the installed client."""
    want = SKELETONS[body].lower()
    hit = None
    for arc in extract_refs.archives():  # later archives (Rebirth's) win, as in the game
        for name, size, off, packed in pigg.pigg_entries(arc):
            if name.lower() == want:
                hit = (arc, size, off, packed)
    if not hit:
        raise SystemExit(f"{SKELETONS[body]} not found in the installed client")
    return parse_skeleton(pigg.read_entry(*hit))

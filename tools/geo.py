"""Read City of Heroes .geo (v8) model files. Read-only; used to export reference meshes.

Layout (worked out from the client's own files and validated against each model's bounding box):
  file:   u32 zsize, u32 0, u32 version, u32 header_size, zlib(header), packed data
  header: i32 datasize, texname_blk, objname_blk, texidx_blk, texnames, objnames, texidx, models...
  model:  244-byte record; counts, bounds and 3-int pack blocks (zipped, unzipped, offset) for
          tris, verts, norms, sts, sts3, weights, matidxs, grid.
Vertex streams are delta-compressed: 2-bit codes per value, then 0/1/2/4-byte payloads.
"""
import struct
import zlib

# version: (record size, name offset, bounds min, bounds max, first pack block)
# v7 lacks one int before the grid, so everything after it sits 4 bytes earlier.
LAYOUTS = {8: (244, 64, 84, 96, 108), 7: (232, 60, 80, 92, 104)}
PACK_NAMES = ("tris", "verts", "norms", "sts", "sts3", "weights", "matidxs", "grid")


class Model:
    def __init__(self, name, verts, tris, norms, sts, weights, matidxs, bounds, tex_count):
        self.name, self.verts, self.tris, self.norms, self.sts = name, verts, tris, norms, sts
        self.weights, self.matidxs, self.bounds, self.tex_count = weights, matidxs, bounds, tex_count


def _cstrings(block):
    """Offset-indexed null-terminated strings."""
    out, i = {}, 0
    while i < len(block):
        j = block.find(b"\0", i)
        if j < 0:
            break
        if j > i:
            out[i] = block[i:j].decode("latin-1")
        i = j + 1
    return out


def _unpack(data, base, packsize, unpacksize, offset):
    if unpacksize == 0:
        return b""
    raw = data[base + offset: base + offset + (packsize or unpacksize)]
    return zlib.decompress(raw) if packsize else raw


def uncompress_deltas(src, stride, count, is_float, int_plus=1):
    codes_len = (2 * count * stride + 7) // 8
    bits, pos = src[:codes_len], codes_len
    # One scale byte follows the codes in every stream; ints ignore it.
    scale_exp = src[pos]
    pos += 1
    inv = 1.0 / (1 << scale_exp) if scale_exp else 1.0
    out, last, cyc = [], [0] * stride, 0
    for _ in range(count):
        row = []
        for j in range(stride):
            code = (bits[cyc >> 3] >> (cyc & 7)) & 3
            cyc += 2
            if code == 0:
                ival = 0
            elif code == 1:
                ival = src[pos] - 0x7F
                pos += 1
            elif code == 2:
                ival = (src[pos] | src[pos + 1] << 8) - 0x7FFF
                pos += 2
            else:
                ival = struct.unpack_from("<i", src, pos)[0]
                pos += 4
            if is_float:
                if code == 3:
                    val = struct.unpack("<f", struct.pack("<i", ival))[0]
                else:
                    val = ival * inv + last[j]
            else:
                val = ival + last[j] + int_plus
            row.append(val)
            last[j] = val
        out.append(tuple(row))
    return out


def read_geo(path):
    data = open(path, "rb").read()
    zsize, _zero, version, hsize = struct.unpack_from("<4I", data, 0)
    if version not in LAYOUTS:
        raise ValueError(f"{path}: geo version {version} not supported ({sorted(LAYOUTS)})")
    record, off_name, off_min, off_max, off_packs = LAYOUTS[version]
    hdr = zlib.decompress(data[16:4 + zsize])
    base = 4 + zsize
    datasize, texblk, objblk, texidxblk = struct.unpack_from("<4i", hdr, 0)
    p = 16
    texnames_raw = hdr[p:p + texblk]
    p += texblk
    objnames = _cstrings(hdr[p:p + objblk])
    p += objblk + texidxblk
    # Model-header block: name[124], ptr, float length, -1, model count; then the records.
    model_count = struct.unpack_from("<i", hdr, p + 136)[0]
    p += 140
    models = []
    while len(models) < model_count and p + record <= len(hdr):
        rec = hdr[p:p + record]
        size, radius, tex_count, _bone_ptr, nverts, ntris = struct.unpack_from("<if4i", rec, 0)
        if size != record:
            break
        name_off = struct.unpack_from("<i", rec, off_name)[0]
        mins = struct.unpack_from("<3f", rec, off_min)
        maxs = struct.unpack_from("<3f", rec, off_max)
        packs = [struct.unpack_from("<3i", rec, off_packs + 12 * k) for k in range(len(PACK_NAMES))]
        blobs = {n: _unpack(data, base, *pk) for n, pk in zip(PACK_NAMES, packs)}
        tris = uncompress_deltas(blobs["tris"], 3, ntris, False) if blobs["tris"] else []
        verts = uncompress_deltas(blobs["verts"], 3, nverts, True) if blobs["verts"] else []
        norms = uncompress_deltas(blobs["norms"], 3, nverts, True) if blobs["norms"] else []
        sts = uncompress_deltas(blobs["sts"], 2, nverts, True) if blobs["sts"] else []
        models.append(Model(objnames.get(name_off, f"model_{len(models)}"), verts, tris, norms, sts,
                            blobs["weights"], blobs["matidxs"], (mins, maxs), tex_count))
        p += record
    return models


def write_obj(models, path, include=lambda m: True):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# exported from CoH .geo for reference\n")
        vo = to = no = 1
        for m in models:
            if not include(m) or not m.verts:
                continue
            f.write(f"o {m.name}\n")
            for x, y, z in m.verts:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            for u, v in m.sts:
                # CoH st.v already runs bottom-up like OBJ; verified on the Croatoa Spirit face.
                f.write(f"vt {u:.6f} {v:.6f}\n")
            for x, y, z in m.norms:
                f.write(f"vn {x:.6f} {y:.6f} {z:.6f}\n")
            has_t, has_n = bool(m.sts), bool(m.norms)
            for a, b, c in m.tris:
                idx = []
                for i in (a, b, c):
                    s = f"{i + vo}"
                    if has_t or has_n:
                        s += f"/{i + to if has_t else ''}"
                    if has_n:
                        s += f"/{i + no}"
                    idx.append(s)
                f.write("f " + " ".join(idx) + "\n")
            vo += len(m.verts)
            to += len(m.sts)
            no += len(m.norms)

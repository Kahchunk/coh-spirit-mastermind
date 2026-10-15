"""Read-only access to City of Heroes .pigg archives and Parse6 .bin files."""
import re
import struct
import zlib

IDENT = re.compile(rb"[\x20-\x7e]{3,}")


def read_pigg(path, name_filter=None):
    """Yield (internal_path, bytes) for each entry, optionally filtered by substring."""
    with open(path, "rb") as f:
        data = f.read()
    marker, _iv, _v, hsize, esize, n = struct.unpack_from("<IHHHHI", data, 0)
    if marker != 0x123:
        raise ValueError(f"{path}: not a pigg archive")
    off = hsize
    entries = []
    for _ in range(n):
        _m, name_id, size, _ts, offset, _r, _hd = struct.unpack_from("<7I", data, off)
        packed = struct.unpack_from("<I", data, off + 44)[0]
        entries.append((name_id, size, offset, packed))
        off += esize
    _m, count, _tsize = struct.unpack_from("<3I", data, off)
    off += 12
    names = []
    for _ in range(count):
        ln = struct.unpack_from("<I", data, off)[0]
        off += 4
        names.append(data[off:off + ln].rstrip(b"\0").decode("latin-1"))
        off += ln
    for name_id, size, offset, packed in entries:
        name = names[name_id]
        if name_filter and name_filter.lower() not in name.lower():
            continue
        if packed:
            raw = data[offset:offset + packed]
            try:
                blob = zlib.decompress(raw)
            except zlib.error:
                blob = zlib.decompress(raw[4:])
        else:
            blob = data[offset:offset + size]
        yield name, blob


def bin_strings(blob, minlen=3):
    """Printable strings in a .bin, in file order."""
    return [m.group().decode() for m in IDENT.finditer(blob) if len(m.group()) >= minlen]


def bin_source_files(blob):
    """Source-file manifest ("Files1" block) of a Parse6 .bin, or [] if absent."""
    i = blob.find(b"Files1")
    if i < 0:
        return []
    i += 6
    _blocklen, count = struct.unpack_from("<II", blob, i)
    i += 8
    out = []
    for _ in range(count):
        ln = struct.unpack_from("<H", blob, i)[0]
        i += 2
        out.append(blob[i:i + ln].decode("latin-1"))
        i += ln
        i += (4 - (ln + 2) % 4) % 4
        i += 4
    return out

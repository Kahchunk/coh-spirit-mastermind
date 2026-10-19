"""Read-only access to City of Heroes .pigg archives and Parse6 .bin files."""
import re
import struct
import zlib

IDENT = re.compile(rb"[\x20-\x7e]{3,}")


def pigg_entries(path):
    """[(internal_path, size, offset, packed)] from the archive's directory, without reading entry data."""
    with open(path, "rb") as f:
        head = f.read(16)
        marker, _iv, _v, hsize, esize, n = struct.unpack_from("<IHHHHI", head, 0)
        if marker != 0x123:
            raise ValueError(f"{path}: not a pigg archive")
        f.seek(hsize)
        table = f.read(n * esize + 12)
        _m, count, tsize = struct.unpack_from("<3I", table, n * esize)
        strings = f.read(tsize)
    entries = []
    for k in range(n):
        _m, name_id, size, _ts, offset, _r, _hd = struct.unpack_from("<7I", table, k * esize)
        packed = struct.unpack_from("<I", table, k * esize + 44)[0]
        entries.append((name_id, size, offset, packed))
    names, off = [], 0
    for _ in range(count):
        ln = struct.unpack_from("<I", strings, off)[0]
        off += 4
        names.append(strings[off:off + ln].rstrip(b"\0").decode("latin-1"))
        off += ln
    return [(names[i], size, offset, packed) for i, size, offset, packed in entries]


def _inflate(raw, packed, size):
    if not packed:
        return raw
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return zlib.decompress(raw[4:])


def read_entry(path, size, offset, packed):
    """One entry's bytes, reading only that entry from disk."""
    with open(path, "rb") as f:
        f.seek(offset)
        return _inflate(f.read(packed or size), packed, size)


def read_pigg(path, name_filter=None):
    """Yield (internal_path, bytes) for each entry, optionally filtered by substring."""
    with open(path, "rb") as f:
        data = f.read()
    for name, size, offset, packed in pigg_entries(path):
        if name_filter and name_filter.lower() not in name.lower():
            continue
        yield name, _inflate(data[offset:offset + (packed or size)], packed, size)


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

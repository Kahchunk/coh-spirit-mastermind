"""Convert City of Heroes .texture files to PNG (read-only on the client).

A .texture is a small header (its first u32 is the header size) followed by a standard DDS image.
"""
import io
import struct

from PIL import Image


def texture_to_image(blob):
    header_size = struct.unpack_from("<I", blob, 0)[0]
    dds = blob[header_size:]
    if dds[:4] != b"DDS ":
        i = blob.find(b"DDS ")
        if i < 0:
            raise ValueError("no DDS payload found")
        dds = blob[i:]
    return Image.open(io.BytesIO(dds))


def texture_to_png(blob, out_path):
    img = texture_to_image(blob)
    img.save(out_path)
    return img.size

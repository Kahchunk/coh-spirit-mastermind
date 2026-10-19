"""Package the CoH Preview panel as a .ccx you can double-click to install into Photoshop.

usage: python tools/photoshop/package_plugin.py
Writes tools/photoshop/dist/coh-preview.ccx (a zip of the plugin folder).
"""
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "coh-preview")
OUT = os.path.join(HERE, "dist", "coh-preview.ccx")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            full = os.path.join(root, f)
            z.write(full, os.path.relpath(full, SRC))
print(OUT)

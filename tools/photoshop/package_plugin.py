"""Package the CoH Preview panel as a .ccx you can double-click to install into Photoshop.

usage: python tools/photoshop/package_plugin.py [--install]
Writes tools/photoshop/dist/coh-preview.ccx (a zip of the plugin folder).

--install also installs it with Adobe's plugin installer, removing any installed copy first:
installing a new version doesn't replace the old one, and Photoshop then loads whichever copy it
finds first (usually the old one). Quit Photoshop before installing.
"""
import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "coh-preview")
OUT = os.path.join(HERE, "dist", "coh-preview.ccx")
NAME = "CoH Preview"
UPIA = os.path.join(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"), "Adobe",
                    "Adobe Desktop Common", "RemoteComponents", "UPI", "UnifiedPluginInstallerAgent",
                    "UnifiedPluginInstallerAgent.exe")


def package():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(SRC):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, SRC))
    print(OUT)


def installed_copies():
    out = subprocess.run([UPIA, "/list", "all"], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if NAME in line)


def install():
    tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Photoshop.exe", "/NH"], capture_output=True, text=True).stdout
    if "Photoshop.exe" in tasks:
        sys.exit("Quit Photoshop first; it keeps the old copy loaded.")
    for _ in range(installed_copies()):
        subprocess.run([UPIA, "/remove", NAME], check=True)
    subprocess.run([UPIA, "/install", OUT], check=True)
    if installed_copies() != 1:
        sys.exit("expected exactly one installed copy; check the Creative Cloud plugin list")


if __name__ == "__main__":
    package()
    if "--install" in sys.argv:
        install()

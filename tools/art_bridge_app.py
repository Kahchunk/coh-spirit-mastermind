"""CoH Art Bridge app: find any model, preview it, open its texture in Photoshop.

Left: every mesh in the installed client (LODs hidden) plus your parts in art/work, searchable.
Right: a preview of the selection. "Open in Photoshop" opens the part's .psd, first creating the
part (mesh + starter PSD with a UV guide) if it's a game mesh you haven't started yet.

The live-preview bridge (Photoshop -> 3ds Max -> CoH Preview panel) runs inside the app, so this
is the only window to leave open.

    pythonw tools/art_bridge_app.py [starting search]
"""
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

sys.path.insert(0, os.path.dirname(__file__))
import art_bridge  # noqa: E402
import extract_refs  # noqa: E402
import geo  # noqa: E402
import pigg  # noqa: E402

INDEX = os.path.join(art_bridge.WORK, ".model_index.json")
INDEX_VERSION = 1
MAX_ROWS = 2500
PREVIEW = 800

BG, PANEL, FIELD, TEXT, MUTED, ACCENT = "#1e1f22", "#26282c", "#2f3236", "#e3e5e8", "#9097a0", "#4c8dff"


# ---------- model index ----------

def _index_key():
    return [[os.path.basename(a), os.path.getmtime(a), os.path.getsize(a)] for a in extract_refs.archives()]


def build_index():
    """[{geo, mesh, tris, arc, size, off, packed}] for every non-LOD mesh; cached until the client updates."""
    key = _index_key()
    try:
        cached = json.load(open(INDEX, encoding="utf-8"))
        if cached.get("version") == INDEX_VERSION and cached.get("key") == key:
            return cached["models"]
    except (OSError, ValueError):
        pass
    found = {}
    # Later archives (Rebirth's) override earlier ones, as in the game.
    for arc in extract_refs.archives():
        for name, size, off, packed in pigg.pigg_entries(arc):
            if name.lower().endswith(".geo"):
                found[name] = (arc, size, off, packed)
    models = []
    for name, (arc, size, off, packed) in sorted(found.items()):
        try:
            heads = geo.parse_geo(pigg.read_entry(arc, size, off, packed), decode=False)
        except Exception:  # pre-v7 world props; nothing we'd texture for costumes anyway
            continue
        for m in heads:
            if "LOD" in m.name.upper() or not m.ntris:
                continue
            models.append({"geo": name, "mesh": m.name, "tris": m.ntris,
                           "arc": arc, "size": size, "off": off, "packed": packed})
    os.makedirs(art_bridge.WORK, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump({"version": INDEX_VERSION, "key": key, "models": models}, f)
    return models


def load_entry(entry):
    data = pigg.read_entry(entry["arc"], entry["size"], entry["off"], entry["packed"])
    models = geo.parse_geo(data)
    return models, next(m for m in models if m.name == entry["mesh"])


# ---------- preview rendering ----------

def _rot(yaw, pitch):
    cy, sy, cp, sp = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    return rx @ ry


def render_views(model, size=PREVIEW):
    """2x2 sheet (iso front, iso back, front, side), lit with the game's normals. CoH is Y-up, +Z forward."""
    v = np.array(model.verts, dtype=float)
    n = np.array(model.norms, dtype=float) if model.norms else None
    tris = np.array(model.tris, dtype=int)
    v -= (v.min(0) + v.max(0)) / 2
    radius = np.linalg.norm(v, axis=1).max() or 1.0
    views = (("iso front", _rot(np.radians(35), np.radians(25))), ("iso back", _rot(np.radians(215), np.radians(25))),
             ("front", _rot(0, 0)), ("side", _rot(np.radians(90), 0)))
    cell = size // 2
    sheet = Image.new("RGB", (size, size), PANEL)
    light = np.array([-0.4, 0.6, 0.7]) / np.linalg.norm([-0.4, 0.6, 0.7])
    for k, (label, r) in enumerate(views):
        img = _raster(v @ r.T, (n @ r.T) if n is not None else None, tris, radius, cell, light)
        ox, oy = (k % 2) * cell, (k // 2) * cell
        sheet.paste(img, (ox, oy))
        ImageDraw.Draw(sheet).text((ox + 8, oy + 6), label, fill=MUTED)
    return sheet


def _raster(p, nrm, tris, radius, cell, light):
    scale = cell * 0.44 / radius
    sx = p[:, 0] * scale + cell / 2
    sy = cell / 2 - p[:, 1] * scale
    z = p[:, 2]
    if nrm is not None:
        shade_v = np.clip(nrm @ light, 0, 1)
    color = np.full((cell, cell, 3), np.array([38, 40, 44], dtype=float))
    depth = np.full((cell, cell), -np.inf)
    base = np.array([168, 186, 210], dtype=float)
    for a, b, c in tris:
        xs, ys = sx[[a, b, c]], sy[[a, b, c]]
        x0, x1 = int(max(xs.min(), 0)), int(min(xs.max() + 1, cell - 1))
        y0, y1 = int(max(ys.min(), 0)), int(min(ys.max() + 1, cell - 1))
        if x1 < x0 or y1 < y0:
            continue
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * z[a] + w1 * z[b] + w2 * z[c]
        region = depth[y0:y1 + 1, x0:x1 + 1]
        win = inside & (zz > region)
        if not win.any():
            continue
        region[win] = zz[win]
        if nrm is not None:
            s = w0 * shade_v[a] + w1 * shade_v[b] + w2 * shade_v[c]
        else:
            fn = np.cross(p[b] - p[a], p[c] - p[a])
            s = np.full(zz.shape, abs(fn @ light) / (np.linalg.norm(fn) or 1))
        lit = (0.28 + 0.72 * s)[..., None] * base
        color[y0:y1 + 1, x0:x1 + 1][win] = lit[win]
    return Image.fromarray(color.clip(0, 255).astype(np.uint8))


# ---------- app ----------

def part_name_for(entry):
    stem = os.path.splitext(os.path.basename(entry["geo"]))[0]
    mesh = re.sub(r"^GEO_", "", entry["mesh"], flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", f"{stem}_{mesh}".lower()).strip("_")


class App:
    def __init__(self, root):
        self.root = root
        self.models, self.rows, self.parts = [], [], []
        self.preview_cache, self.current = {}, None
        self.logq = queue.Queue()
        root.title("CoH Art Bridge")
        root.geometry("1280x820")
        root.minsize(900, 600)
        root.configure(bg=BG)
        self._style()

        split = tk.PanedWindow(root, orient="horizontal", bg=BG, sashwidth=10, bd=0)
        split.pack(fill="both", expand=True, padx=14, pady=14)
        left = tk.Frame(split, bg=BG)
        right = tk.Frame(split, bg=BG)
        split.add(left, minsize=420, stretch="always")
        split.add(right, minsize=380, stretch="always")
        root.after(50, lambda: split.sash_place(0, int(root.winfo_width() * 0.52), 0))

        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._schedule_filter())
        entry = ttk.Entry(bar, textvariable=self.search, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.focus_set()
        self.scope = tk.StringVar(value="Costume pieces")
        scope = ttk.Combobox(bar, textvariable=self.scope, state="readonly", width=16,
                             values=("Costume pieces", "My parts", "Objects", "Everything"))
        scope.pack(side="left", padx=(8, 0), ipady=3)
        scope.bind("<<ComboboxSelected>>", lambda _e: self._filter())
        self.count = tk.Label(left, text="Indexing the client...", bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9))
        self.count.pack(fill="x", pady=(6, 4))

        cols = ("mesh", "file", "tris")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, w, label in (("mesh", 260, "Model"), ("file", 280, "File"), ("tris", 64, "Tris")):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, minwidth=60, anchor="e" if c == "tris" else "w", stretch=c != "tris")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._select())
        self.tree.bind("<Double-1>", lambda _e: self._open())
        self.tree.bind("<Return>", lambda _e: self._open())
        entry.bind("<Down>", lambda _e: self._focus_list())
        entry.bind("<Return>", lambda _e: self._open())

        # Bottom-up so the preview takes whatever height is left.
        self.log = tk.Text(right, height=5, bg=PANEL, fg=MUTED, relief="flat", font=("Consolas", 9), wrap="word")
        self.log.pack(side="bottom", fill="x", pady=(12, 0))
        buttons = tk.Frame(right, bg=BG)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        self.open_btn = ttk.Button(buttons, text="Open in Photoshop", style="Accent.TButton", command=self._open)
        self.open_btn.pack(side="left")
        self.folder_btn = ttk.Button(buttons, text="Show folder", command=self._show_folder)
        self.folder_btn.pack(side="left", padx=8)
        self.info = tk.Label(right, text="", bg=BG, fg=MUTED, anchor="w", justify="left", font=("Segoe UI", 9))
        self.info.pack(side="bottom", fill="x")
        self.title = tk.Label(right, text="", bg=BG, fg=TEXT, anchor="w", font=("Segoe UI Semibold", 12))
        self.title.pack(side="bottom", fill="x", pady=(10, 0))
        self.canvas = tk.Label(right, bg=PANEL)
        self.canvas.pack(side="top", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._refit())
        self._shown = None

        self._filter_job = None
        threading.Thread(target=self._load, daemon=True).start()
        self._start_bridge()
        root.after(200, self._drain_log)

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=FIELD,
                    lightcolor=FIELD, darkcolor=FIELD, troughcolor=PANEL, arrowcolor=MUTED)
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=24,
                    font=("Segoe UI", 10), borderwidth=0)
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        s.configure("Treeview.Heading", background=FIELD, foreground=MUTED, relief="flat", font=("Segoe UI", 9))
        s.map("Treeview.Heading", background=[("active", FIELD)])
        s.configure("Vertical.TScrollbar", background=FIELD, troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTED)
        s.map("Vertical.TScrollbar", background=[("active", "#3a3e44")])
        s.configure("TEntry", foreground=TEXT, insertcolor=TEXT, padding=6)
        s.configure("TCombobox", foreground=TEXT, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        s.configure("TButton", background=FIELD, foreground=TEXT, padding=(14, 7), borderwidth=0)
        s.map("TButton", background=[("active", "#3a3e44"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=("Segoe UI Semibold", 10))
        s.map("Accent.TButton", background=[("active", "#3a78e6"), ("disabled", PANEL)])

    # --- data ---

    def _load(self):
        try:
            models = build_index()
        except Exception as e:
            self.logq.put(f"couldn't index the client: {e}")
            models = []
        self.root.after(0, lambda: self._loaded(models))

    def _loaded(self, models):
        self.models = models
        self._filter()

    def _refresh_parts(self):
        self.parts = art_bridge.find_parts()
        self.part_by_source = {}
        for p in self.parts:
            src = p.read_cfg().get("source")
            if src:
                self.part_by_source[(src["game"], src["mesh"])] = p

    def _schedule_filter(self):
        if self._filter_job:
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(150, self._filter)

    def _filter(self):
        self._refresh_parts()
        words = self.search.get().lower().split()
        scope = self.scope.get()
        rows = []
        if scope in ("My parts", "Everything", "Costume pieces"):
            for p in self.parts:
                hay = p.name.lower()
                if all(w in hay for w in words):
                    rows.append(("part", p))
        if scope != "My parts":
            for m in self.models:
                lib = m["geo"].startswith("player_library/")
                if (scope == "Costume pieces" and not lib) or (scope == "Objects" and lib):
                    continue
                hay = (m["mesh"] + " " + m["geo"]).lower()
                if all(w in hay for w in words):
                    rows.append(("game", m))
        self.rows = rows[:MAX_ROWS]
        self.tree.delete(*self.tree.get_children())
        for i, (kind, item) in enumerate(self.rows):
            if kind == "part":
                self.tree.insert("", "end", iid=str(i), values=(f"★ {item.name}", "art/work", ""))
            else:
                self.tree.insert("", "end", iid=str(i), values=(item["mesh"], item["geo"], item["tris"]))
        more = f" (showing first {MAX_ROWS}; keep typing)" if len(rows) > MAX_ROWS else ""
        self.count.config(text=f"{len(rows):,} matches{more}" if self.models or rows else "Indexing the client...")
        if self.rows:
            self.tree.selection_set("0")

    def _focus_list(self):
        self.tree.focus_set()
        if self.rows:
            self.tree.focus("0")

    def _selected(self):
        sel = self.tree.selection()
        return self.rows[int(sel[0])] if sel else None

    # --- preview ---

    def _select(self):
        row = self._selected()
        if not row:
            return
        kind, item = row
        self.current = row
        if kind == "part":
            self.title.config(text=item.name)
            src = item.read_cfg().get("source")
            self.info.config(text=(f"from {src['game']} / {src['mesh']}\n" if src else "") + item.folder)
            self.open_btn.config(text="Open in Photoshop")
            self.folder_btn.state(["!disabled"])
            if os.path.exists(item.sheet_png):
                self._show(Image.open(item.sheet_png).convert("RGB"), row)
            elif item.mesh:
                self._render_async(row, lambda: _obj_model(item.mesh))
            return
        part = self.part_by_source.get((item["geo"], item["mesh"]))
        self.title.config(text=item["mesh"])
        self.info.config(text=f"{item['geo']}\n{item['tris']:,} triangles  ·  {os.path.basename(item['arc'])}"
                         + (f"\nyour part: {part.name}" if part else ""))
        self.open_btn.config(text="Open in Photoshop" if part else "Start part + open in Photoshop")
        self.folder_btn.state(["!disabled"] if part else ["disabled"])
        self._render_async(row, lambda: load_entry(item)[1])

    def _render_async(self, row, get_model):
        key = id(row[1]) if row[0] == "part" else (row[1]["geo"], row[1]["mesh"])
        if key in self.preview_cache:
            self._show(self.preview_cache[key], row)
            return
        self._shown = None
        self.canvas.config(image="", text="rendering...", fg=MUTED)

        def work():
            try:
                img = render_views(get_model())
            except Exception as e:
                img = Image.new("RGB", (PREVIEW, PREVIEW), PANEL)
                ImageDraw.Draw(img).text((16, 16), f"no preview: {e}", fill=MUTED)
            self.preview_cache[key] = img
            self.root.after(0, lambda: self._show(img, row))
        threading.Thread(target=work, daemon=True).start()

    def _show(self, img, row):
        if row is not self.current:
            return
        self._shown = img
        self._refit()

    def _refit(self):
        if self._shown is None:
            return
        w, h = self.canvas.winfo_width() - 8, self.canvas.winfo_height() - 8
        if w < 50 or h < 50:
            return
        img = self._shown.copy()
        k = min(w / img.width, h / img.height)
        img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.config(image=self._photo, text="")

    # --- actions ---

    def _open(self):
        row = self._selected()
        if not row:
            return
        kind, item = row
        if kind == "game":
            part = self.part_by_source.get((item["geo"], item["mesh"]))
            if not part:
                part = self._create(item)
                if not part:
                    return
        else:
            part = item
        os.startfile(part.psd)
        self.logq.put(f"opening {part.name}.psd in Photoshop")

    def _create(self, entry):
        name = simpledialog.askstring("New part", "Part name (folder in art/work):",
                                      initialvalue=part_name_for(entry), parent=self.root)
        if not name:
            return None
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
        if os.path.exists(os.path.join(art_bridge.WORK, name)):
            messagebox.showerror("New part", f"art/work/{name} already exists.", parent=self.root)
            return None
        try:
            folder = art_bridge.new_part(name, game=entry["geo"], mesh=entry["mesh"], loaded=load_entry(entry))
        except BaseException as e:  # new_part reports problems with SystemExit
            messagebox.showerror("New part", str(e), parent=self.root)
            return None
        self._filter()
        return art_bridge.Part(folder)

    def _show_folder(self):
        row = self._selected()
        if not row:
            return
        kind, item = row
        part = item if kind == "part" else self.part_by_source.get((item["geo"], item["mesh"]))
        if part:
            os.startfile(part.folder)

    # --- bridge ---

    def _start_bridge(self):
        original = art_bridge.log

        def log(msg):
            self.logq.put(msg.replace("  (Ctrl+C to stop)", ""))
            try:
                original(msg)
            except Exception:  # no console under pythonw
                pass
        art_bridge.log = log
        threading.Thread(target=self._bridge_loop, daemon=True).start()

    def _bridge_loop(self):
        while True:
            try:
                art_bridge.run()
            except Exception as e:
                self.logq.put(f"bridge error: {e}; restarting")
                threading.Event().wait(3)

    def _drain_log(self):
        while not self.logq.empty():
            self.log.insert("end", self.logq.get() + "\n")
            self.log.see("end")
        self.root.after(250, self._drain_log)


def _obj_model(path):
    """Minimal OBJ reader for parts made from an outside mesh (positions + normals)."""
    verts, norms, tris = [], [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        t = line.split()
        if not t:
            continue
        if t[0] == "v":
            verts.append(tuple(map(float, t[1:4])))
        elif t[0] == "vn":
            norms.append(tuple(map(float, t[1:4])))
        elif t[0] == "f":
            idx = [int(x.split("/")[0]) - 1 for x in t[1:]]
            tris += [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]
    m = geo.Model(os.path.basename(path), verts, tris, norms if len(norms) == len(verts) else [], [], b"", b"", None, 0)
    return m


def main():
    if sys.stdout is None:  # pythonw: art_bridge.log prints
        sys.stdout = sys.stderr = open(os.devnull, "w")
    try:  # crisp text on high-DPI screens; must happen before the window exists
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:  # optional starting search, e.g. art_bridge_app.py male_shirt chest
        app.search.set(" ".join(sys.argv[1:]))
    root.mainloop()


if __name__ == "__main__":
    main()

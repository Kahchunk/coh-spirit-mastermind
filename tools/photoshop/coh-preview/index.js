// CoH Preview panel: one rotatable view of the part whose .psd is active, plus its preview settings.
// Dragging writes the angle to the part's .preview/orbit.txt; 3ds Max turns its view to match and
// publishes .preview/view.frame (a JPEG draft while you drag, a PNG once you stop), which this panel
// shows. Settings go to part.json via the CoH Art Bridge.
const { app } = require("photoshop");
const fs = require("fs");

const POLL_MS = 50;
const SETTLE_MS = 250; // after the last drag/zoom input, ask Max for the full-quality frame
const DEFAULT_ORBIT = { yaw: 35, pitch: 25, zoom: 1 };
const ZOOM_MIN = 0.25, ZOOM_MAX = 8;
const $ = (id) => document.getElementById(id);
let current = { dir: null, viewStamp: null, cfg: {} };
let orbit = { ...DEFAULT_ORBIT };
let orbitWritten = "";
let lastInput = 0;

function dirOf(p) {
  const i = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
  return i >= 0 ? p.slice(0, i) : p;
}
const join = (...parts) => parts.join("\\");

function activePsdPath() {
  try {
    const doc = app.activeDocument;
    const p = doc && doc.path;
    return p && /\.psd$/i.test(p) ? p : null;
  } catch (e) {
    return null;
  }
}

async function exists(p) {
  try { await fs.lstat(p); return true; } catch (e) { return false; }
}

async function stamp(p) {
  try {
    const s = await fs.lstat(p);
    return String(s.mtimeMs || (s.mtime && s.mtime.getTime && s.mtime.getTime()) || s.size) + ":" + s.size;
  } catch (e) { return null; }
}

// Lookup table + chunked join: much faster than growing one string a character at a time.
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const PAIRS = [];
for (let i = 0; i < 4096; i++) PAIRS.push(B64[i >> 6] + B64[i & 63]);
function toBase64(buf) {
  const b = new Uint8Array(buf);
  const chunks = [];
  let part = [];
  const full = b.length - (b.length % 3);
  for (let i = 0; i < full; i += 3) {
    const n = (b[i] << 16) | (b[i + 1] << 8) | b[i + 2];
    part.push(PAIRS[n >> 12] + PAIRS[n & 4095]);
    if (part.length === 8192) { chunks.push(part.join("")); part = []; }
  }
  if (b.length - full === 1) {
    const n = b[full] << 16;
    part.push(B64[n >> 18] + B64[(n >> 12) & 63] + "==");
  } else if (b.length - full === 2) {
    const n = (b[full] << 16) | (b[full + 1] << 8);
    part.push(B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + "=");
  }
  chunks.push(part.join(""));
  return chunks.join("");
}

async function readCfg(dir) {
  try { return JSON.parse(await fs.readFile(join(dir, "part.json"), { encoding: "utf-8" })); }
  catch (e) { return {}; }
}

async function writeCfg() {
  if (!current.dir) return;
  await fs.writeFile(join(current.dir, "part.json"), JSON.stringify(current.cfg, null, 2), { encoding: "utf-8" });
  $("status").textContent = "Settings saved, re-rendering...";
}

function showCfg() {
  const c = current.cfg;
  $("look").value = c.look || "FLAT";
  $("c1").value = c.color1 || "#b0d8ff";
  $("c2").value = c.color2 || "#2a6f8f";
  $("sw1").style.backgroundColor = $("c1").value;
  $("sw2").style.backgroundColor = $("c2").value;
}

// ---------- double-buffered view ----------
// The new frame decodes in the hidden image and only then swaps in, so the panel never blanks
// or changes height between frames.

let front = $("viewA"), back = $("viewB");
let pending = null;     // the hidden image currently decoding the newest frame
let pendingTimer = null;

function keepSquare() {
  const stage = $("stage");
  const w = stage.offsetWidth;
  if (w && stage.style.height !== w + "px") stage.style.height = w + "px";
}

// Exactly one swap per frame: whichever comes first, the image's load event or the fallback timer,
// commits it, and anything late for an older frame is ignored. (Two swaps per frame used to flip
// back to the previous image for a moment.)
function commit(img) {
  if (img !== pending) return;
  pending = null;
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
  img.style.visibility = "visible";
  const other = img === front ? back : front;
  other.style.visibility = "hidden";
  front = img;
  back = other;
}

for (const img of [front, back]) img.addEventListener("load", () => commit(img));

// A frame is complete when it ends with its format's end marker; anything else is still being written.
function frameMime(b) {
  const n = b.length;
  if (n > 4 && b[0] === 0xff && b[1] === 0xd8) return b[n - 2] === 0xff && b[n - 1] === 0xd9 ? "image/jpeg" : null;
  if (n > 12 && b[0] === 0x89 && b[1] === 0x50) {
    // ...IEND chunk type followed by its 4-byte CRC
    return b[n - 8] === 0x49 && b[n - 7] === 0x45 && b[n - 6] === 0x4e && b[n - 5] === 0x44 ? "image/png" : null;
  }
  return null;
}

function showFrame(buf) {
  const b = new Uint8Array(buf);
  const mime = frameMime(b);
  if (!mime) return false;
  const img = pending || back; // a newer frame replaces one that's still decoding
  pending = img;
  img.src = "data:" + mime + ";base64," + toBase64(buf);
  if (pendingTimer) clearTimeout(pendingTimer);
  // In case this Photoshop build never fires "load" for data URLs.
  pendingTimer = setTimeout(() => commit(img), 150);
  $("empty").style.display = "none";
  return true;
}

async function tick() {
  keepSquare();
  const psd = activePsdPath();
  const dir = psd ? dirOf(psd) : null;
  if (!dir || !(await exists(join(dir, "part.json")))) {
    if (current.dir !== null) {
      current = { dir: null, viewStamp: null, cfg: {} };
      pending = null;
      front.style.visibility = "hidden";
      back.style.visibility = "hidden";
      $("empty").style.display = "block";
    }
    $("status").textContent = "Open a part's .psd from art\\work";
    return;
  }
  if (dir !== current.dir) {
    current = { dir, viewStamp: null, cfg: await readCfg(dir) };
    orbit = await readOrbit(dir);
    orbitWritten = orbitText();
    showCfg();
    showZoom();
    drawCube();
  }
  await writeOrbit();
  const view = join(dir, ".preview", "view.frame");
  const s = await stamp(view);
  if (!s) {
    // Max swaps frames by rename, so the file can be missing for a few ms; keep the current one.
    if (!current.viewStamp) $("status").textContent = "Waiting for 3ds Max to render this part...";
    return;
  }
  if (s !== current.viewStamp) {
    let buf;
    try { buf = await fs.readFile(view); } catch (e) { return; } // mid-swap; next tick
    if (!showFrame(buf)) return; // incomplete; next tick
    current.viewStamp = s;
    if (!interacting()) $("status").textContent = "Updated " + new Date().toLocaleTimeString();
  }
}

// ---------- orbit ----------

function interacting() {
  return drag !== null || Date.now() - lastInput < SETTLE_MS;
}

function orbitText() {
  const q = interacting() ? "draft" : "final";
  return `yaw=${orbit.yaw.toFixed(1)}\npitch=${orbit.pitch.toFixed(1)}\nzoom=${orbit.zoom.toFixed(3)}\nquality=${q}\n`;
}

async function readOrbit(dir) {
  try {
    const txt = await fs.readFile(join(dir, ".preview", "orbit.txt"), { encoding: "utf-8" });
    const o = { ...DEFAULT_ORBIT };
    for (const line of txt.split(/\r?\n/)) {
      const m = /^(yaw|pitch|zoom)=(-?[\d.]+)$/.exec(line.trim());
      if (m) o[m[1]] = parseFloat(m[2]);
    }
    return o;
  } catch (e) {
    return { ...DEFAULT_ORBIT };
  }
}

// Written from the poll loop only, so a fast drag becomes one write per tick, never a queue.
async function writeOrbit() {
  const txt = orbitText();
  if (!current.dir || txt === orbitWritten) return;
  const dir = join(current.dir, ".preview");
  if (!(await exists(dir))) return;
  await fs.writeFile(join(dir, "orbit.txt"), txt, { encoding: "utf-8" });
  orbitWritten = txt;
}

function setOrbit(o) {
  orbit = { ...orbit, ...o };
  orbit.yaw = ((orbit.yaw % 360) + 360) % 360;
  orbit.pitch = Math.max(-89, Math.min(89, orbit.pitch));
  orbit.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, orbit.zoom));
  lastInput = Date.now();
  showZoom();
  drawCube();
}

// The zoom slider is logarithmic (0.25x to 8x), so each step feels the same size.
function zoomToSlider(z) {
  return Math.round(100 * Math.log(z / ZOOM_MIN) / Math.log(ZOOM_MAX / ZOOM_MIN));
}
function sliderToZoom(v) {
  return ZOOM_MIN * Math.pow(ZOOM_MAX / ZOOM_MIN, v / 100);
}
function showZoom() {
  $("zoom").value = zoomToSlider(orbit.zoom);
  $("zoomLabel").textContent = orbit.zoom.toFixed(orbit.zoom < 10 ? 1 : 0) + "x";
}

let drag = null;
let usingPointer = false;
function startDrag(x, y) { drag = { x, y }; lastInput = Date.now(); $("stage").style.cursor = "grabbing"; }
function moveDrag(x, y) {
  if (!drag) return;
  // Like Max's orbit: you drag the model itself. Right spins it right; up tips its top away.
  setOrbit({ yaw: orbit.yaw - (x - drag.x) * 0.5, pitch: orbit.pitch + (y - drag.y) * 0.5 });
  drag = { x, y };
}
function endDrag() {
  if (drag) lastInput = Date.now();
  drag = null;
  $("stage").style.cursor = "grab";
}

const stage = $("stage");
stage.addEventListener("pointerdown", (e) => { usingPointer = true; startDrag(e.clientX, e.clientY); });
stage.addEventListener("mousedown", (e) => { if (!usingPointer) startDrag(e.clientX, e.clientY); });
for (const target of [stage, document]) {
  target.addEventListener("pointermove", (e) => moveDrag(e.clientX, e.clientY));
  target.addEventListener("mousemove", (e) => { if (!usingPointer) moveDrag(e.clientX, e.clientY); });
  target.addEventListener("pointerup", endDrag);
  target.addEventListener("mouseup", endDrag);
}
stage.addEventListener("pointerleave", endDrag);
stage.addEventListener("wheel", (e) => {
  setOrbit({ zoom: orbit.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12) });
  if (e.preventDefault) e.preventDefault();
});
stage.addEventListener("dblclick", () => setOrbit({ ...DEFAULT_ORBIT }));
for (const b of document.querySelectorAll(".views button[data-yaw]")) {
  b.addEventListener("click", () => setOrbit({ yaw: parseFloat(b.dataset.yaw), pitch: parseFloat(b.dataset.pitch) }));
}
// The overlay buttons sit on the stage; don't let a click on them start a rotate.
for (const id of ["zoomIn", "zoomOut", "zoomFit"]) {
  for (const ev of ["pointerdown", "mousedown"]) $(id).addEventListener(ev, (e) => e.stopPropagation());
}
$("zoomIn").addEventListener("click", () => setOrbit({ zoom: orbit.zoom * 1.25 }));
$("zoomOut").addEventListener("click", () => setOrbit({ zoom: orbit.zoom / 1.25 }));
$("zoomFit").addEventListener("click", () => setOrbit({ zoom: 1 }));
$("zoom").addEventListener("input", (e) => setOrbit({ zoom: sliderToZoom(parseFloat(e.target.value)) }));
$("zoom").addEventListener("change", (e) => setOrbit({ zoom: sliderToZoom(parseFloat(e.target.value)) }));

// ---------- orientation cube ----------
// Drawn from the panel's own angle, so it turns the moment you drag, before Max's frame arrives.
// Same camera math as tools/max/coh_bridge.ms (Max is Z-up; the model's front faces -Y, like
// Max's ViewCube). Click a face to look at it.

const CUBE_SIZE = 100, CUBE_SCALE = 27;
const FACES = [
  { id: "front", label: "FRONT", n: [0, -1, 0], view: { yaw: 0, pitch: 0 } },
  { id: "back", label: "BACK", n: [0, 1, 0], view: { yaw: 180, pitch: 0 } },
  { id: "right", label: "RIGHT", n: [1, 0, 0], view: { yaw: 90, pitch: 0 } },
  { id: "left", label: "LEFT", n: [-1, 0, 0], view: { yaw: 270, pitch: 0 } },
  { id: "top", label: "TOP", n: [0, 0, 1], view: { pitch: 89 } },
  { id: "bottom", label: "BOTTOM", n: [0, 0, -1], view: { pitch: -89 } },
];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

function cameraBasis() {
  const yaw = orbit.yaw * Math.PI / 180, pitch = orbit.pitch * Math.PI / 180;
  const z = [Math.cos(pitch) * Math.sin(yaw), -Math.cos(pitch) * Math.cos(yaw), Math.sin(pitch)];
  const x = norm(cross([0, 0, 1], z));
  return { x, y: cross(z, x), z };
}

function faceCorners(n) {
  const axes = [[1, 0, 0], [0, 1, 0], [0, 0, 1]].filter((a) => Math.abs(dot(a, n)) < 0.5);
  const [u, v] = axes;
  return [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([a, b]) =>
    [n[0] + a * u[0] + b * v[0], n[1] + a * u[1] + b * v[1], n[2] + a * u[2] + b * v[2]]);
}

let cubeFaces = []; // visible faces in screen space, front-most last, for drawing and clicks

function drawCube() {
  const { x, y, z } = cameraBasis();
  const c = CUBE_SIZE / 2;
  const project = (p) => [c + CUBE_SCALE * dot(p, x), c - CUBE_SCALE * dot(p, y)];
  cubeFaces = FACES.map((f) => ({ ...f, facing: dot(f.n, z), pts: faceCorners(f.n).map(project), mid: project(f.n) }))
    .filter((f) => f.facing > 0.02)
    .sort((a, b) => a.facing - b.facing);
  const canvas = $("cubeCanvas");
  const ctx = canvas && canvas.getContext ? canvas.getContext("2d") : null;
  if (ctx) {
    ctx.clearRect(0, 0, CUBE_SIZE, CUBE_SIZE);
    for (const f of cubeFaces) {
      const shade = Math.round(70 + 110 * f.facing);
      ctx.beginPath();
      ctx.moveTo(f.pts[0][0], f.pts[0][1]);
      for (const p of f.pts.slice(1)) ctx.lineTo(p[0], p[1]);
      ctx.closePath();
      ctx.fillStyle = f.id === "front" ? `rgb(${shade - 20}, ${shade}, ${shade + 40})` : `rgb(${shade}, ${shade}, ${shade + 8})`;
      ctx.fill();
      ctx.strokeStyle = "#1c1d20";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
  for (const f of FACES) {
    const el = $("lbl-" + f.id);
    const vis = cubeFaces.find((v) => v.id === f.id);
    if (!vis || vis.facing < 0.3) { el.style.display = "none"; continue; }
    el.style.display = "block";
    el.style.left = Math.round(vis.mid[0] - 32) + "px";
    el.style.top = Math.round(vis.mid[1] - 7) + "px";
    el.style.opacity = String(Math.min(1, (vis.facing - 0.3) * 2.2));
  }
  $("angle").textContent = describeView();
}

const SIDES = ["front", "front-right", "right", "back-right", "back", "back-left", "left", "front-left"];
function describeView() {
  const side = SIDES[Math.round(orbit.yaw / 45) % 8];
  const p = Math.round(orbit.pitch);
  if (p >= 80) return "top";
  if (p <= -80) return "bottom";
  const tilt = Math.abs(p) < 5 ? "level" : `${Math.abs(p)}\u00b0 ${p > 0 ? "above" : "below"}`;
  return `${side}, ${tilt}`;
}

function insidePoly(px, py, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const cubeEl = $("cube");
for (const ev of ["pointerdown", "mousedown"]) cubeEl.addEventListener(ev, (e) => e.stopPropagation());
cubeEl.addEventListener("click", (e) => {
  const r = cubeEl.getBoundingClientRect();
  const px = e.clientX - r.left, py = e.clientY - r.top;
  for (const f of [...cubeFaces].reverse()) {
    if (insidePoly(px, py, f.pts)) { setOrbit(f.view); return; }
  }
});

// ---------- settings ----------

function hexFromInput(v) {
  const m = /^#?([0-9a-f]{6})$/i.exec(v.trim());
  return m ? "#" + m[1].toLowerCase() : null;
}

function bindColor(n) {
  $("c" + n).addEventListener("change", (e) => {
    const h = hexFromInput(e.target.value);
    if (!h) return;
    current.cfg["color" + n] = h;
    showCfg();
    writeCfg();
  });
  $("fg" + n).addEventListener("click", () => {
    try {
      current.cfg["color" + n] = "#" + app.foregroundColor.rgb.hexValue.toLowerCase();
      showCfg();
      writeCfg();
    } catch (e) {
      $("status").textContent = "Couldn't read the foreground color";
    }
  });
}

$("look").addEventListener("change", (e) => {
  current.cfg.look = e.target.value;
  writeCfg();
});
bindColor(1);
bindColor(2);
showZoom();
drawCube();

let running = false;
setInterval(async () => {
  if (running) return;
  running = true;
  try { await tick(); } catch (e) { $("status").textContent = "Preview error: " + e.message; }
  running = false;
}, POLL_MS);

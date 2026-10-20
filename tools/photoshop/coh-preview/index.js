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
let swapTimer = null;

function keepSquare() {
  const stage = $("stage");
  const w = stage.offsetWidth;
  if (w && stage.style.height !== w + "px") stage.style.height = w + "px";
}

function swapIn() {
  if (swapTimer) { clearTimeout(swapTimer); swapTimer = null; }
  back.style.visibility = "visible";
  front.style.visibility = "hidden";
  const t = front; front = back; back = t;
}

back.addEventListener("load", swapIn);
front.addEventListener("load", () => { if (front.style.visibility === "hidden") swapIn(); });

function showFrame(buf) {
  const b = new Uint8Array(buf);
  const mime = b[0] === 0xff && b[1] === 0xd8 ? "image/jpeg" : "image/png";
  back.src = "data:" + mime + ";base64," + toBase64(buf);
  // In case this Photoshop build never fires "load" for data URLs.
  if (swapTimer) clearTimeout(swapTimer);
  swapTimer = setTimeout(swapIn, 120);
  $("empty").style.display = "none";
}

async function tick() {
  keepSquare();
  const psd = activePsdPath();
  const dir = psd ? dirOf(psd) : null;
  if (!dir || !(await exists(join(dir, "part.json")))) {
    if (current.dir !== null) {
      current = { dir: null, viewStamp: null, cfg: {} };
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
  }
  await writeOrbit();
  const view = join(dir, ".preview", "view.frame");
  const s = await stamp(view);
  if (!s) {
    $("status").textContent = "Waiting for 3ds Max to render this part...";
    return;
  }
  if (s !== current.viewStamp) {
    let buf;
    try { buf = await fs.readFile(view); } catch (e) { return; } // mid-swap; next tick
    current.viewStamp = s;
    showFrame(buf);
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
  // Drag right turns the model right (camera left); drag up looks from higher.
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

let running = false;
setInterval(async () => {
  if (running) return;
  running = true;
  try { await tick(); } catch (e) { $("status").textContent = "Preview error: " + e.message; }
  running = false;
}, POLL_MS);

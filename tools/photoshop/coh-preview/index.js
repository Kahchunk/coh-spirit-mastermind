// CoH Preview panel: one rotatable view of the part whose .psd is active, plus its preview settings.
// Dragging writes the angle to the part's .preview/orbit.txt; 3ds Max turns its view to match and
// saves .preview/view.png, which this panel shows. Settings go to part.json via the CoH Art Bridge.
const { app } = require("photoshop");
const fs = require("fs");

const POLL_MS = 120;
const DEFAULT_ORBIT = { yaw: 35, pitch: 25, zoom: 1 };
const $ = (id) => document.getElementById(id);
let current = { dir: null, viewStamp: null, cfg: {} };
let orbit = { ...DEFAULT_ORBIT };
let orbitWritten = "";

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
    return String(s.mtimeMs || (s.mtime && s.mtime.getTime && s.mtime.getTime()) || s.size);
  } catch (e) { return null; }
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function toBase64(buf) {
  const b = new Uint8Array(buf);
  let out = "";
  for (let i = 0; i < b.length; i += 3) {
    const n = (b[i] << 16) | ((b[i + 1] || 0) << 8) | (b[i + 2] || 0);
    out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63] +
      (i + 1 < b.length ? B64[(n >> 6) & 63] : "=") + (i + 2 < b.length ? B64[n & 63] : "=");
  }
  return out;
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

async function tick() {
  const psd = activePsdPath();
  const dir = psd ? dirOf(psd) : null;
  if (!dir || !(await exists(join(dir, "part.json")))) {
    if (current.dir !== null) {
      current = { dir: null, viewStamp: null, cfg: {} };
      $("view").removeAttribute("src");
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
  }
  await writeOrbit();
  const view = join(dir, ".preview", "view.png");
  const s = await stamp(view);
  if (!s) {
    $("status").textContent = "Waiting for 3ds Max to render this part...";
    return;
  }
  if (s !== current.viewStamp) {
    current.viewStamp = s;
    let buf;
    try { buf = await fs.readFile(view); } catch (e) { return; }  // mid-swap; next tick
    $("view").src = "data:image/png;base64," + toBase64(buf);
    $("empty").style.display = "none";
    $("status").textContent = "Updated " + new Date().toLocaleTimeString();
  }
}

// ---------- orbit ----------

function orbitText() {
  return `yaw=${orbit.yaw.toFixed(1)}\npitch=${orbit.pitch.toFixed(1)}\nzoom=${orbit.zoom.toFixed(3)}\n`;
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
  orbit.zoom = Math.max(0.25, Math.min(8, orbit.zoom));
}

let drag = null;
let usingPointer = false;
function startDrag(x, y) { drag = { x, y }; $("stage").style.cursor = "grabbing"; }
function moveDrag(x, y) {
  if (!drag) return;
  // Drag right turns the model right (camera left); drag up looks from higher.
  setOrbit({ yaw: orbit.yaw - (x - drag.x) * 0.5, pitch: orbit.pitch + (y - drag.y) * 0.5 });
  drag = { x, y };
}
function endDrag() { drag = null; $("stage").style.cursor = "grab"; }

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
$("zoomIn").addEventListener("click", () => setOrbit({ zoom: orbit.zoom * 1.25 }));
$("zoomOut").addEventListener("click", () => setOrbit({ zoom: orbit.zoom / 1.25 }));

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

let running = false;
setInterval(async () => {
  if (running) return;
  running = true;
  try { await tick(); } catch (e) { $("status").textContent = "Preview error: " + e.message; }
  running = false;
}, POLL_MS);

// CoH Preview panel: shows the multi-angle render of the part whose .psd is active,
// and edits that part's preview settings (part.json), which the CoH Art Bridge passes to 3ds Max.
const { app } = require("photoshop");
const fs = require("fs");

const POLL_MS = 800;
const $ = (id) => document.getElementById(id);
let current = { dir: null, sheetStamp: null, cfg: {} };

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
      current = { dir: null, sheetStamp: null, cfg: {} };
      $("sheet").removeAttribute("src");
    }
    $("status").textContent = "Open a part's .psd from art\\work";
    return;
  }
  if (dir !== current.dir) {
    current = { dir, sheetStamp: null, cfg: await readCfg(dir) };
    showCfg();
  }
  const sheet = join(dir, ".preview", "sheet.png");
  const s = await stamp(sheet);
  if (!s) {
    $("status").textContent = "Waiting for 3ds Max to render this part...";
    return;
  }
  if (s !== current.sheetStamp) {
    current.sheetStamp = s;
    const buf = await fs.readFile(sheet);
    $("sheet").src = "data:image/png;base64," + toBase64(buf);
    $("status").textContent = "Updated " + new Date().toLocaleTimeString();
  }
}

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

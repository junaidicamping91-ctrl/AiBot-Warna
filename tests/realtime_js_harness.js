/* Harness Node untuk menguji logika deteksi di web/realtime.html.
 *
 *   node tests/realtime_js_harness.js <realtime.html> <config.json>
 *
 * Tidak butuh browser: DOM dan canvas dipalsukan, lalu detectFrame() dijalankan
 * pada frame sintetis berisi SEMUA warna sekaligus. Tujuannya memastikan
 * algoritma realtime (HSV -> label prioritas -> connected components -> grup)
 * benar-benar menemukan banyak warna dalam satu frame.
 */
'use strict';
const fs = require('fs');
const vm = require('vm');

const htmlPath = process.argv[2];
const cfgPath = process.argv[3];
const html = fs.readFileSync(htmlPath, 'utf8');
const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (!blocks.length) throw new Error('blok <script> tidak ditemukan');
const script = blocks[blocks.length - 1][1]
  .replace('__CONFIG__', JSON.stringify(cfg).replace(/<\//g, '<\\/'));

/* ------------------------- frame sintetis ------------------------- */
const W = 320, H = 240;
const FRAME = new Uint8ClampedArray(W * H * 4);
function put(x, y, rgb) {
  FRAME[(y * W + x) * 4] = rgb[0];
  FRAME[(y * W + x) * 4 + 1] = rgb[1];
  FRAME[(y * W + x) * 4 + 2] = rgb[2];
  FRAME[(y * W + x) * 4 + 3] = 255;
}
/* Latar (68,58,52): S~60 -> tidak masuk grup netral (S<=45) maupun
   kromatik (S>=80), jadi benar-benar dianggap latar tanpa warna. */
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) put(x, y, [68, 58, 52]);
const colors = cfg.colors || [];
const BW = 80, BH = 60;
colors.forEach((c, i) => {
  const ox = (i % 4) * BW, oy = Math.floor(i / 4) * BH;
  for (let y = oy; y < oy + BH; y++)
    for (let x = ox; x < ox + BW; x++) put(x, y, c.rgb);
});

/* --------------------------- DOM palsu ---------------------------- */
function stubEl() {
  return {
    className: '', dataset: {}, style: {}, innerHTML: '', textContent: '',
    children: [], value: '', checked: true, width: W, height: H,
    classList: { toggle() {}, add() {}, remove() {} },
    addEventListener() {}, appendChild(c) { this.children.push(c); },
    getContext() { return ctxStub; },
  };
}
const ctxStub = {
  getImageData() { return { data: FRAME }; },
  drawImage() {}, fillRect() {}, strokeRect() {}, beginPath() {}, moveTo() {},
  lineTo() {}, arc() {}, stroke() {}, fill() {}, save() {}, restore() {},
  fillText() {}, setLineDash() {},
  measureText(s) { return { width: String(s).length * 6 }; },
};
const elements = {};
const sandbox = {
  console, Date, Math, JSON, Set, Map, Uint8Array, Uint8ClampedArray,
  Int32Array, Array, Object, String, Number, Boolean, Error,
  performance: { now: () => 1000 },
  setTimeout, clearTimeout,
  requestAnimationFrame: () => 0, cancelAnimationFrame() {},
  navigator: { mediaDevices: null },
  SpeechSynthesisUtterance: function () {},
  document: {
    getElementById(id) {
      if (!elements[id]) elements[id] = stubEl();
      return elements[id];
    },
    createElement: () => stubEl(),
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.window.isSecureContext = true;
sandbox.window.addEventListener = () => {};
vm.runInNewContext(script, sandbox, { filename: 'realtime.html' });

const api = sandbox.window.__aimbotTest;
if (!api) throw new Error('hook __aimbotTest tidak tersedia');

/* ------------------------------ ASSERT ---------------------------- */
function assert(cond, msg) { if (!cond) throw new Error(msg); }

/* 1) Konversi HSV mendekati OpenCV (H 0-179, S/V 0-255). */
const red = api.rgb2hsv(230, 60, 45);
assert(red[0] >= 0 && red[0] <= 9, 'merah harus H 0-9, dapat ' + red[0]);
assert(red[1] > 180 && red[2] > 200, 'merah harus S/V tinggi');
const white = api.rgb2hsv(245, 245, 245);
assert(white[1] < 5 && white[2] > 240, 'putih harus S rendah, V tinggi');

/* 2) prioritas: piksel magenta tidak boleh diklaim MERAH. */
assert(api.colorIndex(161, 200, 240) > 0, 'magenta harus cocok salah satu warna');

/* 3) SEMUA warna terdeteksi dalam SATU frame. */
const dets = api.detectFrame();
const ids = dets.map(d => d.spec.id);
console.log('terdeteksi ' + dets.length + '/' + cfg.colors.length + ': ' +
            dets.map(d => d.spec.name).join(', '));
assert(dets.length === cfg.colors.length,
       'harus ' + cfg.colors.length + ' warna sekaligus, dapat ' + dets.length);
for (const c of cfg.colors) {
  assert(ids.indexOf(c.id) >= 0, 'warna hilang: ' + c.name);
}
for (const d of dets) {
  assert(d.conf >= cfg.confidence_threshold,
         'keyakinan ' + d.spec.name + ' di bawah ambang: ' + d.conf);
  assert(d.box[2] >= BW - 6 && d.box[3] >= BH - 6,
         'bounding box ' + d.spec.name + ' terlalu kecil: ' + d.box.join(','));
}

/* 4) prioritas label: tidak ada dua deteksi dengan id sama. */
assert(new Set(ids).size === ids.length, 'ada warna yang dihitung ganda');

console.log('OK: realtime multi-color ' + dets.length + ' warna, HSV & CCL valid');

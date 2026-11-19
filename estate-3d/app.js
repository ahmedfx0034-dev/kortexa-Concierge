import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { AGENCY, loadListings } from './listings.js';
let LISTINGS = [];

// ============================================================================
// Setup
// ============================================================================
const $ = (id) => document.getElementById(id);
const canvas = $('scene');
const isTouch = matchMedia('(pointer: coarse)').matches;

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
} catch (e) {
  $('loaderMsg').outerHTML = '<div class="err">Your browser could not start 3D graphics (WebGL). Try another browser or device.</div>';
  throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, isTouch ? 1.5 : 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.05, 600);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

$('brandName').textContent = AGENCY.name;
$('brandMark').textContent = AGENCY.short;
document.querySelector('.loader .mark').textContent = AGENCY.short;
document.title = `${AGENCY.name} — 3D Homes`;

// ============================================================================
// Procedural textures & materials
// ============================================================================
function canvasTex(size, draw, repeat = 1) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  draw(c.getContext('2d'), size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat, repeat);
  t.anisotropy = 4;
  return t;
}
const rand = (() => { let s = 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; })();

const TEX = {
  wood: canvasTex(512, (g, s) => {
    const rows = 8, h = s / rows;
    for (let r = 0; r < rows; r++) {
      let x = -rand() * s;
      while (x < s) {
        const w = s * (0.45 + rand() * 0.5);
        const l = 52 + rand() * 12;
        g.fillStyle = `hsl(30, 38%, ${l}%)`;
        g.fillRect(x, r * h, w, h);
        g.strokeStyle = 'rgba(60,35,15,.25)';
        for (let i = 0; i < 6; i++) { g.beginPath(); const y = r * h + rand() * h; g.moveTo(x, y); g.bezierCurveTo(x + w / 3, y + 4, x + w * 2 / 3, y - 4, x + w, y); g.stroke(); }
        g.fillStyle = 'rgba(40,20,5,.5)'; g.fillRect(x, r * h, 2, h);
        x += w;
      }
      g.fillStyle = 'rgba(40,20,5,.45)'; g.fillRect(0, r * h, s, 2);
    }
  }),
  tile: canvasTex(256, (g, s) => {
    g.fillStyle = '#d9d6d0'; g.fillRect(0, 0, s, s);
    const n = 4, t = s / n;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const l = 86 + rand() * 6; g.fillStyle = `hsl(40, 8%, ${l}%)`; g.fillRect(i * t + 2, j * t + 2, t - 4, t - 4);
    }
  }),
  marble: canvasTex(512, (g, s) => {
    g.fillStyle = '#f2f0ec'; g.fillRect(0, 0, s, s);
    g.strokeStyle = 'rgba(120,120,130,.18)'; g.lineWidth = 1.5;
    for (let i = 0; i < 18; i++) { g.beginPath(); let x = rand() * s, y = 0; g.moveTo(x, y); while (y < s) { x += (rand() - .5) * 40; y += 20 + rand() * 30; g.lineTo(x, y); } g.stroke(); }
    g.fillStyle = 'rgba(0,0,0,.08)'; for (let k = 0; k <= 2; k++) { g.fillRect(k * s / 2, 0, 1.5, s); g.fillRect(0, k * s / 2, s, 1.5); }
  }),
  grass: canvasTex(256, (g, s) => {
    g.fillStyle = '#6f9e4a'; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 3000; i++) { g.fillStyle = `hsla(${85 + rand() * 25}, 40%, ${30 + rand() * 25}%, .5)`; g.fillRect(rand() * s, rand() * s, 2, 2); }
  }, 40),
  road: canvasTex(256, (g, s) => {
    g.fillStyle = '#4a4d52'; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(${rand() > .5 ? 255 : 0},${rand() > .5 ? 255 : 0},255,.05)`; g.fillRect(rand() * s, rand() * s, 2, 2); }
  }),
  paving: canvasTex(256, (g, s) => {
    g.fillStyle = '#b9b2a6'; g.fillRect(0, 0, s, s);
    const t = s / 8;
    for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) { g.fillStyle = `hsl(35, 10%, ${66 + rand() * 10}%)`; g.fillRect(i * t + (j % 2) * t / 2 + 1, j * t + 1, t - 2, t - 2); }
  }),
  rug: canvasTex(256, (g, s) => {
    g.fillStyle = '#8b6f5a'; g.fillRect(0, 0, s, s);
    g.strokeStyle = '#e8dcc7'; g.lineWidth = 8; g.strokeRect(18, 18, s - 36, s - 36);
    g.lineWidth = 3; g.strokeRect(36, 36, s - 72, s - 72);
    g.fillStyle = 'rgba(232,220,199,.5)';
    for (let i = 0; i < 6; i++) for (let j = 0; j < 6; j++) { g.save(); g.translate(60 + i * 27, 60 + j * 27); g.rotate(Math.PI / 4); g.fillRect(-5, -5, 10, 10); g.restore(); }
  }),
};

const matCache = new Map();
function mat(color, opts = {}) {
  const key = color + JSON.stringify(opts);
  if (!matCache.has(key)) matCache.set(key, new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0, ...opts }));
  return matCache.get(key);
}
const M = {
  white: mat('#f4f2ee'), offwhite: mat('#e9e4da'), darkwood: mat('#5a3d2b', { roughness: .6 }), lightwood: mat('#c8a27a', { roughness: .6 }),
  black: mat('#1d1f22', { roughness: .4 }), metal: mat('#b8bcc2', { metalness: .8, roughness: .3 }), screen: mat('#0b0d12', { roughness: .15, metalness: .2 }),
  linen: mat('#f7f5f0', { roughness: .95 }), leaf: mat('#3f7d3a', { roughness: .9 }), leaf2: mat('#5c9b45', { roughness: .9 }), pot: mat('#d8c9b2'),
  trunk: mat('#8a6a4a', { roughness: .95 }), glass: new THREE.MeshStandardMaterial({ color: '#9fc6e0', roughness: .05, metalness: .3, transparent: true, opacity: .32, side: THREE.DoubleSide, depthWrite: false }),
  darkglass: mat('#253a4f', { roughness: .1, metalness: .55 }), water: mat('#3fb4d8', { roughness: .1, metalness: .1, emissive: '#0c4a63', emissiveIntensity: .3 }),
  lamp: new THREE.MeshStandardMaterial({ color: '#fff7e0', emissive: '#ffe7b0', emissiveIntensity: 1.4 }),
  porcelain: mat('#fbfbfb', { roughness: .2 }), wall: mat('#f1ede6', { roughness: .9 }), roofDark: mat('#3a3f47', { roughness: .8 }),
  tileRoof: mat('#9b4a32', { roughness: .85 }), concrete: mat('#c9c4bb', { roughness: .95 }), grass: new THREE.MeshStandardMaterial({ map: TEX.grass, roughness: 1 }),
};

// ============================================================================
// Geometry helpers
// ============================================================================
function box(w, h, d, material, x = 0, y = 0, z = 0, parent, cast = true) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(x, y + h / 2, z);
  m.castShadow = cast; m.receiveShadow = true;
  if (parent) parent.add(m);
  return m;
}
function cyl(rt, rb, h, material, x = 0, y = 0, z = 0, parent, seg = 16) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), material);
  m.position.set(x, y + h / 2, z); m.castShadow = true; m.receiveShadow = true;
  if (parent) parent.add(m);
  return m;
}
function plane(w, d, material, x = 0, y = 0, z = 0, parent) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), material);
  m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); m.receiveShadow = true;
  if (parent) parent.add(m);
  return m;
}
function texMat(tex, w, d, opts = {}) {
  const t = tex.clone(); t.needsUpdate = true; t.repeat.set(w / (opts.scale || 2), d / (opts.scale || 2));
  return new THREE.MeshStandardMaterial({ map: t, roughness: opts.roughness ?? .7, color: opts.color || '#ffffff' });
}

function palm(parent, x, z, s = 1) {
  const g = new THREE.Group();
  const segs = 6; let px = 0, py = 0;
  for (let i = 0; i < segs; i++) {
    const t = cyl(0.16 * s, 0.2 * s, 1.1 * s, M.trunk, px, py, 0, g, 7);
    px += 0.08 * s; py += 1.05 * s; t.rotation.z = -0.07;
  }
  const leafGeo = new THREE.ConeGeometry(0.35 * s, 3 * s, 4);
  for (let i = 0; i < 8; i++) {
    const l = new THREE.Mesh(leafGeo, i % 2 ? M.leaf : M.leaf2);
    l.castShadow = true;
    const a = (i / 8) * Math.PI * 2;
    l.position.set(px + Math.cos(a) * 1.2 * s, py - 0.2 * s, Math.sin(a) * 1.2 * s);
    l.rotation.set(Math.sin(a) * 1.25, 0, -Math.cos(a) * 1.25);
    l.scale.set(1, 1, 0.25);
    g.add(l);
  }
  g.position.set(x, 0, z); g.rotation.y = rand() * 6;
  parent.add(g);
  return g;
}
function shrub(parent, x, z, s = 1) {
  const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.7 * s, 0), rand() > .5 ? M.leaf : M.leaf2);
  m.position.set(x, 0.5 * s, z); m.scale.y = 0.8; m.castShadow = true; parent.add(m);
}
function treeRound(parent, x, z, s = 1) {
  cyl(0.18 * s, 0.25 * s, 2.2 * s, M.trunk, x, 0, z, parent, 7);
  const c = new THREE.Mesh(new THREE.IcosahedronGeometry(1.8 * s, 1), M.leaf);
  c.position.set(x, 3.2 * s, z); c.castShadow = true; parent.add(c);
}

// ============================================================================
// House exteriors (estate view)
// ============================================================================
function windowsOn(g, w, h, d, floors, floorH, wall, density = 2.6, y0 = 0) {
  // dark glass windows on front (+z) and back (-z) and sides
  const frame = mat('#ffffff');
  for (let f = 0; f < floors; f++) {
    const y = y0 + f * floorH + floorH * 0.35;
    const n = Math.max(1, Math.floor(w / density));
    for (let i = 0; i < n; i++) {
      const x = -w / 2 + (i + 0.5) * (w / n);
      for (const side of [1, -1]) {
        box(1.3, 1.4, 0.05, frame, x, y - 0.05, side * (d / 2 + 0.02), g, false);
        box(1.15, 1.25, 0.06, M.darkglass, x, y + 0.02, side * (d / 2 + 0.03), g, false);
      }
    }
    const m = Math.max(1, Math.floor(d / (density + 1)));
    for (let i = 0; i < m; i++) {
      const z = -d / 2 + (i + 0.5) * (d / m);
      for (const side of [1, -1]) {
        box(0.05, 1.25, 1.1, M.darkglass, side * (w / 2 + 0.03), y + 0.02, z, g, false);
      }
    }
  }
}
function hipRoof(w, d, h, material) {
  const geo = new THREE.ConeGeometry(Math.SQRT1_2, 1, 4, 1);
  geo.rotateY(Math.PI / 4);
  const m = new THREE.Mesh(geo, material);
  m.scale.set(w, h, d);
  m.castShadow = true;
  return m;
}
function gableRoof(w, d, h, material) {
  const s = new THREE.Shape();
  s.moveTo(-d / 2, 0); s.lineTo(d / 2, 0); s.lineTo(0, h); s.closePath();
  const geo = new THREE.ExtrudeGeometry(s, { depth: w, bevelEnabled: false });
  geo.translate(0, 0, -w / 2); geo.rotateY(Math.PI / 2);
  const m = new THREE.Mesh(geo, material); m.castShadow = true;
  return m;
}

function buildExterior(L) {
  const g = new THREE.Group();
  const wallM = mat(L.wall, { roughness: .9 });
  const accentM = mat(L.accent, { roughness: .6 });
  const trimM = mat(L.trim, { roughness: .6 });

  // lot: paving + compound wall (very Ghana) with gate
  const lotW = 24, lotD = 22;
  plane(lotW, lotD, texMat(TEX.paving, lotW, lotD, { scale: 3 }), 0, 0.02, 0, g);
  const cw = 1.3, ct = 0.25;
  box(lotW, cw, ct, wallM, 0, 0, -lotD / 2, g);
  box(ct, cw, lotD, wallM, -lotW / 2, 0, 0, g);
  box(ct, cw, lotD, wallM, lotW / 2, 0, 0, g);
  box(lotW / 2 - 3, cw, ct, wallM, -lotW / 4 - 1.5, 0, lotD / 2, g);
  box(lotW / 2 - 3, cw, ct, wallM, lotW / 4 + 1.5, 0, lotD / 2, g);
  for (const sx of [-3, 3]) box(0.5, 1.8, 0.5, trimM, sx, 0, lotD / 2, g);
  box(5.6, 1.5, 0.08, accentM, 0, 0.05, lotD / 2 + 0.05, g); // gate

  const style = L.style;
  if (style === 'villa') {
    const big = L.beds >= 6 || /luxury|mansion/i.test(L.title);
    const w1 = big ? 15 : 13, d1 = big ? 10 : 9;
    box(w1, 3.3, d1, wallM, 0, 0, -2, g);
    windowsOn(g, w1, 3.3, d1, 1, 3.3, wallM, 2.4);
    // offset upper floor
    const w2 = w1 * 0.72, d2 = d1 * 0.85;
    const up = new THREE.Group(); up.position.set(1.5, 3.3, -2.6); g.add(up);
    box(w2, 3.2, d2, wallM, 0, 0, 0, up);
    windowsOn(up, w2, 3.2, d2, 1, 3.2, wallM, 2.2);
    box(w2 + 0.6, 0.35, d2 + 0.6, accentM, 0, 3.2, 0, up); // roof slab
    box(w1 + 0.4, 0.3, d1 + 0.4, accentM, 0, 3.3, -2, g);
    // glass corner feature
    box(3.2, 2.8, 0.1, M.darkglass, -w1 / 2 + 1.8, 0.2, -2 + d1 / 2 + 0.06, g);
    // gold trim band
    box(w1 + 0.42, 0.1, d1 + 0.42, trimM, 0, 3.58, -2, g);
    // pool
    const pool = plane(big ? 8 : 6, 3, M.water, 0, 0.08, 6.6, g);
    box((big ? 8 : 6) + 0.6, 0.12, 3.6, M.white, 0, 0, 6.6, g, false);
    pool.position.y = 0.13;
    palm(g, -9, 7.5, 1); palm(g, 9, 7.5, 1.1); palm(g, -9.5, -8, 0.9);
    if (big) { palm(g, 9.5, -8, 1); shrub(g, -6, 9); shrub(g, 6, 9); }
    // canopy carport
    box(4.5, 0.15, 5, accentM, -8.5, 2.6, 2, g);
    for (const [px, pz] of [[-10.5, 0], [-10.5, 4], [-6.5, 4], [-6.5, 0]]) cyl(0.08, 0.08, 2.6, M.metal, px, 0, pz, g, 8);
  } else if (style === 'bungalow') {
    const w = 13, d = 9;
    box(w, 3.2, d, wallM, 0, 0, -2, g);
    windowsOn(g, w, 3.2, d, 1, 3.2, wallM, 2.6);
    const r = hipRoof(w + 1.6, d + 1.6, 2.8, M.tileRoof); r.material = mat(L.trim, { roughness: .85 }); r.position.set(0, 3.2 + 1.4, -2); g.add(r);
    // veranda
    box(6, 0.18, 2.6, M.concrete, 0, 0, -2 + d / 2 + 1.3, g);
    box(6.4, 0.15, 2.8, mat(L.trim), 0, 2.9, -2 + d / 2 + 1.3, g);
    for (const px of [-2.8, 0, 2.8]) cyl(0.12, 0.12, 2.9, M.white, px, 0, -2 + d / 2 + 2.4, g, 10);
    box(1.1, 2.2, 0.08, accentM, 0, 0.18, -2 + d / 2 + 0.05, g); // front door
    treeRound(g, -8.5, 6.5, 1); palm(g, 9, 6.5, 0.9); shrub(g, -4.5, 6.8); shrub(g, 4.5, 6.8); shrub(g, -9.5, -8.5); treeRound(g, 9, -7.5, 0.8);
  } else if (style === 'townhouse') {
    for (const [ux, flip] of [[-3.4, 0], [3.4, 1]]) {
      const u = new THREE.Group(); u.position.x = ux; g.add(u);
      const w = 6.6, d = 10;
      const wm = flip ? mat('#dcd6cb', { roughness: .9 }) : wallM;
      box(w, 6.2, d, wm, 0, 0, -1.5, u);
      windowsOn(u, w, 6.2, d, 2, 3.1, wm, 2.2);
      const r = gableRoof(w + 0.2, d + 0.8, 2.6, M.roofDark); r.position.set(0, 6.2, -1.5); u.add(r);
      box(1.1, 2.3, 0.08, accentM, 1.6, 0, -1.5 + d / 2 + 0.05, u);
      box(w, 0.12, 1.2, accentM, 0, 3.0, -1.5 + d / 2 + 0.6, u); // balcony
      box(w, 0.9, 0.05, M.glass, 0, 3.1, -1.5 + d / 2 + 1.2, u, false);
    }
    shrub(g, -8, 7); shrub(g, 8, 7); treeRound(g, -9, -8, 0.8); palm(g, 9, 6, 0.9);
  } else if (style === 'apartment') {
    const w = 14, d = 11, fh = 3.1, floors = 5;
    box(w, fh * floors, d, wallM, 0, 0, -1.5, g);
    windowsOn(g, w, fh * floors, d, floors, fh, wallM, 2.3);
    for (let f = 1; f < floors; f++) {
      box(w + 0.3, 0.15, 1.4, accentM, 0, f * fh, -1.5 + d / 2 + 0.7, g);
      box(w + 0.3, 0.9, 0.05, M.glass, 0, f * fh + 0.15, -1.5 + d / 2 + 1.4, g, false);
    }
    box(w + 0.6, 0.4, d + 0.6, M.concrete, 0, fh * floors, -1.5, g);
    box(w + 0.6, 0.6, 0.2, accentM, 0, fh * floors + 0.4, -1.5 + d / 2 + 0.2, g);
    box(3, 3, 3, M.concrete, -3, fh * floors + 0.4, -3, g); // lift room
    // highlight the listed unit (3rd floor)
    box(w * 0.48, fh - 0.4, 0.08, mat(L.trim, { emissive: '#ffcf6b', emissiveIntensity: .35 }), w * 0.24, 2 * fh + 0.2, -1.5 + d / 2 + 0.05, g, false);
    palm(g, -9, 6, 1); palm(g, 9, 6, 1); shrub(g, -5, 8.5); shrub(g, 5, 8.5);
    // parked cars
    for (const cx of [-8.5, 8.5]) car(g, cx, -7.5, rand() > .5 ? '#c0392b' : '#2c3e50');
  }
  if (style !== 'apartment') car(g, style === 'villa' ? -8.5 : 6.5, style === 'villa' ? 2 : 7.5, ['#f5f5f5', '#1e293b', '#9b1c1c', '#475569'][Math.floor(rand() * 4)]);
  g.traverse((o) => { if (o.isMesh) o.userData.listingId = L.id; });
  return g;
}
function car(parent, x, z, color) {
  const c = new THREE.Group();
  const body = mat(color, { roughness: .35, metalness: .4 });
  box(1.9, 0.7, 4.2, body, 0, 0.3, 0, c);
  box(1.7, 0.6, 2.2, M.darkglass, 0, 1.0, -0.2, c);
  for (const [wx, wz] of [[-.9, 1.3], [.9, 1.3], [-.9, -1.3], [.9, -1.3]]) {
    const w = cyl(0.36, 0.36, 0.25, M.black, 0, 0, 0, c, 12); w.rotation.z = Math.PI / 2; w.position.set(wx, 0.36, wz);
  }
  c.position.set(x, 0, z); parent.add(c);
}

// ============================================================================
// Estate scene
// ============================================================================
const estate = { scene: new THREE.Scene(), houses: new Map(), pins: [], selected: null, ring: null };
function makeSky(scene, top = '#7fb4e0', bottom = '#e8f1f7') {
  const tex = canvasTex(64, (g, s) => { const gr = g.createLinearGradient(0, 0, 0, s); gr.addColorStop(0, top); gr.addColorStop(1, bottom); g.fillStyle = gr; g.fillRect(0, 0, s, s); });
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping; tex.repeat.set(1, 1);
  scene.background = tex;
  scene.fog = new THREE.Fog(bottom, 120, 320);
}
function addSun(scene, extent, pos = [40, 60, 30]) {
  scene.add(new THREE.HemisphereLight('#dfefff', '#6b7f4a', 1.1));
  const sun = new THREE.DirectionalLight('#fff3dc', 2.4);
  sun.position.set(...pos); sun.castShadow = true;
  sun.shadow.mapSize.set(isTouch ? 1024 : 2048, isTouch ? 1024 : 2048);
  Object.assign(sun.shadow.camera, { left: -extent, right: extent, top: extent, bottom: -extent, near: 1, far: 250 });
  sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.03;
  scene.add(sun);
  return sun;
}

// Merge a house's many small meshes into one mesh per material (keeps 60 homes fast on phones)
function flatten(group) {
  group.updateMatrixWorld(true);
  const inv = group.matrixWorld.clone().invert();
  const buckets = new Map();
  group.traverse((o) => {
    if (!o.isMesh) return;
    let g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
    for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
    if (!g.attributes.uv) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
    g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
    const key = o.material.uuid;
    if (!buckets.has(key)) buckets.set(key, { mat: o.material, geos: [], cast: false });
    const b = buckets.get(key); b.geos.push(g); b.cast = b.cast || o.castShadow;
  });
  const out = new THREE.Group();
  for (const b of buckets.values()) {
    const m = new THREE.Mesh(mergeGeometries(b.geos, false), b.mat);
    m.castShadow = b.cast; m.receiveShadow = true;
    out.add(m);
    b.geos.forEach((g) => g.dispose());
  }
  out.position.copy(group.position); out.rotation.copy(group.rotation);
  return out;
}

let estateSun;
function buildEstateBase() {
  const s = estate.scene;
  makeSky(s);
  estateSun = addSun(s, 75, [50, 80, 40]);
  const ground = plane(900, 900, M.grass, 0, 0, 0, s);
  ground.material.map.repeat.set(180, 180);
  const ring = new THREE.Mesh(new THREE.RingGeometry(13.5, 14.3, 64), new THREE.MeshBasicMaterial({ color: '#c9a227', transparent: true, opacity: .9 }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.08; ring.visible = false; s.add(ring);
  estate.ring = ring;
}

// Lay the (filtered) listings out on a street grid: 2 rows of lots face each street
const LOT_X = 30, STREET = 58;
function buildEstate(list) {
  const s = estate.scene;
  if (estate.lots) { s.remove(estate.lots); estate.lots.traverse((o) => { if (o.isMesh) o.geometry.dispose(); }); }
  clearLabels(estate.pins); estate.houses.clear();
  const lots = new THREE.Group(); estate.lots = lots; s.add(lots);
  const n = list.length;
  const cols = n <= 4 ? Math.max(1, n) : n <= 9 ? 3 : n <= 24 ? 4 : 5;
  const rows = Math.max(1, Math.ceil(n / cols));
  const streets = Math.ceil(rows / 2);
  const width = cols * LOT_X;
  const x0 = -width / 2 + LOT_X / 2;
  const roadLen = width + 26;
  for (let k = 0; k < streets; k++) {
    const z = k * STREET;
    plane(roadLen, 9, texMat(TEX.road, roadLen, 9, { scale: 6, roughness: .95 }), 0, 0.03, z, lots);
    for (let x = -roadLen / 2 + 2; x < roadLen / 2 - 2; x += 6) plane(2.6, 0.18, mat('#f1f1e6'), x, 0.05, z, lots);
    for (const dz of [-5.4, 5.4]) box(roadLen, 0.15, 1.8, M.concrete, 0, 0, z + dz, lots, false);
  }
  const zLen = (streets - 1) * STREET + 60;
  plane(9, zLen, texMat(TEX.road, 9, zLen, { scale: 6, roughness: .95 }), -roadLen / 2 - 4.5, 0.03, (streets - 1) * STREET / 2, lots);
  list.forEach((L, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    const street = Math.floor(r / 2), side = r % 2 === 0 ? -1 : 1;
    const x = x0 + c * LOT_X, z = street * STREET + side * 18;
    const raw = buildExterior(L);
    raw.position.set(x, 0, z); raw.rotation.y = side === -1 ? 0 : Math.PI;
    const h = flatten(raw);
    h.traverse((o) => { if (o.isMesh) o.userData.listingId = L.id; });
    lots.add(h);
    estate.houses.set(L.id, { group: h, pos: new THREE.Vector3(x, 0, z), L });
  });
  // street palms + surrounding greenery, merged into one mesh
  const deco = new THREE.Group();
  for (let k = 0; k < streets; k++) for (let c = 0; c <= cols; c++) for (const side of [-1, 1]) palm(deco, x0 - LOT_X / 2 + c * LOT_X, k * STREET + side * 7.4, 0.9);
  const zMin = -40, zMax = (streets - 1) * STREET + 40;
  for (let i = 0; i < 90; i++) {
    const x = (rand() - .5) * (width + 220), z = zMin - 60 + rand() * (zMax - zMin + 120);
    if (x > -roadLen / 2 - 14 && x < roadLen / 2 + 6 && z > zMin + 8 && z < zMax - 8) continue;
    rand() > .5 ? treeRound(deco, x, z, 0.8 + rand() * 0.8) : palm(deco, x, z, 0.8 + rand() * 0.5);
  }
  lots.add(flatten(deco));
  // centre everything on the origin
  const cz = (streets - 1) * STREET / 2;
  lots.position.z = -cz;
  for (const h of estate.houses.values()) h.pos.z -= cz;
  estate.extent = Math.max(width + 30, streets * STREET + 30) / 2;
  Object.assign(estateSun.shadow.camera, { left: -estate.extent - 20, right: estate.extent + 20, top: estate.extent + 20, bottom: -estate.extent - 20, far: 400 });
  estateSun.shadow.camera.updateProjectionMatrix();
  s.fog.near = estate.extent * 2.2; s.fog.far = estate.extent * 5 + 200;
  buildPins();
}

// ============================================================================
// Interior generation
// ============================================================================
const H = 2.8, T = 0.12, CORR = 1.8;
const tour = { scene: null, rooms: [], colliders: [], floors: [], labels: [], ceiling: [], listing: null, bounds: null, mode: 'dollhouse' };

function layoutRooms(L) {
  const rows = [[], []], len = [0, 0];
  for (const [name, type, w, d] of L.rooms) {
    const r = len[0] <= len[1] ? 0 : 1;
    rows[r].push({ name, type, w, d }); len[r] += w;
  }
  const total = Math.max(len[0], len[1]);
  const depth = rows.map((row) => Math.max(...row.map((r) => r.d)));
  const rooms = [];
  rows.forEach((row, ri) => {
    if (len[ri] < total) row[row.length - 1].w += total - len[ri];
    let x = 0;
    for (const r of row) {
      const z0 = ri === 0 ? -CORR / 2 - depth[0] : CORR / 2;
      const z1 = ri === 0 ? -CORR / 2 : CORR / 2 + depth[1];
      rooms.push({ ...r, row: ri, x0: x, x1: x + r.w, z0, z1, cx: x + r.w / 2, cz: (z0 + z1) / 2, d: z1 - z0 });
      x += r.w;
    }
  });
  // centre the plan on the origin
  const zMin = -CORR / 2 - depth[0], zMax = CORR / 2 + depth[1];
  const ox = total / 2, oz = (zMin + zMax) / 2;
  for (const r of rooms) { r.x0 -= ox; r.x1 -= ox; r.cx -= ox; r.z0 -= oz; r.z1 -= oz; r.cz -= oz; }
  const hall = { name: 'Hallway', type: 'hall', x0: -ox, x1: total - ox, z0: -CORR / 2 - oz, z1: CORR / 2 - oz, row: -1 };
  hall.cx = 0; hall.cz = (hall.z0 + hall.z1) / 2; hall.w = total; hall.d = CORR;
  return { rooms, hall, W: total, zMin: zMin - oz, zMax: zMax - oz };
}

// axis-aligned wall with openings: {c (centre along wall), w, bottom, top, glass}
function wall(parent, axis, fixed, a0, a1, openings, material) {
  const ops = openings.filter((o) => o.c - o.w / 2 > a0 && o.c + o.w / 2 < a1).sort((p, q) => p.c - q.c);
  const piece = (from, to, y0, y1, isGlass = false) => {
    const len = to - from; if (len <= 0.01 || y1 - y0 <= 0.01) return;
    const mid = (from + to) / 2;
    const w = axis === 'x' ? len : T, d = axis === 'x' ? T : len;
    const x = axis === 'x' ? mid : fixed, z = axis === 'x' ? fixed : mid;
    const m = box(isGlass ? (axis === 'x' ? len : 0.02) : w, y1 - y0, isGlass ? (axis === 'x' ? 0.02 : len) : d, isGlass ? M.glass : material, x, y0, z, parent, !isGlass);
    if (!isGlass && y0 < 1.4) {
      tour.colliders.push({ minX: x - w / 2, maxX: x + w / 2, minZ: z - d / 2, maxZ: z + d / 2 });
    }
    if (isGlass) tour.colliders.push({ minX: x - w / 2, maxX: x + w / 2, minZ: z - d / 2, maxZ: z + d / 2 });
    return m;
  };
  let cur = a0;
  for (const o of ops) {
    piece(cur, o.c - o.w / 2, 0, H);
    if (o.bottom > 0) piece(o.c - o.w / 2, o.c + o.w / 2, 0, o.bottom);
    piece(o.c - o.w / 2, o.c + o.w / 2, o.top, H);
    if (o.glass) piece(o.c - o.w / 2, o.c + o.w / 2, o.bottom, o.top, true);
    cur = o.c + o.w / 2;
  }
  piece(cur, a1, 0, H);
}

// ---- furniture (local room coords: back wall at -z, door wall at +z) -----
function sofa(c, fabric, len = 2.4) {
  const g = new THREE.Group();
  box(len, 0.42, 0.95, fabric, 0, 0.05, 0, g);
  box(len, 0.5, 0.22, fabric, 0, 0.45, -0.37, g);
  box(0.2, 0.25, 0.95, fabric, -len / 2 + 0.1, 0.45, 0, g);
  box(0.2, 0.25, 0.95, fabric, len / 2 - 0.1, 0.45, 0, g);
  for (let i = 0; i < 3; i++) box(len / 3 - 0.08, 0.1, 0.7, mat('#ffffff', { roughness: 1, color: fabric.color.clone().offsetHSL(0, 0, .08) }), -len / 3 + i * len / 3, 0.47, 0.08, g);
  box(0.45, 0.4, 0.12, M.linen, -len / 2 + 0.5, 0.55, -0.22, g).rotation.x = -0.2;
  c.add(g); return g;
}
function chair(c, m) {
  const g = new THREE.Group();
  box(0.45, 0.05, 0.45, m, 0, 0.45, 0, g);
  box(0.45, 0.5, 0.05, m, 0, 0.5, -0.2, g);
  for (const [x, z] of [[-.19, -.19], [.19, -.19], [-.19, .19], [.19, .19]]) box(0.04, 0.45, 0.04, M.darkwood, x, 0, z, g);
  c.add(g); return g;
}
function plant(c, x, z, s = 1) {
  cyl(0.18 * s, 0.14 * s, 0.4 * s, M.pot, x, 0, z, c, 12);
  for (let i = 0; i < 4; i++) {
    const l = new THREE.Mesh(new THREE.IcosahedronGeometry(0.28 * s, 0), i % 2 ? M.leaf : M.leaf2);
    l.position.set(x + (rand() - .5) * .25 * s, (0.65 + i * 0.22) * s, z + (rand() - .5) * .25 * s); l.castShadow = true; c.add(l);
  }
}
function lampTable(c, x, z) {
  cyl(0.05, 0.08, 0.35, M.metal, x, 0.55, z, c, 10);
  const shade = cyl(0.12, 0.18, 0.22, M.lamp, x, 0.88, z, c, 16); shade.castShadow = false;
}
function rug(c, w, d, x = 0, z = 0) {
  plane(w, d, new THREE.MeshStandardMaterial({ map: TEX.rug, roughness: 1 }), x, 0.012, z, c);
}

function furnish(room, L) {
  const c = new THREE.Group();
  const { w, d } = room;
  const fabric = mat(L.accent, { roughness: .95 });
  const bw = -d / 2 + 0.02; // back wall z
  switch (room.type) {
    case 'living': {
      rug(c, Math.min(3.2, w - 1.5), Math.min(2.4, d - 1.5), 0, -0.2);
      const s1 = sofa(c, fabric, Math.min(2.6, d - 1.6)); s1.rotation.y = Math.PI / 2; s1.position.set(-w / 2 + 0.55, 0, -0.2);
      const s2 = sofa(c, fabric, 1.4); s2.position.set(-0.2, 0, bw + 0.55);
      box(1.1, 0.06, 0.6, M.darkwood, 0, 0.38, -0.2, c); box(0.9, 0.38, 0.45, M.darkwood, 0, 0, -0.2, c);
      const tv = new THREE.Group(); tv.rotation.y = -Math.PI / 2; tv.position.set(w / 2 - 0.3, 0, -0.2); c.add(tv);
      box(2.0, 0.5, 0.45, M.darkwood, 0, 0, 0, tv); box(1.6, 0.92, 0.05, M.screen, 0, 1.0, -0.05, tv); box(1.65, 0.96, 0.03, M.black, 0, 0.98, -0.09, tv);
      plant(c, w / 2 - 0.4, bw + 0.4, 1.3); plant(c, -w / 2 + 0.45, bw + 0.4, 1);
      lampTable(c, -w / 2 + 0.5, bw + 0.5);
      break;
    }
    case 'kitchen': {
      const cab = mat('#ffffff', { roughness: .5 }), top = new THREE.MeshStandardMaterial({ map: TEX.marble, roughness: .25 });
      const len = w - 0.9;
      box(len, 0.86, 0.62, cab, -0.45 + 0, 0, bw + 0.31, c);
      box(len, 0.04, 0.64, top, -0.45, 0.86, bw + 0.32, c);
      box(len, 0.7, 0.36, cab, -0.45, 1.55, bw + 0.18, c);
      box(0.6, 0.02, 0.45, M.metal, -0.8, 0.9, bw + 0.32, c); // sink
      box(0.6, 0.02, 0.5, M.black, 0.6, 0.9, bw + 0.32, c); // hob
      box(0.75, 2.0, 0.7, M.metal, w / 2 - 0.45, 0, bw + 0.36, c); // fridge
      box(len, 0.6, 0.02, mat('#d9d4ca'), -0.45, 0.9, bw + 0.01, c, false); // splashback
      if (d >= 3.6) {
        box(Math.min(2, w - 2), 0.9, 0.9, mat(L.accent), 0, 0, 0.2, c);
        box(Math.min(2, w - 2) + 0.1, 0.04, 1.0, top, 0, 0.9, 0.2, c);
        for (const x of [-0.5, 0.5]) { const st = cyl(0.18, 0.18, 0.06, M.darkwood, x, 0.66, 0.95, c); cyl(0.03, 0.03, 0.66, M.metal, x, 0, 0.95, c, 6); }
      }
      for (const x of [-0.6, 0.6]) { cyl(0.005, 0.005, 0.8, M.black, x, H - 0.8, 0.2, c, 4); cyl(0.12, 0.16, 0.18, M.lamp, x, H - 0.98, 0.2, c); }
      break;
    }
    case 'dining': {
      const tw = Math.min(2.0, w - 1.6);
      box(tw, 0.05, 1.0, M.darkwood, 0, 0.72, -0.1, c); box(tw - 0.3, 0.72, 0.15, M.darkwood, 0, 0, -0.1, c);
      const n = Math.max(2, Math.floor(tw / 0.65));
      for (let i = 0; i < n; i++) {
        const x = -tw / 2 + (i + 0.5) * tw / n;
        chair(c, fabric).position.set(x, 0, -0.85);
        const ch = chair(c, fabric); ch.position.set(x, 0, 0.65); ch.rotation.y = Math.PI;
      }
      cyl(0.005, 0.005, 0.9, M.black, 0, H - 0.9, -0.1, c, 4); cyl(0.25, 0.3, 0.18, M.lamp, 0, H - 1.08, -0.1, c, 20);
      box(1.6, 0.8, 0.45, M.darkwood, 0, 0, bw + 0.23, c);
      plant(c, w / 2 - 0.4, bw + 0.4, 1.1); plant(c, -w / 2 + 0.4, bw + 0.4, 0.8);
      break;
    }
    case 'master': case 'bedroom': {
      const big = room.type === 'master';
      const bwid = big ? 1.9 : 1.45, blen = 2.1;
      rug(c, bwid + 1.2, 1.8, 0, bw + 1.4);
      box(bwid + 0.1, 0.3, blen, M.darkwood, 0, 0.05, bw + blen / 2, c);
      box(bwid, 0.22, blen - 0.05, M.linen, 0, 0.35, bw + blen / 2, c);
      box(bwid + 0.02, 0.08, blen * 0.6, fabric, 0, 0.55, bw + blen * 0.67, c);
      box(bwid + 0.2, 1.15, 0.1, M.darkwood, 0, 0.05, bw + 0.05, c);
      for (const x of big ? [-0.45, 0.45] : [-0.3, 0.3]) box(0.6, 0.14, 0.38, M.linen, x, 0.57, bw + 0.35, c);
      for (const sx of [-1, 1]) { const x = sx * (bwid / 2 + 0.38); box(0.5, 0.5, 0.42, M.lightwood, x, 0, bw + 0.25, c); lampTable(c, x, bw + 0.25); }
      // wardrobe on side wall, toward the back
      if (w > 3.2) {
        const wd = new THREE.Group(); wd.rotation.y = -Math.PI / 2; wd.position.set(w / 2 - 0.32, 0, Math.min(0.6, d / 2 - 1.4)); c.add(wd);
        box(Math.min(2.0, d - 2.4), 2.3, 0.6, mat('#ece6dc', { roughness: .5 }), 0, 0, 0, wd);
      }
      if (big) { plant(c, -w / 2 + 0.45, d / 2 - 0.8, 1.2); const ar = chair(c, fabric); ar.position.set(-w / 2 + 0.6, 0, 0.6); ar.rotation.y = Math.PI / 2; }
      break;
    }
    case 'bath': {
      plane(w - T, d - T, texMat(TEX.tile, w, d, { scale: 1.2, roughness: .3 }), 0, 0.011, 0, c);
      box(1.0, 0.8, 0.5, M.lightwood, -w / 2 + 0.7, 0, bw + 0.25, c);
      box(1.0, 0.05, 0.52, M.porcelain, -w / 2 + 0.7, 0.8, bw + 0.26, c);
      box(0.8, 0.9, 0.03, mat('#cfe3ee', { metalness: .9, roughness: .05 }), -w / 2 + 0.7, 1.05, bw + 0.02, c, false);
      // toilet
      box(0.4, 0.42, 0.55, M.porcelain, w / 2 - 0.5, 0, bw + 0.45, c); box(0.42, 0.4, 0.18, M.porcelain, w / 2 - 0.5, 0.42, bw + 0.12, c);
      // shower / tub along side, toward door
      const tubLen = Math.min(1.7, d - 1.2);
      const tub = new THREE.Group(); tub.position.set(-w / 2 + 0.45, 0, d / 2 - tubLen / 2 - 0.15); c.add(tub);
      box(0.8, 0.55, tubLen, M.porcelain, 0, 0, 0, tub); box(0.65, 0.02, tubLen - 0.15, M.water, 0, 0.5, 0, tub);
      break;
    }
    case 'study': {
      box(1.6, 0.04, 0.7, M.lightwood, 0, 0.74, bw + 0.36, c);
      for (const x of [-0.75, 0.75]) box(0.05, 0.74, 0.7, M.lightwood, x, 0, bw + 0.36, c);
      box(0.6, 0.38, 0.03, M.screen, 0, 0.82, bw + 0.18, c); box(0.08, 0.1, 0.08, M.black, 0, 0.78, bw + 0.2, c);
      const ch = chair(c, M.black); ch.position.set(0, 0, bw + 1.05); ch.rotation.y = Math.PI;
      const shelf = new THREE.Group(); shelf.rotation.y = Math.PI / 2; shelf.position.set(-w / 2 + 0.2, 0, 0); c.add(shelf);
      const sw = Math.min(1.8, d - 1.4);
      box(sw, 2.1, 0.35, M.darkwood, 0, 0, 0, shelf);
      const bookCols = ['#8b2e2e', '#2f4f6f', '#c9a227', '#3e6b48', '#6b4f8b', '#d9d4ca'];
      for (let s = 0; s < 4; s++) for (let b = 0; b < 9; b++) {
        box(0.07 + rand() * 0.05, 0.28 + rand() * 0.08, 0.24, mat(bookCols[(b + s) % 6]), -sw / 2 + 0.15 + b * (sw - 0.3) / 9, 0.12 + s * 0.5, 0.05, shelf, false);
      }
      plant(c, w / 2 - 0.4, bw + 0.4, 1);
      break;
    }
  }
  // orient: row 0 rooms have back wall at north (-z) already; row 1 rotated 180°
  c.position.set(room.cx, 0, room.cz);
  if (room.row === 1) c.rotation.y = Math.PI;
  return c;
}

function makeLabel(text, cls, onClick) {
  const el = document.createElement('div');
  el.className = cls; el.innerHTML = text;
  if (onClick) el.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
  $('labels').appendChild(el);
  return el;
}
function clearLabels(list) { list.forEach((l) => l.el.remove()); list.length = 0; }

function buildTour(L) {
  const s = new THREE.Scene();
  tour.scene = s; tour.listing = L; tour.colliders = []; tour.floors = []; tour.ceiling = [];
  clearLabels(tour.labels);
  makeSky(s, '#8ec0e6', '#eaf3f8');
  s.fog = new THREE.Fog('#eaf3f8', 60, 200);

  const plan = layoutRooms(L);
  tour.plan = plan;
  const { rooms, hall, W, zMin, zMax } = plan;
  const extent = Math.max(W, zMax - zMin) / 2 + 6;
  addSun(s, extent, [18, 30, 22]);

  // outside: grass, terrace, palms
  const ground = plane(400, 400, M.grass, 0, -0.01, 0, s); ground.material = M.grass;
  plane(W + 6, zMax - zMin + 6, texMat(TEX.paving, W + 6, zMax - zMin + 6, { scale: 3 }), 0, 0.0, 0, s);
  for (let i = 0; i < 14; i++) {
    const a = (i / 14) * Math.PI * 2, r = extent + 6 + rand() * 10;
    rand() > .4 ? palm(s, Math.cos(a) * r, Math.sin(a) * r, 0.9 + rand() * .4) : treeRound(s, Math.cos(a) * r, Math.sin(a) * r, 1);
  }
  box(W + 0.6, 0.12, zMax - zMin + 0.6, M.concrete, 0, -0.1, (zMin + zMax) / 2, s, false); // plinth

  // floors
  const floorFor = (r) => {
    const tex = r.type === 'kitchen' || r.type === 'bath' ? TEX.tile : r.type === 'hall' || r.type === 'living' || r.type === 'dining' ? TEX.marble : TEX.wood;
    const scale = tex === TEX.wood ? 2.5 : tex === TEX.marble ? 2.2 : 1.2;
    const f = plane(r.x1 - r.x0, r.z1 - r.z0, texMat(tex, r.x1 - r.x0, r.z1 - r.z0, { scale, roughness: tex === TEX.wood ? .6 : .3 }), (r.x0 + r.x1) / 2, 0.01, (r.z0 + r.z1) / 2, s);
    f.userData.room = r; tour.floors.push(f);
  };
  [...rooms, hall].forEach(floorFor);

  // walls
  const wallM = mat(L.wall === '#f3eee6' ? '#f4f0ea' : L.wall, { roughness: .92 });
  const win = (r) => ({ c: r.cx, w: Math.min(2.2, r.w - 1.2), bottom: r.type === 'bath' ? 1.5 : 0.9, top: 2.2, glass: true });
  const rowA = rooms.filter((r) => r.row === 0), rowB = rooms.filter((r) => r.row === 1);
  const x0 = -W / 2, x1 = W / 2;
  wall(s, 'x', zMin, x0 - T / 2, x1 + T / 2, rowA.filter((r) => r.w > 2).map(win), wallM);
  wall(s, 'x', zMax, x0 - T / 2, x1 + T / 2, rowB.filter((r) => r.w > 2).map(win), wallM);
  wall(s, 'z', x0, zMin, zMax, [{ c: hall.cz, w: 1.2, bottom: 0, top: 2.3 }], wallM); // front door
  wall(s, 'z', x1, zMin, zMax, [{ c: hall.cz, w: 1.2, bottom: 0.9, top: 2.2, glass: true }], wallM);
  const door = (r) => ({ c: r.cx + (r.type === 'bath' || r.type === 'bedroom' ? 0 : 0), w: r.type === 'living' || r.type === 'dining' ? 1.6 : 0.95, bottom: 0, top: 2.15 });
  wall(s, 'x', hall.z0, x0, x1, rowA.map(door), wallM);
  wall(s, 'x', hall.z1, x0, x1, rowB.map(door), wallM);
  for (const row of [rowA, rowB]) for (let i = 0; i < row.length - 1; i++) wall(s, 'z', row[i].x1, row[i].z0, row[i].z1, [], wallM);
  // skirting & door frames for a little detail
  const frameM = M.darkwood;
  for (const r of rooms) {
    const z = r.row === 0 ? hall.z0 : hall.z1, dw = door(r).w;
    for (const sx of [-1, 1]) box(0.06, 2.1, T + 0.04, frameM, r.cx + sx * (dw / 2 - 0.03), 0, z, s, false);
    box(dw, 0.06, T + 0.04, frameM, r.cx, 2.09, z, s, false);
  }
  // front door slab (open) and step
  const fd = box(0.05, 2.25, 1.15, mat(L.accent, { roughness: .5 }), x0 - 0.55, 0, hall.cz - 0.6, s); fd.rotation.y = 0.9;
  box(1.2, 0.08, 2.2, M.concrete, x0 - 0.7, -0.04, hall.cz, s, false);

  // ceiling (walk mode only) + lights
  const ceil = new THREE.Mesh(new THREE.PlaneGeometry(W + 0.2, zMax - zMin + 0.2), new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#e9e5de', emissiveIntensity: .75, roughness: 1, side: THREE.DoubleSide }));
  ceil.rotation.x = Math.PI / 2; ceil.position.set(0, H, (zMin + zMax) / 2); ceil.visible = false; s.add(ceil); tour.ceiling.push(ceil);
  for (const r of [...rooms, hall]) {
    const light = new THREE.PointLight('#ffe9c7', r.type === 'hall' ? 4 : 7, 9, 1.6);
    light.position.set(r.cx, H - 0.3, r.cz); s.add(light);
    if (r.type !== 'hall') {
      const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.03, 20), M.lamp); disc.position.set(r.cx, H - 0.02, r.cz); disc.visible = false; s.add(disc); tour.ceiling.push(disc);
    }
  }
  // furniture
  for (const r of rooms) s.add(furnish(r, L));
  plant(s, x1 - 0.4, hall.z0 + 0.35, 1);

  // room labels
  for (const r of rooms) {
    const el = makeLabel(r.name, 'tag', () => goToRoom(r));
    tour.labels.push({ el, pos: new THREE.Vector3(r.cx, H + 0.4, r.cz) });
  }
  tour.bounds = { W, zMin, zMax, extent };
  return s;
}

// ============================================================================
// Camera animation
// ============================================================================
let camAnim = null;
const ease = (t) => (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
function flyTo(pos, target, dur = 1.2, done) {
  camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos.clone(), t1: target.clone(), start: performance.now(), dur: dur * 1000, done };
}
function stepCamAnim(now) {
  if (!camAnim) return;
  const k = Math.min(1, (now - camAnim.start) / camAnim.dur), e = ease(k);
  camera.position.lerpVectors(camAnim.p0, camAnim.p1, e);
  controls.target.lerpVectors(camAnim.t0, camAnim.t1, e);
  if (k >= 1) { const d = camAnim.done; camAnim = null; d && d(); }
}

// ============================================================================
// App state & UI
// ============================================================================
let view = 'showcase';
let hintTimer;
function hint(text, ms = 4500) {
  const h = $('hint'); h.textContent = text; h.style.opacity = 1;
  clearTimeout(hintTimer); hintTimer = setTimeout(() => (h.style.opacity = 0), ms);
}

const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function buildStrip(list) {
  const strip = $('strip');
  strip.innerHTML = '';
  for (const L of list) {
    const b = document.createElement('button');
    b.className = 'card'; b.dataset.id = L.id;
    const img = L.images[0] ? `<img class="thumb" loading="lazy" alt="" src="${esc(L.images[0])}">` : '';
    b.innerHTML = `${img}<div class="cbody"><div class="st">${L.status}</div><div class="t">${esc(L.title)}</div><div class="a">${esc(L.area)}</div><div class="p">${esc(L.price)}<small>${L.beds} bd · ${L.baths} ba</small></div></div>`;
    b.onclick = () => (view === 'showcase' ? showcaseTo(L.id) : selectListing(L.id));
    strip.appendChild(b);
  }
}
function buildPins() {
  for (const [id, h] of estate.houses) {
    const L = h.L;
    const photo = L.images[0] ? `<img class="pimg" alt="" data-src="${esc(L.images[0])}">` : '';
    const el = makeLabel(`<div class="bubble">${photo}<b>${esc(L.price)}</b><span>${L.beds} bd · ${esc(L.shortArea)}</span></div><div class="stem"></div>`, 'pin', () => selectListing(id));
    const height = L.style === 'apartment' ? 17.5 : L.style === 'townhouse' ? 10 : 8;
    estate.pins.push({ el, pos: new THREE.Vector3(h.pos.x, height, h.pos.z), id, maxDist: 150 });
  }
}

// ---- filters ----
const filter = { kind: 'all', region: 'all' };
function filtered() {
  return LISTINGS.filter((L) => (filter.kind === 'all' || L.kind === filter.kind) && (filter.region === 'all' || L.region === filter.region));
}
function buildFilters() {
  const kinds = [['all', 'All'], ['buy', 'For Sale'], ['rent', 'For Rent'], ['short-stay', 'Short Stay'], ['commercial', 'Commercial']]
    .filter(([k]) => k === 'all' || LISTINGS.some((L) => L.kind === k));
  const regions = ['all', ...new Set(LISTINGS.map((L) => L.region))];
  const count = (k) => LISTINGS.filter((L) => k === 'all' || L.kind === k).length;
  $('filters').innerHTML =
    kinds.map(([k, t]) => `<button data-kind="${k}" class="${filter.kind === k ? 'on' : ''}">${t} <i>${count(k)}</i></button>`).join('') +
    `<select id="regionSel" aria-label="Region">${regions.map((r) => `<option value="${esc(r)}" ${filter.region === r ? 'selected' : ''}>${r === 'all' ? 'All regions' : esc(r)}</option>`).join('')}</select>`;
  $('filters').querySelectorAll('button').forEach((b) => (b.onclick = () => { filter.kind = b.dataset.kind; applyFilter(); }));
  $('regionSel').onchange = (e) => { filter.region = e.target.value; applyFilter(); };
}
function applyFilter() {
  const list = filtered();
  closePanel(); deselect();
  buildEstate(list); buildStrip(list); buildFilters();
  $('emptyMsg').style.display = list.length ? 'none' : '';
  if (view === 'showcase') { estate.pins.forEach((p) => (p.el.style.display = 'none')); startShowcase(); } else overviewEstate();
}
function overviewEstate() {
  const e = estate.extent || 60, mobile = innerWidth < 761;
  controls.maxDistance = Math.max(150, e * 4);
  flyTo(new THREE.Vector3(0, e * (mobile ? 1.9 : 1.05) + 20, e * (mobile ? 1.9 : 1.3) + 30), new THREE.Vector3(0, 0, mobile ? 6 : 0), 1.2);
  controls.autoRotate = true;
}

function panelHTML(L) {
  const wa = AGENCY.whatsapp ? `<a class="btn ghost" style="text-decoration:none" target="_blank" rel="noopener" href="https://wa.me/${AGENCY.whatsapp}?text=${encodeURIComponent('Hello MED Property, I am interested in: ' + L.title + ' (' + L.area + ')')}">Chat on WhatsApp</a>` : '';
  const imgs = L.images;
  const gallery = imgs.length ? `<div class="gallery"><img id="galMain" alt="${esc(L.title)}" src="${esc(imgs[0])}"><span class="gcount" id="galCount">1 / ${imgs.length}</span>
      ${imgs.length > 1 ? '<button class="gnav prev" id="galPrev" aria-label="Previous photo">‹</button><button class="gnav next" id="galNext" aria-label="Next photo">›</button>' : ''}</div>` : '';
  const desc = L.description.length > 320 ? `<p id="descP">${esc(L.description.slice(0, 300))}… <a href="#" id="moreBtn">more</a></p>` : `<p>${esc(L.description)}</p>`;
  return `${gallery}<div class="st">${L.status}</div><h2>${esc(L.title)}</h2><div class="area">${esc(L.area)}</div>
    <div class="price">${esc(L.price)}</div>
    <div class="facts"><div><b>${L.beds}</b><span>Bedrooms</span></div><div><b>${L.baths}</b><span>Bathrooms</span></div><div><b>${esc(L.size)}</b><span>Size</span></div></div>
    ${desc}
    ${L.features.length ? `<div class="chips">${L.features.map((f) => `<span>${esc(f)}</span>`).join('')}</div>` : ''}
    ${view !== 'tour' ? `<button class="btn primary" id="enterBtn">${L.images.length ? 'Walk through this home' : 'Step inside in 3D'}</button>` : ''}
    <button class="btn gold" id="bookBtn">Book a viewing</button>${wa}
    ${L.video ? `<a class="btn ghost" style="text-decoration:none" target="_blank" rel="noopener" href="${esc(L.video)}">▶ Watch the video tour</a>` : ''}
    <div class="demo-note">Photos and details from MED Property. The 3D plan is an illustration based on the room count.</div>`;
}
function openPanel(L) {
  $('panelBody').innerHTML = panelHTML(L);
  $('panel').classList.remove('hidden');
  const eb = $('enterBtn'); if (eb) eb.onclick = () => { if (view !== 'tour') homeView = view; enterTour(L.id); };
  $('bookBtn').onclick = () => openBooking(L);
  let gi = 0; const show = (d) => { gi = (gi + d + L.images.length) % L.images.length; $('galMain').src = L.images[gi]; $('galCount').textContent = `${gi + 1} / ${L.images.length}`; };
  if ($('galPrev')) { $('galPrev').onclick = () => show(-1); $('galNext').onclick = () => show(1); }
  const mb = $('moreBtn'); if (mb) mb.onclick = (e) => { e.preventDefault(); $('descP').textContent = L.description; };
  if (matchMedia('(max-width: 760px)').matches) $('strip').style.display = 'none';
}
function closePanel() {
  $('panel').classList.add('hidden');
  if (view !== 'tour') $('strip').style.display = '';
}
$('panelClose').onclick = () => { closePanel(); if (view === 'estate') deselect(); };

function selectListing(id) {
  if (view !== 'estate') return;
  const h = estate.houses.get(id); if (!h) return;
  estate.selected = id;
  estate.ring.visible = true; estate.ring.position.set(h.pos.x, 0.08, h.pos.z);
  document.querySelectorAll('.card').forEach((c) => c.classList.toggle('sel', c.dataset.id === id));
  estate.pins.forEach((p) => p.el.classList.toggle('sel', p.id === id));
  const card = document.querySelector(`.card[data-id="${id}"]`); card && card.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  const dirZ = h.pos.z < 0 ? 1 : -1;
  const mobile = innerWidth < 761;
  const tgt = h.pos.clone().add(new THREE.Vector3(mobile ? 0 : 4, 3, 0));
  const pos = h.pos.clone().add(new THREE.Vector3(mobile ? 12 : 14, mobile ? 44 : 20, dirZ * (mobile ? 46 : 30)));
  if (mobile) tgt.y = -9; // keep house above the bottom sheet
  controls.autoRotate = false;
  flyTo(pos, tgt, 1.3);
  openPanel(h.L);
  history.replaceState(null, '', `#${id}`);
}
function deselect() {
  estate.selected = null; estate.ring.visible = false;
  document.querySelectorAll('.card').forEach((c) => c.classList.remove('sel'));
  estate.pins.forEach((p) => p.el.classList.remove('sel'));
  history.replaceState(null, '', location.pathname);
}

// ---- booking modal (demo) ----
function openBooking(L) {
  $('bookSub').textContent = `${L.title} · ${L.area}`;
  $('modal').classList.add('show');
}
$('bookCancel').onclick = () => $('modal').classList.remove('show');
$('bookForm').onsubmit = (e) => {
  e.preventDefault();
  const name = $('bName').value.trim();
  $('bookForm').querySelector('.btn.primary').textContent = `Thanks ${name.split(' ')[0] || ''}! We'll be in touch.`;
  setTimeout(() => { $('modal').classList.remove('show'); $('bookForm').reset(); $('bookForm').querySelector('.btn.primary').textContent = 'Request viewing'; }, 1800);
};

// ---- view switching ----
let homeView = 'showcase';
function leaveTour() {
  clearLabels(tour.labels);
  if (tour.scene) { tour.scene.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); } }); tour.scene = null; }
  setWalk(false);
  $('backBtn').style.display = 'none'; $('modeSeg').style.display = 'none'; $('infoBtn').style.display = 'none';
  $('tourbar').classList.remove('show'); $('strip').style.display = ''; $('filters').style.display = '';
  document.body.classList.remove('touring');
  closePanel();
}
function showShowcase() {
  view = 'showcase'; homeView = 'showcase';
  leaveTour();
  estate.pins.forEach((p) => (p.el.style.display = 'none'));
  controls.autoRotate = false;
  $('viewToggle').innerHTML = '🗺 <span class="hide-sm">3D </span>Map'; $('viewToggle').style.display = '';
  startShowcase();
  history.replaceState(null, '', location.pathname);
}
function showEstate() {
  view = 'estate'; homeView = 'estate';
  stopPhotoTour();
  $('viewToggle').innerHTML = '▶ Photos'; $('viewToggle').style.display = '';
  clearLabels(tour.labels);
  if (tour.scene) { tour.scene.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); } }); tour.scene = null; }
  setWalk(false);
  estate.pins.forEach((p) => (p.el.style.display = ''));
  $('backBtn').style.display = 'none'; $('modeSeg').style.display = 'none'; $('infoBtn').style.display = 'none';
  $('tourbar').classList.remove('show'); $('strip').style.display = ''; $('filters').style.display = '';
  closePanel();
  controls.enabled = true; controls.minDistance = 12; controls.maxDistance = Math.max(150, (estate.extent || 60) * 4); controls.maxPolarAngle = 1.38; controls.enablePan = true;
  camera.near = 0.5; camera.fov = 50; camera.updateProjectionMatrix();
  document.body.classList.remove('touring');
  const id = estate.selected;
  if (id && estate.houses.has(id)) selectListing(id); else overviewEstate();
  hint(isTouch ? 'Drag to rotate · Pinch to zoom · Tap a house' : 'Drag to rotate · Scroll to zoom · Click a house');
}

function enterTour(id) {
  const L = LISTINGS.find((l) => l.id === id); if (!L) return;
  view = 'tour';
  estate.selected = id;
  stopPhotoTour(); $('viewToggle').style.display = 'none';
  document.body.classList.add('touring');
  closePanel();
  estate.pins.forEach((p) => (p.el.style.display = 'none'));
  $('strip').style.display = 'none'; $('filters').style.display = 'none';
  buildTour(L);
  $('backBtn').style.display = ''; $('modeSeg').style.display = ''; $('infoBtn').style.display = '';
  $('tourbar').classList.add('show');
  const chips = $('roomChips'); chips.innerHTML = '';
  const all = document.createElement('button'); all.textContent = 'Whole house'; all.className = 'on'; all.onclick = () => overview(); chips.appendChild(all);
  for (const r of tour.plan.rooms) {
    const b = document.createElement('button'); b.textContent = r.name; b.onclick = () => goToRoom(r); b.dataset.room = r.name; chips.appendChild(b);
  }
  controls.autoRotate = false;
  $('modeSeg').querySelector('[data-mode="photos"]').style.display = L.images.length ? '' : 'none';
  if (L.images.length) { setMode('dollhouse', true); setMode('photos'); } else setMode('dollhouse', true);
  history.replaceState(null, '', `#tour=${id}`);
}
function markChip(name) {
  document.querySelectorAll('#roomChips button').forEach((b) => b.classList.toggle('on', (b.dataset.room || 'Whole house') === name));
}
function overview() {
  if (tour.mode !== 'dollhouse') setMode('dollhouse');
  const e = tour.bounds.extent;
  const mobile = innerWidth < 761;
  flyTo(new THREE.Vector3(e * 0.35, e * (mobile ? 2.6 : 1.75), e * (mobile ? 1.5 : 1.15)), new THREE.Vector3(0, 0, mobile ? 0 : 0.5), 1.2);
  markChip('Whole house');
}
function goToRoom(r) {
  markChip(r.name);
  if (tour.mode === 'walk') {
    // stand just inside the door, looking at the back wall
    const inward = r.row === 0 ? -1 : 1;
    const doorZ = r.row === 0 ? r.z1 : r.z0;
    walk.target = null;
    walkFly(new THREE.Vector3(r.cx, EYE, doorZ + inward * 0.25), inward === -1 ? 0 : Math.PI);
  } else {
    const dir = r.row === 0 ? 1 : -1;
    flyTo(new THREE.Vector3(r.cx + 0.5, 6.5, r.cz + dir * 5.5), new THREE.Vector3(r.cx, 0.6, r.cz), 1.1);
  }
}
function setMode(mode, initial = false) {
  tour.mode = mode;
  document.querySelectorAll('#modeSeg button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
  if (mode === 'photos') {
    setWalk(false); controls.enabled = false;
    tour.labels.forEach((l) => (l.el.style.display = 'none'));
    $('tourbar').classList.remove('show');
    startPhotoTour(tour.listing);
    return;
  }
  stopPhotoTour();
  $('tourbar').classList.add('show');
  if (mode === 'dollhouse') {
    setWalk(false);
    tour.ceiling.forEach((c) => (c.visible = false));
    tour.labels.forEach((l) => (l.el.style.display = ''));
    controls.enabled = true; controls.minDistance = 3; controls.maxDistance = 70; controls.maxPolarAngle = 1.35; controls.enablePan = true;
    camera.near = 0.1; camera.fov = 50; camera.updateProjectionMatrix();
    if (initial) {
      const e = tour.bounds.extent;
      camera.position.set(e * 1.6, e * 1.8, e * 2.2); controls.target.set(0, 0, 0);
      overview();
      hint(isTouch ? 'Tap a room name, or switch to “Walk inside”' : 'Click a room name, or switch to “Walk inside”', 6000);
    } else overview();
  } else {
    tour.ceiling.forEach((c) => (c.visible = true));
    tour.labels.forEach((l) => (l.el.style.display = 'none'));
    controls.enabled = false;
    camera.near = 0.05; camera.fov = innerWidth < innerHeight ? 80 : 70; camera.updateProjectionMatrix();
    setWalk(true);
    const { hall } = tour.plan;
    camAnim = null;
    camera.position.set(hall.x0 + 0.7, EYE, hall.cz);
    walk.yaw = -Math.PI / 2; walk.pitch = -0.05;
    hint(isTouch ? 'Drag to look · Joystick to move · Tap the floor to walk there' : 'Drag to look · W A S D / arrows to move · Click the floor to walk there', 6500);
  }
}
document.querySelectorAll('#modeSeg button').forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
$('backBtn').onclick = () => (homeView === 'showcase' ? showShowcase() : showEstate());
$('viewToggle').onclick = () => (view === 'showcase' ? showEstate() : showShowcase());
$('infoBtn').onclick = () => ($('panel').classList.contains('hidden') ? openPanel(tour.listing) : closePanel());
$('brand').onclick = (e) => { e.preventDefault(); closePanel(); if (view === 'estate') deselect(); showShowcase(); };

// ============================================================================
// Cinematic photo walkthrough (the real listing photos, full screen)
// ============================================================================
const pt = { slides: [], kind: 'tour', i: 0, front: 0, timer: null, playing: true, DUR: 6000 };
const KB = [['20% 30%', 1.14], ['80% 30%', 1.14], ['50% 80%', 1.12], ['30% 70%', 1.16], ['70% 60%', 1.12], ['50% 50%', 1.1]];
function startPhotoTour(L) {
  pt.kind = 'tour'; pt.slides = L.images.map((u) => ({ u, L })); pt.i = -1; pt.playing = true;
  $('photoTour').classList.add('show'); $('photoTour').classList.remove('showcase');
  $('pThumbs').innerHTML = L.images.map((u, k) => `<button data-k="${k}" aria-label="Photo ${k + 1}"><img loading="lazy" alt="" src="${esc(u)}"></button>`).join('');
  $('pThumbs').querySelectorAll('button').forEach((b) => (b.onclick = () => photoGo(+b.dataset.k, true)));
  $('pAct').innerHTML = '';
  photoGo(0);
  hint(isTouch ? 'Swipe or tap the arrows to see every room' : 'Use ← → or the arrows to see every room', 5000);
}
// Home screen: a cinematic reel of every listing's real cover photo
function startShowcase() {
  const list = filtered().filter((L) => L.images.length);
  pt.kind = 'showcase'; pt.slides = list.map((L) => ({ u: L.images[0], L })); pt.i = -1; pt.playing = true;
  $('photoTour').classList.add('show', 'showcase');
  $('pThumbs').innerHTML = '';
  if (pt.slides.length) photoGo(0); else { $('pTitle').textContent = ''; $('pSub').textContent = ''; $('pAct').innerHTML = ''; }
}
function stopPhotoTour() { clearTimeout(pt.timer); $('photoTour').classList.remove('show'); }
function photoGo(i, user = false) {
  const n = pt.slides.length; if (!n) return;
  i = (i + n) % n; if (i === pt.i) return; pt.i = i;
  const { u, L } = pt.slides[i];
  const back = $('ps' + (1 - pt.front)), front = $('ps' + pt.front);
  const [origin, scale] = KB[i % KB.length];
  back.style.backgroundImage = `url("${u.replace(/"/g, '%22')}")`;
  back.style.transformOrigin = origin; back.style.setProperty('--kb', scale);
  back.classList.remove('kb'); void back.offsetWidth; back.classList.add('kb');
  back.style.opacity = 1; front.style.opacity = 0;
  pt.front = 1 - pt.front;
  $('pCount').textContent = `${i + 1} / ${n}`;
  $('pTitle').textContent = L.title; $('pSub').textContent = `${L.status} · ${L.area} · ${L.price}`;
  if (pt.kind === 'tour') {
    $('pThumbs').querySelectorAll('button').forEach((b, k) => b.classList.toggle('on', k === i));
    const cur = $('pThumbs').children[i]; cur && cur.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  } else {
    $('pAct').innerHTML = `<button class="btn primary" id="pWalk">Walk through this home</button><button class="btn ghost" id="pDetails">Details & price</button>`;
    $('pWalk').onclick = () => { homeView = 'showcase'; enterTour(L.id); };
    $('pDetails').onclick = () => { setPlaying(false); openPanel(L); };
    document.querySelectorAll('.card').forEach((c) => c.classList.toggle('sel', c.dataset.id === L.id));
    const card = document.querySelector(`.card[data-id="${L.id}"]`); card && card.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }
  const nx = pt.slides[(i + 1) % n]; new Image().src = nx.u; // preload next
  if (user) setPlaying(false); else schedule();
}
function showcaseTo(id) { const k = pt.slides.findIndex((s) => s.L.id === id); if (k >= 0) photoGo(k, true); const L = LISTINGS.find((l) => l.id === id); if (L) openPanel(L); }
function schedule() { clearTimeout(pt.timer); if (pt.playing) pt.timer = setTimeout(() => photoGo(pt.i + 1), pt.DUR); }
function setPlaying(on) { pt.playing = on; $('pPlay').textContent = on ? '❚❚ Pause' : '▶ Play'; schedule(); }
$('pPrev').onclick = () => photoGo(pt.i - 1, true);
$('pNext').onclick = () => photoGo(pt.i + 1, true);
$('pPlay').onclick = () => setPlaying(!pt.playing);
addEventListener('keydown', (e) => { if (!(view === 'showcase' || (view === 'tour' && tour.mode === 'photos'))) return; if (e.key === 'ArrowRight') photoGo(pt.i + 1, true); if (e.key === 'ArrowLeft') photoGo(pt.i - 1, true); if (e.key === ' ') setPlaying(!pt.playing); });
(() => { let sx = null; const el = $('photoTour');
  el.addEventListener('touchstart', (e) => { sx = e.touches[0].clientX; }, { passive: true });
  el.addEventListener('touchend', (e) => { if (sx === null) return; const dx = e.changedTouches[0].clientX - sx; sx = null; if (Math.abs(dx) > 40) photoGo(pt.i + (dx < 0 ? 1 : -1), true); });
})();

// ============================================================================
// Walk mode (first person)
// ============================================================================
const EYE = 1.6, RADIUS = 0.28;
const walk = { on: false, yaw: 0, pitch: 0, keys: new Set(), joy: { x: 0, y: 0 }, target: null, fly: null, lookId: null, lx: 0, ly: 0 };
function setWalk(on) {
  walk.on = on; walk.target = null; walk.fly = null;
  $('joy').classList.toggle('show', on && isTouch);
  if (on) camera.rotation.order = 'YXZ';
}
function walkFly(pos, yaw) { walk.fly = { p0: camera.position.clone(), p1: pos, y0: walk.yaw, y1: yaw, start: performance.now(), dur: 900 }; }

addEventListener('keydown', (e) => { if (e.target.tagName === 'INPUT') return; walk.keys.add(e.key.toLowerCase()); if (e.key === 'Escape') { if (view === 'tour' && tour.mode === 'walk') setMode('dollhouse'); } });
addEventListener('keyup', (e) => walk.keys.delete(e.key.toLowerCase()));
addEventListener('blur', () => walk.keys.clear());

function collide(x, z) {
  for (const c of tour.colliders) {
    const nx = Math.max(c.minX, Math.min(x, c.maxX)), nz = Math.max(c.minZ, Math.min(z, c.maxZ));
    if ((x - nx) ** 2 + (z - nz) ** 2 < RADIUS * RADIUS) return true;
  }
  return false;
}
function tryMove(dx, dz) {
  const p = camera.position;
  if (!collide(p.x + dx, p.z)) p.x += dx;
  if (!collide(p.x, p.z + dz)) p.z += dz;
}
function updateWalk(dt) {
  if (walk.fly) {
    const f = walk.fly, k = Math.min(1, (performance.now() - f.start) / f.dur), e = ease(k);
    camera.position.lerpVectors(f.p0, f.p1, e);
    let dy = f.y1 - f.y0; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    walk.yaw = f.y0 + dy * e; walk.pitch *= 0.9;
    if (k >= 1) walk.fly = null;
  } else {
    const k = walk.keys;
    let f = (k.has('w') || k.has('arrowup') ? 1 : 0) - (k.has('s') || k.has('arrowdown') ? 1 : 0) - walk.joy.y;
    let r = (k.has('d') ? 1 : 0) - (k.has('a') ? 1 : 0) + walk.joy.x;
    if (k.has('arrowleft')) walk.yaw += 1.8 * dt;
    if (k.has('arrowright')) walk.yaw -= 1.8 * dt;
    const speed = (k.has('shift') ? 4.2 : 2.4) * dt;
    if (f || r) {
      walk.target = null;
      const sin = Math.sin(walk.yaw), cos = Math.cos(walk.yaw);
      const len = Math.min(1, Math.hypot(f, r));
      const a = Math.atan2(r, f);
      const mx = (-sin * f + cos * r), mz = (-cos * f - sin * r);
      const n = Math.hypot(mx, mz) || 1;
      tryMove((mx / n) * speed * len, (mz / n) * speed * len);
      void a;
    } else if (walk.target) {
      const d = walk.target.clone().sub(camera.position); d.y = 0;
      const dist = d.length();
      if (dist < 0.08) walk.target = null;
      else {
        const step = Math.min(dist, speed * 1.2);
        const before = camera.position.clone();
        tryMove((d.x / dist) * step, (d.z / dist) * step);
        if (camera.position.distanceTo(before) < step * 0.3) walk.target = null; // blocked
        const want = Math.atan2(-d.x, -d.z); let dy = want - walk.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
        walk.yaw += dy * Math.min(1, dt * 3);
      }
    }
  }
  camera.position.y = EYE;
  camera.rotation.set(walk.pitch, walk.yaw, 0, 'YXZ');
  // current room
  const p = camera.position;
  const room = [...tour.plan.rooms, tour.plan.hall].find((r) => p.x > r.x0 && p.x < r.x1 && p.z > r.z0 && p.z < r.z1);
  const name = room ? room.name : 'Outside';
  if ($('nowRoom').textContent !== name) { $('nowRoom').textContent = name; markChip(room && room.type !== 'hall' ? name : '-'); }
}

// joystick
(() => {
  const joy = $('joy'), knob = $('knob'); let id = null;
  const set = (e) => {
    const r = joy.getBoundingClientRect(); let x = (e.clientX - r.left - r.width / 2) / (r.width / 2), y = (e.clientY - r.top - r.height / 2) / (r.height / 2);
    const l = Math.hypot(x, y); if (l > 1) { x /= l; y /= l; }
    walk.joy.x = x; walk.joy.y = y; knob.style.transform = `translate(${x * 34}px, ${y * 34}px)`;
  };
  joy.addEventListener('pointerdown', (e) => { id = e.pointerId; joy.setPointerCapture(id); set(e); e.preventDefault(); });
  joy.addEventListener('pointermove', (e) => { if (e.pointerId === id) set(e); });
  const end = (e) => { if (e.pointerId !== id) return; id = null; walk.joy.x = walk.joy.y = 0; knob.style.transform = ''; };
  joy.addEventListener('pointerup', end); joy.addEventListener('pointercancel', end);
})();

// ============================================================================
// Pointer: picking (estate), look + tap-to-walk (tour)
// ============================================================================
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
let down = null;
canvas.addEventListener('pointerdown', (e) => {
  down = { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId };
  if (view === 'estate') controls.autoRotate = false;
  if (walk.on && walk.lookId === null) { walk.lookId = e.pointerId; walk.lx = e.clientX; walk.ly = e.clientY; canvas.setPointerCapture(e.pointerId); }
});
canvas.addEventListener('pointermove', (e) => {
  if (walk.on && e.pointerId === walk.lookId) {
    const s = isTouch ? 0.006 : 0.004;
    walk.yaw += (e.clientX - walk.lx) * s; walk.pitch += (e.clientY - walk.ly) * s;
    walk.pitch = Math.max(-1.2, Math.min(1.2, walk.pitch));
    walk.lx = e.clientX; walk.ly = e.clientY;
    if (walk.fly) walk.fly = null;
  } else if (view === 'estate' && !isTouch) {
    ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects([...estate.houses.values()].map((h) => h.group), true)[0];
    canvas.style.cursor = hit ? 'pointer' : 'grab';
  }
});
const pointerEnd = (e) => {
  if (walk.on && e.pointerId === walk.lookId) walk.lookId = null;
  if (!down || e.pointerId !== down.id) return;
  const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
  const quick = performance.now() - down.t < 450;
  down = null;
  if (moved > 8 || !quick) return;
  ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  if (view === 'estate') {
    const hit = ray.intersectObjects([...estate.houses.values()].map((h) => h.group), true)[0];
    if (hit) selectListing(hit.object.userData.listingId);
  } else if (tour.mode === 'walk') {
    const hit = ray.intersectObjects(tour.floors, false)[0];
    if (hit) { walk.target = hit.point.clone(); walk.fly = null; }
  } else {
    const hit = ray.intersectObjects(tour.floors, false)[0];
    if (hit && hit.object.userData.room.type !== 'hall') goToRoom(hit.object.userData.room);
  }
};
canvas.addEventListener('pointerup', pointerEnd);
canvas.addEventListener('pointercancel', (e) => { if (e.pointerId === walk.lookId) walk.lookId = null; down = null; });
// mouse wheel in walk mode = move forward/back
canvas.addEventListener('wheel', (e) => {
  if (!walk.on) return; e.preventDefault();
  const step = -Math.sign(e.deltaY) * 0.35;
  tryMove(-Math.sin(walk.yaw) * step, -Math.cos(walk.yaw) * step);
}, { passive: false });

// ============================================================================
// Labels projection
// ============================================================================
const v = new THREE.Vector3();
function placeLabels(list) {
  const w = innerWidth, h = innerHeight;
  for (const l of list) {
    if (l.el.style.display === 'none') continue;
    const far = l.maxDist && !l.el.classList.contains('sel') && camera.position.distanceTo(l.pos) > l.maxDist;
    v.copy(l.pos).project(camera);
    const vis = !far && v.z < 1 && v.x > -1.2 && v.x < 1.2 && v.y > -1.2 && v.y < 1.2;
    l.el.style.visibility = vis ? 'visible' : 'hidden';
    if (vis && !l.loaded) { l.loaded = true; const im = l.el.querySelector('img[data-src]'); if (im) im.src = im.dataset.src; }
    if (vis) l.el.style.transform = `translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px) translate(-50%, ${l.el.classList.contains('pin') ? '-100%' : '-50%'})`;
  }
}

// ============================================================================
// Loop
// ============================================================================
const clock = new THREE.Clock();
function loop(now) {
  const dt = Math.min(0.05, clock.getDelta());
  stepCamAnim(now);
  if (view === 'showcase') { /* full-screen photos; 3D paused */ }
  else if (view === 'estate') {
    if (estate.ring.visible) { const s = 1 + Math.sin(now / 350) * 0.025; estate.ring.scale.set(s, s, s); }
    controls.update();
    renderer.render(estate.scene, camera);
    placeLabels(estate.pins);
  } else if (tour.scene) {
    if (walk.on) updateWalk(dt); else controls.update();
    renderer.render(tour.scene, camera);
    placeLabels(tour.labels);
  }
  requestAnimationFrame(loop);
}
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ============================================================================
// Boot
// ============================================================================
buildEstateBase();
controls.autoRotateSpeed = 0.35;
camera.position.set(90, 120, 160); controls.target.set(0, 0, 0);
requestAnimationFrame(loop);
(async () => {
  try {
    LISTINGS = await loadListings();
  } catch (e) {
    $('loaderMsg').outerHTML = `<div class="err">Couldn't load MED Property's listings right now. Please check your connection and <a href="" style="color:#e3c25a">try again</a>.</div>`;
    return;
  }
  const hash = decodeURIComponent(location.hash.slice(1));
  const target = hash.startsWith('tour=') ? hash.slice(5) : hash;
  buildFilters();
  buildEstate(filtered()); buildStrip(filtered());
  $('loader').classList.add('done');
  if (hash.startsWith('tour=') && estate.houses.has(target)) { estate.selected = target; enterTour(target); }
  else if (estate.houses.has(target)) { showEstate(); selectListing(target); }
  else if (hash === 'map') showEstate();
  else showShowcase();
})();
// expose for debugging
window.__app = { showShowcase, showcaseTo, applyFilter, filter, get listings() { return LISTINGS; }, enterTour, showEstate, setMode, selectListing, goToRoom, tour, estate, camera };

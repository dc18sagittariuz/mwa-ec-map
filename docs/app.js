"use strict";
// ---------- ตัวช่วย ----------
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const LVC = ["--l0", "--l1", "--l2", "--l3", "--l4"];
let D, CUTS, NAMES, RATIO, DIST, BR;
const lvlOf = ec => { if (ec == null) return -1; let i = 0; while (i < CUTS.length && ec >= CUTS[i]) i++; return i; };
const colorOf = i => i < 0 ? css("--nodata") : css(LVC[i]);
const fmt = v => v == null ? "–" : Math.round(v).toLocaleString("th-TH");
const salt = v => (v * RATIO).toFixed(2);
const SRC = { CP: "เจ้าพระยา", MK: "แม่กลอง" };
const HOW = { measured: "ค่าวัดจริง", outlet: "คาดจากทางออกโรงผลิต", siphon: "คาดจากไซฟอนรังสิต", samlae: "คาดจากจุดสูบสำแล", persist: "คงค่าล่าสุด", suspect: "ค่าวัดล่าสุดกระโดดผิดปกติ (อาจเป็นเซนเซอร์) จึงใช้ค่ากลาง 24 ชม. แทน", unknown: "ยังคาดการณ์ไม่ได้" };
const PROV = { "10": "กรุงเทพมหานคร", "12": "นนทบุรี", "11": "สมุทรปราการ" };
const TZ = { timeZone: "Asia/Bangkok" };
const tTH = (d, o = {}) => d ? new Date(d).toLocaleString("th-TH", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", ...TZ, ...o }) + " น." : "–";
const tShort = d => new Date(d).toLocaleString("th-TH", { hour: "2-digit", minute: "2-digit", ...TZ });
const dName = p => (p.pro === "กรุงเทพมหานคร" ? "เขต" : "อ.") + p.th;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pinSVG = (c, w = 18) => `<svg class="pin" width="${w}" height="${w * 1.36}" viewBox="0 0 22 30"><path d="M11 29s9-8.4 9-16a9 9 0 1 0-18 0c0 7.6 9 16 9 16Z" fill="${c}" stroke="#fff" stroke-width="1.6"/><circle cx="11" cy="12.5" r="3.3" fill="#fff"/></svg>`;
const statusPill = li => li < 0 ? `<span class="status" style="background:var(--soft);color:var(--muted)">ไม่มีข้อมูล</span>`
  : `<span class="status" style="background:color-mix(in srgb,${css(LVC[li])} 18%,var(--surface));color:color-mix(in srgb,${css(LVC[li])} 70%,var(--ink))">${NAMES[li]}</span>`;

let hi = 0, selected = null, map, distLayer, brLayer, markers = {}, tiles, mode = "dist";
try { if (localStorage.getItem("ecw-mode") === "branch") mode = "branch"; } catch (e) {}
// พื้นที่ที่กำลังแสดง: เขต/อำเภอ หรือ สาขา กปน.
const AREA = () => mode === "dist" ? D.districts : (D.branches || {});
const curLayer = () => mode === "dist" ? distLayer : brLayer;
const curGeo = () => mode === "dist" ? DIST : BR;
const areaName = p => mode === "dist" ? dName(p) : "สาขา" + p.name;
const areaProps = code => curGeo().features.find(f => f.properties.code === code).properties;

// ---------- โหลด ----------
async function load() {
  const [d, g, b] = await Promise.all([
    fetch("data/latest.json", { cache: "no-store" }).then(x => x.json()),
    fetch("data/districts.json").then(x => x.json()),
    fetch("data/branches.json").then(x => x.json()),
  ]);
  D = d; DIST = g; BR = b; CUTS = d.levels; NAMES = d.level_names; RATIO = d.salt_per_ec;
  init();
}

const hTime = i => new Date(new Date(D.generated).getTime() + D.horizons[i] * 3600e3);
const hName = i => D.horizons[i] ? `คาดการณ์ +${D.horizons[i]} ชม.` : "แสดงค่าปัจจุบัน";

function setH(i) {
  hi = i;
  document.getElementById("hsel").value = i;
  document.querySelectorAll("#hseg button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.i === i));
  render();
}

function init() {
  // ช่วงเวลา
  const hsel = document.getElementById("hsel");
  hsel.innerHTML = D.horizons.map((h, i) => `<option value="${i}">${hName(i)}</option>`).join("");
  hsel.onchange = () => setH(+hsel.value);
  const quick = [0, 6, 24, 48].map(h => D.horizons.indexOf(h)).filter(i => i >= 0);
  document.getElementById("hseg").innerHTML = quick.map(i => `<button data-i="${i}" aria-pressed="${i === 0}">${D.horizons[i] ? D.horizons[i] + " ชม." : "ตอนนี้"}</button>`).join("");
  document.querySelectorAll("#hseg button").forEach(b => b.onclick = () => setH(+b.dataset.i));

  // แผนที่
  map = L.map("map", { zoomSnap: 0.25, minZoom: 9, maxZoom: 16 });
  const dark = () => false;   // โทนสว่างเสมอ
  const setTiles = () => {
    if (tiles) map.removeLayer(tiles);
    tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, className: dark() ? "tiles-dark" : "tiles-light",
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);
    tiles.bringToBack();
  };
  setTiles();
  distLayer = L.geoJSON(DIST, { style: () => ({ weight: 1, fillOpacity: .3 }) });
  brLayer = L.geoJSON(BR, { style: () => ({ weight: 1.5, fillOpacity: .3 }) });
  curLayer().addTo(map);
  map.fitBounds(distLayer.getBounds(), { padding: [10, 10] });
  [distLayer, brLayer].forEach(g => g.eachLayer(l => l.on("click", () => select(l.feature.properties.code))));
  [["นนทบุรี", 13.885, 100.43], ["กรุงเทพมหานคร", 13.76, 100.57], ["สมุทรปราการ", 13.585, 100.69]].forEach(([n, la, lo]) =>
    L.tooltip({ permanent: true, direction: "center", className: "plabel", interactive: false }).setLatLng([la, lo]).setContent(n).addTo(map));
  Object.entries(D.stations).forEach(([c, s]) => {
    markers[c] = L.marker([s.lat, s.lon], { icon: L.divIcon({ className: "mk", html: "", iconSize: [18, 24], iconAnchor: [9, 24], popupAnchor: [0, -22] }) }).addTo(map);
  });

  addLocateControl();

  // ค้นหาพื้นที่ + สลับชั้นเขต/สาขา
  const pick = document.getElementById("pick");
  pick.onchange = () => select(pick.value || null, true);
  fillPick();
  document.querySelectorAll("#layerSeg button").forEach(b => b.onclick = () => setMode(b.dataset.m));
  setModeButtons();

  // แท็บ
  const tabs = { tabOverview: "o", tabMap: "m", tabMethod: "x" };
  Object.keys(tabs).forEach(id => document.getElementById(id).onclick = () => {
    Object.keys(tabs).forEach(t => document.getElementById(t).setAttribute("aria-selected", t === id));
    document.getElementById("viewOverview").hidden = tabs[id] === "x";
    document.getElementById("viewMethod").hidden = tabs[id] !== "x";
    document.querySelector(".grid").classList.toggle("mapfull", tabs[id] === "m");
    document.body.classList.toggle("mapmode", tabs[id] === "m");
    window.scrollTo(0, 0);
    setTimeout(() => { map.invalidateSize(); if (!selected) map.fitBounds(curLayer().getBounds(), { padding: [10, 10] }); }, 60);
  });
  document.getElementById("mLevels").innerHTML = levelList();
  render();
}

// ---------- ปุ่มตำแหน่งปัจจุบัน ----------
// ตำแหน่งใช้ในเบราว์เซอร์เท่านั้น ไม่ได้ส่งไปที่ใด
let meLayer = null, meLatLng = null;
const ICON_LOC = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="currentColor"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>`;
function addLocateControl() {
  const Ctl = L.Control.extend({
    options: { position: "topleft" },
    onAdd() {
      const box = L.DomUtil.create("div", "leaflet-bar locate-ctl");
      const a = L.DomUtil.create("a", "", box);
      a.href = "#"; a.title = "ไปยังตำแหน่งปัจจุบัน"; a.setAttribute("role", "button"); a.setAttribute("aria-label", "ไปยังตำแหน่งปัจจุบัน");
      a.innerHTML = ICON_LOC;
      L.DomEvent.on(a, "click", e => { L.DomEvent.preventDefault(e); L.DomEvent.stopPropagation(e); locateMe(a); });
      return box;
    },
  });
  map.addControl(new Ctl());
}
function toast(msg) {
  let t = document.getElementById("maptoast");
  if (!t) { t = document.createElement("div"); t.id = "maptoast"; t.className = "maptoast"; t.setAttribute("role", "status"); document.querySelector(".mapwrap").appendChild(t); }
  t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, 5000);
}
function inRing(pt, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function inGeom(pt, g) {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
  return polys.some(p => inRing(pt, p[0]) && !p.slice(1).some(h => inRing(pt, h)));
}
function areaAt(lat, lon, geo) { const f = geo.features.find(f => inGeom([lon, lat], f.geometry)); return f ? f.properties.code : null; }
function placeMe() {
  if (!meLatLng) return;
  const code = areaAt(meLatLng.lat, meLatLng.lng, curGeo());
  if (code) { select(code); return true; }
  return false;
}
function locateMe(btn) {
  if (!navigator.geolocation) { toast("เบราว์เซอร์นี้ไม่รองรับการระบุตำแหน่ง"); return; }
  btn.classList.add("busy"); toast("กำลังหาตำแหน่ง…");
  navigator.geolocation.getCurrentPosition(pos => {
    btn.classList.remove("busy");
    const { latitude: la, longitude: lo, accuracy: acc } = pos.coords;
    meLatLng = L.latLng(la, lo);
    if (meLayer) map.removeLayer(meLayer);
    meLayer = L.layerGroup([
      L.circle(meLatLng, { radius: Math.min(acc, 2000), color: css("--accent"), weight: 1, fillOpacity: .08, interactive: false }),
      L.circleMarker(meLatLng, { radius: 7, color: "#fff", weight: 3, fillColor: css("--accent"), fillOpacity: 1 }).bindTooltip("ตำแหน่งของคุณ"),
    ]).addTo(map);
    const found = placeMe();
    map.setView(meLatLng, Math.max(map.getZoom(), 13));
    toast(found ? `คุณอยู่ใน${areaName(areaProps(selected))} · ดูรายละเอียดใต้แผนที่` : "ตำแหน่งของคุณอยู่นอกพื้นที่ที่ระบบครอบคลุม (กรุงเทพฯ นนทบุรี สมุทรปราการ)");
  }, err => {
    btn.classList.remove("busy");
    toast(err.code === 1 ? "ไม่ได้รับอนุญาตให้ใช้ตำแหน่ง · เปิดสิทธิ์ตำแหน่งให้เว็บนี้ในการตั้งค่าเบราว์เซอร์แล้วลองใหม่" : "หาตำแหน่งไม่สำเร็จ ลองใหม่อีกครั้ง");
  }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
}

function fillPick() {
  const pick = document.getElementById("pick");
  let html = `<option value="">${mode === "dist" ? "ค้นหาเขต/อำเภอ…" : "ค้นหาสาขา…"}</option>`;
  if (mode === "dist") {
    // จัดกลุ่มตามจังหวัด: หัวข้อจังหวัด แล้วตามด้วยรายชื่อเขต/อำเภอ
    ["กรุงเทพมหานคร", "นนทบุรี", "สมุทรปราการ"].forEach(pro => {
      const items = DIST.features.map(f => f.properties).filter(p => p.pro === pro).sort((a, b) => a.th.localeCompare(b.th, "th"));
      html += `<optgroup label="${pro}">` + items.map(p => `<option value="${p.code}">${esc(p.th)}</option>`).join("") + `</optgroup>`;
    });
  } else {
    html += `<optgroup label="สาขาการประปา">` + BR.features.map(f => f.properties).sort((a, b) => a.name.localeCompare(b.name, "th"))
      .map(p => `<option value="${p.code}">${esc(p.name)}</option>`).join("") + `</optgroup>`;
  }
  pick.innerHTML = html;
  pick.value = selected || "";
  pick.setAttribute("aria-label", mode === "dist" ? "ค้นหาเขต/อำเภอ" : "ค้นหาสาขา");
}
function setModeButtons() { document.querySelectorAll("#layerSeg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.m === mode)); }
function setMode(m) {
  if (m === mode) return;
  map.removeLayer(curLayer()); mode = m; curLayer().addTo(map);
  try { localStorage.setItem("ecw-mode", m); } catch (e) {}
  selected = null; fillPick(); setModeButtons(); if (!placeMe()) render();
}

function levelList() {
  let lo = 0;
  return NAMES.map((n, i) => { const h = CUTS[i]; const s = `<div class="legend-row" style="display:flex;gap:8px;align-items:center;margin:4px 0">${pinSVG(css(LVC[i]), 14)} <b>${n}</b> <span class="small">${h == null ? "≥ " + lo.toLocaleString() : lo.toLocaleString() + "–" + h.toLocaleString()} µS/cm (~${salt(lo)}${h == null ? "+" : "–" + salt(h)} g/L)</span></div>`; lo = h; return s; }).join("");
}

// ---------- วาด ----------
function render() {
  const surf = css("--surface"), ink = css("--ink");
  const A = AREA(), br = mode === "branch";
  curLayer().eachLayer(l => {
    const p = l.feature.properties, v = A[p.code]?.f[hi] ?? null, li = lvlOf(v), sel = selected === p.code;
    l.setStyle({ fillColor: colorOf(li), color: sel ? ink : (br ? css("--accent") : surf), weight: sel ? 3 : (br ? 1.5 : 1), fillOpacity: v == null ? .12 : .34, dashArray: v == null ? "3 3" : null });
    const parts = (A[p.code]?.parts || []).slice(0, 3).map(x => `สถานีสูบจ่าย${x[0]} ${Math.round(x[1] * 100)}%`).join(", ");
    l.bindTooltip(`<b>${areaName(p)}</b><br>EC ${fmt(v)} µS/cm · ${v == null ? (hi ? "ยังคาดการณ์ไม่ได้" : "ไม่มีข้อมูล") : NAMES[li]}<br><span style="opacity:.75">${parts}</span>`, { sticky: true });
  });
  Object.entries(D.stations).forEach(([c, s]) => {
    const v = s.f[hi], li = lvlOf(v);
    markers[c].setIcon(L.divIcon({ className: "mk", html: pinSVG(colorOf(li)), iconSize: [18, 24], iconAnchor: [9, 24], popupAnchor: [0, -22] }));
    markers[c].bindPopup(`<b>${esc(s.name)}</b> <span class="small">${c}</span><br>EC <b>${fmt(v)}</b> µS/cm${v != null ? ` (~${salt(v)} g/L)` : ""}<br><span class="small">${HOW[s.how[hi]]}</span><br>`
      + `รับน้ำจากโรงผลิต${s.plant} (${SRC[s.src]})${s.src === "MK" && s.gain > 0 ? ` · ผสมน้ำจากบางเขน ~${Math.round(s.gain * 100)}%` : ""}${s.lag_samlae_h != null ? `<br>น้ำเดินทางจากสำแล ~${Math.round(s.lag_samlae_h)} ชม.` : ""}<br>`
      + `<span class="small">ค่าวัดล่าสุด ${fmt(s.ec)} เมื่อ ${tTH(s.t, { year: undefined })}${s.stale ? " (ข้อมูลค้าง)" : ""}</span>`);
  });
  const t = hTime(hi);
  document.querySelector("#whenPill span").textContent = tTH(t);
  document.querySelector("#updated span").innerHTML = `<span class="ulong">อัปเดตล่าสุด ${tTH(D.generated)}</span><span class="ushort">${tShort(D.generated)} น.</span>`;
  renderKPI(); renderLegend(); renderDetail(); renderProv(); renderSrc(); renderTrend(); renderOutlook();
}

function stVals() { return Object.entries(D.stations).map(([c, s]) => ({ c, s, v: s.f[hi] })).filter(x => x.v != null); }

function renderKPI() {
  const vs = stVals();
  const avg = vs.length ? vs.reduce((a, b) => a + b.v, 0) / vs.length : null;
  const mx = vs.reduce((a, b) => (!a || b.v > a.v ? b : a), null);
  document.getElementById("kN").textContent = vs.length;
  document.getElementById("kAvg").textContent = fmt(avg);
  document.getElementById("kMax").textContent = fmt(mx?.v);
  document.getElementById("kMax").style.color = mx ? colorOf(lvlOf(mx.v)) : "";
  document.getElementById("kMaxAt").textContent = mx ? mx.s.name : "";
}

function renderLegend() {
  let lo = 0;
  document.getElementById("legend").innerHTML = NAMES.map((n, i) => { const h = CUTS[i];
    const s = `<div class="it">${pinSVG(css(LVC[i]), 13)}<span>${n}<small>${h == null ? "≥ " + lo.toLocaleString() : lo + "–" + h.toLocaleString()}</small></span></div>`; lo = h; return s; }).join("")
    + `<div class="it"><span class="sw-unk"></span><span>${hi ? "ยังคาดการณ์ไม่ได้" : "ไม่มีข้อมูล"}<small>µS/cm</small></span></div>`;
}

function renderDetail() {
  const el = document.getElementById("detail");
  if (!selected) {
    el.innerHTML = `<p class="small" style="margin:0">${mode === "dist" ? "แตะเขตหรือหมุดบนแผนที่" : "แตะพื้นที่สาขาหรือหมุดบนแผนที่"} หรือเลือกจากช่องค้นหา เพื่อดูว่าพื้นที่นั้นรับน้ำจากที่ไหน และค่าที่คาดการณ์ 48 ชั่วโมง · หมุด = สถานีตรวจวัด สีพื้น = ค่าสูงสุดของพื้นที่จ่ายน้ำที่ครอบคลุมพื้นที่นั้นตั้งแต่ 10%</p>`;
    return;
  }
  const p = areaProps(selected), d = AREA()[selected], v = d.f[hi], li = lvlOf(v);
  const parts = d.parts.map(x => { const z = D.zones[x[0]]; return `${Math.round(x[1] * 100)}% สถานีสูบจ่าย${x[0]} <span class="small">(โรงผลิต${z.plant} · น้ำดิบ${SRC[z.src]})</span>`; }).join("<br>");
  el.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:8px 18px;align-items:baseline;justify-content:space-between">
      <div><div class="small">${mode === "dist" ? p.pro : "สาขาการประปา (ขอบเขตตามไฟล์ KMZ)"}</div><h2 style="font-family:var(--f-display);font-size:20px;margin:0">${mode === "dist" ? (p.pro === "กรุงเทพมหานคร" ? "เขต" : "อำเภอ") + p.th : "สาขา" + p.name}</h2></div>
      <div style="display:flex;gap:10px;align-items:baseline"><span class="big" style="color:${colorOf(li)}">${fmt(v)}</span><span class="small">µS/cm</span>${statusPill(li)}</div></div>
    <dl class="kv"><dt>ความเค็มโดยประมาณ</dt><dd>${v == null ? "–" : "~" + salt(v) + " g/L"}</dd><dt>รับน้ำจาก</dt><dd>${parts}</dd></dl>
    <div class="small" style="margin-top:10px">คาดการณ์ (µS/cm)</div>
    <div class="fcrow">${D.horizons.map((h, i) => `<span>${h ? "+" + h : "ตอนนี้"} ${statusLike(d.f[i])}</span>`).join("")}</div>
    <p style="margin:10px 0 0"><button class="link" id="clr">กลับไปภาพรวม</button></p>`;
  document.getElementById("clr").onclick = () => select(null);
}
const statusLike = v => { const li = lvlOf(v); return `<span class="status" style="background:${li < 0 ? "var(--soft)" : `color-mix(in srgb,${css(LVC[li])} 22%,var(--surface))`};color:var(--ink)">${fmt(v)}</span>`; };

function renderProv() {
  const by = {};
  stVals().forEach(x => { const p = PROV[x.s.district.slice(0, 2)]; (by[p] ??= []).push(x.v); });
  document.getElementById("prov").innerHTML = ["กรุงเทพมหานคร", "นนทบุรี", "สมุทรปราการ"].map(p => {
    const v = by[p] || [], avg = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    const w = avg == null ? 0 : Math.min(100, avg / (CUTS[1] || 600) * 100);
    return `<div class="prov"><span class="pn">${p}</span><div><div class="meta"><span>ค่าเฉลี่ย<b style="color:${colorOf(lvlOf(avg))}">${fmt(avg)}</b>µS/cm</span><span>ช่วง ${v.length ? fmt(Math.min(...v)) + " – " + fmt(Math.max(...v)) : "–"} · ${v.length} จุด</span></div>
      <div class="track"><span style="width:${w}%;${avg != null && lvlOf(avg) >= 2 ? `background:${colorOf(lvlOf(avg))}` : ""}"></span></div></div></div>`;
  }).join("") + `<p class="small" style="margin:8px 0 0">แถบเต็ม = ${CUTS[1]} µS/cm (ระดับเฝ้าระวัง)</p>`;
}

// ช่วงคาดการณ์ไกลสุดที่ทราบ (น้ำที่จะถึงต้องผ่านจุดวัดต้นทางแล้ว เช่น บางเขนรู้ล่วงหน้าได้ ~17 ชม. จากสำแล)
function farCell(f) {
  let i = f.length - 1;
  while (i > 0 && f[i] == null) i--;
  if (i === 0) return `<div class="val">คาดการณ์<b>ยังไม่ทราบ</b></div>`;
  return `<div class="val">คาดการณ์ (+${D.horizons[i]} ชม.)<b>${fmt(f[i])} µS/cm</b></div>`;
}
const ICON_RAW = `<svg class="ic" viewBox="0 0 24 32"><path d="M12 1C9 7 3 13.5 3 20a9 9 0 0 0 18 0C21 13.5 15 7 12 1Z"/></svg>`;
const ICON_PLANT = `<svg class="ic" viewBox="0 0 24 24"><path d="M3 21V9l5 3V9l5 3V5h4l1 16H3Z"/></svg>`;
function renderSrc() {
  const r = D.raw || {}, last = D.horizons.length - 1, rows = [];
  const raw = (n, sub, x) => {
    const li = lvlOf(x?.cond), d = x && x.cond_24h_ago != null && x.cond != null ? x.cond - x.cond_24h_ago : null;
    return `<div class="srcrow">${ICON_RAW}<div class="nm">${n}<small>${sub}</small></div>${statusPill(li)}
      <div class="val">ค่า EC ปัจจุบัน<b>${fmt(x?.cond)} µS/cm</b></div><div class="val">เทียบ 24 ชม. ก่อน<b>${d == null ? "–" : (d >= 0 ? "+" : "") + fmt(d)}</b></div></div>`; };
  rows.push(raw("น้ำดิบ จุดสูบสำแล", "แม่น้ำเจ้าพระยา จ.ปทุมธานี", r.samlae), raw("ไซฟอนรังสิต", "คลองประปา ~7 ชม. หลังสำแล", r.siphon));
  Object.entries(D.plants).forEach(([n, p]) => {
    rows.push(`<div class="srcrow">${ICON_PLANT}<div class="nm">โรงผลิตน้ำ${n}<small>น้ำดิบ${SRC[p.src]}</small></div>${statusPill(lvlOf(p.f[0]))}
      <div class="val">ค่า EC ปัจจุบัน<b>${fmt(p.f[0])} µS/cm</b></div>${farCell(p.f)}</div>`);
  });
  document.getElementById("srcBox").innerHTML = rows.join("");
}

function renderTrend() {
  const W = 560, H = 220, L0 = 44, R0 = 26, T0 = 12, B0 = 34;
  const now = new Date(D.generated).getTime(), t0 = now - 48 * 3600e3, t1 = now + 48 * 3600e3;
  const S = D.series || {};
  const ts = p => (p || []).map(q => [new Date(q[0]).getTime(), q[1]]).filter(q => q[0] >= t0);
  const fc = f => D.horizons.map((h, i) => f && f[i] != null ? [now + h * 3600e3, f[i]] : null).filter(Boolean);
  // โรงผลิตฝั่งเจ้าพระยา: เส้นทึบ = ค่าวัดย้อนหลัง, เส้นประ = คาดการณ์
  const PL = [
    { n: "บางเขน", c: css("--accent"), h: ts(S.bangkhen_out), f: fc(D.plants["บางเขน"]?.f) },
    { n: "สามเสน", c: css("--c-ss"), h: ts(S.samsen_out), f: fc(D.plants["สามเสน"]?.f) },
    { n: "ธนบุรี", c: css("--c-tb"), h: ts(S.thonburi_out), f: fc(D.plants["ธนบุรี"]?.f) },
  ];
  const raw = ts(S.samlae);
  const SA = selected ? AREA()[selected] : null;
  const selF = SA ? fc(SA.f) : [];
  const pts = [...raw, ...selF, ...PL.flatMap(p => [...p.h, ...p.f])];
  const vals = pts.map(p => p[1]);
  const vmax = Math.max(300, ...vals), vmin = Math.min(...vals, vmax);
  const step = [25, 50, 100, 200, 250, 500, 1000].find(st => (vmax - vmin + 40) / st <= 5) || 1000;
  let hiV = Math.ceil((vmax + 10) / step) * step, lo = Math.max(0, Math.floor((vmin - 20) / step) * step);
  if (hiV - lo < 3 * step) lo = Math.max(0, hiV - 3 * step);
  const nT = Math.round((hiV - lo) / step);
  const x = t => L0 + (t - t0) / (t1 - t0) * (W - L0 - R0), y = v => T0 + (1 - (v - lo) / (hiV - lo)) * (H - T0 - B0);
  const line = (p, col, dash, wd = 2) => p.length > 1 ? `<path d="${p.map((q, i) => (i ? "L" : "M") + x(q[0]).toFixed(1) + " " + y(q[1]).toFixed(1)).join(" ")}" fill="none" stroke="${col}" stroke-width="${wd}" ${dash ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round"/>` : "";
  const dots = (p, col) => p.map(q => `<circle cx="${x(q[0]).toFixed(1)}" cy="${y(q[1]).toFixed(1)}" r="3" fill="${css("--surface")}" stroke="${col}" stroke-width="2"/>`).join("");
  const mut = css("--muted"), grid = css("--line"), acc2 = css("--accent-2"), warn = css("--l2");
  let g = "";
  for (let k = 0; k <= nT; k++) { const v = lo + step * k, yy = y(v); g += `<line x1="${L0}" x2="${W - R0}" y1="${yy}" y2="${yy}" stroke="${grid}"/><text x="${L0 - 6}" y="${yy + 4}" font-size="11" text-anchor="end" fill="${mut}">${fmt(v)}</text>`; }
  for (let h = -48; h <= 48; h += 12) { const t = now + h * 3600e3, xx = x(t); g += `<text x="${xx}" y="${H - 18}" font-size="11" text-anchor="middle" fill="${mut}">${h ? tShort(t) : "ตอนนี้"}</text><text x="${xx}" y="${H - 5}" font-size="10" text-anchor="middle" fill="${mut}">${h ? (h > 0 ? "+" : "") + h + " ชม." : ""}</text>`; }
  const wy = CUTS[2] != null && CUTS[2] < hiV && CUTS[2] > lo ? `<line x1="${L0}" x2="${W - R0}" y1="${y(CUTS[2])}" y2="${y(CUTS[2])}" stroke="${warn}" stroke-dasharray="3 3"/>` : "";
  const nowX = x(now), hx = x(hTime(hi).getTime());
  const svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="กราฟ EC ย้อนหลังและคาดการณ์ของโรงผลิตน้ำ">
    <rect x="${nowX}" y="${T0}" width="${W - R0 - nowX}" height="${H - T0 - B0}" fill="${css("--soft")}"/>${g}${wy}
    <line x1="${nowX}" x2="${nowX}" y1="${T0}" y2="${H - B0}" stroke="${mut}" stroke-width="1"/>
    ${line(raw, acc2, false, 1.5)}
    ${PL.map(p => line(p.h, p.c, false) + line(p.f, p.c, true) + dots(p.f, p.c)).join("")}
    ${selF.length ? line(selF, css("--l3"), false, 2.5) + dots(selF, css("--l3")) : ""}
    <line x1="${hx}" x2="${hx}" y1="${T0}" y2="${H - B0}" stroke="${css("--ink")}" stroke-width="1.5" opacity=".6"/>
  </svg>`;
  const enough = raw.length + PL[0].h.length > 4;
  document.getElementById("trend").innerHTML = svg + `<div class="chart-legend">
    <span><i style="background:${acc2}"></i>น้ำดิบสำแล</span>
    ${PL.map(p => `<span><i style="background:${p.c}"></i>โรงผลิต${p.n}</span>`).join("")}
    ${selected ? `<span><i style="background:${css("--l3")}"></i>${areaName(areaProps(selected))}</span>` : ""}
    ${wy ? `<span><i style="background:${warn}"></i>ระดับเฝ้าระวัง</span>` : ""}</div>
    <p class="small" style="margin:4px 0 0">เส้นทึบ = ค่าวัดย้อนหลัง · เส้นประและจุด = คาดการณ์ · บางเขนคาดได้ไกลสุด ~17 ชม. ส่วนสามเสนและธนบุรีได้ถึง 48 ชม. เพราะน้ำเดินทางจากสำแลนานกว่า</p>
    ${enough ? "" : `<p class="small" style="margin:6px 0 0">ระบบเริ่มเก็บข้อมูลเมื่อ 17 ต.ค. 2569 เส้นย้อนหลังจะครบเมื่อสะสมข้อมูลได้ 2 วัน</p>`}`;
}

function renderOutlook() {
  const o = D.outlook || {}, lv = o.level, names = ["ความเสี่ยงต่ำ", "เฝ้าระวัง", "ความเสี่ยงสูง"], li = lv == null ? -1 : [0, 2, 4][lv];
  const c13 = D.flow?.["C.13"];
  document.getElementById("outlook").innerHTML = `<div class="card-h"><h2><svg class="h-ic" viewBox="0 0 24 24"><path d="M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 20c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M12 3v6M9 6l3 3 3-3" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>แนวโน้มน้ำเค็ม 2–3 วัน</h2>
    ${li < 0 ? statusPill(-1) : `<span class="status" style="background:color-mix(in srgb,${css(LVC[li])} 20%,var(--surface));color:color-mix(in srgb,${css(LVC[li])} 70%,var(--ink))">${names[lv]}</span>`}</div>
    <dl class="kv"><dt>น้ำจากเขื่อนเจ้าพระยา (C.13)</dt><dd>${c13 && c13.q != null ? fmt(c13.q) + " ลบ.ม./วินาที" + (c13.dq ? ` (${c13.dq > 0 ? "+" : ""}${fmt(c13.dq)} จากเมื่อวาน)` : "") + `<br><span class="small">ข้อมูล ${tTH(c13.q_t || c13.t, { year: undefined })}</span>` : "ยังไม่มีข้อมูล"}</dd>
    <dt>น้ำขึ้นสูงสุดครั้งถัดไป</dt><dd>${o.next_high ? tTH(o.next_high.t, { year: undefined }) + " · " + o.next_high.m.toFixed(2) + " ม." + (o.spring_tide ? " · ช่วงน้ำเกิด" : "") : "–"}</dd>
    <dt>แนวน้ำเค็ม 0.25 g/L</dt><dd>${o.front ? `${esc(o.front.name)} กม. ${o.front.km} · ห่างสำแล ${o.front.dist_km} กม.` : (o.front_level === 0 ? "ยังไม่เข้าใกล้จุดสูบ" : "–")}</dd></dl>
    <p class="small" style="margin:10px 0 0">ใช้ดูความเสี่ยงที่ไกลกว่าเวลาเดินทางของน้ำ ประเมินจากน้ำจืดที่ปล่อยจากเขื่อน ช่วงน้ำเกิด และแนวลิ่มน้ำเค็มในแม่น้ำ</p>`;
}

function select(code, zoom) {
  selected = code; document.getElementById("pick").value = code || "";
  if (code && zoom) curLayer().eachLayer(l => { if (l.feature.properties.code === code) map.fitBounds(l.getBounds(), { maxZoom: 13, padding: [40, 40] }); });
  render();
}

load().catch(e => { document.querySelector("#updated span").textContent = "โหลดข้อมูลไม่สำเร็จ"; console.error(e); });
setInterval(() => fetch("data/latest.json", { cache: "no-store" }).then(x => x.json()).then(d => { if (d.generated !== D.generated) { D = d; render(); } }).catch(() => {}), 5 * 60e3);

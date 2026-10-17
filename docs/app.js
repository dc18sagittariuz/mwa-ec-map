"use strict";
// ---------- ตัวช่วย ----------
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const LVC = ["--l0", "--l1", "--l2", "--l3", "--l4"];
let D, CUTS, NAMES, RATIO;
const lvlOf = ec => { if (ec == null) return -1; let i = 0; while (i < CUTS.length && ec >= CUTS[i]) i++; return i; };
const colorOf = i => i < 0 ? css("--nodata") : css(LVC[i]);
const fmt = v => v == null ? "–" : Math.round(v).toLocaleString("th-TH");
const salt = v => (v * RATIO).toFixed(2);
const SRC = { CP: "เจ้าพระยา", MK: "แม่กลอง" };
const HOW = { measured: "ค่าวัดจริง", outlet: "จากค่าทางออกโรงผลิต", siphon: "จากค่าที่ไซฟอนรังสิต", samlae: "จากค่าที่สำแล", persist: "คงค่าล่าสุด", unknown: "ยังคาดการณ์ไม่ได้" };
const tTH = iso => { if (!iso) return "–"; const d = new Date(iso); return d.toLocaleString("th-TH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" }); };
const dName = p => (p.pro === "กรุงเทพมหานคร" ? "เขต" : "อ.") + p.th;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let hi = 0, selected = null, map, distLayer, river, stLayer, markers = {}, DIST, tiles;

async function load() {
  const [d, g, r] = await Promise.all([
    fetch("data/latest.json", { cache: "no-store" }).then(x => x.json()),
    fetch("data/districts.json").then(x => x.json()),
    fetch("data/river.json").then(x => x.json()),
  ]);
  D = d; DIST = g; CUTS = d.levels; NAMES = d.level_names; RATIO = d.salt_per_ec;
  init(r);
}

function hlabel(i) { const h = D.horizons[i]; return h ? `+${h} ชม. (${tTH(new Date(new Date(D.generated).getTime() + h * 3600e3).toISOString())})` : "ตอนนี้"; }

function init(riverGeo) {
  const hr = document.getElementById("hr");
  hr.max = D.horizons.length - 1;
  hr.oninput = () => { hi = +hr.value; document.getElementById("tlabel").textContent = hlabel(hi); render(); };
  document.getElementById("tlabel").textContent = hlabel(0);

  map = L.map("map", { zoomSnap: 0.25, minZoom: 9, maxZoom: 15 });
  const dark = () => document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const setTiles = () => {
    if (tiles) map.removeLayer(tiles);
    tiles = L.tileLayer(`https://{s}.basemaps.cartocdn.com/${dark() ? "dark_all" : "light_all"}/{z}/{x}/{y}{r}.png`, {
      subdomains: "abcd", maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>' }).addTo(map);
  };
  setTiles();
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { setTiles(); render(); });

  distLayer = L.geoJSON(DIST, { style: () => ({ weight: 1, fillOpacity: .62 }) }).addTo(map);
  river = L.geoJSON(riverGeo, { interactive: false, style: () => ({ color: css("--river"), weight: 3, opacity: .0 }) }).addTo(map); // พื้นหลังมีแม่น้ำจริงแล้ว
  map.fitBounds(distLayer.getBounds(), { padding: [10, 10] });
  stLayer = L.layerGroup().addTo(map);
  Object.entries(D.stations).forEach(([c, s]) => { markers[c] = L.circleMarker([s.lat, s.lon], { radius: c.startsWith("SP") ? 6 : 4.5, weight: 1.5, fillOpacity: 1 }).addTo(stLayer); });
  distLayer.eachLayer(l => l.on("click", () => select(l.feature.properties.code)));

  const pick = document.getElementById("pick");
  DIST.features.map(f => f.properties).sort((a, b) => a.pro.localeCompare(b.pro, "th") || a.th.localeCompare(b.th, "th"))
    .forEach(p => { const o = document.createElement("option"); o.value = p.code; o.textContent = `${p.th} (${p.pro === "กรุงเทพมหานคร" ? "กทม." : p.pro})`; pick.appendChild(o); });
  pick.onchange = () => select(pick.value || null, true);
  renderStatus(); render();
}

function renderStatus() {
  const s = D.status, names = { twqms: "น้ำประปา", rwc: "น้ำดิบ", rid: "น้ำจากเขื่อน", tide: "น้ำขึ้นน้ำลง" };
  const chips = Object.entries(names).map(([k, n]) => {
    const ok = s[k] && s[k].ok;
    return `<span class="chip" title="${esc(ok ? (s[k].newest ? "ข้อมูลล่าสุด " + tTH(s[k].newest) : "ดึงสำเร็จ") : (s[k]?.error || "ไม่มีข้อมูล"))}"><i style="background:${ok ? css("--l0") : css("--l3")}"></i>${n}</span>`;
  }).join("");
  document.getElementById("status").innerHTML = `<span>อัปเดต ${tTH(D.generated)} น. · ทุก 30 นาที</span>${chips}`;
}

function distVal(code) { const d = D.districts[code]; return d ? d.f[hi] : null; }

function render() {
  const surf = css("--surface"), ink = css("--ink"), byProv = {}, ranks = [];
  distLayer.eachLayer(l => {
    const p = l.feature.properties, v = distVal(p.code), li = lvlOf(v), sel = selected === p.code;
    const unk = v == null;
    l.setStyle({ fillColor: colorOf(li), color: sel ? ink : surf, weight: sel ? 3 : 1, fillOpacity: unk ? .25 : .62, dashArray: unk ? "3 3" : null });
    const parts = (D.districts[p.code]?.parts || []).slice(0, 3).map(x => `สถานีสูบจ่าย${x[0]} ${Math.round(x[1] * 100)}%`).join(", ");
    l.bindTooltip(`<b>${dName(p)}</b><br>EC ${fmt(v)} µS/cm · ${unk ? (hi ? "ยังคาดการณ์ไม่ได้" : "ไม่มีข้อมูล") : NAMES[li]}<br><span style="opacity:.75">${parts}</span>`, { sticky: true });
    (byProv[p.pro] ??= [0, 0, 0, 0, 0, 0])[li < 0 ? 5 : li]++;
    ranks.push({ id: p.code, label: dName(p), sub: p.pro === "กรุงเทพมหานคร" ? "" : p.pro, v, li });
  });
  Object.entries(D.stations).forEach(([c, s]) => {
    const v = s.f[hi], li = lvlOf(v);
    markers[c].setStyle({ fillColor: colorOf(li), color: ink });
    markers[c].bindPopup(`<b>${esc(s.name)}</b> <span class="num">${c}</span><br>EC <b class="num">${fmt(v)}</b> µS/cm${v != null ? ` (~${salt(v)} g/L)` : ""} · ${HOW[s.how[hi]]}<br>`
      + `รับน้ำจากโรงผลิต${s.plant} (${SRC[s.src]})${s.lag_samlae_h != null ? ` · จากสำแล ~${Math.round(s.lag_samlae_h)} ชม.` : ""}<br>`
      + `ค่าวัดล่าสุด ${fmt(s.ec)} เมื่อ ${tTH(s.t)}${s.stale ? " (ค้าง)" : ""}`);
  });
  renderLegend(); renderProv(byProv); renderRank(ranks); renderSrc(); renderOutlook(); renderDetail();
}

function renderLegend() {
  let h = `<div class="hd">EC น้ำประปา (µS/cm) · เกณฑ์ชั่วคราว</div>`, lo = 0;
  NAMES.forEach((n, i) => { const hiV = CUTS[i]; h += `<div class="row"><span class="sw" style="background:${css(LVC[i])}"></span>${n}<span class="num">${hiV == null ? "≥ " + lo.toLocaleString() : lo.toLocaleString() + "–" + hiV.toLocaleString()}</span></div>`; lo = hiV; });
  h += `<div class="row"><span class="sw unknown-sw"></span>${hi ? "ยังคาดการณ์ไม่ได้ (น้ำยังไม่ผ่านจุดวัด)" : "ไม่มีข้อมูล"}</div>`;
  document.getElementById("legend").innerHTML = h;
}

function renderProv(by) {
  document.getElementById("prov").innerHTML = ["กรุงเทพมหานคร", "นนทบุรี", "สมุทรปราการ"].map(p => {
    const c = by[p] || [0, 0, 0, 0, 0, 0], tot = c.reduce((a, b) => a + b, 0), bad = c[2] + c[3] + c[4];
    const segs = c.map((n, i) => n ? `<span style="width:${n / tot * 100}%;background:${i === 5 ? css("--nodata") : css(LVC[i])}" title="${i === 5 ? "ไม่ทราบ" : NAMES[i]}: ${n}"></span>` : "").join("");
    return `<div class="provrow"><span>${p === "กรุงเทพมหานคร" ? "กรุงเทพฯ" : p}</span><div class="bar">${segs}</div><span class="num">${bad}/${tot}</span></div>`;
  }).join("") + `<p class="small" style="margin:8px 0 0">จำนวนเขต/อำเภอ · ตัวเลขขวา = ระดับเฝ้าระวังขึ้นไป / ทั้งหมด</p>`;
}

function renderRank(r) {
  r = r.filter(x => x.v != null).sort((a, b) => b.v - a.v).slice(0, 6);
  document.getElementById("rank").innerHTML = r.length ? r.map(x => `<li data-id="${x.id}"><span>${x.label} <span class="small">${x.sub}</span></span><span class="pill num" style="background:${colorOf(x.li)}">${fmt(x.v)}</span></li>`).join("")
    : `<li class="small">ยังไม่มีค่าในช่วงเวลานี้</li>`;
  document.querySelectorAll("#rank li[data-id]").forEach(li => li.onclick = () => select(li.dataset.id, true));
}

function spark(series) {
  const all = Object.values(series).flat();
  if (all.length < 2) return `<p class="small" style="margin:10px 0 0">กราฟย้อนหลังจะแสดงเมื่อเก็บข้อมูลได้มากพอ</p>`;
  const W = 300, H = 90, t0 = Date.now() - 72 * 3600e3, t1 = Date.now();
  let lo = Math.min(...all.map(p => p[1])), hiV = Math.max(...all.map(p => p[1]));
  if (hiV - lo < 50) { lo -= 25; hiV += 25; }
  const x = t => 8 + (new Date(t).getTime() - t0) / (t1 - t0) * (W - 16), y = v => H - 16 - (v - lo) / (hiV - lo) * (H - 26);
  const cols = { samlae: css("--l3"), siphon: css("--l2"), bangkhen_out: css("--accent") };
  const lbl = { samlae: "สำแล", siphon: "ไซฟอนรังสิต", bangkhen_out: "ทางออกโรงผลิตบางเขน" };
  const paths = Object.entries(series).filter(([, p]) => p.length > 1).map(([k, p]) => `<path d="${p.map((q, i) => (i ? "L" : "M") + x(q[0]).toFixed(1) + " " + y(q[1]).toFixed(1)).join(" ")}" fill="none" stroke="${cols[k]}" stroke-width="2"/>`).join("");
  return `<p class="small" style="margin:12px 0 2px">ย้อนหลัง 72 ชม. (µS/cm) · ${Object.keys(series).filter(k => series[k].length > 1).map(k => `<span style="color:${cols[k]}">━ ${lbl[k]}</span>`).join(" · ")}</p>
  <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="กราฟ EC ย้อนหลัง">${paths}
    <text x="8" y="${H - 3}" font-size="10" fill="${css("--muted")}">−72 ชม.</text><text x="${W - 8}" y="${H - 3}" font-size="10" text-anchor="end" fill="${css("--muted")}">ตอนนี้</text>
    <text x="${W - 8}" y="10" font-size="10" text-anchor="end" fill="${css("--muted")}">${fmt(hiV)}</text><text x="${W - 8}" y="${H - 18}" font-size="10" text-anchor="end" fill="${css("--muted")}">${fmt(lo)}</text></svg>`;
}

function renderSrc() {
  const r = D.raw || {}, rows = [];
  const rawRow = (n, x) => { if (!x) return `<span>${n}</span><span class="small">ไม่มีข้อมูล</span><span></span>`;
    const d = x.cond_24h_ago != null && x.cond != null ? x.cond - x.cond_24h_ago : null;
    return `<span><span class="dot" style="background:${colorOf(lvlOf(x.cond))}"></span>${n}</span><span class="small">${d == null ? "" : (d >= 0 ? "+" : "") + fmt(d) + " / 24 ชม."}</span><span class="num">${fmt(x.cond)}</span>`; };
  rows.push(rawRow("น้ำดิบ สำแล", r.samlae), rawRow("ไซฟอนรังสิต", r.siphon));
  Object.entries(D.plants).forEach(([n, p]) => { const v = p.f[0]; rows.push(`<span><span class="dot" style="background:${colorOf(lvlOf(v))}"></span>โรงผลิต${n}</span><span class="small">${SRC[p.src]}</span><span class="num">${fmt(v)}</span>`); });
  document.getElementById("srcBox").innerHTML = `<div class="src">${rows.join("")}</div>${spark(D.series || {})}`;
}

function renderOutlook() {
  const o = D.outlook || {}, lv = o.level, names = ["ความเสี่ยงต่ำ", "เฝ้าระวัง", "ความเสี่ยงสูง"], cols = ["--l0", "--l2", "--l4"];
  const c13 = D.flow?.["C.13"];
  document.getElementById("outlook").innerHTML = `<h2>แนวโน้มน้ำเค็ม 2–3 วัน</h2>
    <span class="pill" style="background:${lv == null ? css("--nodata") : css(cols[lv])}">${lv == null ? "ไม่มีข้อมูล" : names[lv]}</span>
    <ul>${(o.why || []).map(w => `<li>${esc(w)}</li>`).join("") || "<li>ยังไม่มีข้อมูลน้ำจากเขื่อนและน้ำขึ้นน้ำลง</li>"}</ul>
    <dl class="kv"><dt>น้ำจากเขื่อน C.13</dt><dd class="num">${c13 ? fmt(c13.q) + " ลบ.ม./วิ" + (c13.dq ? ` (${c13.dq > 0 ? "+" : ""}${fmt(c13.dq)} จากเมื่อวาน)` : "") : "–"}</dd>
    <dt>น้ำขึ้นสูงสุดครั้งถัดไป</dt><dd>${o.next_high ? tTH(o.next_high.t) + " · " + o.next_high.m.toFixed(2) + " ม." + (o.spring_tide ? " · น้ำเกิด" : "") : "–"}</dd>
    <dt>แนวน้ำเค็ม 0.25 g/L</dt><dd>${o.front ? `${esc(o.front.name)} กม. ${o.front.km} · ห่างสำแล ${o.front.dist_km} กม.` : (o.front_level === 0 ? "ยังไม่เข้าใกล้" : "–")}</dd></dl>
    <p class="small" style="margin:8px 0 0">ประเมินจากน้ำจืดที่ปล่อยจากเขื่อนเจ้าพระยา ช่วงน้ำเกิด และแนวลิ่มน้ำเค็มในแม่น้ำ ใช้ดูความเสี่ยงที่ไกลกว่าเวลาเดินทางของน้ำ</p>`;
}

function renderDetail() {
  const el = document.getElementById("detail");
  if (!selected) {
    const vs = Object.values(D.stations).map(s => s.f[hi]).filter(v => v != null);
    const mx = vs.length ? Math.max(...vs) : null, avg = vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null;
    el.innerHTML = `<div class="eyebrow">ภาพรวม 3 จังหวัด · ${hi ? "คาดการณ์ " + hlabel(hi) : "ตอนนี้"}</div>
      <div style="display:flex;gap:22px;flex-wrap:wrap;margin-top:6px">
      <div><div class="big">${fmt(avg)}</div><div class="unit">เฉลี่ย µS/cm (${vs.length} สถานี)</div></div>
      <div><div class="big" style="color:${colorOf(lvlOf(mx))}">${fmt(mx)}</div><div class="unit">สูงสุด µS/cm${mx != null ? ` (~${salt(mx)} g/L)` : ""}</div></div></div>
      <p class="small" style="margin:10px 0 0">แตะเขตบนแผนที่ หรือเลือกจากช่องค้นหา เพื่อดูว่ารับน้ำจากที่ไหนและค่าที่คาดการณ์</p>`;
    return;
  }
  const p = DIST.features.find(f => f.properties.code === selected).properties, d = D.districts[selected], v = d.f[hi], li = lvlOf(v);
  const fc = D.horizons.map((h, i) => `<span style="display:inline-block;margin:2px 6px 2px 0" title="${hlabel(i)}"><span class="small">${h ? "+" + h : "ตอนนี้"}</span> <span class="pill num" style="background:${colorOf(lvlOf(d.f[i]))}">${fmt(d.f[i])}</span></span>`).join("");
  const parts = d.parts.map(x => { const z = D.zones[x[0]]; return `${Math.round(x[1] * 100)}% สถานีสูบจ่าย${x[0]} <span class="small">(โรงผลิต${z.plant} · ${SRC[z.src]})</span> <span class="num">${fmt(z.f[hi])}</span>`; }).join("<br>");
  el.innerHTML = `<div class="eyebrow">${p.pro}</div><h2 style="font-size:20px;margin:2px 0 8px">${p.pro === "กรุงเทพมหานคร" ? "เขต" : "อำเภอ"}${p.th}</h2>
    <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap"><span class="big">${fmt(v)}</span><span class="unit">µS/cm</span>
    <span class="pill" style="background:${colorOf(li)}">${v == null ? (hi ? "ยังคาดการณ์ไม่ได้" : "ไม่มีข้อมูล") : NAMES[li]}</span></div>
    <dl class="kv"><dt>ความเค็มโดยประมาณ</dt><dd class="num">${v == null ? "–" : "~" + salt(v) + " g/L"}</dd><dt>รับน้ำจาก</dt><dd>${parts}</dd></dl>
    <p class="small" style="margin:10px 0 4px">คาดการณ์ 48 ชม. (µS/cm)</p><div>${fc}</div>
    <p class="small" style="margin:10px 0 0"><a href="#" id="clr" style="color:var(--accent)">กลับไปภาพรวม</a></p>`;
  document.getElementById("clr").onclick = e => { e.preventDefault(); select(null); };
}

function select(code, zoom) {
  selected = code; document.getElementById("pick").value = code || "";
  if (code && zoom) distLayer.eachLayer(l => { if (l.feature.properties.code === code) map.fitBounds(l.getBounds(), { maxZoom: 12, padding: [40, 40] }); });
  render();
}

load().catch(e => { document.getElementById("status").textContent = "โหลดข้อมูลไม่สำเร็จ: " + e.message; console.error(e); });
setInterval(() => fetch("data/latest.json", { cache: "no-store" }).then(x => x.json()).then(d => { if (d.generated !== D.generated) { D = d; renderStatus(); render(); } }).catch(() => {}), 5 * 60e3);

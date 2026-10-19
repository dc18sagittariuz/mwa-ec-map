"""คาดการณ์ EC น้ำประปา 0–48 ชม. ด้วยการส่งต่อค่าที่วัดได้ตามเวลาเดินทางของน้ำ
และประเมินความเสี่ยงน้ำเค็ม 2–3 วันจากน้ำจืดที่ปล่อยจากเขื่อน น้ำขึ้นน้ำลง และแนวลิ่มน้ำเค็ม

หลักคิด: น้ำที่จะออกจากก๊อกใน h ชั่วโมงข้างหน้า ส่วนใหญ่ผ่านจุดวัดต้นทางไปแล้ว
  EC(สถานี, ตอนนี้+h) ≈ EC(ต้นทาง, ตอนนี้+h−เวลาเดินทาง) + ค่าชดเชยของสถานี
เลือกต้นทางที่อยู่ใกล้สถานีที่สุดเท่าที่ข้อมูลยังครอบคลุม: ทางออกโรงผลิต → ไซฟอนรังสิต → สำแล
"""
from datetime import timedelta
from statistics import median

HORIZONS = [0, 6, 12, 18, 24, 30, 36, 42, 48]
SIPHON_FROM_SAMLAE = 7          # สำแล → ไซฟอนรังสิต (ชม.)
STALE_H = 6


class Series:
    def __init__(self, pts):
        self.p = sorted((t, v) for t, v in pts if v is not None)

    def __bool__(self):
        return bool(self.p)

    @property
    def last_t(self):
        return self.p[-1][0] if self.p else None

    def at(self, t, max_gap_h=4.0, edge_s=2700):
        """ค่าที่เวลา t (ประมาณเชิงเส้นระหว่างจุดที่ห่างกันไม่เกิน max_gap_h)"""
        p = self.p
        if not p or t < p[0][0] - timedelta(seconds=edge_s) or t > p[-1][0] + timedelta(seconds=edge_s):
            return None
        lo, hi = 0, len(p) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if p[mid][0] < t:
                lo = mid + 1
            else:
                hi = mid
        j = lo
        if p[j][0] == t:
            return p[j][1]
        if j == 0 or p[j][0] < t:
            near = p[j]
            return near[1] if abs((near[0] - t).total_seconds()) <= edge_s else None
        a, b = p[j - 1], p[j]
        gap = (b[0] - a[0]).total_seconds()
        if gap > max_gap_h * 3600:
            near = a if (t - a[0]) < (b[0] - t) else b
            return near[1] if abs((near[0] - t).total_seconds()) <= edge_s else None
        w = (t - a[0]).total_seconds() / gap
        return a[1] + (b[1] - a[1]) * w


def mean_series(series_list):
    """รวมหลายสถานี (เช่น บางเขน TR1–3) เป็นค่าเฉลี่ยตามเวลา"""
    times = sorted({t for s in series_list for t, _ in s.p})
    pts = []
    for t in times:
        vs = [s.at(t) for s in series_list]
        vs = [v for v in vs if v is not None]
        if vs:
            pts.append((t, sum(vs) / len(vs)))
    return Series(pts)


def level(ec, cuts):
    if ec is None:
        return -1
    for i, c in enumerate(cuts):
        if ec < c:
            return i
    return len(cuts)


def build(cfg, now, tw_hist, raw_hist, latest_tw, latest_raw):
    NET = cfg["stations"]
    up = cfg["upstream_h"]

    # ---------- ชุดข้อมูลต้นทาง ----------
    tw_series = {}
    for r in tw_hist:
        tw_series.setdefault(r["code"], []).append((r["t"], r["ec"]))
    tw_series = {k: Series(v) for k, v in tw_series.items()}
    raw_series = {}
    for r in raw_hist:
        raw_series.setdefault(r["id"], []).append((r["t"], r["cond"]))
    raw_series = {k: Series(v) for k, v in raw_series.items()}

    outlets = {p: mean_series([tw_series[c] for c in v["stations"] if c in tw_series]) for p, v in cfg["plants"].items()}
    samlae, siphon = raw_series.get("S1", Series([])), raw_series.get("S2", Series([]))
    # จุดอ้างอิง = ทางออกโรงผลิตบางเขน (ค่าเฉลี่ย TR1–3) — ทุกสถานีฝั่งเจ้าพระยามีเวลาหน่วง/อัตราส่งต่อเทียบจุดนี้
    ref = mean_series([tw_series[c] for c in ("SP01", "SP02", "SP03") if c in tw_series])
    rup = cfg.get("ref_upstream_h", {"samlae": up["บางเขน"], "siphon": up["บางเขน"] - SIPHON_FROM_SAMLAE})
    g = cfg.get("raw_gain", 1.0)   # อัตราส่งต่อ น้ำดิบ → ทางออกโรงผลิต

    # ค่าชดเชย น้ำดิบ → จุดอ้างอิง (median ย้อนหลัง; ถ้าข้อมูลยังน้อยใช้ 0)
    def raw_offset(raw, lag):
        diffs = []
        if ref and raw:
            for t, v in ref.p[-200:]:
                rv = raw.at(t - timedelta(hours=lag))
                if rv is not None:
                    diffs.append(v - g * rv)
        return (median(diffs), len(diffs)) if len(diffs) >= 6 else ((1 - g) * 330.0, len(diffs))

    cal = {"samlae": raw_offset(samlae, rup["samlae"]), "siphon": raw_offset(siphon, rup["siphon"])}
    # ค่าที่จุดอ้างอิง ณ เวลา t: ใช้ค่าวัดจริงก่อน ถ้ายังไม่ถึงให้ส่งต่อจากไซฟอน/สำแล
    REF_CANDS = [("outlet", ref, 0, 0.0, 1.0), ("siphon", siphon, rup["siphon"], cal["siphon"][0], g), ("samlae", samlae, rup["samlae"], cal["samlae"][0], g)]

    def ref_at(t):
        for name, ser, lag, off, gain in REF_CANDS:
            if ser:
                v = ser.at(t - timedelta(hours=lag))
                if v is not None:
                    return off + gain * v, name
        return None, None

    # ---------- ค่าล่าสุดของสถานี ----------
    newest = max((r["t"] for r in latest_tw), default=now)
    live = {r["code"]: r for r in latest_tw}

    stations = {}
    for code, meta in NET.items():
        r = live.get(code)
        ec_now = r["ec"] if r else None
        stale = (r is None) or (newest - r["t"] > timedelta(hours=STALE_H)) or ec_now is None
        plant = meta["plant"]
        L, k = meta.get("lag_bk_h"), meta.get("gain", 0.0) or 0.0
        linked = L is not None and k > 0
        # ค่าชดเชยของสถานี: median( EC สถานี − gain × อ้างอิง(t − L) ) ย้อนหลัง
        st_off = None
        ser = tw_series.get(code)
        if linked and ser and ref:
            diffs = [v - k * rv for t, v in ser.p[-150:] for rv in [ref.at(t - timedelta(hours=L))] if rv is not None]
            if diffs:
                st_off = median(diffs)
        if linked and st_off is None and not stale:
            rv, _ = ref_at(r["t"] - timedelta(hours=L))
            if rv is not None:
                st_off = ec_now - k * rv

        fc, how = [], []
        for h in HORIZONS:
            T = now + timedelta(hours=h)
            if h == 0 and not stale:
                fc.append(round(ec_now, 1)); how.append("measured"); continue
            val, src = None, "unknown"
            if linked and st_off is not None:
                rv, src0 = ref_at(T - timedelta(hours=L))
                if rv is not None:
                    val, src = st_off + k * rv, src0
            elif not linked and not stale:
                val, src = ec_now, "persist"       # ไม่รับน้ำฝั่งเจ้าพระยา: คงค่าล่าสุด
            fc.append(None if val is None else round(val, 1))
            how.append(src)
        stations[code] = {
            "name": (r or {}).get("name") or meta["name"], "lat": meta["lat"], "lon": meta["lon"],
            "plant": plant, "src": meta["src"], "zone": meta["zone"], "district": meta["district"],
            "ec": ec_now, "salt": (r or {}).get("salt"), "t": r["t"].isoformat() if r else None, "stale": stale,
            "lag_samlae_h": (rup["samlae"] + L) if linked else None, "gain": k, "fit": meta.get("fit"),
            "f": fc, "how": how,
        }

    # ---------- รวมเป็นโซน / เขต ----------
    def agg(codes, i):
        vs = [stations[c]["f"][i] for c in codes if c in stations and stations[c]["f"][i] is not None]
        return max(vs) if vs else None

    zones = {}
    for ps, z in cfg["zones"].items():
        codes = z["ps_stations"] + z["stations"]
        f = []
        for i in range(len(HORIZONS)):
            # ถ้าสถานีสูบจ่ายของโซนยังไม่ทราบค่า ถือว่าโซนยังไม่ทราบ (กันค่าสูงสุดหลอกจากสถานีปลายสายที่ช้ากว่า)
            ps_known = any(stations[c]["f"][i] is not None for c in z["ps_stations"] if c in stations)
            f.append(agg(codes, i) if ps_known else None)
        zones[ps] = {"plant": z["plant"], "src": z["src"], "stations": codes, "f": f}
    def area(parts):
        use = [p for p in parts if p[1] >= 0.1]   # โซนที่ครอบคลุมพื้นที่ ≥10%
        f = []
        for i in range(len(HORIZONS)):
            vs = [zones[p[0]]["f"][i] for p in use]
            f.append(max(vs) if vs and None not in vs else None)
        return {"parts": parts, "f": f}

    districts = {dc: area(parts) for dc, parts in cfg["district_zones"].items()}
    branches = {bc: dict(area(parts), name=cfg["branch_names"][bc]) for bc, parts in cfg.get("branch_zones", {}).items()}
    plants = {p: {"src": v["src"], "f": [agg(v["stations"], i) for i in range(len(HORIZONS))]} for p, v in cfg["plants"].items()}

    return {"horizons": HORIZONS, "stations": stations, "zones": zones, "districts": districts, "branches": branches, "plants": plants,
            "calib": {k: {"offset": round(v[0], 1), "pairs": v[1]} for k, v in cal.items()},
            "series": {
                "samlae": [[t.isoformat(), round(v, 1)] for t, v in samlae.p if t > now - timedelta(hours=72)],
                "siphon": [[t.isoformat(), round(v, 1)] for t, v in siphon.p if t > now - timedelta(hours=72)],
                "bangkhen_out": [[t.isoformat(), round(v, 1)] for t, v in outlets["บางเขน"].p if t > now - timedelta(hours=72)],
            }}


# ---------- แนวโน้มน้ำเค็ม 2–3 วัน (หลักเดียวกับเฟิร์มแวร์ ESP32) ----------
FLOW_WARN, FLOW_LOW = 150, 80
SALT_FRONT_GL, FRONT_WARN_KM, FRONT_OVER_KM = 0.25, 30, 10


def outlook(now, flow, flow_hist, tide, raw_latest):
    why = []
    lv = 0
    c13 = (flow or {}).get("C.13")
    falling = False
    if c13 and c13.get("q") is not None:
        q, dq = c13["q"], c13.get("dq") or 0
        if dq < 0 and q - dq > 0 and -dq * 100 / (q - dq) >= 10:
            falling = True
        old = [r["q"] for r in flow_hist if r["code"] == "C.13" and r["q"] is not None
               and timedelta(hours=66) <= c13["t"] - r["t"] <= timedelta(hours=78)]
        if old and old[0] > 0 and (old[0] - q) * 100 / old[0] >= 25:
            falling = True
        if q < FLOW_LOW:
            lv = 2
        elif q < FLOW_WARN:
            lv = 1
        why.append(f"น้ำจากเขื่อนเจ้าพระยา {q:.0f} ลบ.ม./วิ" + (" กำลังลดลง" if falling else ""))

    # น้ำเกิด: ยอดน้ำขึ้นใน 48 ชม. ข้างหน้าใกล้ยอดสูงสุดของช่วง 10 วัน
    spring, next_high = False, None
    if tide:
        win = max(v for _, v in tide)
        ahead = [(t, v) for t, v in tide if now <= t <= now + timedelta(hours=48)]
        if ahead:
            pt, pv = max(ahead, key=lambda x: x[1])
            spring = pv >= win - 0.10
            for i in range(1, len(tide) - 1):
                t, v = tide[i]
                if t >= now and v >= tide[i - 1][1] and v > tide[i + 1][1]:
                    next_high = {"t": t.isoformat(), "m": round(v, 2)}
                    break
    if lv == 1 and (spring or falling):
        lv = 2
    if lv == 0 and falling and c13 and c13["q"] < FLOW_WARN * 1.5:
        lv = 1

    # แนวลิ่มน้ำเค็ม
    cp = [r for r in raw_latest if r["river"] == "chao_phraya" and r.get("km") is not None]
    samlae_km = next((r["km"] for r in cp if r["id"] == "S1"), 96)
    salty = [r for r in cp if r.get("salt") is not None and r["salt"] >= SALT_FRONT_GL]
    front = max(salty, key=lambda r: r["km"]) if salty else None
    front_lvl = None
    if cp:
        front_lvl = 0
        if front:
            d = samlae_km - front["km"]
            front_lvl = 2 if d <= FRONT_OVER_KM else 1 if d <= FRONT_WARN_KM else 0
    if lv == 0 and front_lvl and spring:
        lv = 1
    if spring:
        why.append("ช่วงน้ำเกิด")
    if front:
        why.append(f"แนวน้ำเค็ม ≥{SALT_FRONT_GL} g/L อยู่ กม. {front['km']:.0f} (ห่างสำแล {max(samlae_km - front['km'], 0):.0f} กม.)")
    have = bool(c13) or bool(tide)
    return {
        "level": lv if have else None, "why": why, "spring_tide": spring, "next_high": next_high,
        "front": {"id": front["id"], "name": front["name"], "km": front["km"], "dist_km": round(samlae_km - front["km"], 1)} if front else None,
        "front_level": front_lvl, "samlae_km": samlae_km,
    }

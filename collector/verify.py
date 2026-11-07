"""ตรวจความแม่นยำจากการใช้งานจริง (forecast verification)

1) archive(): เก็บค่าคาดการณ์ที่ระบบออกจริงทุก ~3 ชม. → data/forecasts/YYYY-MM.csv
   (ไม่เก็บทุก 30 นาทีเพราะค่าแต่ละรอบใกล้กันมาก และ repo จะบวม)
2) summarize(): เทียบกับค่าวัด TWQMS (ผ่าน QC) เมื่อถึงเวลาเป้าหมาย → docs/data/verify.json

ตัวชี้วัด (ตามแนวทางตรวจระบบเตือนภัย):
  MAE, bias            ความคลาดเฉลี่ย / คาดสูง(+) หรือต่ำ(−) กว่าจริง
  skill                1 − MAE/MAE(ใช้ค่าปัจจุบันเป็นค่าคาด) — >0 = ดีกว่าวิธีง่ายที่สุด
  coverage, above      ค่าจริงตกในช่วงความไม่แน่นอน / สูงกว่าขอบบน (เป้า ~83% / ~6% จากการทดสอบปี 2567)
  POD, FAR             จับเหตุการณ์ได้ / เตือนผิด ที่เกณฑ์ 700 และ 1,200 µS/cm (นับเป็น สถานี×ชั่วโมงเป้าหมาย)

ใช้:  python collector/verify.py            สรุปอย่างเดียว
      python collector/verify.py backfill   ดึงค่าคาดการณ์ย้อนหลังจาก git history ของ latest.json
"""
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import model  # noqa: E402
import qc     # noqa: E402
import store  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
FC_DIR = os.path.join(ROOT, "data", "forecasts")
OUT = os.path.join(ROOT, "docs", "data", "verify.json")
COLS = ["issued", "code", "h", "f", "lo", "hi", "how", "ec0"]
EVERY_H = 3
EVENTS = (700, 1200)   # เริ่มกร่อย / เกินเกณฑ์ (เกณฑ์ กปน. 2559)
GROUP = {"samlae_fc": "fc", "persist": "persist"}   # อื่น ๆ = ส่งต่อจากค่าวัด ("chain")


def _rows(out):
    t = out["generated"]
    for code, s in out["stations"].items():
        ec0 = s["f"][0] if s.get("how") and s["how"][0] in ("measured",) else None
        for i, h in enumerate(out["horizons"]):
            if h == 0 or s["f"][i] is None:
                continue
            lo = (s.get("lo") or [None] * len(s["f"]))[i]
            hi = (s.get("hi") or [None] * len(s["f"]))[i]
            yield [t, code, h, s["f"][i], "" if lo is None else lo, "" if hi is None else hi, s["how"][i], "" if ec0 is None else ec0]


def _write(rows_by_month):
    os.makedirs(FC_DIR, exist_ok=True)
    for m, rows in rows_by_month.items():
        path = os.path.join(FC_DIR, m + ".csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLS)
            w.writerows(rows)


def archive(out, state):
    """เก็บค่าคาดการณ์รอบนี้ ถ้าห่างจากรอบที่เก็บล่าสุด ≥ EVERY_H ชม. — คืน True ถ้าเก็บ"""
    t = datetime.fromisoformat(out["generated"])
    last = state.get("fc_archived")
    if last and t - datetime.fromisoformat(last) < timedelta(hours=EVERY_H) - timedelta(minutes=10):
        return False
    _write({t.strftime("%Y-%m"): list(_rows(out))})
    state["fc_archived"] = out["generated"]
    return True


def backfill():
    """ดึง latest.json ทุกเวอร์ชันจาก git แล้วเก็บรอบที่ห่างกัน ≥ EVERY_H ชม. (ข้ามช่วงที่มีใน archive แล้ว)"""
    existing = set()
    if os.path.isdir(FC_DIR):
        for fn in os.listdir(FC_DIR):
            with open(os.path.join(FC_DIR, fn), encoding="utf-8") as f:
                existing |= {r["issued"] for r in csv.DictReader(f)}
    log = subprocess.run(["git", "-C", ROOT, "log", "--reverse", "--format=%H", "--", "docs/data/latest.json"],
                         capture_output=True, text=True, check=True).stdout.split()
    by_month, last, n = defaultdict(list), None, 0
    for sha in log:
        try:
            out = json.loads(subprocess.run(["git", "-C", ROOT, "show", f"{sha}:docs/data/latest.json"],
                                            capture_output=True, text=True, check=True).stdout)
            t = datetime.fromisoformat(out["generated"])
        except (subprocess.CalledProcessError, ValueError, KeyError):
            continue
        if last and t - last < timedelta(hours=EVERY_H) - timedelta(minutes=10):
            continue
        last = t
        if out["generated"] in existing:
            continue
        by_month[t.strftime("%Y-%m")].extend(_rows(out))
        n += 1
    # เขียนเรียงตามเวลา (ไฟล์เดือนใหม่ทั้งหมด เพื่อให้เรียงถูก)
    for m, rows in by_month.items():
        path = os.path.join(FC_DIR, m + ".csv")
        old = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = [list(r.values()) for r in csv.DictReader(f)]
            os.remove(path)
        _write({m: sorted(old + rows, key=lambda r: (r[0], r[1], int(r[2])))})
    return n


def _load_forecasts():
    rows = []
    if not os.path.isdir(FC_DIR):
        return rows
    for fn in sorted(os.listdir(FC_DIR)):
        with open(os.path.join(FC_DIR, fn), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                num = lambda x: float(x) if x != "" else None  # noqa: E731
                rows.append({"issued": datetime.fromisoformat(r["issued"]), "code": r["code"], "h": int(r["h"]),
                             "f": float(r["f"]), "lo": num(r["lo"]), "hi": num(r["hi"]), "how": r["how"], "ec0": num(r["ec0"])})
    return rows


def _stats(pairs):
    """pairs = [(row, truth)] → ตัวชี้วัด"""
    n = len(pairs)
    if not n:
        return {"n": 0}
    err = [r["f"] - t for r, t in pairs]
    out = {"n": n, "mae": round(sum(abs(e) for e in err) / n, 1), "bias": round(sum(err) / n, 1)}
    pp = [(abs(r["ec0"] - t), abs(r["f"] - t)) for r, t in pairs if r["ec0"] is not None]
    if len(pp) >= 20:
        mp = sum(a for a, _ in pp) / len(pp)
        out["mae_persist"] = round(mp, 1)
        out["skill"] = round(1 - (sum(b for _, b in pp) / len(pp)) / mp, 2) if mp > 0 else None
    band = [(r, t) for r, t in pairs if r["lo"] is not None and r["hi"] is not None]
    if band:
        out["coverage"] = round(sum(r["lo"] <= t <= r["hi"] for r, t in band) / len(band), 3)
        out["above"] = round(sum(t > r["hi"] for r, t in band) / len(band), 3)
        out["n_band"] = len(band)
    for th in EVENTS:
        obs = sum(t >= th for _, t in pairs)
        fc = sum(r["f"] >= th for r, _ in pairs)
        hit = sum(t >= th and r["f"] >= th for r, t in pairs)
        out[f"ev{th}"] = {"obs": obs, "fc": fc, "hit": hit,
                          "pod": round(hit / obs, 2) if obs else None, "far": round((fc - hit) / fc, 2) if fc else None}
    return out


def summarize(now=None):
    rows = _load_forecasts()
    if not rows:
        return None
    now = now or max(r["issued"] for r in rows)
    days = (now - min(r["issued"] for r in rows)).days + 2
    tw = store.read_recent("twqms", now, days + 3)
    pts = defaultdict(list)
    for r in tw:
        pts[r["code"]].append((r["t"], r["ec"]))
    truth = {k: model.Series(qc.clean(v, "tap")[0]) for k, v in pts.items()}

    matched = []
    for r in rows:
        T = r["issued"] + timedelta(hours=r["h"])
        if T > now or r["code"] not in truth:
            continue
        t = truth[r["code"]].at(T, max_gap_h=1.5, edge_s=1800)
        if t is not None:
            matched.append((r, t))

    hs = sorted({r["h"] for r, _ in matched})
    windows = {"7d": now - timedelta(days=7), "30d": now - timedelta(days=30), "all": datetime.min.replace(tzinfo=now.tzinfo)}
    res = {"generated": now.isoformat(), "since": min(r["issued"] for r in rows).isoformat(),
           "n_issued": len({r["issued"] for r in rows}), "n_matched": len(matched), "every_h": EVERY_H,
           "windows": {}, "by_group": {}, "daily": []}
    for wname, start in windows.items():
        sel = [(r, t) for r, t in matched if r["issued"] + timedelta(hours=r["h"]) >= start]
        res["windows"][wname] = {"all": _stats(sel), "by_h": {str(h): _stats([(r, t) for r, t in sel if r["h"] == h]) for h in hs}}
    for g in ("chain", "fc", "persist"):
        sel = [(r, t) for r, t in matched if GROUP.get(r["how"], "chain") == g]
        res["by_group"][g] = {str(h): _stats([(r, t) for r, t in sel if r["h"] == h]) for h in hs}
    # รายวัน (ตามวันเป้าหมาย) สำหรับกราฟ: MAE ที่ +12 / +24 / +48 ชม. และค่าวัดสูงสุดของวัน
    day = defaultdict(lambda: defaultdict(list))
    for r, t in matched:
        d = (r["issued"] + timedelta(hours=r["h"])).date().isoformat()
        day[d]["max"].append(t)
        if r["h"] in (12, 24, 48):
            day[d][r["h"]].append(abs(r["f"] - t))
    for d in sorted(day)[-90:]:
        v = day[d]
        res["daily"].append({"d": d, "obs_max": round(max(v["max"]), 0),
                             **{f"mae{h}": round(sum(v[h]) / len(v[h]), 1) if v[h] else None for h in (12, 24, 48)}})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        print("backfilled runs:", backfill())
    r = summarize()
    if r:
        a = r["windows"]["all"]["all"]
        print(json.dumps({k: r[k] for k in ("since", "n_issued", "n_matched")}, ensure_ascii=False), json.dumps(a, ensure_ascii=False))

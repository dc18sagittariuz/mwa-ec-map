"""เก็บประวัติเป็น CSV รายเดือน (เพิ่มเฉพาะแถวใหม่) และอ่านย้อนหลัง"""
import csv
import json
import os
from datetime import datetime, timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
HIST = os.path.join(ROOT, "data", "history")
STATE = os.path.join(ROOT, "data", "state.json")

COLS = {
    "twqms": ["t", "code", "ec", "salt", "cl2", "turb", "ph", "temp"],
    "raw": ["t", "id", "river", "km", "ph", "salt", "turb", "tds", "nh4", "do", "temp", "depth", "cond", "wl"],
    "flow": ["t", "code", "q", "dq", "wl"],
}


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"last": {}}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)


def append(kind, rows, key, state):
    """เพิ่มแถวที่เวลาใหม่กว่าครั้งก่อน (ต่อสถานี) คืนจำนวนแถวที่เพิ่ม"""
    last = state["last"].setdefault(kind, {})
    by_month = {}
    for r in rows:
        k = str(r[key])
        ts = r["t"].isoformat()
        if last.get(k, "") >= ts:
            continue
        last[k] = ts
        by_month.setdefault(r["t"].strftime("%Y-%m"), []).append(r)
    n = 0
    for month, rs in by_month.items():
        d = os.path.join(HIST, kind)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, month + ".csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLS[kind])
            for r in sorted(rs, key=lambda x: x["t"]):
                w.writerow([r["t"].isoformat() if c == "t" else ("" if r.get(c) is None else r.get(c)) for c in COLS[kind]])
                n += 1
    return n


def read_recent(kind, now, days):
    """อ่านแถวย้อนหลัง `days` วัน คืน list ของ dict (ค่าตัวเลขเป็น float)"""
    start = now - timedelta(days=days)
    months = sorted({(start + timedelta(days=i)).strftime("%Y-%m") for i in range(days + 2)})
    out = []
    for m in months:
        path = os.path.join(HIST, kind, m + ".csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                t = datetime.fromisoformat(r["t"])
                if t < start:
                    continue
                rec = {"t": t}
                for k, v in r.items():
                    if k == "t":
                        continue
                    try:
                        rec[k] = float(v) if v != "" else None
                    except ValueError:
                        rec[k] = v
                out.append(rec)
    return out

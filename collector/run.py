"""รอบเก็บข้อมูล 1 ครั้ง: ดึงทุกแหล่ง → เพิ่มประวัติ → คำนวณ → เขียน docs/data/latest.json"""
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
import sources  # noqa: E402
import store    # noqa: E402
import model    # noqa: E402
import qc       # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
ICT = sources.ICT


def iso(t):
    return t.isoformat() if t else None


def main():
    now = datetime.now(ICT).replace(microsecond=0)
    cfg = json.load(open(os.path.join(ROOT, "config", "network.json"), encoding="utf-8"))
    state = store.load_state()
    sess = requests.Session()
    status = {}

    def grab(name, fn):
        try:
            v = fn(sess)
            status[name] = {"ok": True}
            return v
        except Exception as e:  # แหล่งใดล่มก็ยังทำงานต่อด้วยข้อมูลเดิม
            status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
            traceback.print_exc()
            return None

    tw = grab("twqms", sources.fetch_twqms) or []
    raw = grab("rwc", sources.fetch_rwc) or []
    flow = grab("rid", sources.fetch_flow) or {}
    tide = grab("tide", sources.fetch_tide) or []

    status.setdefault("twqms", {})["rows_added"] = store.append("twqms", tw, "code", state)
    status.setdefault("rwc", {})["rows_added"] = store.append("raw", raw, "id", state)
    status.setdefault("rid", {})["rows_added"] = store.append(
        "flow", [dict(code=k, **v) for k, v in flow.items()], "code", state)
    # เก็บเฉพาะค่าจนถึงปัจจุบัน (ค่าอนาคตเป็นพยากรณ์ที่เปลี่ยนได้)
    status.setdefault("tide", {})["rows_added"] = store.append(
        "tide", [{"t": t, "code": "CPY", "sl": v} for t, v in tide if t <= now], "code", state)
    for k, v in (("twqms", tw), ("rwc", raw)):
        if v:
            status[k]["n"] = len(v)
            status[k]["newest"] = iso(max(r["t"] for r in v))

    # ใช้ค่าล่าสุดจากประวัติ ถ้ารอบนี้ดึงไม่สำเร็จ
    tw_hist = store.read_recent("twqms", now, 7)
    raw_hist = store.read_recent("raw", now, 7)
    flow_hist = store.read_recent("flow", now, 7)
    # ชั่วโมงล่าสุดของกรมชลฯ มักยังไม่มีค่าปริมาณน้ำ (มีแค่ระดับน้ำ) → ใช้ค่าล่าสุดที่มีภายใน 12 ชม.
    for code, v in flow.items():
        if v.get("q") is None:
            prev = [x for x in flow_hist if x["code"] == code and x.get("q") is not None and v["t"] - x["t"] <= timedelta(hours=12)]
            if prev:
                p = max(prev, key=lambda x: x["t"])
                v.update(q=p["q"], dq=p.get("dq"), q_t=p["t"])
    if not tw:
        last = {}
        for r in tw_hist:
            last[r["code"]] = r
        tw = list(last.values())
    if not raw:
        last = {}
        for r in raw_hist:
            last[r["id"]] = r
        raw = [dict(r, name=r["id"]) for r in last.values()]
        for r in raw:
            r["river"] = r.get("river") or ""

    out = model.build(cfg, now, tw_hist, raw_hist, tw, raw)
    out["outlook"] = model.outlook(now, flow, flow_hist, tide, raw)

    def rawpick(i):
        r = next((x for x in raw if x["id"] == i), None)
        if not r:
            return None
        # ธง QC ของค่าล่าสุด (เช่น สำแลรายงาน 1 µS/cm) — ค่าที่ไม่ผ่านไม่ใช้เทียบย้อนหลังด้วย
        chk = qc.check([(x["t"], x.get("cond")) for x in raw_hist if x["id"] == i], "raw")
        flag = {t: (f, test) for t, _, f, test in chk}
        f_now, test_now = flag.get(r["t"], (qc.NOT_EVAL, None))
        old = [x for x in raw_hist if x["id"] == i and x.get("cond") is not None and r["t"] - x["t"] >= timedelta(hours=23)
               and flag.get(x["t"], (qc.PASS,))[0] < qc.SUSPECT]
        return {"qc": test_now if f_now >= qc.SUSPECT else None,"name": r.get("name"), "t": iso(r["t"]), "cond": r.get("cond"), "salt": r.get("salt"),
                "cond_24h_ago": old[-1]["cond"] if old else None}

    out.update({
        "generated": iso(now),
        "status": status,
        "raw": {"samlae": rawpick("S1"), "siphon": rawpick("S2")},
        "flow": {k: {**v, "t": iso(v["t"]), "q_t": iso(v.get("q_t") or v["t"])} for k, v in flow.items()},
        "chao_phraya": sorted([{"id": r["id"], "name": r.get("name"), "km": r["km"], "salt": r.get("salt"), "cond": r.get("cond")}
                               for r in raw if r.get("river") == "chao_phraya" and r.get("km") is not None],
                              key=lambda x: x["km"]),
        "levels": cfg["levels"], "level_names": cfg["level_names"], "salt_per_ec": cfg["salt_per_ec"],
    })
    os.makedirs(os.path.join(ROOT, "docs", "data"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "data", "latest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    # จดเวลารอบที่ cron-job.org สั่ง (workflow_dispatch) ไว้ให้ health.py ตรวจว่าตัวตั้งเวลาหลักยังทำงาน
    state["last_run"] = iso(now)
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        state["last_dispatch"] = iso(now)
    store.save_state(state)
    print(json.dumps(status, ensure_ascii=False, indent=1))
    # ล้มเหลวเฉพาะเมื่อดึงไม่ได้สักแหล่ง (ให้ Actions แจ้งเตือน)
    if not any(s.get("ok") for s in status.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()

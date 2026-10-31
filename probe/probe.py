"""สำรวจครั้งเดียว: ข้อมูลย้อนหลังที่หาได้สำหรับโมเดลพยากรณ์สำแล (ไม่ใช่ส่วนของระบบ)"""
import json, requests
out = {}
s = requests.Session(); s.headers["User-Agent"] = "mwa-ec-map/1.0"
# 1) ระดับน้ำทะเล (แบบจำลองน้ำขึ้นน้ำลง) ย้อนหลังช่วงเหตุการณ์ 2567 และหน้าแล้ง 2563-2566
for y in (2020, 2021, 2023, 2024):
    u = ("https://marine-api.open-meteo.com/v1/marine?latitude=13.40&longitude=100.55&hourly=sea_level_height_msl"
         f"&start_date={y}-01-01&end_date={y}-05-31&timezone=GMT")
    try:
        r = s.get(u, timeout=60); j = r.json()
        h = j.get("hourly", {}); v = h.get("sea_level_height_msl") or []
        out[f"tide_{y}"] = {"status": r.status_code, "n": len(v), "non_null": sum(x is not None for x in v), "err": j.get("reason")}
        if v:
            with open(f"probe/tide_{y}.csv", "w") as f:
                f.write("t,sl\n" + "".join(f"{t},{x}\n" for t, x in zip(h["time"], v) if x is not None))
    except Exception as e:
        out[f"tide_{y}"] = str(e)[:200]
# 2) สถานีกรมชลฯ ที่มีในระบบ (หา C.29A บางไทร ฯลฯ)
try:
    r = s.get("https://bigdata-swoc.rid.go.th/api/ma/pier/all/get_pier_data", timeout=90)
    d = r.json().get("data", [])
    out["rid_n"] = len(d)
    out["rid_sample_keys"] = sorted(d[0].keys()) if d else []
    out["rid_stations"] = sorted({(x.get("station_code"), x.get("station_name") or x.get("name") or "", x.get("river_name") or "") for x in d})
except Exception as e:
    out["rid"] = str(e)[:200]
json.dump(out, open("probe/result.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: v for k, v in out.items() if k != "rid_stations"}, ensure_ascii=False, default=str))

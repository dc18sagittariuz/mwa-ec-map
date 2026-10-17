"""ดึงข้อมูลจากแหล่งต่าง ๆ — แต่ละฟังก์ชันคืนค่าที่อ่านได้ หรือยก exception ถ้าดึงไม่สำเร็จ"""
import re
import json
import html as htmllib
from datetime import datetime, timezone, timedelta

import requests

ICT = timezone(timedelta(hours=7))
UA = "Mozilla/5.0 (compatible; mwa-ec-map/1.0; +https://github.com/)"
TIMEOUT = 40

TWQMS_URL = "https://twqonline.mwa.co.th/TWQMSServicepublic/api/public/getstations"
RWC_URL = "http://rwc.mwa.co.th/page/home/table.php"
RWC_HOME = "http://rwc.mwa.co.th/page/home/"
RID_URL = "https://bigdata-swoc.rid.go.th/api/ma/pier/all/get_pier_data"
TIDE_URL = ("https://marine-api.open-meteo.com/v1/marine?latitude=13.40&longitude=100.55"
            "&hourly=sea_level_height_msl&past_days=7&forecast_days=3&timeformat=unixtime&timezone=GMT")

# ค่าใน TWQMS: valueN
TW_PARAMS = {"turb": 1, "cl2": 2, "ph": 4, "ec": 5, "temp": 6, "salt": 9}
# คอลัมน์ในตารางน้ำดิบ rwc (ต่อจาก กม. / วันที่ / เวลา)
RAW_PARAMS = ["ph", "salt", "turb", "tds", "nh4", "do", "temp", "depth", "cond", "wl"]


def _num(v):
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", ""))
    except ValueError:
        return None
    if f <= -999:
        return None
    return f


def fetch_twqms(session):
    r = session.get(TWQMS_URL, timeout=TIMEOUT, headers={
        "User-Agent": UA, "Accept": "application/json", "Referer": "https://twqonline.mwa.co.th/"})
    r.raise_for_status()
    out = []
    for s in r.json().get("stations", []):
        v = s.get("value") or {}
        dtm = s.get("sourceDtm") or ""
        try:
            t = datetime.fromisoformat(dtm[:19]).replace(tzinfo=ICT)
        except ValueError:
            continue
        row = {"code": s.get("stationCode"), "name": s.get("shortStationName") or s.get("stationName"),
               "lat": s.get("latitude"), "lon": s.get("longtitude"), "t": t}
        for k, i in TW_PARAMS.items():
            row[k] = _num(v.get(f"value{i}"))
            row[k + "_lvl"] = v.get(f"rangeType{i}")
        out.append(row)
    return out


def _cell(td):
    """อ่านค่าจาก 1 ช่อง <TD> ของตารางน้ำดิบ (แบบเดียวกับเฟิร์มแวร์ ESP32)"""
    spans = list(re.finditer(r"<SPAN([^>]*)>(.*?)</SPAN>", td, re.I | re.S))
    if spans:
        attrs, txt = spans[-1].group(1), spans[-1].group(2)
        cls = re.search(r'CLASS="([^"]*)"', attrs, re.I)
        cls = cls.group(1) if cls else ""
    else:
        txt = re.sub(r"<[^>]+>", "", td[td.find(">") + 1:])
        cls = ""
    txt = htmllib.unescape(re.sub(r"<[^>]+>", "", txt)).strip()
    if not txt or txt == "-" or txt == "-9999" or "black_fade" in cls:
        return None, None
    lvl = "O" if "f_red" in cls else ("W" if "f_yellow" in cls else "N")
    return txt, lvl


def _river(s):
    if "แม่น้ำน้อย" in s:
        return "noi"
    if "เจ้าพระยา" in s:
        return "chao_phraya"
    if "ตะวันออก" in s:
        return "east_canal"
    if "ตะวันตก" in s:
        return "west_canal"
    if "แม่กลอง" in s:
        return "mae_klong"
    return ""


def parse_rwc(page):
    stop = page.find("อยู่ระหว่างทดสอบระบบ")
    if stop > 0:
        page = page[:stop]
    rows = []
    river = ""
    pos = 0
    while True:
        a = page.find("?id=", pos)
        if a < 0:
            break
        b = page.upper().find("<B>", pos)
        if 0 <= b < a:
            e = page.upper().find("</B>", b)
            river = _river(page[b + 3:e]) or river
        end = page.upper().find("</TR>", a)
        end = len(page) if end < 0 else end
        pos = end + 1
        row = page[a:end]
        sid = row[4:row.find('"')]
        name = re.sub(r"<[^>]+>", "", row[row.find(">") + 1:row.upper().find("</A>")]).strip()
        if "Test run" in name:
            continue
        tds = re.findall(r"<TD(.*?)</TD>", row[row.upper().find("</TD>"):], re.I | re.S)
        if len(tds) < 13:
            continue
        km, _ = _cell(tds[0])
        date, _ = _cell(tds[1])
        tim, _ = _cell(tds[2])
        try:
            dd, mm, yy = [int(x) for x in date.split("/")]
            hh, mi = [int(x) for x in tim.split(":")[:2]]
            t = datetime(yy - 543 if yy > 2400 else yy, mm, dd, hh, mi, tzinfo=ICT)
        except Exception:
            continue
        rec = {"id": sid, "name": htmllib.unescape(name), "river": river, "km": _num(km), "t": t}
        for i, p in enumerate(RAW_PARAMS):
            txt, lvl = _cell(tds[3 + i])
            rec[p] = _num(txt)
            rec[p + "_lvl"] = lvl
        rows.append(rec)
    return rows


def fetch_rwc(session):
    h = {"User-Agent": UA, "Accept": "text/html, */*", "X-Requested-With": "XMLHttpRequest", "Referer": RWC_HOME}
    r = session.get(RWC_URL, timeout=TIMEOUT, headers=h)
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = "utf-8"
    page = r.text if r.ok else ""
    if "<TABLE" not in page.upper():
        session.get(RWC_HOME, timeout=TIMEOUT, headers={"User-Agent": UA})   # รับ session cookie แล้วลองใหม่
        r = session.get(RWC_URL, timeout=TIMEOUT, headers=h)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = "utf-8"
        page = r.text
    rows = parse_rwc(page)
    if not rows:
        raise RuntimeError(f"rwc: ไม่พบแถวข้อมูล ({len(page)} bytes)")
    return rows


def fetch_flow(session, codes=("C.13", "C.35")):
    r = session.get(RID_URL, timeout=90, headers={"User-Agent": UA, "Accept": "application/json"})
    r.raise_for_status()
    out = {}
    for rec in r.json().get("data", []):
        c = rec.get("station_code")
        if c in codes:
            t = rec.get("hourly_time_utc") or ""
            try:
                tt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            except ValueError:
                continue
            out[c] = {"q": _num(rec.get("q_values")), "dq": _num(rec.get("qval_diff_yd")),
                      "wl": _num(rec.get("wl_values_msl")), "t": tt}
    return out


def fetch_tide(session):
    r = session.get(TIDE_URL, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    h = r.json()["hourly"]
    return [(datetime.fromtimestamp(t, timezone.utc), v) for t, v in zip(h["time"], h["sea_level_height_msl"]) if v is not None]

"""สร้างรูป/PDF รายงานผู้บริหาร (docs/report.html) วันละครั้ง ตอนรอบเก็บข้อมูลแรกหลัง 07:00 น.

  python collector/daily_report.py check          exit 0 = ถึงเวลาสร้างรายงานวันนี้แล้วและยังไม่ได้สร้าง, 1 = ข้าม
  python collector/daily_report.py render OUTDIR  เปิด report.html ด้วย Chromium (Playwright) → PNG 2 เท่า + PDF A4
                                                  แล้วจดวันที่ไว้ใน data/state.json (report_date)

ไฟล์ขึ้นไว้ที่ GitHub Release "daily-report" (ทำใน workflow) ไม่ commit เข้า repo เพื่อไม่ให้ repo บวม
"""
import functools
import http.server
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
ICT = timezone(timedelta(hours=7))
HOUR = 7
STATE = os.path.join(ROOT, "data", "state.json")


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"last": {}}


def due(now=None):
    now = now or datetime.now(ICT)
    return now.hour >= HOUR and _state().get("report_date") != now.date().isoformat()


def render(outdir):
    from playwright.sync_api import sync_playwright

    os.makedirs(outdir, exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=os.path.join(ROOT, "docs"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/report.html"
    now = datetime.now(ICT)
    day = now.date().isoformat()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 900, "height": 1300}, device_scale_factor=2, locale="th-TH", timezone_id="Asia/Bangkok")
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url, wait_until="networkidle")
            pg.wait_for_selector("#sheet .band", timeout=30000)
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(500)
            if errors:
                raise RuntimeError("report.html error: " + "; ".join(errors))
            png = os.path.join(outdir, f"ec-report-{day}.png")
            pg.locator("#sheet").screenshot(path=png)
            pdf = os.path.join(outdir, f"ec-report-{day}.pdf")
            pg.emulate_media(media="print")
            pg.evaluate("document.documentElement.classList.add('full-bleed')")
            pg.pdf(path=pdf, format="A4", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                   prefer_css_page_size=True)
            b.close()
    finally:
        srv.shutdown()
    # ชื่อคงที่สำหรับลิงก์ถาวร
    shutil.copy(png, os.path.join(outdir, "ec-report-latest.png"))
    shutil.copy(pdf, os.path.join(outdir, "ec-report-latest.pdf"))
    st = _state()
    st["report_date"] = day
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("rendered", day, os.listdir(outdir))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        force = os.environ.get("FORCE_REPORT") == "1"
        sys.exit(0 if force or due() else 1)
    elif cmd == "render":
        render(sys.argv[2] if len(sys.argv) > 2 else "report-out")

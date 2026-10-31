"""ตรวจสุขภาพระบบ แล้วเปิด/ปิด GitHub Issue เป็นการแจ้งเตือน (เจ้าของ repo ได้อีเมลเมื่อมี issue ใหม่ที่มอบหมายให้)

ใช้ 2 ที่:
  python collector/health.py collect    หลังรอบเก็บข้อมูล — ตรวจแหล่งข้อมูล + ตัวตั้งเวลา + token
  python collector/health.py watchdog   workflow แยก รันทุกชั่วโมง — ตรวจว่าระบบยังเก็บข้อมูลอยู่หรือไม่
  เพิ่ม --dry-run เพื่อพิมพ์ผลโดยไม่แตะ GitHub

ปัญหาแต่ละอย่างมี key ของตัวเอง → 1 issue ต่อ key เปิดเมื่อพบ (ต่อเนื่องเกิน problem_grace_min สำหรับปัญหาแหล่งข้อมูล)
และปิดพร้อมคอมเมนต์เมื่อกลับมาปกติ จึงไม่ส่งอีเมลซ้ำทุกรอบ
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.join(os.path.dirname(__file__), "..")
ICT = timezone(timedelta(hours=7))
LABEL = "ec-alert"
MARK = "<!-- ec-alert:{} -->"


def _load(path, default=None):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _t(s):
    return datetime.fromisoformat(s) if s else None


def _ago(now, t):
    m = int((now - t).total_seconds() // 60)
    return f"{m // 60} ชม. {m % 60} นาที" if m >= 60 else f"{m} นาที"


def checks(mode, now, ops, latest, state):
    """คืน dict key → (มีปัญหา?, หัวข้อ, รายละเอียด, ต้องรอ grace?) เฉพาะ key ที่โหมดนี้รับผิดชอบ"""
    out = {}
    fmt = "%d/%m %H:%M"

    # --- ระบบหยุดเก็บข้อมูลทั้งหมด (ตรวจจาก watchdog เท่านั้น; รอบ collect แปลว่าระบบยังทำงาน) ---
    gen = _t((latest or {}).get("generated"))
    if mode == "watchdog":
        bad = gen is None or now - gen > timedelta(minutes=ops["data_max_age_min"])
        out["collector-stalled"] = (bad, "ระบบหยุดเก็บข้อมูล",
            f"ข้อมูลล่าสุดสร้างเมื่อ {gen.astimezone(ICT).strftime(fmt) if gen else '–'} ({_ago(now, gen) if gen else 'ไม่ทราบ'}ที่แล้ว) "
            f"เกินเกณฑ์ {ops['data_max_age_min']} นาที\n\n"
            "ตรวจ: แท็บ Actions ของ repo ว่า workflow `collect` รันล้มหรือไม่ และหน้า cron-job.org ว่ายังเรียกอยู่หรือไม่ "
            "แหล่งข้อมูลให้แค่ค่าล่าสุด ช่วงที่ไม่ได้เก็บจะหายถาวร", False)
    else:
        out["collector-stalled"] = (False, "", "", False)

    # --- ตัวตั้งเวลาหลัก cron-job.org (รอบที่มาจาก workflow_dispatch) ---
    ld = _t(state.get("last_dispatch"))
    if ld is not None:
        bad = now - ld > timedelta(minutes=ops["primary_max_gap_min"])
        out["primary-scheduler"] = (bad, "cron-job.org หยุดเรียกรอบเก็บข้อมูล",
            f"รอบล่าสุดที่ cron-job.org สั่งรันคือ {ld.astimezone(ICT).strftime(fmt)} ({_ago(now, ld)}ที่แล้ว)\n\n"
            "ตอนนี้เหลือแค่ตัวสำรองของ GitHub ซึ่งรันห่างราว 2.5–3 ชม. ข้อมูลระหว่างนั้นจะหาย\n"
            "ตรวจที่ cron-job.org: งานถูกปิดหรือไม่ / ประวัติการเรียกได้ 401-403 (token หมดอายุหรือถูกเพิกถอน) หรือไม่", False)

    # --- token ใกล้หมดอายุ ---
    exp = datetime.fromisoformat(ops["token_expires"]).replace(tzinfo=ICT)
    days = (exp - now).days
    out["token-expiry"] = (days <= ops["token_warn_days"], f"token ของ cron-job.org จะหมดอายุใน {max(days, 0)} วัน",
        f"token หมดอายุ {exp.strftime('%d/%m/%Y')}\n\n"
        "1. GitHub → Settings → Developer settings → Fine-grained tokens → Regenerate (สิทธิ์ Actions: Read and write เฉพาะ repo นี้)\n"
        "2. ใส่ token ใหม่ใน header Authorization ของงานใน cron-job.org แล้วกดทดสอบ (ต้องได้ 204)\n"
        "3. แก้ `token_expires` ใน config/ops.json เป็นวันหมดอายุใหม่ — issue นี้จะปิดเองในรอบถัดไป", False)

    if mode != "collect" or not latest:
        return out

    # --- แหล่งข้อมูล (เฉพาะรอบ collect ซึ่งมีสถานะสด) ---
    st = latest.get("status", {})
    names = {"twqms": "TWQMS (น้ำประปา)", "rwc": "rwc (น้ำดิบ/แม่น้ำ)", "rid": "กรมชลประทาน (C.13/C.35)", "tide": "Open-Meteo (น้ำขึ้นน้ำลง)"}
    for k, nm in names.items():
        s = st.get(k, {})
        out[f"source-{k}"] = (not s.get("ok", False), f"ดึงข้อมูล {nm} ไม่สำเร็จ",
            f"ข้อผิดพลาดล่าสุด: `{s.get('error', '–')}`\n\nระบบใช้ค่าล่าสุดที่มีแทนไปก่อน ถ้าแหล่งเปลี่ยนรูปแบบ API ต้องแก้ collector/sources.py", True)

    tw = st.get("twqms", {})
    newest = _t(tw.get("newest"))
    if tw.get("ok"):
        few = tw.get("n", 0) < ops["twqms_min_stations"]
        old = newest is not None and now - newest > timedelta(minutes=ops["twqms_max_age_min"])
        out["twqms-coverage"] = (few or old, "TWQMS ส่งข้อมูลไม่ครบหรือไม่อัปเดต",
            f"ได้ {tw.get('n', 0)} สถานี (เกณฑ์ ≥ {ops['twqms_min_stations']}), ค่าใหม่สุด "
            f"{newest.astimezone(ICT).strftime(fmt) if newest else '–'} ({_ago(now, newest) if newest else '–'}ที่แล้ว)", True)

    sam = (latest.get("raw") or {}).get("samlae") or {}
    st_t = _t(sam.get("t"))
    old = st_t is None or now - st_t > timedelta(minutes=ops["samlae_max_age_min"])
    out["samlae"] = (old or bool(sam.get("qc")), "ข้อมูลน้ำดิบสำแลใช้ไม่ได้",
        f"ค่าล่าสุด {sam.get('cond', '–')} µS/cm เมื่อ {st_t.astimezone(ICT).strftime(fmt) if st_t else '–'}"
        f"{' · ไม่ผ่าน QC (' + sam['qc'] + ')' if sam.get('qc') else ''}\n\n"
        "สำแลเป็นจุดเดียวที่ทำให้คาดการณ์ได้ไกล 17–48 ชม. ระหว่างนี้คาดการณ์ระยะไกลจะสั้นลงหรือว่าง", True)
    return out


class GitHub:
    def __init__(self, repo, token):
        self.base = f"https://api.github.com/repos/{repo}"
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def call(self, method, path, **kw):
        r = self.s.request(method, self.base + path, timeout=20, **kw)
        if r.status_code >= 400 and not (method == "POST" and path == "/labels" and r.status_code == 422):
            r.raise_for_status()
        return r.json() if r.content else None

    def open_alerts(self):
        issues = self.call("GET", "/issues", params={"labels": LABEL, "state": "open", "per_page": 100})
        out = {}
        for i in issues:
            for line in (i.get("body") or "").splitlines():
                if line.startswith("<!-- ec-alert:"):
                    out[line.split(":", 1)[1].split(" ")[0]] = i["number"]
        return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "collect"
    dry = "--dry-run" in sys.argv
    now = datetime.now(ICT).replace(microsecond=0)
    ops = _load("config/ops.json")
    latest = _load("docs/data/latest.json")
    state = _load("data/state.json", {"last": {}})
    res = checks(mode, now, ops, latest, state)

    # ปัญหาแหล่งข้อมูลต้องเป็นต่อเนื่องเกิน grace ก่อนแจ้ง (กันแจ้งจากการล่มชั่วคราวรอบเดียว)
    seen = state.setdefault("health", {})
    active = {}
    for key, (bad, title, body, grace) in res.items():
        if not bad:
            seen.pop(key, None)
            active[key] = False
            continue
        first = _t(seen.setdefault(key, now.isoformat()))
        active[key] = (not grace) or now - first >= timedelta(minutes=ops["problem_grace_min"])
    if mode == "collect":   # watchdog ไม่ commit จึงไม่บันทึก state
        with open(os.path.join(ROOT, "data", "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)

    for key, on in active.items():
        print(f"{'PROBLEM' if on else 'ok     '} {key}" + (f" — {res[key][1]}" if res[key][0] else ""))
    if dry:
        return

    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("ไม่มี GITHUB_TOKEN/GITHUB_REPOSITORY — ข้ามการเปิด issue")
        return
    gh = GitHub(repo, token)
    gh.call("POST", "/labels", json={"name": LABEL, "color": "d93f0b", "description": "แจ้งเตือนอัตโนมัติจาก health.py"})
    opened = gh.open_alerts()
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repo.split("/")[0]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    stamp = now.strftime("%d/%m/%Y %H:%M")
    for key, on in active.items():
        _, title, body, _ = res[key]
        if on and key not in opened:
            n = gh.call("POST", "/issues", json={
                "title": f"⚠️ {title}", "labels": [LABEL], "assignees": [owner],
                "body": f"{MARK.format(key)}\nพบเมื่อ {stamp} น.\n\n{body}\n\n— แจ้งอัตโนมัติจาก [รอบตรวจนี้]({run_url}) · issue จะปิดเองเมื่อกลับมาปกติ"})["number"]
            print(f"เปิด issue #{n} ({key})")
        elif not on and key in opened and not res[key][0]:
            gh.call("POST", f"/issues/{opened[key]}/comments", json={"body": f"✅ กลับมาปกติแล้ว เมื่อ {stamp} น."})
            gh.call("PATCH", f"/issues/{opened[key]}", json={"state": "closed", "state_reason": "completed"})
            print(f"ปิด issue #{opened[key]} ({key})")


if __name__ == "__main__":
    main()

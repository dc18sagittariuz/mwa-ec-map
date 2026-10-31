"""ตรวจคุณภาพข้อมูลอนุกรมเวลา ตามแนว QARTOD (IOOS, คู่มือ QC ข้อมูลคุณภาพน้ำแบบเรียลไทม์)

ธงผลตรวจ (ตามรหัส QARTOD):
  1 = ผ่าน   2 = ไม่ได้ตรวจ   3 = น่าสงสัย   4 = ไม่ผ่าน
โมเดลใช้เฉพาะค่าที่ธง < 3 ส่วนไฟล์ประวัติเก็บค่าดิบไว้ตามเดิม (ตรวจซ้ำได้เสมอ)

การทดสอบ
  gross_range  ค่าเกินช่วงที่เซนเซอร์/น้ำชนิดนั้นเป็นไปได้ → 4
  spike        จุดเดียว (หรือกลุ่มสั้น ≤2 ชม.) โดดจากค่าก่อนและหลัง ขณะที่ค่าก่อน/หลังใกล้กันเอง → 4
               (น้ำขึ้นน้ำลงเปลี่ยนแบบต่อเนื่อง ไม่ใช่จุดเดียว จึงไม่โดนตัด)
  rate_last    จุดล่าสุดซึ่งยังไม่มีจุดถัดไปให้ตรวจ spike: ต่างจากค่ากลาง 3 ชม. ก่อนหน้ามาก → 3
               (ถ้าเป็นการเปลี่ยนจริง รอบถัดไปจะผ่าน spike test และกลับมาใช้ได้ ช้าไปแค่ 1 รอบ)
  flat_high    ค่าเดิมเป๊ะติดกัน ≥ 24 ชม. ที่ระดับสูง (เช่น S027 ค้าง 2000) → 3
               ช่วงน้ำเค็มค่าจะแกว่งตามน้ำขึ้นน้ำลงเสมอ ค่าที่นิ่งสนิทระดับสูงจึงน่าจะเป็นเซนเซอร์ค้าง
               (ค่านิ่งในระดับปกติเกิดได้จริงเพราะรายงานเป็นจำนวนเต็ม — ตรวจแยกใน model.py โดยดูว่าต้นทางขยับหรือไม่)
"""
from datetime import timedelta
from statistics import median

PASS, NOT_EVAL, SUSPECT, FAIL = 1, 2, 3, 4

# พารามิเตอร์ต่อชนิดข้อมูล (µS/cm)
CFG = {
    # น้ำประปา: ปกติ ~200–300, ช่วงน้ำเค็ม 2567 สูงสุด ~2,400 ที่ทางออกโรงผลิต
    "tap": dict(lo=100, hi=20000, spike_abs=120, spike_rel=0.35, spike_pts=4, spike_h=2.5,
                last_abs=300, last_rel=0.6, flat_h=24, flat_min=1000),
    # น้ำดิบ (สำแล/ไซฟอน/แม่น้ำ): น้ำจืด ~150–400, ปี 2567 สูงสุด ~3,000; ปากแม่น้ำอาจถึงระดับน้ำทะเล
    "raw": dict(lo=50, hi=60000, spike_abs=150, spike_rel=0.5, spike_pts=2, spike_h=1.0,
                last_abs=400, last_rel=0.6, flat_h=24, flat_min=1000),
}
NEIGHBOR_GAP_H = 2.0   # เพื่อนบ้านต้องห่างไม่เกินนี้จึงใช้ตรวจ spike


def check(pts, kind="tap"):
    """pts = [(t, v)] เรียงหรือไม่เรียงก็ได้ (v อาจเป็น None)
    คืน [(t, v, flag, test)] เรียงตามเวลา — test = ชื่อการทดสอบที่ไม่ผ่าน หรือ None"""
    c = CFG[kind]
    p = sorted((t, v) for t, v in pts if v is not None)
    flags = [PASS] * len(p)
    why = [None] * len(p)

    def mark(i, f, test):
        if f > flags[i]:
            flags[i], why[i] = f, test

    # 1) gross range
    for i, (_, v) in enumerate(p):
        if not (c["lo"] <= v <= c["hi"]):
            mark(i, FAIL, "gross_range")
    ok = [i for i in range(len(p)) if flags[i] < FAIL]

    # 2) spike — จุดเดียว หรือกลุ่มสั้น ๆ ไม่เกิน spike_pts จุด / spike_h ชม. (เช่น S006 ค้าง 1,567 อยู่ ~1 ชม.)
    #    ที่โดดจากค่าก่อนและหลังซึ่งใกล้กันเอง; ใช้เพื่อนบ้านที่ผ่าน gross range แล้ว
    gap = timedelta(hours=NEIGHBOR_GAP_H)
    for n in range(1, c["spike_pts"] + 1):
        for s0 in range(1, len(ok) - n):
            a, seg, b = ok[s0 - 1], ok[s0:s0 + n], ok[s0 + n]
            (ta, va), (tb, vb) = p[a], p[b]
            t0, t1 = p[seg[0]][0], p[seg[-1]][0]
            if t0 - ta > gap or tb - t1 > gap or t1 - t0 > timedelta(hours=c["spike_h"]):
                continue
            nb = (va + vb) / 2
            thr = max(c["spike_abs"], c["spike_rel"] * nb)
            devs = [p[i][1] - nb for i in seg]
            # ทุกจุดในกลุ่มต้องโดดไปทางเดียวกันเกินเกณฑ์ และค่าก่อน/หลังต้องใกล้กันเอง
            if all(d > thr for d in devs) or all(d < -thr for d in devs):
                if abs(va - vb) < min(abs(d) for d in devs) / 2:
                    for i in seg:
                        mark(i, FAIL, "spike")

    # 3) จุดล่าสุด (ยังตรวจ spike ไม่ได้)
    ok = [i for i in range(len(p)) if flags[i] < SUSPECT]
    if len(ok) >= 4:
        last = ok[-1]
        tl, vl = p[last]
        prev = [p[j][1] for j in ok[:-1] if tl - timedelta(hours=3) <= p[j][0] < tl]
        if len(prev) >= 3:
            m = median(prev)
            if abs(vl - m) > max(c["last_abs"], c["last_rel"] * m):
                mark(last, SUSPECT, "rate_last")

    # 4) flat line ระดับสูง
    run_start = 0
    for i in range(1, len(p) + 1):
        if i == len(p) or p[i][1] != p[run_start][1]:
            if (p[i - 1][0] - p[run_start][0] >= timedelta(hours=c["flat_h"])
                    and p[run_start][1] >= c["flat_min"]):
                for j in range(run_start, i):
                    mark(j, SUSPECT, "flat_high")
            run_start = i
    return [(t, v, flags[i], why[i]) for i, (t, v) in enumerate(p)]


def clean(pts, kind="tap"):
    """คืนเฉพาะจุดที่ใช้ได้ [(t, v)] และสรุป {ชื่อการทดสอบ: จำนวนจุดที่ตัด}"""
    out, bad = [], {}
    for t, v, f, test in check(pts, kind):
        if f < SUSPECT:
            out.append((t, v))
        else:
            bad[test] = bad.get(test, 0) + 1
    return out, bad


def is_flat(values, min_n=12):
    """ค่าเดิมเป๊ะทั้งชุด (ใช้ตรวจเซนเซอร์ค้างเทียบกับต้นทางใน model.py)"""
    return len(values) >= min_n and max(values) == min(values)

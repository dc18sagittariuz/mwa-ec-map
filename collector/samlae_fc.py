"""พยากรณ์ EC น้ำดิบที่จุดสูบสำแลล่วงหน้า 1–48 ชม.

ทำไมต้องมี: น้ำจากสำแลถึงทางออกโรงผลิตบางเขน ~17 ชม. ระบบเดิมจึงรู้ล่วงหน้าได้แค่ ~17 ชม. (ไกลกว่านั้น = "ยังไม่ทราบ")
ถ้าคาดค่าที่สำแลได้ 31 ชม. การคาดการณ์ที่บางเขนก็ไปได้ถึง 48 ชม.

ตัวขับเคลื่อนความเค็มที่สำแล (จากข้อมูล มี.ค.–พ.ค. 2567):
  - น้ำขึ้นน้ำลงที่ปากแม่น้ำ: EC สำแลแกว่งตามระดับน้ำทะเลโดยช้ากว่า ~7 ชม.
  - รอบน้ำเกิด-น้ำตาย: ค่าสูงสุดรายวันตามช่วงกว้างของน้ำขึ้นน้ำลงโดยช้ากว่า 2–3 วัน (เกลือสะสม)
  - ระดับน้ำจืดที่ไหลลงมา: สะท้อนอยู่ในประวัติ EC ล่าสุดของสำแลเอง

วิธี (พารามิเตอร์ใน config/samlae_model.json, สคริปต์ fit อยู่นอก repo เพราะใช้ข้อมูลภายใน):
  z = log(EC − น้ำจืดพื้นฐาน)    น้ำจืดพื้นฐาน = ค่าต่ำสุด 7 วัน × 0.95 (ปรับตามฤดูเอง)
  model(h)  = พื้นฐาน + exp(b + Σ coef × feature)       ridge แยกทุก 3 ชม.
  analog(h) = ค่าวัดที่ช่วงน้ำเดียวกันของรอบก่อน (25 ชม. × k ก่อนเวลาเป้าหมาย)
  ค่าคาด    = (model + analog) / 2      — ทดสอบแล้วจับค่าสูงได้เท่า analog แต่คลาดน้อยกว่า
ถ้าไม่มีข้อมูลน้ำขึ้นน้ำลง ใช้ analog อย่างเดียว
"""
import json
import math
import os
from datetime import timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
_H = timedelta(hours=1)


def load_params():
    with open(os.path.join(ROOT, "config", "samlae_model.json"), encoding="utf-8") as f:
        p = json.load(f)
    p["horizons"] = {int(k): v for k, v in p["horizons"].items()}
    return p


class _Interp:
    """ค่าที่เวลา t แบบเส้นตรงระหว่างจุด (ไม่ข้ามช่องว่างเกิน max_gap ชม.)"""

    def __init__(self, pts, max_gap=4.0):
        self.p = sorted((t, v) for t, v in pts if v is not None)
        self.g = max_gap * 3600

    def __call__(self, t):
        p = self.p
        if not p or t < p[0][0] or t > p[-1][0]:
            return None
        lo, hi = 0, len(p) - 1
        while lo < hi:
            m = (lo + hi) // 2
            if p[m][0] < t:
                lo = m + 1
            else:
                hi = m
        if p[lo][0] == t:
            return p[lo][1]
        a, b = p[lo - 1], p[lo]
        gap = (b[0] - a[0]).total_seconds()
        if gap > self.g:
            return None
        return a[1] + (b[1] - a[1]) * (t - a[0]).total_seconds() / gap


def _window(f, t, back, fwd=0):
    """ค่า f ทุกชั่วโมงในช่วง t−back … t+fwd (เฉพาะที่มีค่า)"""
    vs = [f(t + k * _H) for k in range(-back, fwd + 1)]
    return [v for v in vs if v is not None]


def forecast(samlae_pts, tide_pts, params=None, hmax=48):
    """samlae_pts = [(t, EC)] ผ่าน QC แล้ว, tide_pts = [(t, ระดับน้ำทะเล ม.)] ทั้งอดีตและพยากรณ์
    คืน (T0, [(t, EC คาด, วิธี)]) ทุก 1 ชม. หลังค่าวัดล่าสุด T0 — วิธี = "model" หรือ "analog" """
    P = params or load_params()
    c = _Interp(samlae_pts)
    if not c.p:
        return None, []
    T0 = c.p[-1][0]
    past = _window(c, T0, 167)
    if len(past) < 48:
        return T0, []
    base = min(past) * P.get("base_factor", 0.95)

    def L(x):
        return math.log(max(x - base, 5.0))

    w24, w25, w48 = _window(c, T0, 23), _window(c, T0, 24), [v for v in _window(c, T0 - 24 * _H, 23)]
    if len(w24) < 18 or len(w25) < 18 or len(w48) < 18:
        return T0, []
    lc, lmax24, lmean25 = L(c(T0)), L(max(w24)), L(sum(w25) / len(w25))
    trend = lmax24 - L(max(w48))

    sl = _Interp(tide_pts, max_gap=3.0) if tide_pts else None
    cache = {}

    def rng(t):
        k = ("r", t)
        if k not in cache:
            w = _window(sl, t, 12, 12)
            cache[k] = max(w) - min(w) if len(w) >= 20 else None
        return cache[k]

    def rng48(t):
        vs = [rng(t - k * _H) for k in range(48)]
        vs = [v for v in vs if v is not None]
        return sum(vs) / len(vs) if len(vs) >= 40 else None

    def hp(t):
        w, v = _window(sl, t, 12, 12), sl(t)
        return v - sum(w) / len(w) if v is not None and len(w) >= 20 else None

    lag_tide = P.get("tide_to_samlae_h", 7)
    rng_past = rng48(T0) if sl else None
    hs = sorted(P["horizons"])
    pred = {0: (c(T0), "obs")}
    for h in hs:
        k = math.ceil(h / 25)
        an = c(T0 + (h - 25 * k) * _H)
        m = None
        if sl and rng_past is not None:
            tgt = T0 + h * _H
            f = {"lc": lc, "lmax24": lmax24, "lmean25": lmean25, "trend": trend,
                 "lan": L(an) if an is not None else None, "rng_past48": rng_past,
                 "rng_fut": rng(tgt), "rng48_fut": rng48(tgt), "hp_tgt": hp(tgt - lag_tide * _H)}
            if f["hp_tgt"] is not None:
                f["hp_tgt_x"] = f["hp_tgt"] * (lmax24 - lmean25)
            q = P["horizons"][h]
            if all(f.get(n) is not None for n in q["coef"]):
                z = q["b"] + sum(cf * f[n] for n, cf in q["coef"].items())
                m = base + math.exp(min(z, 12.0))
        if m is not None and an is not None:
            pred[h] = ((m + an) / 2, "model")
        elif an is not None:
            pred[h] = (an, "analog")
    # เติมทุก 1 ชม. แบบเส้นตรงระหว่างช่วงที่คำนวณ (0, 3, 6, …)
    out = []
    keys = sorted(pred)
    for a, b in zip(keys, keys[1:]):
        for hh in range(a + 1, b + 1):
            if hh > hmax:
                break
            w = (hh - a) / (b - a)
            v = pred[a][0] + (pred[b][0] - pred[a][0]) * w
            out.append((T0 + hh * _H, v, pred[b][1]))
    return T0, out

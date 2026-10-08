# -*- coding: utf-8 -*-
"""
管弦乐配乐引擎 (推荐默认)

设计目标: 不刺耳, 不单调
  不刺耳: 全部音色基于谐波堆叠而非宽带噪声, 母带压高频补温暖区
  不单调: 十段式配器表, 每段换乐器组合与音区, 旋律用动机加变奏, 力度有起落弧线

  python orchestra.py <时长秒> <BPM> <输出文件名> <切点逗号分隔>
  python orchestra.py 108 100 score_orch.wav "7.2,16.8,26.4,36,50.4,64.8,79.2,91.2,103.2"
"""
import os
import sys

import numpy as np

import dsp
from dsp import SR, add, lp_fft, hp_fft, bp_fft, sat, hz, reverb, make_ir, bus_compress, warm_master, write_wav

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 108.0
BPM = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
OUTNAME = sys.argv[3] if len(sys.argv) > 3 else "score_orch.wav"
BEAT = 60.0 / BPM
BAR = 4 * BEAT
N = int(round(SR * DUR))
T = np.arange(N) / SR
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[5] if len(sys.argv) > 5 else "audio"
os.makedirs(OUT, exist_ok=True)

if len(sys.argv) > 4:
    CUTS = [float(x) for x in sys.argv[4].split(",")]
else:
    CUTS = [round(k * BAR, 4) for k in (3, 7, 11, 15, 21, 27, 33, 38, 43)]

rng = np.random.default_rng(20261009)

# ----------------------------------------------------------------- 调性
KEY = 57
CHORDS = [
    (57, [57, 60, 64], 0),
    (53, [53, 57, 60], 1),
    (48, [48, 52, 55], 2),
    (55, [55, 59, 62], 3),
]
SCALE = [KEY + s for s in (0, 2, 3, 5, 7, 8, 10, 12, 14, 15, 17, 19, 20, 22)]


def deg(i):
    """音阶级数转 MIDI 号, 支持越界上下行"""
    while i < 0:
        i += len(SCALE)
    return SCALE[i % len(SCALE)] + 12 * (i // len(SCALE))


# ----------------------------------------------------------------- 音色
def strings(f, dur, amp=1.0, vib=5.2, cutoff=2600, atk=0.30, detune=0.0016):
    """弦乐群: 五路失谐锯齿 + 颤音 + 慢起, 是整套配器的底"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-detune, -detune * 0.4, 0.0, detune * 0.5, detune):
        fd = f * (1 + d) * (1 + 0.0025 * np.sin(2 * np.pi * vib * tt + rng.random() * 6.283))
        ph = 2 * np.pi * np.cumsum(fd) / SR
        out += 2 * ((ph / (2 * np.pi)) % 1.0) - 1.0
    out /= 5.0
    out = lp_fft(out, cutoff, 2)
    env = (1 - np.exp(-tt / atk)) * np.exp(-np.maximum(tt - (dur - 0.5), 0) / 0.45)
    return out * env * amp


def horn(f, dur, amp=1.0, atk=0.10):
    """圆号: 锯齿加共振峰与轻微过载, 用于对位长音"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    saw = 2 * ((f * tt) % 1.0) - 1
    x = sat(saw * 1.2, 1.2)
    x = lp_fft(x, 1400, 2) + 0.4 * bp_fft(x, 900, 2200)
    env = (1 - np.exp(-tt / atk)) * np.exp(-np.maximum(tt - (dur - 0.35), 0) / 0.35)
    return x * env * amp


def clarinet(f, dur, amp=1.0):
    """单簧管: 只堆奇次谐波, 音色空而暖"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.zeros(n)
    for k in range(1, 9, 2):
        if f * k > 8000:
            break
        x += np.sin(2 * np.pi * f * k * tt) / k
    x += bp_fft(rng.standard_normal(n), 2000, 5500) * 0.015
    env = (1 - np.exp(-tt / 0.07)) * np.exp(-np.maximum(tt - (dur - 0.3), 0) / 0.3)
    return x * env * amp * 0.75


def flute(f, dur, amp=1.0):
    """长笛: 正弦加少量二次谐波与气声"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) + 0.18 * np.sin(2 * np.pi * 2 * f * tt)
    x += bp_fft(rng.standard_normal(n), 1500, 4500) * 0.05
    env = (1 - np.exp(-tt / 0.10)) * np.exp(-np.maximum(tt - (dur - 0.4), 0) / 0.4)
    return x * env * amp * 0.8


def harp(f, dur=0.9, amp=1.0):
    """竖琴: 明亮拨弦. 衰减不能长, 超过 1 秒会把琶音糊成声墙并掩掉拍点"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.42)
    x += 0.50 * np.sin(2 * np.pi * 2 * f * tt) * np.exp(-tt / 0.20)
    x += 0.25 * np.sin(2 * np.pi * 3 * f * tt) * np.exp(-tt / 0.12)
    x += 0.12 * np.sin(2 * np.pi * 4.02 * f * tt) * np.exp(-tt / 0.07)
    env = 1 - np.exp(-tt / 0.003)
    return x * env * amp / 1.9


def pizz(f, dur=0.35, amp=1.0):
    """拨弦低音: 短促有颗粒感, 是管弦乐里最可靠的拍点来源"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * 2 * f * tt) + 0.25 * np.sin(2 * np.pi * 3 * f * tt)
    x = bp_fft(x, f * 0.8, 3200)
    env = (1 - np.exp(-tt / 0.002)) * np.exp(-tt / 0.12)
    return x * env * amp / 1.8


def stacc(f, dur=0.22, amp=1.0):
    """弦乐断奏: 短弓, 用来做节奏性固定音型, 让连奏的底子有脉冲"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.zeros(n)
    for d in (-0.0012, 0.0, 0.0012):
        fd = f * (1 + d)
        saw = 2 * ((fd * tt) % 1.0) - 1.0
        x += saw
    x /= 3.0
    x = lp_fft(x, 3000, 2)
    env = (1 - np.exp(-tt / 0.008)) * np.exp(-tt / 0.085)
    return x * env * amp / 1.4


def cymbal_swell(dur=2.0, amp=0.30):
    """滚镲渐强: 段落切换前铺一层空气感, 电平必须压低否则刺耳"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    nz = rng.standard_normal(n)
    out = np.zeros(n)
    steps = 16
    for i in range(steps):
        a, b = i / steps, (i + 1) / steps
        i0, i1 = int(a * n), int(b * n)
        if i1 <= i0:
            continue
        f0 = 1200 + 4200 * a
        out[i0:i1] = bp_fft(nz[i0:i1], f0 * 0.6, min(f0 * 1.5, 9000), 3)
    return out * (tt / dur) ** 2.2 * amp / max(np.max(np.abs(out)), 1e-9)


def timpani(f, dur=1.7, amp=1.0):
    """定音鼓: 低频加五度泛音与噪声击打, 只落在段落头"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    fd = f * (1 + 0.03 * np.exp(-tt / 0.05))
    ph = 2 * np.pi * np.cumsum(fd) / SR
    x = np.sin(ph) * np.exp(-tt / 0.55)
    x += 0.30 * np.sin(2 * np.pi * 1.5 * f * tt) * np.exp(-tt / 0.30)
    x += bp_fft(rng.standard_normal(n), 180, 1400) * np.exp(-tt / 0.03) * 0.22
    return sat(x * 1.1, 1.1) * amp / 1.4


def choir(f, dur, amp=1.0):
    """人声: 三共振峰, 只在全奏段铺在最底层"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-0.004, 0.0, 0.004):
        out += np.sin(2 * np.pi * f * (1 + d) * tt + rng.random() * 6.283)
    out /= 3.0
    form = lp_fft(out, 900, 2) + 0.6 * bp_fft(out, 900, 1400) + 0.3 * bp_fft(out, 2400, 3200)
    env = (1 - np.exp(-tt / 0.5)) * np.exp(-np.maximum(tt - (dur - 0.6), 0) / 0.6)
    return form * env * amp


# ----------------------------------------------------------------- 旋律动机
# (小节内偏移, 拍, 音阶级数, 时值拍数)
MOTIF_A = [(0, 0.0, 7, 1.0), (0, 1.0, 5, 0.5), (0, 1.5, 4, 0.5), (0, 2.0, 5, 2.0),
           (1, 0.0, 4, 1.0), (1, 1.0, 2, 1.0), (1, 2.0, 0, 2.0),
           (2, 0.0, 2, 1.0), (2, 1.0, 4, 0.5), (2, 1.5, 5, 0.5), (2, 2.0, 7, 2.0),
           (3, 0.0, 9, 1.0), (3, 1.0, 7, 1.0), (3, 2.0, 5, 2.0)]
MOTIF_B = [(0, 0.0, 9, 1.5), (0, 1.5, 7, 0.5), (0, 2.0, 9, 1.0), (0, 3.0, 11, 1.0),
           (1, 0.0, 12, 2.0), (1, 2.0, 9, 2.0),
           (2, 0.0, 7, 1.0), (2, 1.0, 9, 1.0), (2, 2.0, 7, 1.0), (2, 3.0, 5, 1.0),
           (3, 0.0, 4, 2.0), (3, 2.0, 2, 2.0)]


def phrase_motif(kind, shift):
    src = MOTIF_B if kind == "B" else MOTIF_A
    return [(b, beat, d + shift, dur) for (b, beat, d, dur) in src]


# 每 4 小节一个乐句, 循环取用, 避免整片重复同一句
PHRASE_PLAN = ["A", "A", "B", "A", "A", "B", "A", "A", "B", "A", "A"]
PHRASE_SHIFT = [0, 0, 0, -1, 0, 0, 1, 0, 0, -1, 0]
ARP = [(0, 1, 2, 3), (0, 1, 2, 3, 2, 1), (0, 2, 1, 3), (3, 2, 1, 0)]

# ----------------------------------------------------------------- 配器表
# 每项: 起小节, 止小节, 弦乐, 竖琴, 主奏, 对位, 拨弦, 定音鼓, 人声, 音区偏移, 力度
SECTIONS = [
    (0, 3, 1.0, 1.0, None, None, 0.0, 0.0, 0.0, 0, 0.62),
    (3, 7, 1.0, 1.0, "flute", None, 0.8, 0.0, 0.0, 0, 0.74),
    (7, 11, 1.0, 0.9, "clarinet", "flute", 0.9, 0.35, 0.0, 0, 0.82),
    (11, 15, 1.0, 1.0, "horn", None, 0.5, 0.0, 0.35, 0, 0.70),
    (15, 21, 1.0, 1.0, "clarinet", "horn", 1.0, 0.7, 0.0, 0, 0.92),
    (21, 27, 1.0, 1.0, "clarinet", "horn", 1.0, 0.7, 0.55, 12, 1.00),
    (27, 33, 1.0, 1.0, "flute", None, 0.6, 0.0, 0.0, 0, 0.72),
    (33, 38, 1.0, 1.0, "clarinet", "flute", 1.0, 0.5, 0.30, 0, 0.88),
    (38, 43, 1.0, 1.0, "clarinet", "horn", 1.0, 0.8, 0.65, 12, 1.00),
    (43, 999, 1.0, 1.0, "horn", None, 0.0, 0.6, 0.7, 0, 0.66),
]


def section_of(bar_i):
    for s in SECTIONS:
        if s[0] <= bar_i < s[1]:
            return s
    return SECTIONS[-1]


def main():
    strings_b = np.zeros(N)
    harp_b = np.zeros(N)
    lead_b = np.zeros(N)
    cnt_b = np.zeros(N)
    low_b = np.zeros(N)
    perc_b = np.zeros(N)
    air_b = np.zeros(N)

    nbars = int(DUR // BAR)
    for bar_i in range(nbars):
        t0 = bar_i * BAR
        root, tones, ci = CHORDS[bar_i % 4]
        (_, _, s_str, s_harp, lead, cnt, s_pizz, s_timp, s_choir, oct_shift, dyn) = section_of(bar_i)

        if s_str > 0:
            for k, semi in enumerate(tones):
                f = hz(semi - 12 + (12 if k == 0 else 0))
                add(strings_b, strings(f, BAR + 0.8, 0.16 * s_str * dyn), t0)
            add(strings_b, strings(hz(tones[0] + 12), BAR + 0.8, 0.10 * s_str * dyn), t0)

        if s_harp > 0:
            pat = ARP[(bar_i // 4) % len(ARP)]
            for k in range(8):
                idx = pat[k % len(pat)]
                semi = tones[idx % len(tones)] + (12 if idx >= len(tones) else 0) + (12 if k >= 4 else 0)
                amp = 0.20 if k % 2 == 0 else 0.06
                add(harp_b, harp(hz(semi), 0.9, amp * s_harp * dyn), t0 + k * BEAT * 0.5)

        if lead:
            ph = (bar_i // 4) % len(PHRASE_PLAN)
            kind = PHRASE_PLAN[ph]
            shift = PHRASE_SHIFT[ph]
            for (bo, beat, d, dur) in phrase_motif(kind, shift):
                if bo != bar_i % 4:
                    continue
                f = hz(deg(d) + oct_shift)
                voice = {"flute": flute, "clarinet": clarinet, "horn": horn}[lead]
                add(lead_b, voice(f, dur * BEAT + 0.35, 0.22 * dyn), t0 + beat * BEAT)

        if cnt and bar_i % 2 == 0:
            # 对位必须稀疏. 每小节都奏长音会变成连续声墙, 把拍点整个掩掉
            for k, semi in enumerate(tones[1:]):
                voice = {"flute": flute, "horn": horn, "clarinet": clarinet}[cnt]
                f = hz(semi - 12 + (12 if k else 0))
                add(cnt_b, voice(f, 1.6 * BEAT, 0.09 * dyn), t0 + k * 2 * BEAT)

        if s_pizz > 0:
            # 四个拍点都落拨弦, 1 与 3 拍加重, 这是全片节奏的地基
            for k, beat in enumerate((0.0, 1.0, 2.0, 3.0)):
                amp = 0.95 if k in (0, 2) else 0.56
                # 低音不要沉到 A1, 小喇叭听不到拍点. 拨弦落在 110 到 220Hz 区间最稳
                semi = root - 12 if k in (0, 2) else root
                add(low_b, pizz(hz(semi), 0.40, amp * s_pizz * dyn), t0 + beat * BEAT)
            # 弦乐断奏固定音型铺八分音符, 拍上重音
            for k in range(8):
                semi = tones[0] if k % 2 == 0 else tones[2]
                amp = 0.55 if k % 2 == 0 else 0.24
                add(low_b, stacc(hz(semi - 12), 0.22, amp * s_pizz * dyn), t0 + k * BEAT * 0.5)

        if s_timp > 0:
            add(perc_b, timpani(hz(root - 12), 1.7, 0.70 * s_timp * dyn), t0)

        if s_choir > 0:
            for semi in tones:
                add(air_b, choir(hz(semi), BAR + 1.6, 0.09 * s_choir * dyn), t0)

    # 滚镲渐强: 每个切点前铺 2 秒, 让转场有呼吸
    for cu in CUTS:
        if cu > 2.0:
            add(perc_b, cymbal_swell(2.0, 0.20), cu - 2.0)

    # 力度弧线: 每个切点前 2.4 秒渐强, 切点后回落, 制造呼吸
    dyn_env = np.ones(N)
    for cu in CUTS:
        i0 = max(0, int((cu - 2.4) * SR))
        i1 = min(N, int(cu * SR))
        if i1 > i0:
            dyn_env[i0:i1] *= np.linspace(0.86, 1.0, i1 - i0)
        i2 = min(N, i1 + int(0.9 * SR))
        if i2 > i1:
            dyn_env[i1:i2] *= np.linspace(0.88, 1.0, i2 - i1)
    for bus in (strings_b, harp_b, lead_b, cnt_b, low_b, perc_b, air_b):
        bus *= dyn_env

    # 空气层: 极低电平的宽带噪声, 模拟演奏厅的空气与弓弦摩擦, 让弦乐不闷
    air_noise = bp_fft(rng.standard_normal(N), 1800, 9000, 2) * 0.010 * dyn_env

    if os.environ.get("ORCH_DEBUG"):
        for nm, b in (("strings", strings_b), ("harp", harp_b), ("lead", lead_b),
                      ("cnt", cnt_b), ("low", low_b), ("perc", perc_b), ("air", air_b)):
            print("bus %-8s peak %.4f rms %.4f" % (nm, float(np.abs(b).max()),
                                                   float(np.sqrt((b ** 2).mean()))), flush=True)

    # 混响: 弦乐与人声多给, 打击少给, IR 必须低通
    ir = make_ir(2.4, 0.8, 2300, 3, rng)
    strings_r = reverb(strings_b, ir, 0.50)
    harp_r = reverb(harp_b, ir, 0.24)
    lead_r = reverb(lead_b, ir, 0.40)
    cnt_r = reverb(cnt_b, ir, 0.45)
    air_r = reverb(air_b, ir, 0.55)
    low_r = reverb(low_b, ir, 0.10)
    perc_r = reverb(perc_b, ir, 0.22)

    # 声场: 弦乐宽, 主奏居中偏右, 对位居左
    def spread(x, d):
        l, r = x.copy(), x.copy()
        k = int(d * SR)
        if k > 0:
            l[k:] = x[:-k]
            r[:-k] = x[k:]
        return l, r

    sl, sr = spread(strings_r, 0.014)
    hl, hr = spread(harp_r, 0.008)
    ll, lr = spread(lead_r, 0.004)
    cl, cr = spread(cnt_r, 0.009)
    al, ar = spread(air_r, 0.016)

    left = 0.55 * (sl + strings_r) + 0.5 * (hl + harp_r) + 0.85 * ll + 0.7 * cl + low_r + perc_r + 0.5 * (al + air_r) + air_noise
    right = 0.55 * (sr + strings_r) + 0.5 * (hr + harp_r) + 0.85 * lr + 0.7 * cr + low_r + perc_r + 0.5 * (ar + air_r) + air_noise

    st = np.stack([left, right])
    # 时间常数必须远大于打击瞬态, 否则压缩器会把拍点压平, 卡点全毁
    st = bus_compress(st, thr=0.22, power=0.50, tau=0.45)
    fade_in = np.clip(T / 1.0, 0, 1)
    fade_out = np.clip((DUR - T) / 2.4, 0, 1) ** 1.3
    st *= np.stack([fade_in * fade_out, fade_in * fade_out])
    st = warm_master(st, warm=0.42, cut1_amt=0.28, cut2_amt=0.22, lpf=6000, peak=0.95)

    path = os.path.join(OUT, OUTNAME)
    shape = write_wav(path, st)
    print("wrote", path, shape, "peak %.3f" % float(np.max(np.abs(st))))


if __name__ == "__main__":
    main()

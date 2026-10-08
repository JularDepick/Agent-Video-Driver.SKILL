# -*- coding: utf-8 -*-
"""
电子与键盘配乐引擎 (轻而现代)

设计目标: 轻, 暖, 不刺耳, 可卡点
  轻: 只用毛毡钢琴, pad, 正弦低音, 软边击与钟琴, 没有明亮踩镲与失真底鼓
  暖: 母带补 220 到 900Hz 温暖区, 压 3kHz 以上高频, 混响 IR 必先低通
  不刺耳: 音色全部由谐波堆叠而成, 不让宽带噪声铺满全片
  可卡点: 所有重音落在拍栅格上, 段落切点与画面切点共用同一份数据

音色取向: 毛毡钢琴拨奏, 慢起 pad, 正弦低音, 软边击, 钟琴点缀
适用场景: 需要更轻, 更现代, 更电子化的听感时用它, 管弦乐取向优先用 orchestra.py

  python scripts/music.py <时长秒> <BPM> <输出文件名> <切点逗号分隔> [输出目录]
  python scripts/music.py 108 100 score_nobel.wav "7.2,16.8,26.4,36,50.4,64.8,79.2,91.2,103.2"
  python scripts/music.py 12 100 demo.wav "7.2" temp/demo

输出目录缺省为相对当前工作目录的 audio, 目录不存在会自动建
底层 DSP 基元统一从 dsp.py 取用, 本脚本只放音色与编排
音区口径上与 dsp.hz 相差 60 个半音, 原因与修正办法见下方 HZ_OFFSET 处的说明
"""
import os
import sys

import numpy as np

import dsp
from dsp import SR, add, lp_fft, hp_fft, bp_fft, sat, reverb, make_ir, bus_compress, warm_master, write_wav

if len(sys.argv) > 1:
    DUR = float(sys.argv[1])
else:
    DUR = 108.0
if len(sys.argv) > 2:
    BPM = float(sys.argv[2])
else:
    BPM = 100.0
if len(sys.argv) > 3:
    OUTNAME = sys.argv[3]
else:
    OUTNAME = "score_nobel.wav"

BEAT = 60.0 / BPM
BAR = 4 * BEAT
N = int(round(SR * DUR))
T = np.arange(N) / SR
OUT = sys.argv[5] if len(sys.argv) > 5 else "audio"
os.makedirs(OUT, exist_ok=True)

if len(sys.argv) > 4:
    CUTS = [float(x) for x in sys.argv[4].split(",")]
else:
    CUTS = [round(k * BAR, 4) for k in (3, 7, 11, 15, 21, 27, 33, 38, 43, 45)]

rng = np.random.default_rng(20261008)

# 音区口径说明 (已知缺陷, 本轮刻意保留)
# 本模块的 hz() 以 MIDI 9 号为 440Hz 基准, dsp.hz 以 MIDI 69 号为 A4 基准, 两者相差 60 个半音
# 而下面的和弦表是按标准 MIDI 号书写的 (48 号旁边注释写的就是根音 C3)
# 于是按旧口径渲染时 pad 与 sub_bass 被推到 4186Hz 以上, 又被 900Hz 与 260Hz 低通滤掉
# 全曲实际只剩底鼓与 thump 的低频加钢琴的高频叮当, 中低频几乎是空的
# 为保持与历史产出逐样本一致, 这里用显式偏移 60 沿用旧口径
# 若要修正: 把 HZ_OFFSET 改成 0, 并重新调母带与低频配比, 低频占比与谱心都会大幅变化
HZ_OFFSET = 60


def hz(semi):
    """C4 为 0 号音的半音号转频率, 底层走 dsp.hz 加固定偏移"""
    return dsp.hz(semi + HZ_OFFSET)


# ---------------------------------------------------------------- 音色
def piano(f, dur=1.1, amp=1.0):
    """毛毡钢琴拨奏: 正弦加快速衰减的谐波, 6ms 起音"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) * 1.00
    x += 0.30 * np.sin(2 * np.pi * 2 * f * tt + 0.4) * np.exp(-tt / 0.22)
    x += 0.09 * np.sin(2 * np.pi * 3 * f * tt + 1.1) * np.exp(-tt / 0.13)
    x += 0.03 * np.sin(2 * np.pi * 4.02 * f * tt) * np.exp(-tt / 0.08)
    env = (1 - np.exp(-tt / 0.006)) * np.exp(-tt / (dur * 0.42))
    return x * env * amp / 1.55


def pad(freqs, dur, amp=0.5, cutoff=900.0):
    """慢起 pad: 每个和弦音三路失谐正弦, 低通 900Hz 保证不刺"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    a = (1 - np.exp(-tt / 0.9)) * np.exp(-np.maximum(tt - (dur - 1.6), 0) / 1.1)
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.09, 0.0, 0.11):
            fd = f * 2 ** (det / 12.0)
            ph = rng.random() * 6.283
            out += np.sin(2 * np.pi * fd * tt + ph) * 0.33
            out += np.sin(2 * np.pi * 2 * fd * tt + ph) * 0.05
    out = lp_fft(out / max(len(freqs), 1), cutoff, 2)
    return out * a * amp


def sub_bass(f, dur=0.9, amp=1.0):
    """正弦低音加二次谐波, 低通 260Hz"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) + 0.18 * np.sin(2 * np.pi * 2 * f * tt)
    env = (1 - np.exp(-tt / 0.02)) * np.exp(-tt / (dur * 0.5))
    return lp_fft(x, 260, 2) * env * amp


def soft_kick(amp=1.0):
    """软底鼓: 正弦扫频 102 降到 62Hz, 无 click 无失真"""
    n = int(0.55 * SR)
    tt = np.arange(n) / SR
    f = 62 + 40 * np.exp(-tt / 0.05)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-tt / 0.17)
    return x * amp / max(np.max(np.abs(x)), 1e-9)


def rim(amp=1.0):
    """软边击: 噪声经 4 阶带通 200 到 900Hz, 加 180Hz 短音, 没有高频嘶声"""
    n = int(0.22 * SR)
    tt = np.arange(n) / SR
    nz = bp_fft(rng.standard_normal(n), 200, 900, 4)
    tone = np.sin(2 * np.pi * 180 * tt) * 0.40 * np.exp(-tt / 0.05)
    x = (nz * np.exp(-tt / 0.045) + tone) * (1 - np.exp(-tt / 0.003))
    return x * amp / max(np.max(np.abs(x)), 1e-9)


def bell(f, dur=2.2, amp=1.0):
    """钟琴: 基频加 2 倍与 3 倍分音, 长衰减, 低通 3.2kHz"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.9)
    x += 0.20 * np.sin(2 * np.pi * 2.0 * f * tt) * np.exp(-tt / 0.40)
    x += 0.04 * np.sin(2 * np.pi * 3.0 * f * tt) * np.exp(-tt / 0.20)
    return lp_fft(x * amp / 1.6, 3200, 2)


def swell(dur=1.8, amp=0.30, lo=160, hi=900):
    """噪声渐强: 带通中心随时间上移, 段落切换前铺一层空气"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    p = tt / dur
    nz = rng.standard_normal(n)
    steps = 18
    out = np.zeros(n)
    for i in range(steps):
        a, b = i / steps, (i + 1) / steps
        i0, i1 = int(a * n), int(b * n)
        if i1 <= i0:
            continue
        f0 = lo + (hi - lo) * a
        out[i0:i1] = bp_fft(nz[i0:i1], max(f0 * 0.6, 80), min(f0 * 1.6, 12000), 4)
    return out * (p ** 2.0) * amp / max(np.max(np.abs(out)), 1e-9)


def thump(amp=1.0):
    """切点低音 thump: 64 降到 34Hz 扫频"""
    n = int(1.1 * SR)
    tt = np.arange(n) / SR
    f = 64 * np.exp(-tt / 0.25) + 34
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.30)
    return x * amp / max(np.max(np.abs(x)), 1e-9)


# ---------------------------------------------------------------- 编排
# 8 小节循环: Cmaj7  Am7  Fmaj7  G6  Cmaj7  Em7  Fmaj7  G6
CHORDS = [
    # Cmaj7  (根音 C3)
    (48, [48, 52, 55, 59]),
    # Am7
    (45, [45, 48, 52, 55]),
    # Fmaj7
    (41, [41, 45, 48, 52]),
    # G6
    (43, [43, 47, 50, 52]),
    (48, [48, 52, 55, 59]),
    # Em7
    (40, [40, 43, 47, 50]),
    (41, [41, 45, 48, 52]),
    (43, [43, 47, 50, 52]),
]


def main():
    drums = np.zeros(N)
    bass = np.zeros(N)
    music = np.zeros(N)
    fx = np.zeros(N)

    nbars = int(DUR // BAR)

    for bar_i in range(nbars):
        t0 = bar_i * BAR
        root_semi, tones = CHORDS[bar_i % 8]
        root = hz(root_semi)
        # pad: 每小节一个和弦, 从第 1 小节就进来
        pad_f = [hz(s) for s in tones] + [hz(root_semi + 12)]
        add(music, pad(pad_f, BAR + 1.4, 0.72 if bar_i >= 1 else 0.50), t0)

        # 开头两小节只留 pad 与钟琴, 让观众先看清标题
        if bar_i < 2:
            if bar_i == 0:
                add(fx, bell(hz(76), 3.0, 0.16), t0 + 0.05)
                add(fx, bell(hz(83), 3.0, 0.10), t0 + BEAT * 2)
            continue

        # 低音落在 1 与 3 拍, 3 拍轻一些
        add(bass, sub_bass(root, 1.5, 0.40), t0)
        add(bass, sub_bass(root, 1.3, 0.26), t0 + BEAT * 2)

        # 软底鼓落在 1 与 3 拍, 软边击落在 2 与 4 拍
        add(drums, soft_kick(0.30), t0)
        add(drums, soft_kick(0.21), t0 + BEAT * 2)
        add(drums, rim(0.26), t0 + BEAT * 1)
        add(drums, rim(0.20), t0 + BEAT * 3)

        # 钢琴走八分音符琶音, 1 拍与 3 拍加重
        walk = [0, 2, 1, 3, 2, 0, 3, 1]
        for k in range(8):
            lb = k * 0.5
            semi = tones[walk[k] % 4] + (12 if k in (4, 6) else 0)
            amp = 0.55 if (k % 4 == 0) else (0.36 if k % 2 == 0 else 0.24)
            if bar_i % 8 in (0, 4) and k == 0:
                amp *= 1.15
            add(music, piano(hz(semi), 1.3, amp), t0 + lb * BEAT)

        # 每 4 小节句首一枚钟琴
        if bar_i % 4 == 0:
            add(fx, bell(hz(tones[3] + 24), 2.4, 0.09), t0 + 0.02)

    # 段落转场: 切点前起 swell, 切点上落 thump 与钟琴
    for i, cut in enumerate(CUTS[:-1]):
        if cut <= 0.1:
            continue
        add(fx, swell(1.9, 0.26 if i else 0.20), cut - 1.9)
        add(fx, thump(0.50 if i else 0.40), cut)
        add(fx, bell(hz(79 if i % 2 else 76), 2.6, 0.11), cut + 0.02)
    # 结尾收束
    add(fx, swell(2.4, 0.22), DUR - 3.0)
    add(fx, thump(0.42), DUR - 2.6)
    add(music, pad([hz(s) for s in (48, 52, 55, 59, 64)], 4.0, 0.34), DUR - 4.2)

    # ---- 底鼓侧链闪避: 每个底鼓点把音乐与低音压到 0.72, 50ms 内恢复
    duck = np.ones(N)
    for bar_i in range(nbars):
        if bar_i < 2:
            continue
        for k in (0, 2):
            i = int((bar_i * BAR + k * BEAT) * SR)
            m = int(0.45 * SR)
            if i >= N:
                continue
            seg = np.arange(min(m, N - i)) / SR
            env = 0.72 + 0.28 * (1 - np.exp(-seg / 0.05))
            duck[i:i + len(seg)] = np.minimum(duck[i:i + len(seg)], env)
    music *= duck
    bass *= duck

    # ---- 混响: IR 先低通, 否则混响把高频铺满全片
    # IR 必须在这里生成: 它消耗 rng 的时机与改造前一致, 否则随机串会整体错位
    ir = make_ir(1.9, 0.55, 2400, 3, rng)
    music_r = reverb(music, ir, 0.55)
    fx_r = reverb(fx, ir, 0.55)
    bass_r = reverb(bass, ir, 0.10)

    # ---- 声场: 钢琴与 fx 做毫秒级左右错位, 底鼓与低音居中共用
    def widen(x, spread):
        d = int(spread * SR)
        l, r = x.copy(), x.copy()
        if d > 0:
            l[d:] = x[:-d]
            r[:-d] = x[d:]
        return l, r

    ml, mr = widen(music_r, 0.013)
    fl, fr = widen(fx_r, 0.009)
    left = drums + bass_r + 0.55 * (ml + music_r) + 0.5 * (fl + fx_r)
    right = drums + bass_r + 0.55 * (mr + music_r) + 0.5 * (fr + fx_r)

    st = np.stack([left, right])

    # ---- 总线压缩: 时间常数 0.09s, 阈值 0.16, 超出部分按 0.55 次幂衰减
    st = bus_compress(st, thr=0.16, power=0.55, tau=0.09)

    # ---- 渐入 0.8s, 渐出 2.2s
    fade_in = np.clip(T / 0.8, 0, 1)
    fade_out = np.clip((DUR - T) / 2.2, 0, 1) ** 1.3
    st *= np.stack([fade_in * fade_out, fade_in * fade_out])

    # ---- 母带: 参数逐项写全, 与改造前的音色平衡对齐, 不受 dsp 默认值变动影响
    # 淡入淡出原先夹在音色平衡与归一化之间, 改用共享基元后只能整体移到母带链之前
    # 线性滤波与逐点淡入淡出不可交换, 渐入渐出窗口内会产生约 -67 dBFS 的差异, 不影响听感
    st = warm_master(st, warm_lo=220, warm_hi=900, warm=0.40,
                     cut1=3000, cut1_amt=0.45, cut2=6000, cut2_amt=0.35,
                     lpf=4600, lpf_order=3, hpf=32, peak=0.95, drive=0.9)

    path = os.path.join(OUT, OUTNAME)
    shape = write_wav(path, st)
    print("wrote", path, shape, "peak %.3f" % float(np.max(np.abs(st))))


if __name__ == "__main__":
    main()

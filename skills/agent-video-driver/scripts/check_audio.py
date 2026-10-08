# -*- coding: utf-8 -*-
"""
配乐客观检查: 一次跑完卡点, 频段, 脉冲, 单调性四类指标

  python scripts/check_audio.py audio/score.wav 100
  python scripts/check_audio.py audio/score.wav 120

判据见 references/audio-engine.md
"""
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1] if len(sys.argv) > 1 else "audio/score.wav"
BPM = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
if not os.path.isabs(name) and not os.path.exists(name):
    name = os.path.join(HERE, "..", name)
BEAT = 60.0 / BPM


def load(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768.0
    return sr, a, a.mean(axis=1)


def level_map(mono, sr, label="level map"):
    win = int(0.25 * sr)
    nb = len(mono) // win
    rms = np.array([np.sqrt((mono[i * win:(i + 1) * win] ** 2).mean()) for i in range(nb)])
    mx = max(rms.max(), 1e-9)
    print("\n%s (每格 0.25s, 每行 60 格):" % label)
    for r in range(0, nb, 60):
        print("".join(" .:-=+*#%@"[min(9, int(v / mx * 9.999))] for v in rms[r:r + 60]))


def beat_metrics(mono, sr):
    hop = 256
    env = np.array([np.abs(mono[i:i + hop]).mean() for i in range(0, len(mono) - hop, hop)])
    env = np.diff(env)
    env[env < 0] = 0
    env = env - env.mean()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    ac /= max(ac[0], 1e-9)
    fps = sr / hop
    print("\n起始包络自相关 (拍长 %.0f ms):" % (BEAT * 1000))
    for mult in (0.5, 1, 2, 4):
        target = BEAT * 1000 * mult
        best = None
        for lag in range(1, int(4 * fps)):
            ms = lag / fps * 1000
            if abs(ms - target) < 12 and (best is None or ac[lag] > best[1]):
                best = (ms, ac[lag])
        if best:
            print("  x%.1f  %7.1f ms  r=%.3f" % (mult, best[0], best[1]))
    onb, offb = [], []
    for k in range(int(30.0 / BEAT)):
        i = int(k * BEAT * sr)
        w = int(0.09 * sr)
        if i + w < len(mono):
            onb.append(np.abs(mono[i:i + w]).max())
        j = i + int(BEAT * 0.5 * sr)
        if j + w < len(mono):
            offb.append(np.abs(mono[j:j + w]).max())
    ratio = np.mean(onb) / max(np.mean(offb), 1e-9)
    print("  拍上 %.3f / 拍间 %.3f = %.2f 倍 (目标大于 1.8)" % (np.mean(onb), np.mean(offb), ratio))


def folded_envelope(mono, sr):
    hop = int(0.02 * sr)
    env = np.array([np.abs(mono[i:i + hop]).mean() for i in range(0, len(mono) - hop, hop)])
    ph = (np.arange(len(env)) * 0.02 % BEAT) / BEAT
    idx = np.clip((ph * 20).astype(int), 0, 19)
    prof = np.array([env[idx == k].mean() for k in range(20)])
    prof = prof / max(prof.mean(), 1e-9)
    print("\n折叠包络 (按拍折叠成 20 格):")
    print("  " + " ".join("%.2f" % v for v in prof))
    print("  峰值相位 %.2f  起伏 %.2f (目标大于 0.35)" % (prof.argmax() / 20.0, prof.max() - prof.min()))


def spectrum(mono, sr):
    sp = np.abs(np.fft.rfft(mono)) ** 2
    fr = np.fft.rfftfreq(len(mono), 1 / sr)
    tot = max(sp.sum(), 1e-12)
    print("\n频段占比:")
    for lo, hi, nm in ((20, 90, "sub 20-90"), (90, 300, "low 90-300"), (300, 2000, "mid"),
                       (2000, 8000, "hi 2-8k"), (8000, 16000, "air 8-16k")):
        m = (fr >= lo) & (fr < hi)
        print("  %-12s %5.1f%%   %.4f %%/Hz" % (nm, sp[m].sum() / tot * 100,
                                                sp[m].sum() / tot * 100 / (hi - lo)))
    for lo, hi, nm in ((2000, 6000, "刺耳 2-6k"), (300, 800, "温暖 0.3-0.8k")):
        m = (fr >= lo) & (fr < hi)
        print("  %-12s %5.1f%%" % (nm, sp[m].sum() / tot * 100))
    print("  谱心        %.0f Hz (目标按引擎区分: 键盘与电子 600 到 1500, 管弦乐 300 到 550)" % ((sp * fr).sum() / tot))
    print("\n倍频程电平 (相对总功率):")
    for lo, hi in ((44, 88), (88, 177), (177, 355), (355, 710), (710, 1420),
                   (1420, 2840), (2840, 5680), (5680, 11360)):
        m = (fr >= lo) & (fr < hi)
        lvl = 10 * np.log10(sp[m].sum() / tot + 1e-12)
        print("  %6d-%-6d %+6.1f dB  %s" % (lo, hi, lvl, "#" * max(0, int((lvl + 60) / 1.5))))


def monotony(mono, sr):
    win = 10 * sr
    rms, cent = [], []
    for i in range(0, len(mono) - win, win):
        s = mono[i:i + win]
        sp = np.abs(np.fft.rfft(s)) ** 2
        fr = np.fft.rfftfreq(len(s), 1 / sr)
        rms.append(np.sqrt((s ** 2).mean()))
        cent.append((sp * fr).sum() / max(sp.sum(), 1e-12))
    rms = np.array(rms)
    cent = np.array(cent)
    print("\n单调性 (每 10 秒一段):")
    print("  RMS   " + " ".join("%.3f" % v for v in rms))
    print("  谱心  " + " ".join("%.0f" % v for v in cent))
    print("  起伏 %.2f 倍 (目标大于 2.0)   谱心 %.0f 到 %.0f Hz"
          % (rms.max() / max(rms.min(), 1e-9), cent.min(), cent.max()))


def main():
    sr, a, mono = load(name)
    print("%s  %d Hz  %.3f s  峰值 %.3f  RMS %.4f" % (name, sr, len(mono) / sr,
                                                    np.abs(a).max(), np.sqrt((mono ** 2).mean())))
    level_map(mono, sr)
    beat_metrics(mono, sr)
    folded_envelope(mono, sr)
    spectrum(mono, sr)
    monotony(mono, sr)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
配乐客观检查: 卡点, 频段, 脉冲, 单调性一次跑完

  python scripts/check_audio.py audio/score.wav 100
  python scripts/check_audio.py audio/score.wav 100 --quick
  python scripts/check_audio.py audio/score.wav 100 --from 120 --to 180
  python scripts/check_audio.py audio/score.wav 100 --engine keyboard

调参迭代时不必每次都量全片: --quick 只跑拍点与折叠包络两项主判据, --from/--to 只量一段.
判据见 references/audio-engine.md.
"""
import argparse
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BEAT = 0.6
ENGINE = "orchestra"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="配乐客观检查: 卡点, 频段, 脉冲, 单调性")
    ap.add_argument("file", nargs="?", default=os.path.join("audio", "score.wav"),
                    help="要检查的 WAV, 缺省 audio/score.wav")
    ap.add_argument("bpm", nargs="?", type=float, default=100.0, help="BPM, 缺省 100")
    ap.add_argument("--from", dest="t_from", type=float, default=None, help="只量从这一秒起")
    ap.add_argument("--to", dest="t_to", type=float, default=None, help="只量到这一秒为止")
    ap.add_argument("--quick", action="store_true",
                    help="只跑拍点与折叠包络两项主判据, 跳过频段与单调性")
    ap.add_argument("--engine", choices=("orchestra", "keyboard"), default="orchestra",
                    help="按引擎取拍点峰值比的判据档: 管弦乐 1.3, 键盘与电子 1.8")
    return ap.parse_args(argv)


def resolve(path):
    if not os.path.isabs(path) and not os.path.exists(path):
        return os.path.join(HERE, "..", path)
    return path


def load(path, t_from=None, t_to=None):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768.0
    i0 = 0 if t_from is None else max(0, int(t_from * sr))
    i1 = len(a) if t_to is None else min(len(a), int(t_to * sr))
    if i1 <= i0:
        raise SystemExit("分段范围为空: --from %s --to %s" % (t_from, t_to))
    a = a[i0:i1]
    return sr, a, a.mean(axis=1)


def level_map(mono, sr, label="level map"):
    win = int(0.25 * sr)
    nb = len(mono) // win
    if nb == 0:
        return
    rms = np.array([np.sqrt((mono[i * win:(i + 1) * win] ** 2).mean()) for i in range(nb)])
    mx = max(rms.max(), 1e-9)
    print("\n%s (每格 0.25s, 每行 60 格):" % label)
    for r in range(0, nb, 60):
        print("".join(" .:-=+*#%@"[min(9, int(v / mx * 9.999))] for v in rms[r:r + 60]))


def beat_metrics(mono, sr):
    hop = 256
    if len(mono) <= hop:
        print("\n音频太短, 跳过拍点指标")
        return
    env = np.array([np.abs(mono[i:i + hop]).mean() for i in range(0, len(mono) - hop, hop)])
    env = np.diff(env)
    env[env < 0] = 0
    env = env - env.mean()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    ac /= max(ac[0], 1e-9)
    fps = sr / hop
    print("\n起始包络自相关 (拍长 %.0f ms):" % (BEAT * 1000))
    # lag 上限要同时受自相关长度约束, 否则短片或分段量测时会越界
    max_lag = max(1, min(int(4 * fps), len(ac) - 1))
    for mult in (0.5, 1, 2, 4):
        target = BEAT * 1000 * mult
        best = None
        for lag in range(1, max_lag + 1):
            ms = lag / fps * 1000
            if abs(ms - target) < 12 and (best is None or ac[lag] > best[1]):
                best = (ms, ac[lag])
        if best:
            print("  x%.1f  %7.1f ms  r=%.3f" % (mult, best[0], best[1]))
    onb, offb = [], []
    for k in range(int(min(30.0, len(mono) / float(sr)) / BEAT)):
        i = int(k * BEAT * sr)
        w = int(0.09 * sr)
        if i + w < len(mono):
            onb.append(np.abs(mono[i:i + w]).max())
        j = i + int(BEAT * 0.5 * sr)
        if j + w < len(mono):
            offb.append(np.abs(mono[j:j + w]).max())
    if not onb or not offb:
        print("  音频太短, 拍上/拍间能量比没量到")
        return
    ratio = np.mean(onb) / max(np.mean(offb), 1e-9)
    # 判据按引擎分档: 键盘与电子的拍点靠强瞬态, 管弦乐靠配器层次, 拿同一个门槛会逼着 Agent 推高频
    thr = 1.8 if ENGINE == "keyboard" else 1.3
    print("  拍上 %.3f / 拍间 %.3f = %.2f 倍 (目标大于 %.1f, %s 档)"
          % (np.mean(onb), np.mean(offb), ratio, thr, "键盘与电子" if ENGINE == "keyboard" else "管弦乐"))
    print("  说明: 折叠包络起伏是更贴近听感的主判据, 这一项贴不到门槛时先看那一项")


def folded_envelope(mono, sr):
    hop = int(0.02 * sr)
    if len(mono) <= hop:
        print("\n音频太短, 跳过折叠包络")
        return
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
    if len(mono) < 2 * win:
        print("\n音频短于 20 秒, 跳过单调性")
        return
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


def main(argv=None):
    global BEAT, ENGINE
    a = parse_args(argv)
    BEAT = 60.0 / a.bpm
    ENGINE = a.engine
    path = resolve(a.file)
    if not os.path.exists(path):
        raise SystemExit("找不到音频文件: %s" % path)
    sr, arr, mono = load(path, a.t_from, a.t_to)
    span = ""
    if a.t_from is not None or a.t_to is not None:
        span = "  分段 %s 到 %s 秒" % ("0" if a.t_from is None else a.t_from,
                                      "末尾" if a.t_to is None else a.t_to)
    print("%s  %d Hz  %.3f s  峰值 %.3f  RMS %.4f%s"
          % (path, sr, len(mono) / sr, np.abs(arr).max(),
             np.sqrt((mono ** 2).mean()), span))
    if a.quick:
        print("快检模式: 只跑拍点与折叠包络两项主判据")
    else:
        level_map(mono, sr)
    beat_metrics(mono, sr)
    folded_envelope(mono, sr)
    if not a.quick:
        spectrum(mono, sr)
        monotony(mono, sr)


if __name__ == "__main__":
    main()

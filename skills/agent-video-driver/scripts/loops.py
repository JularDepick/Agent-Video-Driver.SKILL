# -*- coding: utf-8 -*-
"""
找音乐接缝: 比较各小节的频谱, 列出可以无缝重复或剪掉的小节区间

用户自备音乐时, 画面段落数往往与音乐的段落结构对不上. 直接硬切会在接缝处听到
音色跳变, 所以先用频谱相似度找出"接得上"的小节, 再交给 scripts/cutmusic.py 剪.

  python scripts/loops.py music.mp3 temp/beats.json
  python scripts/loops.py music.mp3 temp/beats.json --len 8 14
  python scripts/loops.py music.mp3 temp/beats.json --from 9 --to 74 --min-sim 0.985
  python scripts/loops.py music.mp3 temp/beats.json --json temp/loops.json

判据 (与外部参考方案一致): 相似度 0.99 以上通常听不出接缝, 0.985 到 0.99 之间需要试听.

两种用途:
  可重复区间: 第 i 小节与第 i+L 小节相似, 于是第 i 到 i+L-1 小节可以整段重复
  可剪接点: 第 i 小节与第 j 小节相似, 于是剪掉第 i 到 j-1 小节之后接得上

小节号约定: 人看的文本摘要一律 1 基, 写进 json 的一律 0 基, 与 beats.py 一致
"""
import argparse
import json
import math
import os
import sys

import numpy as np

import beats

MIN_SIM = 0.99


def load_beats(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    bars = d.get("bars") or []
    if len(bars) < 4:
        raise RuntimeError("beats.json 里的 bar 少于 4 个, 先确认它是不是用 beats.py 生成的")
    starts = [float(b["start"]) for b in bars]
    dur = float(d.get("duration") or (starts[-1] + (starts[1] - starts[0])))
    return d, starts, dur


def bar_spectra(mono, sr, starts, dur):
    """每个小节的平均对数谱, 形状 (小节数, 频点数)"""
    spec = beats.log_spectra(mono, sr)
    times = (np.arange(spec.shape[0]) * beats.HOP + beats.NFFT) / float(sr)
    out = np.zeros((len(starts), spec.shape[1]), np.float32)
    for i, t0 in enumerate(starts):
        t1 = starts[i + 1] if i + 1 < len(starts) else dur + 1e-6
        m = (times >= t0) & (times < t1)
        if m.any():
            out[i] = spec[m].mean(axis=0)
    return out


def similarity(rows):
    """
    小节之间的频谱余弦相似度矩阵

    用余弦而不是欧氏距离: 它只看频谱形状与相对电平, 与整体音量无关,
    于是某几小节整体轻一点不会把接缝判成不可用.
    """
    n = np.linalg.norm(rows, axis=1, keepdims=True)
    unit = rows / np.maximum(n, 1e-9)
    return unit @ unit.T


def find_loops(sim, lo, hi, min_sim, starts, dur):
    """可重复区间: 第 i 与第 i+L 小节相似, 于是 [i, i+L) 可整段重复"""
    out = []
    nb = sim.shape[0]
    for L in range(max(1, lo), max(1, hi) + 1):
        for i in range(0, nb - L):
            s = float(sim[i, i + L])
            if s >= min_sim:
                out.append({
                    "start_bar": i,
                    "length": L,
                    "end_bar": i + L - 1,
                    "sim": round(s, 5),
                    "start": round(starts[i], 4),
                    "end": round(starts[i + L], 4) if i + L < len(starts) else round(dur, 4),
                })
    out.sort(key=lambda x: -x["sim"])
    return out


def find_cuts(sim, lo, hi, min_sim, starts):
    """可剪接点: 第 i 与第 j 小节相似, 于是剪掉 [i, j) 之后接得上"""
    out = []
    nb = sim.shape[0]
    for i in range(max(0, lo), min(nb, hi + 1)):
        for j in range(i + 1, nb):
            s = float(sim[i, j])
            if s >= min_sim:
                out.append({
                    "drop_from_bar": i,
                    "drop_to_bar": j - 1,
                    "drop_bars": j - i,
                    "resume_bar": j,
                    "sim": round(s, 5),
                    "drop_seconds": round(starts[j] - starts[i], 4),
                })
    out.sort(key=lambda x: (-x["sim"], x["drop_bars"]))
    return out


def top_pairs(sim, k=8):
    """相似度最高的若干小节对, 用于没有候选达标时给线索"""
    nb = sim.shape[0]
    pairs = []
    for i in range(nb):
        for j in range(i + 1, nb):
            pairs.append((float(sim[i, j]), i, j))
    pairs.sort(reverse=True)
    return pairs[:k]


def report(path, d, loops, cuts, sim, min_sim):
    nb = sim.shape[0]
    print("=" * 62)
    print("接缝分析 %s" % path)
    print("=" * 62)
    print("BPM %.2f   小节 %d 个   小节长 %.3f s   时长 %.3f s"
          % (d.get("bpm", 0.0), nb,
             d.get("beat_seconds", 0.0) * d.get("meter", 4), d.get("duration", 0.0)))
    print("判据: 相似度不低于 %.3f" % min_sim)

    print("-" * 62)
    if loops:
        print("可重复区间 %d 个 (小节号从 1 开始):" % len(loops))
        for x in loops[:20]:
            print("  第 %d 到 %d 小节 (共 %d 小节, %.2f 到 %.2f 秒) 重复后接第 %d 小节   相似度 %.4f"
                  % (x["start_bar"] + 1, x["end_bar"] + 1, x["length"],
                     x["start"], x["end"], x["end_bar"] + 2, x["sim"]))
        if len(loops) > 20:
            print("  ... 另有 %d 个, 用 --json 拿全量" % (len(loops) - 20))
    else:
        print("可重复区间: 无 (没有小节的相似度达到 %.3f)" % min_sim)

    print("-" * 62)
    if cuts:
        print("可剪接点 %d 个 (剪掉之后从 resume 小节接着走):" % len(cuts))
        for x in cuts[:20]:
            print("  剪掉第 %d 到 %d 小节 (共 %d 小节, %.2f 秒), 从第 %d 小节接上   相似度 %.4f"
                  % (x["drop_from_bar"] + 1, x["drop_to_bar"] + 1, x["drop_bars"],
                     x["drop_seconds"], x["resume_bar"] + 1, x["sim"]))
        if len(cuts) > 20:
            print("  ... 另有 %d 个, 用 --json 拿全量" % (len(cuts) - 20))
    else:
        print("可剪接点: 无 (没有小节对的相似度达到 %.3f)" % min_sim)
        print("  参考: 相似度最高的几对")
        for s, i, j in top_pairs(sim):
            print("    第 %d 与第 %d 小节   相似度 %.4f" % (i + 1, j + 1, s))
        print("  处置: 放宽 --min-sim 试听, 或改用整段重复而不是剪接, 或换一首音乐")

    print("-" * 62)
    print("提醒: 相似度只是线索, 剪完必须试听接缝那 2 秒; 剪出来的音频再跑一次 beats.py 复测拍表")


def main():
    ap = argparse.ArgumentParser(description="找音乐接缝: 列出可无缝重复或剪掉的小节区间")
    ap.add_argument("audio", help="音频路径, WAV 直读, 其他格式经 ffmpeg 转 22050 单声道")
    ap.add_argument("beats_json", help="beats.py --json 产出的拍表文件")
    ap.add_argument("--len", dest="lens", nargs=2, type=int, default=[4, 16], metavar="A B",
                    help="搜索的可重复长度范围, 单位小节, 缺省 4 16")
    ap.add_argument("--from", dest="from_bar", type=int, default=1,
                    help="可剪接点的小节搜索下界, 1 基, 缺省 1")
    ap.add_argument("--to", dest="to_bar", type=int, default=None,
                    help="可剪接点的小节搜索上界, 1 基, 缺省到最后一个小节")
    ap.add_argument("--min-sim", dest="min_sim", type=float, default=MIN_SIM,
                    help="相似度阈值, 缺省 %.3f" % MIN_SIM)
    ap.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON 的路径")
    a = ap.parse_args()

    for p in (a.audio, a.beats_json):
        if not os.path.exists(p):
            print("找不到文件: %s" % p)
            return 2
    if a.lens[0] < 1 or a.lens[1] < a.lens[0]:
        print("--len 要给两个整数, 且前者不大于后者")
        return 2
    if not (0.0 < a.min_sim <= 1.0):
        print("--min-sim 要落在 (0, 1] 内")
        return 2

    try:
        d, starts, dur = load_beats(a.beats_json)
        sr, mono = beats.decode(a.audio)
    except Exception as e:
        print("读输入失败: %s" % e)
        return 2

    if abs(len(mono) / sr - dur) > max(0.25, dur * 0.02):
        print("警告: 音频时长 %.2f s 与 beats.json 的 %.2f s 差得多, 确认两者是不是同一份文件"
              % (len(mono) / sr, dur))

    rows = bar_spectra(mono, sr, starts, dur)
    sim = similarity(rows)
    nb = sim.shape[0]
    lo = max(0, a.from_bar - 1)
    hi = nb - 1 if a.to_bar is None else min(nb - 1, a.to_bar - 1)
    if hi <= lo:
        print("--from 与 --to 圈出的范围太窄, 至少要跨两个小节")
        return 2

    loops = find_loops(sim, a.lens[0], a.lens[1], a.min_sim, starts, dur)
    cuts = find_cuts(sim, lo, hi, a.min_sim, starts)
    report(a.audio, d, loops, cuts, sim, a.min_sim)

    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as fp:
            json.dump({"file": a.audio, "min_sim": a.min_sim, "bars": nb,
                       "loops": loops, "cuts": cuts}, fp, ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

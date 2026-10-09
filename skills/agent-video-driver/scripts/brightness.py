# -*- coding: utf-8 -*-
"""
亮度标定: 对着参考片量均值, 中位数与 p95, 判断底色深浅与字幕亮度是否对得上

编码与调色的头号问题是整体亮了 2 到 3 倍还看不出来, 显示器会骗人. 所以判据不是"看着差不多",
而是与参考片在相同位置量出来的三个数比.

  python scripts/brightness.py out/成片.mp4 --at 5 20 45
  python scripts/brightness.py out/成片.mp4 --at 20 --ref 参考片.mp4 --ref-at 20
  python scripts/brightness.py temp/frames_proj/n001200.png
  python scripts/brightness.py out/成片.mp4 --json temp/brightness.json

判据:
  中位数决定底色深浅, 暗场片常在 5 到 30 之间
  p95 决定字幕亮度, 白字约 200 到 250
  均值偏离参考 2 倍以上说明管线有问题, 不要用调色去补
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

TMP = "brightness_tmp_%d.png" % os.getpid()
DARK_MAX = 30.0
BRIGHT_MIN = 140.0


def luma(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def measure(path):
    """量一张图的亮度统计, 返回 dict"""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    y = luma(a)
    return {
        "file": path,
        "size": [int(a.shape[1]), int(a.shape[0])],
        "mean": round(float(y.mean()), 2),
        "median": round(float(np.median(y)), 2),
        "p95": round(float(np.percentile(y, 95)), 2),
        "p99": round(float(np.percentile(y, 99)), 2),
        "dark_frac": round(float((y < DARK_MAX).mean()), 4),
        "bright_frac": round(float((y > BRIGHT_MIN).mean()), 4),
        "median_rgb": [round(float(np.median(a[..., k])), 1) for k in range(3)],
    }


def grab(video, t, out_path):
    """
    从视频里精确抽一帧

    定位参数必须放在 -i 之后: 放在前面是输入定位, 会跳到目标时间之前最近的关键帧,
    抽到的不是目标帧, 判据就失效了 (见 pitfalls.md 的抽帧一条)
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found, 请确认它在 PATH 中")
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video,
                        "-ss", "%.6f" % max(0.0, t), "-frames:v", "1", out_path],
                       capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError("抽帧失败: %s" % (p.stderr or "").strip()[:200])


def is_video(path):
    return os.path.splitext(path)[1].lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp")


def analyse(path, times):
    """返回 [(时间或 None, 统计), ...]; 图片只量一次, 视频按给定时刻逐点抽帧"""
    if not is_video(path):
        return [(None, measure(path))]
    out = []
    os.makedirs("temp", exist_ok=True)
    tmp = os.path.join("temp", TMP)
    try:
        for t in times:
            grab(path, t, tmp)
            out.append((t, measure(tmp)))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def judge(ms, ref):
    """按参考片判底色与字幕, 返回提示清单"""
    notes = []
    if ref is not None:
        for k in ("mean", "median", "p95"):
            a, b = ms[k], ref[k]
            if b <= 1e-6:
                continue
            r = a / b
            if r >= 2.0 or r <= 0.5:
                notes.append("%s 是参考的 %.2f 倍 (%s 对 %s), 偏离 2 倍以上, 先查管线再谈调色"
                             % (k, r, a, b))
    if ms["median"] > 120.0:
        notes.append("中位数 %.1f 偏高, 这是亮场片的量级; 暗场片应落在 5 到 30 之间" % ms["median"])
    if ms["p95"] < 120.0:
        notes.append("p95 只有 %.1f, 白字不够亮; 字幕用的白字 p95 应在 200 到 250" % ms["p95"])
    if ms["dark_frac"] > 0.98:
        notes.append("暗部占比 %.3f, 整帧几乎全黑, 检查这一段是不是渲成了空场" % ms["dark_frac"])
    return notes


def main():
    ap = argparse.ArgumentParser(description="亮度标定: 量均值, 中位数与 p95, 可与参考片对比")
    ap.add_argument("input", help="成片, 视频片段或单张帧图")
    ap.add_argument("--at", type=float, nargs="+", default=None,
                    help="抽帧时刻秒数, 可给多个; 缺省取片长的 1/4 与 3/4 两处")
    ap.add_argument("--ref", default=None, help="参考片或参考帧图, 用于对比")
    ap.add_argument("--ref-at", dest="ref_at", type=float, nargs="+", default=None,
                    help="参考片的抽帧时刻, 缺省与 --at 相同")
    ap.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON 的路径")
    a = ap.parse_args()

    if not os.path.exists(a.input):
        print("找不到文件: %s" % a.input)
        return 2
    if a.ref and not os.path.exists(a.ref):
        print("找不到参考文件: %s" % a.ref)
        return 2

    times = a.at
    if times is None:
        if is_video(a.input):
            times = [10.0, 30.0]
        else:
            times = [0.0]
    ref_times = a.ref_at if a.ref_at else times

    try:
        rows = analyse(a.input, times)
        ref_rows = analyse(a.ref, ref_times) if a.ref else None
    except Exception as e:
        print("量测失败: %s" % e)
        return 2

    print("=" * 66)
    print("亮度标定 %s" % a.input)
    print("=" * 66)
    print("%-10s %8s %8s %8s %8s %8s %8s" % ("时刻(s)", "均值", "中位数", "p95", "p99", "暗部", "亮部"))
    for t, m in rows:
        print("%-10s %8.2f %8.2f %8.2f %8.2f %8.4f %8.4f"
              % ("-" if t is None else "%.2f" % t, m["mean"], m["median"], m["p95"],
                 m["p99"], m["dark_frac"], m["bright_frac"]))
    print("中位数 RGB: " + "   ".join(
        "%s -> %s" % ("-" if t is None else "%.1fs" % t, m["median_rgb"]) for t, m in rows))

    if ref_rows:
        print("-" * 66)
        print("参考 %s" % a.ref)
        print("%-10s %8s %8s %8s %8s %8s %8s" % ("时刻(s)", "均值", "中位数", "p95", "p99", "暗部", "亮部"))
        for t, m in ref_rows:
            print("%-10s %8.2f %8.2f %8.2f %8.2f %8.4f %8.4f"
                  % ("-" if t is None else "%.2f" % t, m["mean"], m["median"], m["p95"],
                     m["p99"], m["dark_frac"], m["bright_frac"]))

    print("-" * 66)
    any_note = False
    for i, (t, m) in enumerate(rows):
        ref = None
        if ref_rows:
            ref = ref_rows[i][1] if i < len(ref_rows) else ref_rows[-1][1]
        notes = judge(m, ref)
        if notes:
            any_note = True
            print("时刻 %s:" % ("-" if t is None else "%.2f" % t))
            for x in notes:
                print("  - %s" % x)
    if not any_note:
        print("判据全部通过: 底色与字幕亮度都落在区间内")

    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as fp:
            json.dump({"input": a.input,
                       "rows": [{"t": t, **m} for t, m in rows],
                       "ref": None if not ref_rows else
                       {"file": a.ref, "rows": [{"t": t, **m} for t, m in ref_rows]}},
                      fp, ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

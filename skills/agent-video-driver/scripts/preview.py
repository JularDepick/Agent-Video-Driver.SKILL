# -*- coding: utf-8 -*-
"""
字符图预览: 把一帧做最大池化后按色相分类, 打成 96x48 字符图
没有视觉输入的模型也能据此核对构图

  python scripts/preview.py temp/frames/n001200.png            # 一张或多张图片, 行为不变
  python scripts/preview.py --around temp/frames 1200 3        # 第 1200 帧前后各 3 帧
  python scripts/preview.py --ink temp/frames/n001200.png      # 亮场: 按块内最暗像素取色

--around 打印帧目录下 n%05d.png 中 指定帧 前后各 半径 帧的字符图, 每张前面一行给
帧路径, 平均亮度 与 与前一帧的平均绝对差, 末了报出相邻帧差分的峰值落在第几帧.
用途是证明画面变化正好发生在这一帧, 也就是卡点是否落对的直接证据.
半径缺省 3, 与既有 全片逐帧差分找运动峰值 的手段互补.

缺省取块内最亮像素, 只适用于暗场. 白底深字的亮场必须加 --ink: 亮场里每一块的最亮像素
都是背景, 缺省模式会把整屏糊成一片背景色, 看不出文字与元素位置. --ink 取块内最暗像素
当墨色, 并按墨量给字符浓淡.
"""
import argparse
import os
import sys
import numpy as np
from PIL import Image

CW, CH = 96, 48
# 换行符写成常量, 避免在不同编辑器与转义层之间来回丢反斜杠
NL = chr(10)


def classify(px):
    r, g, b = int(px[0]), int(px[1]), int(px[2])
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum < 26:
        return " "
    if b > 90 and b > r + 30 and g > r:
        return "C" if g > 150 else "c"
    if r > 150 and b > 90 and g < r - 40:
        return "P" if b > 110 else "p"
    if r > 120 and g > 90 and b < g - 30:
        return "A" if r > 200 else "a"
    if g > 130 and g > r + 30 and g > b:
        return "G" if g > 200 else "g"
    if lum > 170:
        return "#"
    if lum > 90:
        return "+"
    return "."


def classify_ink(px):
    """
    亮场用: 底色留空, 墨迹越浓字符越重

    与 classify 正好相反: 那边的空是"暗到没东西", 这边的空是"亮到底色"
    """
    r, g, b = int(px[0]), int(px[1]), int(px[2])
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum > 205:
        return " "
    if b > 90 and b > r + 25 and g > r:
        return "C" if lum < 150 else "c"
    if r > 140 and b > 80 and g < r - 30:
        return "P" if lum < 150 else "p"
    if r > 120 and g > 90 and b < g - 30:
        return "A" if lum < 150 else "a"
    if g > 120 and g > r + 25 and g > b:
        return "G" if lum < 160 else "g"
    if lum < 60:
        return "@"
    if lum < 110:
        return "#"
    if lum < 160:
        return "+"
    return "."


def preview(path, cw=CW, ch=CH, ink=False):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    h, w, _ = a.shape
    bh, bw = h // ch, w // cw
    a = a[:bh * ch, :bw * cw]
    blocks = a.reshape(ch, bh, cw, bw, 3)
    lum = (0.299 * blocks[..., 0] + 0.587 * blocks[..., 1] + 0.114 * blocks[..., 2])
    flat = blocks.reshape(ch, bh, cw, bw, 3)
    if ink:
        # 亮场: 每块取最暗的像素当墨色; 背景块的最暗像素也很亮, 于是自然留空
        idx = lum.reshape(ch, bh, cw, bw).min(axis=(1, 3))
        li = lum.argmin(axis=1)
        cols = np.take_along_axis(flat, li[:, None, :, :, None], axis=1)[:, 0]
        ci = lum.min(axis=1).argmin(axis=2)
        px = np.take_along_axis(cols, ci[:, :, None, None], axis=2)[:, :, 0]
        lines = ["".join(classify_ink(px[y, x]) for x in range(cw)) for y in range(ch)]
        return NL.join(lines), 1.0 - idx
    # (ch, cw, bw)
    idx = lum.reshape(ch, bh, cw, bw).max(axis=(1, 3))
    li = lum.argmax(axis=1)
    cols = np.take_along_axis(flat, li[:, None, :, :, None], axis=1)[:, 0]
    # (ch,cw)
    ci = lum.max(axis=1).argmax(axis=2)
    px = np.take_along_axis(cols, ci[:, :, None, None], axis=2)[:, :, 0]
    lines = []
    for y in range(ch):
        lines.append("".join(classify(px[y, x]) for x in range(cw)))
    return NL.join(lines), idx


def stats(path):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    out = {
        "mean": float(lum.mean()),
        "p99": float(np.percentile(lum, 99)),
        "bright_frac": float((lum > 140).mean()),
        "dark_frac": float((lum < 30).mean()),
    }
    return out


def rgb(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def mae(a, b):
    """两图平均绝对差 (0 到 255), 尺寸不一致时取左上公共区"""
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return float(np.abs(a[:h, :w] - b[:h, :w]).mean())


def frame_path(frames, i):
    return os.path.join(frames, "n%05d.png" % i)


def around(frames, idx, radius=3, ink=False):
    """打印指定帧前后各 radius 帧的字符图与相邻帧差分, 末了报峰值帧落在第几帧"""
    items = []
    for i in range(max(0, idx - radius), idx + radius + 1):
        p = frame_path(frames, i)
        if not os.path.exists(p):
            print("[警告] 缺帧 %s, 已跳过" % p)
            continue
        items.append((i, p, rgb(p)))
    if not items:
        print("帧目录 %s 下没有可读的 n%05d.png" % (frames, idx))
        return 2
    diffs = []
    prev = None
    for i, p, a in items:
        d = None if prev is None else mae(prev, a)
        if d is not None:
            diffs.append((i, d))
        s = stats(p)
        print("=" * 100)
        print("%s mean=%.1f p99=%.0f bright=%.3f dark=%.3f dmae_prev=%s%s"
              % (p, s["mean"], s["p99"], s["bright_frac"], s["dark_frac"],
                 "-" if d is None else "%.2f" % d,
                 "  ink" if ink else ""))
        txt, _ = preview(p, ink=ink)
        print(txt)
        prev = a
    print("=" * 100)
    if not diffs:
        print("半径内只有一帧, 算不出相邻帧差分")
        return 2
    peak_i, peak_v = max(diffs, key=lambda x: x[1])
    print("相邻帧差分数列: " + "  ".join("f%d %.2f" % (i, d) for i, d in diffs))
    print("差分峰值落在第 %d 帧 (值 %.2f), 给定第 %d 帧, 相差 %d 帧  [%s]"
          % (peak_i, peak_v, idx, abs(peak_i - idx),
             "画面变化正好发生在这一帧" if peak_i == idx else "峰值不在给定帧上"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="字符图预览, 支持前后帧差分")
    ap.add_argument("paths", nargs="*", help="一张或多张图片路径")
    ap.add_argument("--around", nargs="+", metavar="帧目录 帧序号 [半径]",
                    help="打印指定帧前后各若干帧的字符图与相邻帧差分, 半径缺省 3")
    ap.add_argument("--ink", action="store_true",
                    help="亮场模式: 按块内最暗像素取色, 底色留空; 白底深字的画面必须加它")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.around:
        if len(a.around) not in (2, 3):
            print("--around 用法: --around <帧目录> <帧序号> [半径]")
            return 2
        frames = a.around[0]
        try:
            idx = int(a.around[1])
            radius = int(a.around[2]) if len(a.around) == 3 else 3
        except ValueError:
            print("--around 的帧序号与半径必须是整数")
            return 2
        if idx < 0 or radius < 1:
            print("帧序号要大于等于 0, 半径要大于等于 1")
            return 2
        if not os.path.isdir(frames):
            print("帧目录不存在: %s" % frames)
            return 2
        return around(frames, idx, radius, a.ink)
    if not a.paths:
        ap.print_help()
        return 2
    missing = 0
    for p in a.paths:
        if not os.path.exists(p):
            print("找不到图片: %s" % p)
            missing += 1
            continue
        s = stats(p)
        print("=" * 100)
        print(p, "mean=%.1f p99=%.0f bright=%.3f dark=%.3f%s"
              % (s["mean"], s["p99"], s["bright_frac"], s["dark_frac"],
                 "  ink" if a.ink else ""))
        txt, _ = preview(p, ink=a.ink)
        print(txt)
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

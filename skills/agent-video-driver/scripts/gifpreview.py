# -*- coding: utf-8 -*-
"""
从帧序列抽帧存成 GIF, 用来看运动

字符图能核对构图, 总览图能核对屏序, 但两者都看不出运动. GIF 能把入场顺序, 错帧与
转场节奏一次看完, 是给用户过风格确认时最省事的形式.

  python scripts/gifpreview.py temp/frames_proj -o temp/preview.gif
  python scripts/gifpreview.py temp/frames_proj --from 0 --to 300 --every 5
  python scripts/gifpreview.py temp/frames_proj --from 900 --to 1200 --every 3 --fps 15

限制与纪律:
  GIF 无声音, 只有 256 色, 只用于看运动, 不能替代用户过目成片
  抽帧间隔要大于 1 帧, 逐帧存会得到一个几百兆的 GIF; 缺省按总帧数与 --max-frames 自动定步长
"""
import argparse
import os
import sys

from PIL import Image

MAX_FRAMES = 120
# 与 canvas.FRAME_PATTERN 保持一致; 不 import canvas, 单独复制走也能跑
FRAME_PATTERN = "n%05d.png"


def frame_paths(frames, frm, to, every):
    out = []
    i = frm
    while i <= to:
        p = os.path.join(frames, FRAME_PATTERN % i)
        if os.path.exists(p):
            out.append((i, p))
        i += max(1, every)
    return out


def auto_step(total, frm, to, max_frames):
    span = max(1, to - frm + 1)
    return max(1, int(round(span / float(max(2, max_frames)))))


def main():
    ap = argparse.ArgumentParser(description="从帧序列抽帧存成 GIF, 用来看运动")
    ap.add_argument("frames", help="帧目录, 里面是 n%05d.png")
    ap.add_argument("--from", dest="frm", type=int, default=None, help="起始帧号, 缺省 0")
    ap.add_argument("--to", dest="to", type=int, default=None, help="结束帧号, 缺省到最后一个")
    ap.add_argument("--every", type=int, default=None,
                    help="抽帧步长, 缺省按总帧数与 --max-frames 自动定")
    ap.add_argument("--max-frames", dest="max_frames", type=int, default=MAX_FRAMES,
                    help="GIF 最多几帧, 缺省 %d" % MAX_FRAMES)
    ap.add_argument("--width", type=int, default=640, help="输出宽度, 缺省 640")
    ap.add_argument("--fps", type=float, default=12.0, help="GIF 播放帧率, 缺省 12")
    ap.add_argument("-o", "--out", default=os.path.join("temp", "preview.gif"),
                    help="输出路径, 缺省 temp/preview.gif")
    a = ap.parse_args()

    if not os.path.isdir(a.frames):
        print("帧目录不存在: %s" % a.frames)
        return 2
    names = sorted(n for n in os.listdir(a.frames)
                   if n.startswith("n") and n.endswith(".png"))
    if not names:
        print("%s 下没有 n%05d.png" % a.frames)
        return 2
    first = int(names[0][1:6])
    last = int(names[-1][1:6])

    frm = first if a.frm is None else max(first, a.frm)
    to = last if a.to is None else min(last, a.to)
    if to < frm:
        print("--from 比 --to 大, 或区间里没有帧")
        return 2

    every = a.every if a.every else auto_step(last - first + 1, frm, to, a.max_frames)
    picked = frame_paths(a.frames, frm, to, every)
    if not picked:
        print("区间里没有可读的帧")
        return 2
    if len(picked) > a.max_frames:
        print("抽到 %d 帧, 超过 --max-frames %d, 已按步长 %d 再抽一次"
              % (len(picked), a.max_frames, every))
        picked = picked[::max(1, len(picked) // a.max_frames + 1)][:a.max_frames]

    if a.width < 32 or a.fps <= 0:
        print("--width 至少 32, --fps 要大于 0")
        return 2

    base = Image.open(picked[0][1]).convert("RGB")
    w = int(a.width)
    h = max(1, int(round(base.height * w / float(base.width))))
    frames = [Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
              for _, p in picked]

    # 统一调色板: 逐帧各自量化会让同一块背景在帧间跳色, 看起来像闪
    k = min(len(frames), 8)
    strip = Image.new("RGB", (w, h * k))
    for i in range(k):
        strip.paste(frames[i * len(frames) // k], (0, i * h))
    pal = strip.quantize(colors=255, method=Image.MEDIANCUT)
    quants = [f.quantize(palette=pal, dither=Image.FLOYDSTEINBERG) for f in frames]

    parent = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(parent, exist_ok=True)
    dur = int(round(1000.0 / a.fps))
    quants[0].save(a.out, save_all=True, append_images=quants[1:],
                   duration=dur, loop=0, optimize=True)

    size_mb = os.path.getsize(a.out) / 1048576.0
    print("抽帧 %d 张 (步长 %d, 帧号 %d 到 %d)" % (len(picked), every, frm, to))
    print("wrote %s  %dx%d  %d ms/帧  约 %.1f 秒循环  %.2f MB"
          % (a.out, w, h, dur, len(picked) / a.fps, size_mb))
    print("提醒: GIF 无声音只有 256 色, 只用于看运动, 不能替代用户过目成片")
    return 0


if __name__ == "__main__":
    sys.exit(main())

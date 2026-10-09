# -*- coding: utf-8 -*-
"""
PSNR 复测: 把源帧与视频流或成片逐帧对齐量 PSNR, 作为独立命令随时可跑

  python scripts/psnr_check.py --frames temp/frames_proj --video temp/_video_only.mp4
  python scripts/psnr_check.py --frames temp/frames_proj --video out/成片.mp4
  python scripts/psnr_check.py --frames temp/frames_proj --video out/成片.mp4 --count 240
  python scripts/psnr_check.py --frames temp/frames_proj --video out/成片.mp4 --json temp/psnr.json

为什么单开这条命令: ffmpeg 的 psnr 滤镜对输入顺序与参照物极其敏感, 口径错一次,
均值可以从 49dB 掉到 17.5dB, 看起来像画质崩了, 其实是量法错了. 两条硬规则在这里
固定住, 不要手写命令:
  1 顺序: 源帧在 [0:v], 视频在 [1:v], lavfi 写成 "[0:v][1:v]psnr"; 反了就是拿视频当参照
  2 参照物: 本来的口径是编码前的无损视频流 (分批路线的 _video_only.mp4, 拼接后混音前);
    对成片量时响度归一与重封装都不动视频流, 均值只应比视频流口径低不到 0.5dB,
    差得多说明成片与源帧不是同一条视频, 先查改过的帧有没有用 --redo 重编

判据: average 高于 45dB 为视觉无损, 低于 40dB 说明 CRF 给大了或帧不对齐
(分批路线见 SKILL.md 铁律 21).
帧目录缺帧时会在启动前报出来: 缺帧对齐错位会把后面所有帧的差值算到错的对象上.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# 与 canvas.FRAME_PATTERN 保持一致; 不 import canvas, 单独复制走也能跑
FRAME_PATTERN = "n%05d.png"
PSNR_FLOOR = 45.0


def count_frames(frames):
    """数帧目录里按 FRAME_PATTERN 命名的帧数, 并返回最大帧号"""
    if not os.path.isdir(frames):
        return 0, -1
    n = 0
    mx = -1
    for name in os.listdir(frames):
        if name.startswith("n") and name.endswith(".png") and name[1:-4].isdigit():
            n += 1
            mx = max(mx, int(name[1:-4]))
    return n, mx


def missing_frames(frames, total):
    """[0, total) 里缺掉的帧号列表"""
    return [i for i in range(int(total))
            if not os.path.exists(os.path.join(frames, FRAME_PATTERN % i))]


def video_frames(video):
    """ffprobe 读视频流帧数; 读不到就用时长乘帧率估算"""
    exe = shutil.which("ffprobe") or "ffprobe"
    p = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames,avg_frame_rate:format=duration",
         "-of", "default=nw=1", video],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    nb = None
    fps = None
    dur = None
    for line in (p.stdout or "").splitlines():
        k, _, v = line.partition("=")
        v = v.strip()
        if k == "nb_frames" and v.isdigit():
            nb = int(v)
        elif k == "avg_frame_rate" and "/" in v:
            a, _, b = v.partition("/")
            try:
                if float(b):
                    fps = float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                pass
        elif k == "duration":
            try:
                dur = float(v)
            except ValueError:
                pass
    if nb is None and dur is not None and fps:
        nb = int(round(dur * fps))
    return nb


def run_psnr(frames, video, count, fps):
    """跑量测, 返回 (均值或 None, 原始输出尾部)"""
    pattern = os.path.join(frames, FRAME_PATTERN)
    cmd = ["ffmpeg", "-hide_banner", "-nostats",
           "-framerate", str(fps), "-i", pattern,
           "-i", video, "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"]
    if count and count > 0:
        cmd += ["-frames:v", str(count)]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    hits = re.findall(r"average:(\d+(?:\.\d+)?)", out)
    return (float(hits[-1]) if hits else None), out


def main(argv=None):
    ap = argparse.ArgumentParser(description="PSNR 复测: 源帧对视频流或成片")
    ap.add_argument("--frames", default=os.path.join("temp", "frames"),
                    help="源帧目录, 里面是 n%%05d.png")
    ap.add_argument("--video", required=True,
                    help="对齐对象: 编码后的视频流 (口径最准) 或成片")
    ap.add_argument("--count", type=int, default=0,
                    help="只量前 N 帧 (抽检用), 0 表示全量")
    ap.add_argument("--fps", type=float, default=30.0, help="帧序列的帧率")
    ap.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.isdir(a.frames):
        print("找不到帧目录: %s" % a.frames)
        return 2
    if not os.path.exists(a.video):
        print("找不到视频: %s" % a.video)
        return 2

    total, mx = count_frames(a.frames)
    if total == 0:
        print("帧目录里没有 %s 命名的帧: %s" % (FRAME_PATTERN, a.frames))
        return 2
    expected = mx + 1
    if expected != total:
        miss = missing_frames(a.frames, expected)
        head = ", ".join(str(x) for x in miss[:8])
        more = "" if len(miss) <= 8 else " 等 %d 处" % len(miss)
        print("错误: 帧号 [0, %d) 有空洞 (应为 %d 张, 实际 %d 张): %s%s"
              % (expected, expected, total, head, more))
        print("  缺帧会让对齐错位, 量出来的均值没有意义; 先补帧或改用 --count 量缺帧之前的段")
        return 2

    vnb = video_frames(a.video)
    print("源帧   : %s  共 %d 帧" % (a.frames, total))
    print("对齐   : %s  视频流 %s 帧"
          % (a.video, ("%d" % vnb) if vnb else "未知"))
    if vnb and abs(vnb - total) > 1:
        print("[警告] 帧数差 %d 帧: 视频流与源帧不是同一条视频, 结果不可信, 先查 --redo"
              % abs(vnb - total))
    if a.count:
        print("抽检   : 只量前 %d 帧" % a.count)

    v, out = run_psnr(a.frames, a.video, a.count, a.fps)
    if v is None:
        print("没量到 PSNR, ffmpeg 输出尾部:")
        print("\n".join(out.strip().splitlines()[-6:]))
        return 2
    verdict = "视觉无损" if v >= PSNR_FLOOR else (
        "不合格: 先查帧对齐 (--redo), 再查 CRF" if v < 40.0 else "偏低, 查 CRF 与帧对齐")
    print("PSNR average: %.2f dB  判据高于 %.0f dB, %s" % (v, PSNR_FLOOR, verdict))
    print("参照口径: 源帧 [0:v] 对视频 [1:v]; 对成片量只应比视频流口径低不到 0.5dB")

    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as fp:
            json.dump({"frames": a.frames, "frames_count": total,
                       "video": a.video, "video_frames": vnb,
                       "count": a.count, "fps": a.fps,
                       "psnr_average": v}, fp, ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

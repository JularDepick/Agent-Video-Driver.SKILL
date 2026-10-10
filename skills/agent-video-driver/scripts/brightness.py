# -*- coding: utf-8 -*-
"""
亮度标定: 对着参考片量均值, 中位数与 p95, 判断底色深浅与字幕亮度是否对得上
支持一次传多个输入 (逐屏终检时把整段帧逐张传进来), 并可把结果写成一张 markdown 表

编码与调色的头号问题是整体亮了 2 到 3 倍还看不出来, 显示器会骗人. 所以判据不是"看着差不多",
而是与参考片在相同位置量出来的三个数比.

  python scripts/brightness.py out/成片.mp4 --at 5 20 45
  python scripts/brightness.py out/成片.mp4 --at 20 --ref 参考片.mp4 --ref-at 20
  python scripts/brightness.py temp/frames_proj/n001200.png
  python scripts/brightness.py out/成片.mp4 --json temp/brightness.json
  python scripts/brightness.py temp/qa/screen01.png temp/qa/screen02.png --md temp/qa/brightness.md
  python scripts/brightness.py --at 12.5 temp/frames_proj/n00375.png --md temp/bright.md

判据:
  中位数决定底色深浅, 暗场片常在 5 到 30 之间
  亮部决定字幕亮度, 白字约 200 到 250; p95 与 p99 达标其一即算通过
    (暗场少亮元素的构图里, 亮字面积不足 5%, p95 天然落在底色亮度上, 只看 p95 会系统性误报)
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
# 亮部判据的两个分位数下限; 达标其一即算通过, 原因见 judge()
P95_MIN = 120.0
P99_MIN = 120.0
# 亮部面积占比低于这个值时, p95 必然落在底色亮度上, 不能拿它判"白字不亮"
BRIGHT_FRAC_LOW = 0.05


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
    抽到的不是目标帧, 判据就失效了 (见 pitfalls.md 的抽帧一条).
    与 qa.py 的 grab 同一条规矩: 请求时间往前挪半帧再格式化, 否则浮点进位会
    把抽帧整体推到下一帧, 亮度对照的口径就错了.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found, 请确认它在 PATH 中")
    ss = max(0.0, t - 0.5 / 30.0)
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video,
                        "-ss", "%.6f" % ss, "-frames:v", "1", out_path],
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
    """
    按参考片判底色与字幕, 返回 [(级别, 提示), ...], 级别取 "fail" 或 "info"

    亮部判据用 p95 与 p99 达标其一, 不单看 p95: p95 本质在量亮色像素的面积占比,
    暗场蓝底占 75% 像素而亮字面积不足 5% 的屏, p95 天然落在底色亮度上, 与"白字不亮"
    无关. 实测一组 27 屏的片子里 11 屏被单看 p95 的判据误报, 逐屏字符图核对构图全部完整
    """
    notes = []
    if ref is not None:
        for k in ("mean", "median", "p95"):
            a, b = ms[k], ref[k]
            if b <= 1e-6:
                continue
            r = a / b
            if r >= 2.0 or r <= 0.5:
                notes.append(("fail", "%s 是参考的 %.2f 倍 (%s 对 %s), 偏离 2 倍以上, "
                                      "先查管线再谈调色" % (k, r, a, b)))
    if ms["median"] > 120.0:
        notes.append(("fail", "中位数 %.1f 偏高, 这是亮场片的量级; 暗场片应落在 5 到 30 之间"
                      % ms["median"]))
    p95, p99 = ms["p95"], ms["p99"]
    frac = ms["bright_frac"]
    if p95 < P95_MIN and p99 < P99_MIN:
        notes.append(("fail", "p95 与 p99 都只有 %.1f 与 %.1f, 亮部确实不够亮 (亮部面积占 %.2f%%); "
                              "白字应在 200 到 250, 先加宽主句或给每屏加一道全宽亮色顶杠补面积, "
                              "最后才调配色" % (p95, p99, frac * 100.0)))
    elif p95 < P95_MIN:
        notes.append(("info", "p95 只有 %.1f 但 p99 有 %.1f, 判为通过: 亮部面积只占 %.2f%%, "
                              "低于 %.0f%%, p95 落在底色亮度上是暗场构图的正常现象, "
                              "不是白字不亮" % (p95, p99, frac * 100.0, BRIGHT_FRAC_LOW * 100.0)))
    if ms["dark_frac"] > 0.98:
        notes.append(("fail", "暗部占比 %.3f, 整帧几乎全黑, 检查这一段是不是渲成了空场"
                      % ms["dark_frac"]))
    return notes


def write_md(path, groups):
    """
    把量测结果写成一张 markdown 表

    groups 是 [(输入路径, [rows], [notes]), ...]; 提示正文只留在 stdout,
    表里的提示列只标该输入有没有判据提示, 避免表格里塞长句
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    lines = ["| 输入 | 时刻s | 均值 | 中位数 | p95 | p99 | 暗部 | 亮部 | 提示 |",
             "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"]
    for label, rows, notes in groups:
        tip = "有 %d 条, 见输出" % len(notes) if notes else "-"
        for t, m in rows:
            lines.append("| %s | %s | %.2f | %.2f | %.1f | %.2f | %.4f | %.4f | %s |"
                         % (label, "-" if t is None else "%.2f" % t,
                            m["mean"], m["median"], m["p95"], m["p99"],
                            m["dark_frac"], m["bright_frac"], tip))
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description="亮度标定: 量均值, 中位数与 p95, 可与参考片对比")
    ap.add_argument("inputs", nargs="+", help="成片, 视频片段或帧图, 可给多个 (逐屏表就逐张传)")
    ap.add_argument("--at", type=float, nargs="+", default=None,
                    help="抽帧时刻秒数, 可给多个; 缺省取片长的 1/4 与 3/4 两处")
    ap.add_argument("--ref", default=None, help="参考片或参考帧图, 只与最后一个输入对比")
    ap.add_argument("--ref-at", dest="ref_at", type=float, nargs="+", default=None,
                    help="参考片的抽帧时刻, 缺省与 --at 相同")
    ap.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON 的路径")
    ap.add_argument("--md", dest="md_path", default=None,
                    help="把结果写成 markdown 表的路径, 逐屏终检用")
    a = ap.parse_args()

    for p in a.inputs:
        if not os.path.exists(p):
            print("找不到文件: %s" % p)
            return 2
    if a.ref and not os.path.exists(a.ref):
        print("找不到参考文件: %s" % a.ref)
        return 2

    times = a.at
    if times is None:
        if any(is_video(p) for p in a.inputs):
            times = [10.0, 30.0]
        else:
            times = [0.0]
    ref_times = a.ref_at if a.ref_at else times

    try:
        groups = []
        for idx, src in enumerate(a.inputs):
            rows = analyse(src, times)
            ref_rows = analyse(a.ref, ref_times) if (a.ref and idx == len(a.inputs) - 1) else None
            notes = []
            for i, (t, m) in enumerate(rows):
                ref = None
                if ref_rows:
                    ref = ref_rows[i][1] if i < len(ref_rows) else ref_rows[-1][1]
                got = judge(m, ref)
                if got:
                    notes.append((t, got))
            groups.append((src, rows, notes))
    except Exception as e:
        print("量测失败: %s" % e)
        return 2

    print("=" * 66)
    print("亮度标定: %d 个输入" % len(a.inputs))
    print("=" * 66)
    any_fail = False
    any_info = False
    for src, rows, notes in groups:
        print("")
        print("[%s]" % src)
        print("%-10s %8s %8s %8s %8s %8s %8s"
              % ("时刻(s)", "均值", "中位数", "p95", "p99", "暗部", "亮部"))
        for t, m in rows:
            print("%-10s %8.2f %8.2f %8.2f %8.2f %8.4f %8.4f"
                  % ("-" if t is None else "%.2f" % t, m["mean"], m["median"], m["p95"],
                     m["p99"], m["dark_frac"], m["bright_frac"]))
        print("中位数 RGB: " + "   ".join(
            "%s -> %s" % ("-" if t is None else "%.1fs" % t, m["median_rgb"]) for t, m in rows))
        for t, got in notes:
            fails = [x for lv, x in got if lv == "fail"]
            infos = [x for lv, x in got if lv == "info"]
            if fails:
                any_fail = True
            if infos:
                any_info = True
            if not fails and not infos:
                continue
            print("时刻 %s:" % ("-" if t is None else "%.2f" % t))
            for x in fails:
                print("  [不合格] %s" % x)
            for x in infos:
                print("  [说明] %s" % x)
    if not any_fail:
        print("")
        print("判据全部通过: 底色与字幕亮度都落在区间内" if not any_info
              else "判据全部通过: 底色与字幕亮度都落在区间内 (上面 [说明] 行是误报解释, 不是不合格项)")

    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as fp:
            json.dump({"inputs": a.inputs,
                       "groups": [{"input": src,
                                   "rows": [{"t": t, **m} for t, m in rows]}
                                  for src, rows, _ in groups],
                       "ref": a.ref}, fp, ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    if a.md_path:
        write_md(a.md_path, groups)
        print("wrote %s" % a.md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

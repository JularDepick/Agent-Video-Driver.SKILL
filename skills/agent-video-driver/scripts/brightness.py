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
   近黑 (luma < 18) 与近白 (luma > 250) 的占比各报一个数:
     亮色系画面上出现近黑像素, 说明有纯黑残留 (忘了填的底, 蒙版没盖住的边);
     暗色系上把文字写成纯白, 换到浅底平台就整段隐形, 近白占比高才看得出这个风险
   色带统计最长同值连续段与这种段的总数:
     相邻像素完全同值的大段就是 banding 的信号. 是否算问题取决于画面本身有没有
     大面积渐变 (纯色块的同值段天然很长但不是色带), 所以只给数不给阈值
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
# 近黑与近白的判定线. 这两个值比 DARK_MAX 与 BRIGHT_MIN 更极端, 量的是"画面上有没有
# 纯黑残留"与"有没有写成纯白的字", 而不是底色深浅
NEAR_BLACK = 18.0
NEAR_WHITE = 250.0
# 色带统计里算作一段的最短同值连续长度; 比这更短的同值段是纯色块之间的正常边界
BAND_MIN_RUN = 3


def luma(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def banding(y, min_run=BAND_MIN_RUN):
    """
    色带 (banding) 的阶跃统计: 返回 (最长同值连续段的长度, 这种段的总数)

    大面积渐变被量化成 8 bit 后, 相邻像素会有一长串完全同值, 人眼看到的就是一圈圈的
    色带. 所以统计每行里"相邻像素亮度差为 0"的连续段: 渐变越平滑越宽, 这种段越长.
    只数长度达到 min_run 的段, 短段是纯色块之间的正常边界, 数进来会淹没信号.
    这里不给硬性阈值: 画面本来就是纯色块时同值段天然很长却没有色带, 是否算问题取决于
    这一帧有没有大面积渐变, 那要人看字符图才知道

    段边界靠两次 diff 找: 首尾各补一个 False 后, 每个 True 段必然贡献一个 +1 与一个 -1,
    按行取到的起点与终点天然两两对齐. 逐行逐列写 Python 循环要跑两百万步, 太慢.
    段长按像素数算 (差的个数加 1): 报"10 个像素连着同值"比报"9 个相邻差为 0"直观
    """
    yi = np.rint(y).astype(np.int64)
    if yi.shape[1] < 2:
        return 0, 0
    same = (np.diff(yi, axis=1) == 0)
    padded = np.zeros((same.shape[0], same.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = same.astype(np.int8)
    d = np.diff(padded, axis=1)
    starts = np.argwhere(d == 1)[:, 1]
    ends = np.argwhere(d == -1)[:, 1]
    if starts.size == 0:
        return 0, 0
    lengths = (ends - starts) + 1
    kept = lengths[lengths >= min_run]
    if kept.size == 0:
        return 0, 0
    return int(kept.max()), int(kept.size)


def measure(path):
    """量一张图的亮度统计, 返回 dict"""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    y = luma(a)
    bl, bt = banding(y)
    return {
        "file": path,
        "size": [int(a.shape[1]), int(a.shape[0])],
        "mean": round(float(y.mean()), 2),
        "median": round(float(np.median(y)), 2),
        "p95": round(float(np.percentile(y, 95)), 2),
        "p99": round(float(np.percentile(y, 99)), 2),
        "dark_frac": round(float((y < DARK_MAX).mean()), 4),
        "bright_frac": round(float((y > BRIGHT_MIN).mean()), 4),
        "near_black_frac": round(float((y < NEAR_BLACK).mean()), 4),
        "near_white_frac": round(float((y > NEAR_WHITE).mean()), 4),
        "band_longest": bl,
        "band_runs": bt,
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
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    lines = ["| 输入 | 时刻s | 均值 | 中位数 | p95 | p99 | 暗部 | 亮部 | 近黑 | 近白 | 同值段 | 段数 | 提示 |",
             "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"]
    for label, rows, notes in groups:
        tip = "有 %d 条, 见输出" % len(notes) if notes else "-"
        for t, m in rows:
            lines.append("| %s | %s | %.2f | %.2f | %.1f | %.2f | %.4f | %.4f | %.4f | %.4f | %d | %d | %s |"
                         % (label, "-" if t is None else "%.2f" % t,
                            m["mean"], m["median"], m["p95"], m["p99"],
                            m["dark_frac"], m["bright_frac"],
                            m["near_black_frac"], m["near_white_frac"],
                            m["band_longest"], m["band_runs"], tip))
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
    print("新增三列的读法:")
    print("  近黑占比是 luma < %.0f 的像素占比: 亮色系画面上它不是 0, 说明有纯黑残留"
          % NEAR_BLACK)
    print("  近白占比是 luma > %.0f 的像素占比: 暗色系画面上它高, 说明文字写成了纯白, "
          "换浅底时会隐形" % NEAR_WHITE)
    print("  同值段与段数是相邻像素亮度完全相等的最长连续段长度与这种段的总数: "
          "大段同值是色带的信号, 但是否算问题取决于这一帧有没有大面积渐变, "
          "纯色块的同值段天然很长, 所以不给阈值")
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
        print("%-10s %8s %8s %8s %8s" % ("时刻(s)", "近黑", "近白", "同值段", "段数"))
        for t, m in rows:
            print("%-10s %8.4f %8.4f %8d %8d"
                  % ("-" if t is None else "%.2f" % t, m["near_black_frac"],
                     m["near_white_frac"], m["band_longest"], m["band_runs"]))
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
    # any_fail 已经算出来了, 就让它落到退出码上: 0 全部通过, 1 有不合格项,
    # 2 用法或量测失败 (前面已返回). 只打印不改退出码的话, 按退出码判断的自动化
    # 分不出"跑过了"和"合格", 判据就只是一段输出文本.
    if any_fail:
        print("")
        print("[不合格] 上面标 [不合格] 的项都需处理后再交付")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

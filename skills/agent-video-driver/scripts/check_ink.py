# -*- coding: utf-8 -*-
"""
墨迹体检: 拿着 check_layout.py 抽出来的文字框, 到已经渲出来的帧上量"这个框里到底有没有字"

  python scripts/check_ink.py temp/qa/screen01.png --blocks temp/qa/layout.json
  python scripts/check_ink.py temp/qa/screen01.png --blocks temp/qa/layout.json --min-coverage 0.02
  python scripts/check_ink.py temp/qa/screen01.png --blocks temp/qa/layout.json --func s_title
  python scripts/check_ink.py temp/frames_proj --blocks temp/qa/layout.json --limit 12

为什么要单独有这一件: 面板画出来了而框里的字没画 (或者糊到看不出来) 是一类静默失败,
整帧平均亮度完全正常, 逐帧差分也看不出来 (它每帧都一样), 亮度体检与版面体检都抓不到.
check_layout.py 只回答"这些框会不会互相压字", 它是静态的, 不执行场景模块也不渲染整帧;
本脚本是它的下游, 只回答"框里的字到底画出来了吗"这一个问题, 两件合起来才算收口.

判据:
  墨迹覆盖率  框内与底板亮度差超过 40 的像素占该框面积的比例, 每个框不低于 2% (--min-coverage 改)
  底板亮度    取该框外扩一圈的区域的中位数亮度近似, 不要求另给背景图
  对比度      框内 luma 的 95 分位与底板 luma 的中位数, 按 (L1+0.05)/(L2+0.05) 算, 只提示不判

底板取外扩圈的中位数而不是框内中位数: 字没画出来时框内中位数就等于底板自己, 拿它当底板
会把"没画字"量成"处处零差异", 覆盖率判据会漏报; 外扩圈取的是字周围的纸, 与框内独立.
对比度只提示不强判, 是因为不同配色方案的目标不同: 有的牌面故意做低对比的压印感,
统一按 4.5 比 1 判会把正常的风格判成缺陷.

退出码: 全部达标 0, 有框不达标 1, 参数错误 2
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 与底板亮度差超过这个值才算墨迹: 40 是 8 位 luma 上"肉眼能确定这里有东西"的量级,
# 再低就会把底噪, 颗粒与 JPEG 振铃一起收进来
INK_DIFF = 40.0
# 默认覆盖率下限; 中文墨迹在自己墨迹框里通常占 20% 以上, 2% 是"确实画了字"的宽松下限
DEFAULT_MIN_COVERAGE = 0.02
# 外扩圈宽度取框高的这个倍数, 至少 2 px: 框高比框宽更能代表字号量级, 而框宽常常横跨整屏
DEFAULT_PAD_RATIO = 0.15
PAD_MIN = 2
# 框内亮部 p95 与底板的相对差低于这个值时两者几乎同色, 覆盖率判据只会一直叫, 得先调配色
PLATE_DIFF_LOW = 0.06
# 对比度提示线: WCAG 对大字的下限, 低于它字与底板偏同色, 只提示
CONTRAST_HINT = 3.0
FRAME_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
FRAME_LIST_MAX = 24
FAIL_LIST_MAX = 40


def luma(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def rel_lum(y):
    """
    把一个 8 位 luma 折算成相对亮度

    严格做法是逐通道线性化再加权, 但覆盖率判据全程只用标量 luma (框内要取分位数,
    逐通道取分位数没有意义), 这里对标量 luma 单独走一次 sRGB 传递函数, 保证与 WCAG 的
    (L1+0.05)/(L2+0.05) 同一口径, 并且在 luma 上单调
    """
    c = min(255.0, max(0.0, float(y))) / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def contrast(y1, y2):
    a, b = rel_lum(y1), rel_lum(y2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def preview(s, n=18):
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def load_blocks(path):
    """
    读 check_layout.py --json 的落盘结果, 返回 (可用框, 跳过清单)

    字段名按 check_layout.py 里写 JSON 的那一段对齐: 顶层 blocks 是块数组, 每块带
    line / func / call / text / kind / size / anchor / rect{left,top,right,bottom} / source.
    缺 rect 或 rect 不是数值的块按跳过处理并提示, 不猜坐标
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("blocks", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return [], [{"text": "", "why": "JSON 里没有 blocks 数组, 认不出框"}]
    blocks = []
    skipped = []
    for item in raw:
        if not isinstance(item, dict):
            skipped.append({"text": "", "why": "块不是对象"})
            continue
        text = item.get("text", "")
        rect = item.get("rect")
        why = ""
        if not isinstance(rect, dict):
            why = "没有 rect 字段, 缺框的位置按跳过处理"
        else:
            try:
                box = (float(rect["left"]), float(rect["top"]),
                       float(rect["right"]), float(rect["bottom"]))
            except (KeyError, TypeError, ValueError):
                why = "rect 的四个边界不是数值, 按跳过处理"
            else:
                if box[2] <= box[0] or box[3] <= box[1]:
                    why = "rect 是空的或反向的, 按跳过处理"
        if why:
            skipped.append({"text": preview(text), "why": why})
            continue
        size = item.get("size")
        try:
            size = float(size)
        except (TypeError, ValueError):
            size = None
        blocks.append({"line": item.get("line", 0),
                       "func": item.get("func", "<module>"),
                       "call": item.get("call", ""),
                       "text": text,
                       "size": size,
                       "box": box,
                       "source": item.get("source", "")})
    return blocks, skipped


def frame_luma(path):
    """读一帧, 返回 (luma 二维数组, 宽, 高)"""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    return luma(a), int(a.shape[1]), int(a.shape[0])


def list_frames(d):
    names = [n for n in sorted(os.listdir(d))
             if os.path.splitext(n)[1].lower() in FRAME_EXTS]
    return [os.path.join(d, n) for n in names]


def measure_one(y, w, h, box, scale, pad_ratio):
    """
    在 luma 图 y 上量一个框, 返回量测 dict; 框完全落在帧外时返回 None

    check_layout.py 的框是 canvas 设计坐标, 传进来的帧若没降采样 (超采样中间图),
    用 --scale 对齐, 缺省 1.0
    """
    xs = [box[0] * scale, box[2] * scale]
    ys = [box[1] * scale, box[3] * scale]
    x0 = max(0, min(w, int(round(min(xs)))))
    x1 = max(0, min(w, int(round(max(xs)))))
    y0 = max(0, min(h, int(round(min(ys)))))
    y1 = max(0, min(h, int(round(max(ys)))))
    if x1 <= x0 or y1 <= y0:
        return None
    inner = y[y0:y1, x0:x1]
    pad = max(PAD_MIN, int(round(pad_ratio * (y1 - y0))))
    ox0, oy0 = max(0, x0 - pad), max(0, y0 - pad)
    ox1, oy1 = min(w, x1 + pad), min(h, y1 + pad)
    outer = y[oy0:oy1, ox0:ox1]
    vals = np.empty(0, dtype=np.float32)
    if outer.size:
        mask = np.ones(outer.shape, dtype=bool)
        mask[y0 - oy0:y1 - oy0, x0 - ox0:x1 - ox0] = False
        vals = outer[mask]
    if vals.size:
        plate = float(np.median(vals))
        plate_src = "外扩圈"
    else:
        # 框顶到画幅边缘时外扩圈可能是空的, 退回整帧中位数, 否则底板量不出来
        plate = float(np.median(y))
        plate_src = "整帧"
    med = float(np.median(inner))
    p95 = float(np.percentile(inner, 95))
    return {"box": (x0, y0, x1, y1),
            "area": int(inner.size),
            "coverage": float((np.abs(inner - plate) > INK_DIFF).mean()),
            "plate": plate,
            "plate_src": plate_src,
            "median": med,
            "p95": p95,
            "contrast": contrast(p95, plate),
            # 框内中位数在"字稀而清晰"的正常case里就等于底板自己 (中位数天然忽略少数亮像素),
            # 只有框亮到 p95 也贴着底板时才说明字与底板同色, 所以这里看 p95 而不是中位数
            "plate_diff": abs(p95 - plate) / 255.0}


def run_frame(path, blocks, min_cov, scale, pad_ratio):
    """对一帧上的全部框量一遍, 返回该帧的结果 dict"""
    y, w, h = frame_luma(path)
    rows = []
    outside = []
    for b in blocks:
        m = measure_one(y, w, h, b["box"], scale, pad_ratio)
        if m is None:
            outside.append(b)
            continue
        m["block"] = b
        m["pass"] = m["coverage"] >= min_cov
        rows.append(m)
    worst = min((r["coverage"] for r in rows), default=0.0)
    return {"file": path, "size": (w, h), "rows": rows,
            "outside": outside, "worst": worst,
            "fails": [r for r in rows if not r["pass"]]}


def print_header(n_frames, n_blocks, min_cov):
    print("=" * 84)
    print("墨迹体检: %d 帧, %d 个文字框, 判据 每个框的墨迹覆盖率不低于 %.2f%%"
          % (n_frames, n_blocks, min_cov * 100.0))
    print("=" * 84)


def print_table(res):
    print("")
    print("[%s] %dx%d" % (res["file"], res["size"][0], res["size"][1]))
    print("%-6s %-14s %-20s %8s %9s %9s %-8s"
          % ("行", "函数", "文本", "字号", "覆盖率", "对比度", "判定"))
    for r in res["rows"]:
        b = r["block"]
        print("%-6s %-14s %-20s %8s %8.2f%% %9.2f %-8s"
              % (b["line"], preview(b["func"], 14), preview(b["text"], 20),
                 "-" if b["size"] is None else "%.1f" % b["size"],
                 r["coverage"] * 100.0, r["contrast"],
                 "通过" if r["pass"] else "不达标"))


def print_fail(r, min_cov):
    """打一条不合格明细, 并按"底板与背景明度差"给一句定位提示"""
    b = r["block"]
    print("  行 %s (%s) \"%s\""
          % (b["line"], b["func"], preview(b["text"], 24)))
    print("      框 %d, %d 到 %d, %d, 覆盖率 %.2f%% (判据 %.2f%%), 框内 luma 中位数 %.1f, "
          "底板 %.1f (%s), 对比度 %.2f"
          % (r["box"][0], r["box"][1], r["box"][2], r["box"][3],
             r["coverage"] * 100.0, min_cov * 100.0,
             r["median"], r["plate"], r["plate_src"], r["contrast"]))
    if r["plate_diff"] < PLATE_DIFF_LOW:
        # 这句只在真的不达标时才打: 达标的框偶尔也贴着底板, 打出来是噪声, 还会让人误判成因
        print("      提示: 框内亮部与底板只差 %.1f%%, 低于 %.0f%%, 两者几乎同色, "
              "先调配色再谈判据"
              % (r["plate_diff"] * 100.0, PLATE_DIFF_LOW * 100.0))


def print_notes(results, skipped, min_cov):
    """打对比度提示, 跳过清单与处置建议"""
    hints = []
    for res in results:
        for r in res["rows"]:
            if r["contrast"] < CONTRAST_HINT:
                hints.append((res["file"], r))
    if hints:
        print("")
        print("[说明] %d 个框的对比度低于 %.1f, 字与底板偏同色 (配色方案的目标不同, 不作为不合格项):"
              % (len(hints), CONTRAST_HINT))
        for f, r in hints[:12]:
            print("  %s 行 %s \"%s\": 对比度 %.2f"
                  % (os.path.basename(f), r["block"]["line"],
                     preview(r["block"]["text"], 20), r["contrast"]))
        if len(hints) > 12:
            print("  ... 另有 %d 个" % (len(hints) - 12))

    outside = []
    for res in results:
        for b in res["outside"]:
            outside.append((res["file"], b))
    if outside:
        print("")
        print("[跳过] %d 个框完全落在帧外或尺寸为零, 未参与判定:" % len(outside))
        seen = set()
        for f, b in outside:
            key = (b["line"], b["text"])
            if key in seen:
                continue
            seen.add(key)
            print("  行 %s \"%s\" (%s)" % (b["line"], preview(b["text"], 20), os.path.basename(f)))
    if skipped:
        print("")
        print("[跳过] %d 个框拿不到可判定的位置, 未参与判定:" % len(skipped))
        for s in skipped[:12]:
            print("  \"%s\": %s" % (s["text"], s["why"]))
        if len(skipped) > 12:
            print("  ... 另有 %d 个" % (len(skipped) - 12))

    print("")
    print("说明: 底板取框外扩一圈的中位数亮度, 不要求另给背景图; 覆盖率是框内与底板亮度差")
    print("      超过 %d 的像素占框面积的比例; 对比度按 (L1+0.05)/(L2+0.05) 算, 只提示不判."
          % int(INK_DIFF))
    print("      一帧只画一幕, 而 layout.json 里是所有幕的文字框, 跨幕的框会误报, 用 --func 指定幕")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="墨迹体检: 到渲染出来的帧上量 check_layout.py 抽出的文字框里有没有字")
    ap.add_argument("frame", help="帧图片路径, 或帧目录 (目录则逐帧跑并汇总最差的一帧)")
    ap.add_argument("--blocks", required=True,
                    help="check_layout.py --json 落盘的 JSON 路径")
    ap.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE,
                    help="墨迹覆盖率下限 (缺省 %.2f)" % DEFAULT_MIN_COVERAGE)
    ap.add_argument("--func", action="append", default=[], metavar="NAME",
                    help="只判定该幕函数里的框 (layout.json 含全部幕, 可重复)")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="框坐标到帧像素的缩放, 帧是超采样中间图时给超采样倍数 (缺省 1.0)")
    ap.add_argument("--pad-ratio", type=float, default=DEFAULT_PAD_RATIO,
                    help="底板外扩圈宽度, 单位是框高 (缺省 %.2f)" % DEFAULT_PAD_RATIO)
    ap.add_argument("--limit", type=int, default=0,
                    help="帧目录里最多取前多少帧, 0 表示全部 (缺省 0)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.frame):
        print("错误: 找不到帧或帧目录 %s" % args.frame)
        return 2
    if not os.path.exists(args.blocks):
        print("错误: 找不到 --blocks 的 JSON %s" % args.blocks)
        return 2
    if not (0.0 < args.min_coverage <= 1.0):
        print("错误: --min-coverage 要落在 (0, 1] 之间, 现在是 %s" % args.min_coverage)
        return 2
    if args.scale <= 0:
        print("错误: --scale 要大于 0, 现在是 %s" % args.scale)
        return 2
    if args.pad_ratio < 0:
        print("错误: --pad-ratio 不能为负, 现在是 %s" % args.pad_ratio)
        return 2
    if args.limit < 0:
        print("错误: --limit 不能为负, 现在是 %s" % args.limit)
        return 2

    try:
        blocks, skipped = load_blocks(args.blocks)
    except (OSError, ValueError) as e:
        print("错误: 读 --blocks 失败: %s" % e)
        return 2
    if args.func:
        keep = set(args.func)
        blocks = [b for b in blocks if b["func"] in keep]
    if not blocks:
        print("错误: %s 里没有可判定的文字框 (可用块被 --func 过滤空了, 或 rect 全部缺失)" % args.blocks)
        return 2

    if os.path.isdir(args.frame):
        files = list_frames(args.frame)
        if not files:
            print("错误: 帧目录里没有图片 (%s)" % ", ".join(FRAME_EXTS))
            return 2
        if args.limit:
            files = files[:args.limit]
        is_dir = True
    else:
        files = [args.frame]
        is_dir = False

    try:
        results = [run_frame(f, blocks, args.min_coverage, args.scale, args.pad_ratio)
                   for f in files]
    except (OSError, ValueError) as e:
        print("错误: 量测失败: %s" % e)
        return 2

    print_header(len(results), len(blocks), args.min_coverage)
    total_fail = sum(len(r["fails"]) for r in results)
    worst = min(results, key=lambda r: r["worst"])

    if is_dir:
        print("")
        print("每帧最差覆盖率 (%d 帧):" % len(results))
        for res in results[:FRAME_LIST_MAX]:
            print("  %-28s 最低 %6.2f%%  不达标 %d 个"
                  % (os.path.basename(res["file"]), res["worst"] * 100.0, len(res["fails"])))
        if len(results) > FRAME_LIST_MAX:
            print("  ... 另有 %d 帧" % (len(results) - FRAME_LIST_MAX))

    print_table(worst if is_dir else results[0])

    print("")
    if total_fail:
        print("[不合格] %d 个框次不达标 (判据 覆盖率不低于 %.2f%%):"
              % (total_fail, args.min_coverage * 100.0))
        shown = 0
        for res in results:
            for r in res["fails"]:
                if shown >= FAIL_LIST_MAX:
                    break
                print_fail(r, args.min_coverage)
                shown += 1
        if total_fail > shown:
            print("  ... 另有 %d 个框次未列出" % (total_fail - shown))
    else:
        print("[不合格] 无: 全部文字框的墨迹覆盖率都达到 %.2f%%" % (args.min_coverage * 100.0))

    if is_dir and len(results) > 1:
        print("")
        print("[最差的一帧] %s: 最低覆盖率 %.2f%%, 不达标 %d 个"
              % (worst["file"], worst["worst"] * 100.0, len(worst["fails"])))

    print_notes(results, skipped, args.min_coverage)

    if total_fail:
        print("")
        print("建议: 先去查这些块到底画没画 (调用是不是被分支跳过了, 文本是不是空串, "
              "字色是不是被写成了底板色),")
        print("      再查底板与背景的明度差是不是低于 %.0f%%: 差太小时墨迹框里量不出覆盖率, "
              "得先调配色再谈判据" % (PLATE_DIFF_LOW * 100.0))
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())

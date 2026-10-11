# -*- coding: utf-8 -*-
"""
按计划逐屏抽帧与总览: 把 plan.json 与画面对上, 产出给数据看的结果与给用户看的拼图

  python scripts/qa.py temp/frames_proj --plan temp/plan.json --out temp/qa
  python scripts/qa.py <成片.mp4> --plan temp/plan.json --out temp/qa --anchor 8 12
  python scripts/qa.py temp/short.mp4 --plan temp/plan.json --sheet 12
   python scripts/qa.py temp/frames_proj --plan temp/plan.json --bg temp/bg.png

两种输入模式
  帧序列模式: 输入是帧目录 (阶段 6 逐屏终检, 编码前跑), 每屏直接取屏内 80% 处那一帧
    的 n%05d.png, 跳过 ffprobe 与锚点对比, 时长以 plan 为准
  成片模式: 输入是 mp4 (阶段 8 客观验收, 编码后跑), 用 ffprobe 精确抽帧并做锚点对比

做七件事
  1 成片模式: ffprobe 读实际时长与流信息, 与 plan.json 的 duration 与 fps 对照,
    偏差按帧算, 超过 1 帧判为不合格
  2 每屏抽 1 帧, 时间取 屏幕起点 + 0.8 * 屏时长, 避开入场动画未完成的那一段;
    时间已经越过片尾的屏进跳过清单, 于是短的试渲染也能对上整片的计划
  3 逐屏表带幕号 (凭幕号猜屏号是返工根源, 反查用 scene_module.py screen N), 带 p95 与 p99
     与上一屏的 MAE 列带自动判定: 低于 1.0 提示"几乎一样", 低于 0.3 提示"疑似重复屏";
     帧序列模式开跑前先查帧目录是否正在被重渲, 正在重渲时打印醒目警告 (那时的表不可信)
  4 成片模式: 锚点屏抽 切点前一帧 与 切点后一帧, 用 Pillow 算 MAE 与平均亮度差,
    并与该屏前后普通帧对的水平对比, 看变化是不是正好落在切点帧上;
    锚点屏前后各 3 帧算相邻帧差分, 打印成一行数列, 峰值落在切点帧上才算卡点对齐
  5 屏帧每 --sheet 张拼一页 6 列图, 每张下写 屏号与秒, 供人眼快速过一遍
   6 传了 --bg 时, 每屏帧与该纯背景图逐像素相减, 统计显著差异像素的包围盒与最靠上的
      那一行, 并报包围盒是否落在画幅 93% 的安全区内; 每屏一行, 打印在逐屏表之后
   7 成片模式额外抽 t=0 那一帧报平均亮度: 平台拿首帧当缩略图, 首帧是黑的就是一张黑封面

--bg 的用途: 背景是逐帧重画的纯渐变时, 拿单帧减背景剩下的就是"每帧都存在的静态叠加",
也就是水印, 误留的调试框, 忘了删的占位文字这类东西. 包围盒贴边说明它是装饰性的版式元素,
包围盒落在画面中间偏上且很小, 才是要人工确认的疑似幽灵文字.

抽帧定位方式 (成片模式): 一律使用 `ffmpeg -i <成片> -ss <时间> -frames:v 1 -vf scale=W:-1 <输出>`.
`-ss` 必须放在 `-i` 之后, 也就是输出侧定位. 输入侧的 `-ss` 会就近取关键帧, 抽到的可能
不是要检查的那一帧, 卡点验收会直接失效; 输出侧定位会先解码再丢帧到指定时刻, 精确到帧.
请求时间还要再前挪半帧, 抵消浮点进位: 目标帧时间戳是浮点值, 请求时间一进位就会被判成
已过, 抽到的是下一帧, 整个卡点验收会偏一帧.
代价是每次抽帧都要从片头解码, 长片耗时随抽帧数线性增长, 所以长片可以只对可疑段落传参.

出口码 0 表示跑完, 1 表示时长或帧率偏差超过 1 帧, 2 表示输入文件缺失.
只依赖标准库 + numpy + Pillow, 不联网, 产物全部写进 --out 目录(默认 temp/qa).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

# 帧名与编码参数取自共享定义 (scripts/videoconf.py), 不在本文件另写一份

# 把本文件所在目录挂进 sys.path: 共享模块 (videoconf / fontpaths) 必须能找到,
# 而本脚本可能以任意工作目录被调用 (工程根, 或 bench 的输出目录)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import videoconf as _videoconf


try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

# ----------------------------------------------------------------- 参数默认值
SCREEN_W = 480
ANCHOR_W = 640
ANCHOR_SPAN = 3
SHEET_COLS = 6
SHEET_TILE = (480, 270)
SHEET_PAD = 8
LABEL_H = 22
TOL_FRAMES = 1.0
MAE_RATIO = 3.0
# 相邻屏 MAE 的自动判定线: 逐屏表只出数不判定时靠人看表, 实测有两屏主句写重复了
# 而 MAE 只有 0.28 却没人发现; 这两档给的是提示, 不是硬闸
MAE_NEAR_SAME = 1.0
MAE_DUPLICATE = 0.3
# 帧序列模式的重渲预警: 帧目录里最近这么多秒被改写过的帧超过该比例时, 逐屏表不可信
REWRITE_WINDOW_S = 60.0
REWRITE_FRAC = 0.05
# 空场与平板帧的判定线. 空场指这一屏几乎没画东西 (底色铺满或漏渲); 平板帧指画面里
# 只有灰阶没有色彩层次, 常见于"只有一层纯色底加一行灰字"的漏做配色的屏.
# 两个判据都取或的关系: 亮度低但色数够多的图 (例如深色渐变背景) 不是空场,
# 饱和度低但色数够多的图 (例如大范围渐变) 也不是平板帧, 只有两个维度同时塌才报
BLANK_LUMA = 2.0
BLANK_UNIQ = 400
FLAT_SAT = 0.02
FLAT_UNIQ = 3000
# 唯一色数降采样到的宽度: 1920x1080 全量塞进 set 要几百万次哈希, 缩到 480 宽后
# 色数的量级不变 (渐变本来就是量化出来的), 代价只有几十毫秒
UNIQ_W = 480
# 与纯背景差分时的显著差异阈值, 按 luma 差算; 30 约等于一圈能看出来的灰阶,
# 低于它的差异是编码噪声与缩放插值, 报出来会淹掉真正的残留
BG_DIFF_LUMA = 30.0
# 安全区占画幅的比例; 包围盒整体落进去才说明这个差异是画面内的元素,
# 越界意味着有东西贴在画幅边缘上, 编码后容易被裁掉或压变形
SAFE_FRAC = 0.93
# 首帧亮度下限: 平台拿成片首帧当缩略图, 全黑首帧就是一张全黑封面
FIRST_FRAME_LUMA = 2.0
# 与 canvas.FRAME_PATTERN 保持一致; 不 import canvas, 单独复制走也能跑
# 帧名取自共享定义, 不在这里写第二份
FRAME_PATTERN = _videoconf.FRAME_PATTERN
FONTS = (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\consolab.ttf")


def _text(raw):
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def run_cmd(cmd):
    # text=True 配 encoding: 子进程输出按 UTF-8 解, 不靠系统代码页 (中文 Windows 上是
    # GBK, 会抛 UnicodeDecodeError)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, _text(p.stdout), _text(p.stderr)


# ----------------------------------------------------------------- 计划与成片
def parse_rate(s):
    """把 ffprobe 的 r_frame_rate (形如 30000/1001) 换成浮点帧率"""
    if not s:
        return None
    s = str(s)
    if "/" in s:
        a, b = s.split("/", 1)
        a, b = _num(a), _num(b)
        if a is None or not b:
            return None
        return a / b
    return _num(s)


def ffprobe(path):
    """读成片时长, 帧率, 尺寸与流清单"""
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("PATH 里找不到 ffprobe, 无法读取成片信息")
    cmd = [exe, "-v", "error",
           "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
           "-of", "json", path]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError("ffprobe 读取失败: %s" % err.strip())
    js = json.loads(out or "{}")
    info = {"duration": None, "fps": None, "width": 0, "height": 0, "streams": []}
    fmt = js.get("format") or {}
    info["duration"] = _num(fmt.get("duration"))
    for st in js.get("streams") or []:
        info["streams"].append("%s/%s" % (st.get("codec_type"), st.get("codec_name")))
        if st.get("codec_type") == "video" and info["fps"] is None:
            info["fps"] = parse_rate(st.get("r_frame_rate"))
            info["width"] = int(st.get("width") or 0)
            info["height"] = int(st.get("height") or 0)
    return info


def _screen_of(raw, fallback_n, fps):
    """单屏归一化: 允许数字 / [起, 止] / 字典三种写法"""
    t = dur = end = None
    n = fallback_n
    text = ""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        t = float(raw)
    elif isinstance(raw, (list, tuple)):
        if len(raw) >= 1:
            t = _num(raw[0])
        if len(raw) >= 2:
            end = _num(raw[1])
    elif isinstance(raw, dict):
        n = raw.get("n", raw.get("index", fallback_n))
        text = str(raw.get("text", "") or "")
        for k in ("t", "start", "at", "time"):
            if _num(raw.get(k)) is not None:
                t = _num(raw[k])
                break
        dur = _num(raw.get("dur"))
        if dur is None:
            dur = _num(raw.get("duration"))
        for k in ("end", "t1"):
            if _num(raw.get(k)) is not None:
                end = _num(raw[k])
                break
        f0, f1 = _num(raw.get("frame0")), _num(raw.get("frame1"))
        if t is None and f0 is not None and fps:
            t = f0 / fps
        if dur is None and f0 is not None and f1 is not None and fps:
            dur = (f1 - f0) / fps
    else:
        return None
    if t is None:
        return None
    if dur is None and end is not None:
        dur = end - t
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = fallback_n
    return {"n": n, "t": float(t), "dur": (None if dur is None else float(dur)),
            "text": text, "scene": ""}


def load_plan(path):
    """
    读 plan.json, 归一化成一张屏表

    契约字段: fps, duration, scenes[].title, scenes[].screens[] 里的 n, t, dur, text
    兼容: 顶层直接给 screens; 数字或 [起, 止] 的屏; 缺 t, dur 时用 frame0, frame1 换算
    """
    with open(path, "r", encoding="utf-8") as f:
        js = json.load(f)
    plan = {"fps": _num(js.get("fps")), "duration": _num(js.get("duration")),
            "bpm": _num(js.get("bpm")), "bars": _num(js.get("bars")), "screens": []}
    raw = []
    if isinstance(js.get("screens"), list):
        for s in js["screens"]:
            raw.append((None, s))
    for sc in js.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        title = str(sc.get("title", "") or "")
        for s in sc.get("screens") or []:
            raw.append((title, s))
    seq = 0
    last_title = ""
    title_seq = 0
    for title, s in raw:
        seq += 1
        if title and title != last_title:
            title_seq += 1
            last_title = title
        item = _screen_of(s, seq, plan["fps"])
        if item is None:
            print("[警告] 计划第 %d 项读不出起点时间, 已跳过" % seq)
            continue
        if not item["scene"]:
            item["scene"] = title or ""
        item["act"] = title_seq
        item["act_title"] = title or ""
        plan["screens"].append(item)
    plan["screens"].sort(key=lambda x: x["t"])
    for i, item in enumerate(plan["screens"]):
        if item["dur"] is None:
            nxt = plan["screens"][i + 1]["t"] if i + 1 < len(plan["screens"]) else None
            if nxt is None and plan["duration"] is not None:
                nxt = plan["duration"]
            if nxt is not None:
                item["dur"] = max(0.0, nxt - item["t"])
    return plan


# ----------------------------------------------------------------- 图像读数
def load_rgb(path):
    im = Image.open(path).convert("RGB")
    return np.asarray(im).astype(np.float32)


def lum_of(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def uniq_colors(a, width=UNIQ_W):
    """
    不同的 RGB 三元组数量, 先按宽度降采样再统计

    整帧直接建 set 会把几百万个像素各哈希一遍, 而色数的量级在降采样后几乎不变:
    渐变本来就是量化出来的, 缩小一半不会凭空多出或吃掉多少色阶.
    于是这里只花几十毫秒换一个可比的数
    """
    im = Image.fromarray(a.astype(np.uint8), "RGB")
    if im.width > width:
        h = max(1, int(round(im.height * width / float(im.width))))
        im = im.resize((width, h), Image.NEAREST)
    arr = np.asarray(im)
    packed = (arr[..., 0].astype(np.uint32) << 16) | (arr[..., 1].astype(np.uint32) << 8) \
        | arr[..., 2].astype(np.uint32)
    return int(np.unique(packed).size)


def mean_sat(a):
    """
    HSV 里 S 通道的均值 (0 到 1)

    逐像素转 HSV 太慢, 这里只取 S = (max - min) / max 这一支: 它与 HSV 的 S 同值,
    而且是纯向量运算. max 为 0 的纯黑像素 S 取 0, 与 HSV 的定义一致
    """
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    s = np.zeros_like(mx)
    nz = mx > 1e-6
    s[nz] = (mx[nz] - mn[nz]) / mx[nz]
    return float(s.mean())


def mae(a, b):
    """两图平均绝对差 (0 到 255), 尺寸不一致时取左上公共区"""
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return float(np.abs(a[:h, :w] - b[:h, :w]).mean())


def grab(src, t, out, width, fps=30.0):
    """
    精确抽一帧, 返回 (是否成功, 错误文本)

    请求时间要往前挪半帧再用: 输出侧 `-ss` 丢的是时间戳小于请求时刻的帧, 而目标帧的
    时间戳是浮点数, 请求时间一进位(例如 44/30 打成 1.4667)就会被判成已过, 抽到的是下
    一帧, 卡点验收会整体偏一帧. 前挪半帧既不会退到上一帧, 也抵消掉进位.
    """
    exe = shutil.which("ffmpeg")
    if not exe:
        return False, "PATH 里找不到 ffmpeg"
    if os.path.exists(out):
        os.remove(out)
    ss = max(0.0, t - 0.5 / max(fps, 1.0))
    cmd = [exe, "-y", "-v", "error", "-i", src,
           "-ss", "%.6f" % ss, "-frames:v", "1",
           "-vf", "scale=%d:-1" % width, out]
    code, _, err = run_cmd(cmd)
    if code != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        return False, err.strip() or "ffmpeg 未产出文件"
    return True, ""


# ----------------------------------------------------------------- 拼图
def sheet_font(size=15):
    """拼图标注字体: Windows 固定路径优先, 缺了走 fonts.py 探测, 再缺退 Pillow 内置"""
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        import fonts as _fonts
        found, _missing = _fonts.probe()
        for key in ("monor", "mono", "cn", "cnb"):
            p = found.get(key)
            if p:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
    except Exception:
        pass
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def fit(im, box):
    """等比缩放着放进 box, 多余方向补黑边"""
    w, h = box
    r = min(w / max(im.width, 1), h / max(im.height, 1))
    inner = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
    tile = Image.new("RGB", box, (8, 10, 14))
    tile.paste(inner, ((w - inner.width) // 2, (h - inner.height) // 2))
    return tile


def build_sheets(items, outdir, per_page):
    """items 是 (屏号, 秒, 图路径) 的列表, 每 per_page 张拼一页"""
    font = sheet_font(15)
    tw, th = SHEET_TILE
    cw = tw + SHEET_PAD
    chh = th + LABEL_H + SHEET_PAD
    pages = []
    rows = max(1, (min(per_page, len(items)) + SHEET_COLS - 1) // SHEET_COLS)
    for k in range(0, len(items), per_page):
        chunk = items[k:k + per_page]
        page = Image.new("RGB", (SHEET_COLS * cw + SHEET_PAD, rows * chh + SHEET_PAD), (6, 8, 12))
        dr = ImageDraw.Draw(page)
        for i, (n, sec, p) in enumerate(chunk):
            cx = SHEET_PAD + (i % SHEET_COLS) * cw
            cy = SHEET_PAD + (i // SHEET_COLS) * chh
            try:
                page.paste(fit(Image.open(p).convert("RGB"), SHEET_TILE), (cx, cy))
            except Exception as e:
                dr.rectangle([cx, cy, cx + tw, cy + th], fill=(40, 10, 10))
                dr.text((cx + 6, cy + 6), "读取失败 %s" % e, font=font, fill=(255, 120, 120))
            dr.text((cx + 2, cy + th + 3), "n%d  %.2fs" % (n, sec), font=font, fill=(190, 205, 230))
        idx = k // per_page + 1
        path = os.path.join(outdir, "sheet-%d.jpg" % idx)
        page.save(path, quality=88)
        pages.append(path)
    return pages


# ----------------------------------------------------------------- 主流程
def report_clip(info, plan, fps_arg):
    fps = plan["fps"] or fps_arg
    print("成片    : %s" % info["path"])
    print("流信息  : %s" % (", ".join(info["streams"]) or "无"))
    print("画面    : %dx%d  实际帧率 %.3f fps  实际时长 %.3f s"
          % (info["width"], info["height"], (info["fps"] or 0.0), (info["duration"] or 0.0)))
    print("计划    : %s  BPM %s  %s 小节  设计帧率 %.3f fps  设计时长 %s s  共 %d 屏"
          % (info["plan_path"], ("%.1f" % plan["bpm"]) if plan["bpm"] else "?",
             ("%g" % plan["bars"]) if plan["bars"] else "?", fps,
             ("%.3f" % plan["duration"]) if plan["duration"] is not None else "?", len(info["screens"])))
    bad = []
    real_fps = info["fps"] or fps
    if plan["duration"] is not None and info["duration"] is not None:
        dev = info["duration"] - plan["duration"]
        dev_f = dev * real_fps
        verdict = "合格" if abs(dev_f) <= TOL_FRAMES else "不合格"
        if verdict == "不合格":
            bad.append("时长偏差 %.2f 帧, 超过容差 %.0f 帧" % (dev_f, TOL_FRAMES))
        print("时长对照: 偏差 %+.3f s = %+.2f 帧 (容差 %.0f 帧)  [%s]"
              % (dev, dev_f, TOL_FRAMES, verdict))
    else:
        print("时长对照: 计划或成片缺 duration, 跳过")
    if info["fps"] is not None:
        ok = abs(real_fps - fps) <= 0.01
        if not ok:
            bad.append("帧率 %.3f 与设计 %.3f 不一致" % (real_fps, fps))
        print("帧率对照: 实际 %.4f fps / 设计 %.4f fps  [%s]"
              % (real_fps, fps, "一致" if ok else "不合格"))
    return fps, bad


def extract_screens(video, screens, dur, outdir, fps):
    """每屏抽 1 帧, 返回 (成功项, 跳过清单)"""
    got, skipped = [], []
    for s in screens:
        if s["dur"] <= 0:
            skipped.append((s["n"], s["t"], "屏时长非正"))
            continue
        t = s["t"] + 0.8 * s["dur"]
        if t >= dur:
            skipped.append((s["n"], t, "抽帧时间 %.3f s 已越过片尾 %.3f s" % (t, dur)))
            continue
        path = os.path.join(outdir, "screen%02d.png" % s["n"])
        ok, err = grab(video, t, path, SCREEN_W, fps)
        if not ok:
            skipped.append((s["n"], t, "抽帧失败: %s" % err))
            continue
        got.append({"n": s["n"], "t": t, "dur": s["dur"], "path": path,
                    "text": s.get("text", ""), "scene": s.get("scene", ""),
                    "act": s.get("act", ""), "act_title": s.get("act_title", "")})
    return got, skipped


def extract_from_frames(frames_dir, screens, fps, dur):
    """帧序列模式: 每屏直接取屏内 80% 处那一帧的 n%05d.png, 不抽帧不解码"""
    got, skipped = [], []
    for s in screens:
        if s["dur"] <= 0:
            skipped.append((s["n"], s["t"], "屏时长非正"))
            continue
        t = s["t"] + 0.8 * s["dur"]
        if t >= dur:
            skipped.append((s["n"], t, "抽帧时间 %.3f s 已越过片尾 %.3f s" % (t, dur)))
            continue
        f = int(round(t * fps))
        path = os.path.join(frames_dir, FRAME_PATTERN % f)
        if not os.path.exists(path):
            skipped.append((s["n"], t, "缺帧 %s" % path))
            continue
        got.append({"n": s["n"], "t": t, "dur": s["dur"], "path": path,
                    "text": s.get("text", ""), "scene": s.get("scene", ""),
                    "act": s.get("act", ""), "act_title": s.get("act_title", "")})
    return got, skipped


# 亮部判据的两档门槛, 与 brightness.py 的 P95_MIN / P99_MIN 同一口径.
# 为什么两档: p95 本质在量亮色像素的面积占比, 不是在量对比度; 暗场蓝底占 75% 像素而
# 亮字面积不足 5% 的屏, p95 天然落在底色亮度上, 与"白字不够亮"无关.
P95_MIN = 120.0
P99_MIN = 120.0


def p95_of(l):
    return float(np.percentile(l, 95))


def p99_of(l):
    """p99 与 p95 的作用不同: p95 量的是亮色像素的面积占比, p99 量的是亮部峰值本身.
    暗场构图 (大面积暗底 + 少量亮字) 的 p95 会落在底色亮度上, 与"白字够不够亮"无关,
    所以偏暗必须两档一起看. 阈值与 brightness.py 的 judge() 同一口径."""
    return float(np.percentile(l, 99))


def dark_verdict(p95, p99):
    """
    偏暗判定, 返回 (是否不合格, 标注文字)

    两档: p95 与 p99 达标其一就算合格, 两个都低于门槛才判不合格.
    只报 p95 的话暗场构图会被成片误伤; 只报 p99 的话大面积发白的屏会漏判.
    """
    if p95 < P95_MIN and p99 < P99_MIN:
        return True, "偏暗 (p95 %.1f 与 p99 %.1f 都低于 %.0f)" % (p95, p99, P95_MIN)
    if p95 < P95_MIN:
        return False, "p95 %.1f 偏低但 p99 %.1f 达标, 暗场构图的正常现象" % (p95, p99)
    return False, ""


def warn_if_rewriting(frames_dir):
    """
    帧序列模式下, 先看帧目录是不是正在被重渲

    正在重渲时逐屏表会读到新旧混合的帧, 给出的是假阳性: 实测有一轮改了顶杠后重渲
    9360 帧, 重渲中途跑逐屏表读出 3 屏 p95 不达标, 等全部渲完再跑这三屏全部达标,
    中间白查了一轮"为什么顶杠没生效". 表是编码前最后一道闸, 假阳性会把人引向错方向
    """
    if not os.path.isdir(frames_dir):
        return
    now = time.time()
    total = 0
    recent = 0
    for name in os.listdir(frames_dir):
        if not (name.startswith("n") and name.endswith(".png")):
            continue
        p = os.path.join(frames_dir, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        total += 1
        if now - st.st_mtime <= REWRITE_WINDOW_S:
            recent += 1
    if total and recent / float(total) > REWRITE_FRAC:
        print("")
        print("[警告] 帧目录里有 %d/%d 帧在过去 %.0f 秒内被改写, 可能正在重渲中,"
              % (recent, total, REWRITE_WINDOW_S))
        print("       此刻的逐屏表不可信 (会读到新旧混合的帧, 出的是假阳性);")
        print("       请等渲染进程全部退出后再跑一次本命令")


def screen_table(got):
    """
    屏号 | 幕 | 时间 | 帧文件 | 平均亮度 | p95 | p99 | 高亮占比 | 与上一屏的 MAE | 唯一色 | 饱和度

    新增的两列一律排在原有列之后: 逐屏表是给人扫的, 但已有人按列序号取数,
    把新列插进中间会让旧取数整体错位一格
    """
    print("")
    print("屏号 | 幕 | 时间s | 帧文件 | 平均亮度 | p95 | p99 | 高亮占比 | 与上一屏MAE | 唯一色 | 饱和度")
    prev = None
    rows = []
    suspects = []
    flats = []
    for it in got:
        a = load_rgb(it["path"])
        l = lum_of(a)
        mean = float(l.mean())
        p95 = p95_of(l)
        p99 = p99_of(l)
        bright = float((l > 140).mean())
        uniq = uniq_colors(a)
        sat = mean_sat(a)
        d = None if prev is None else mae(a, prev)
        mark = ""
        if d is not None:
            if d < MAE_DUPLICATE:
                mark = "  <- 疑似重复屏"
                suspects.append((it["n"], d, "重复"))
            elif d < MAE_NEAR_SAME:
                mark = "  <- 相邻屏几乎一样"
                suspects.append((it["n"], d, "几乎一样"))
        kinds = []
        notes = []
        if mean < BLANK_LUMA or uniq < BLANK_UNIQ:
            kinds.append("空场")
        if sat < FLAT_SAT and uniq < FLAT_UNIQ:
            kinds.append("平板")
        # 偏暗: p95 与 p99 达标其一就算合格, 两个都低于门槛才判不合格.
        # 只看 p95 会误伤暗场构图 (大面积暗底 + 少量亮字时 p95 落在底色亮度上),
        # 这正是历史上把 27 屏里的 11 屏误判成不合格的那一轮.
        dark_bad, dark_note = dark_verdict(p95, p99)
        if dark_bad:
            kinds.append("偏暗")
        elif dark_note:
            notes.append(dark_note)
        if kinds:
            mark += "  <- " + "/".join(kinds)
            flats.append((it["n"], mean, uniq, sat, kinds))
        if notes:
            mark += "  <- " + "; ".join(notes)
        rows.append({"n": it["n"], "t": it["t"], "path": it["path"],
                     "mean": mean, "p95": p95, "p99": p99, "bright": bright, "mae_prev": d,
                     "uniq": uniq, "sat": sat,
                     "text": it["text"], "act": it.get("act", ""),
                     "act_title": it.get("act_title", ""), "scene": it.get("scene", "")})
        prev = a
        print("%4d | %s | %7.2f | %-28s | %8.1f | %5.1f | %5.1f | %8.3f | %s | %6d | %6.4f%s"
              % (it["n"], ("%2d" % it["act"]) if it.get("act") else " -",
                 it["t"], it["path"], mean, p95, p99, bright,
                 "-" if d is None else "%8.2f" % d, uniq, sat, mark))
    if suspects:
        print("")
        print("相邻屏 MAE 自动判定 (低于 %.1f 提示几乎一样, 低于 %.1f 提示疑似重复):"
              % (MAE_NEAR_SAME, MAE_DUPLICATE))
        for n, d, kind in suspects:
            print("  屏 %d 与上一屏 MAE = %.2f, %s; 反查用 scene_module.py screen %d"
                  % (n, d, kind, n))
    if flats:
        print("")
        print("空场与平板帧判定 (空场: 平均亮度 < %.1f 或 唯一色 < %d; 平板: 饱和度 < %.2f 且 唯一色 < %d):"
              % (BLANK_LUMA, BLANK_UNIQ, FLAT_SAT, FLAT_UNIQ))
        for n, mean, uniq, sat, kinds in flats:
            print("  屏 %d 平均亮度 %.1f, 唯一色 %d, 饱和度 %.4f, 判定 %s; "
                  "反查用 scene_module.py screen %d"
                  % (n, mean, uniq, sat, "/".join(kinds), n))
    return rows


def bg_diff_table(got, bg_path):
    """
    每屏帧与纯背景图逐像素相减, 报显著差异像素的包围盒, 每屏一行

    背景是逐帧重画的纯渐变时, 单帧减背景剩下的就是"每帧都存在的静态叠加": 水印,
    误留的调试框, 忘了删的占位文字. 这类缺陷在逐屏表上看不出来, 因为它的亮度与色数
    都正常, 只有与背景差分才现形.
    包围盒贴边通常是装饰性的版式元素 (顶杠, 页脚), 落在画面中间且很小才要人工确认;
    所以除包围盒之外再报最靠上那一行, 顶部的孤立小团块是最常见的幽灵文字位置
    """
    try:
        bg = load_rgb(bg_path)
    except Exception as e:
        print("")
        print("[警告] 读不了纯背景图 %s (%s), 跳过与背景差分" % (bg_path, e))
        return []
    bg_l = lum_of(bg)
    print("")
    print("与纯背景差分: %s  %dx%d  (显著差异取 luma 差 > %.0f)"
          % (bg_path, bg.shape[1], bg.shape[0], BG_DIFF_LUMA))
    print("屏号 | 差异占比 | 包围盒 x0,y0,x1,y1 | 最靠上y | 安全区")
    out = []
    for it in got:
        a = load_rgb(it["path"])
        h = min(a.shape[0], bg.shape[0])
        w = min(a.shape[1], bg.shape[1])
        d = np.abs(lum_of(a[:h, :w]) - bg_l[:h, :w])
        mask = d > BG_DIFF_LUMA
        n = int(mask.sum())
        if n == 0:
            print("%4d | %8.4f | %-20s | %6s | %s"
                  % (it["n"], 0.0, "(无显著差异)", "-", "-"))
            out.append({"n": it["n"], "frac": 0.0, "box": None, "top_y": None,
                        "in_safe": None})
            continue
        ys, xs = np.nonzero(mask)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        # 安全区按各自画幅算, 帧与背景尺寸不一致时两边各按自己的边留白
        fw = min(a.shape[1], bg.shape[1])
        fh = min(a.shape[0], bg.shape[0])
        mx = fw * (1.0 - SAFE_FRAC) / 2.0
        my = fh * (1.0 - SAFE_FRAC) / 2.0
        in_safe = (x0 >= mx and y0 >= my and x1 < fw - mx and y1 < fh - my)
        print("%4d | %8.4f | %d,%d,%d,%d | %6d | %s"
              % (it["n"], n / float(h * w), x0, y0, x1, y1, y0,
                 "在区内" if in_safe else "越界"))
        out.append({"n": it["n"], "frac": n / float(h * w),
                    "box": [x0, y0, x1, y1], "top_y": y0, "in_safe": in_safe})
    ghost = [r for r in out if r["box"] is not None]
    if ghost:
        print("")
        print("幽灵文字排查: 上面每屏的最靠上 y 是显著差异像素里最靠上的那一行;")
        print("  该 y 很小 (贴顶) 且差异占比很小 (不足 1%) 时, 多半是忘了删的占位文字或调试框;")
        print("  差异占比很大时是这一屏本来就该有内容, 不用管; 反查用 scene_module.py screen N")
    return out


def first_frame_check(video, outdir, fps):
    """
    成片模式额外抽 t=0 那一帧报平均亮度

    平台一律拿成片首帧当缩略图, 而入场动画的起点常常是黑的: 那张封面就是纯黑一块,
    在列表里跟"渲染失败"没有区别. 这一项不看别的, 只回答首帧是不是黑的
    """
    path = os.path.join(outdir, "screen00-first.png")
    ok, err = grab(video, 0.0, path, SCREEN_W, fps)
    if not ok:
        print("")
        print("[警告] 首帧抽帧失败: %s" % err)
        return None
    mean = float(lum_of(load_rgb(path)).mean())
    print("")
    print("首帧 (t=0) 平均亮度 %.1f  [%s]"
          % (mean, "正常" if mean >= FIRST_FRAME_LUMA else "首帧是黑的, 平台会拿它当缩略图"))
    if mean < FIRST_FRAME_LUMA:
        print("  平台拿成片首帧当缩略图, 全黑首帧就是一张全黑封面; "
              "给片头加一帧有内容的起始态, 或把入场动画的起点抬亮")
    return {"path": path, "mean": mean}


def anchor_check(video, anchor_n, screens, outdir, fps, dur):
    """锚点屏的前后帧对比与逐帧差分"""
    t = None
    for s in screens:
        if s["n"] == anchor_n:
            t = s["t"]
            break
    if t is None:
        print("")
        print("锚点屏 %d 不在计划里, 跳过 (锚点用全局连续屏号)" % anchor_n)
        return None
    f0 = int(round(t * fps))
    print("")
    print("锚点屏 %d  t=%.3fs  frame=%d" % (anchor_n, t, f0))
    if t - ANCHOR_SPAN / fps < 0 or t + ANCHOR_SPAN / fps > dur:
        print("  该切点距片头或片尾不足 %d 帧, 无法做前后帧对比, 跳过" % ANCHOR_SPAN)
        return None
    frames = []
    for k in range(-ANCHOR_SPAN, ANCHOR_SPAN + 1):
        p = os.path.join(outdir, "_anchor%02d_%+d.png" % (anchor_n, k))
        ok, err = grab(video, (f0 + k) / fps, p, ANCHOR_W, fps)
        if not ok:
            print("  抽帧失败 frame=%d: %s" % (f0 + k, err))
            return None
        frames.append((f0 + k, p, load_rgb(p)))
    before = frames[ANCHOR_SPAN - 1]
    after = frames[ANCHOR_SPAN + 1]
    p_before = os.path.join(outdir, "anchor%02d-before.png" % anchor_n)
    p_after = os.path.join(outdir, "anchor%02d-after.png" % anchor_n)
    shutil.copyfile(before[1], p_before)
    shutil.copyfile(after[1], p_after)
    m = mae(before[2], after[2])
    dl = float(lum_of(after[2]).mean() - lum_of(before[2]).mean())
    base_pairs = [mae(frames[0][2], frames[2][2]), mae(frames[4][2], frames[6][2])]
    base = float(np.mean(base_pairs)) if base_pairs else 0.0
    ratio = m / max(base, 1e-6)
    print("  前后帧: %s  %s  (宽 %d)" % (p_before, p_after, ANCHOR_W))
    print("  MAE(前, 后) = %.2f   平均亮度差 = %+.2f   跨 2 帧的普通帧对 MAE = %.2f / %.2f"
          % (m, dl, base_pairs[0], base_pairs[1]))
    print("  判据: 比值 %.2f 倍, %s (阈值 %.1f 倍)"
          % (ratio, "变化正好落在切点帧上" if ratio >= MAE_RATIO else "变化不明显, 需人工复核",
             MAE_RATIO))
    diffs = []
    for i in range(1, len(frames)):
        diffs.append((frames[i][0], mae(frames[i - 1][2], frames[i][2])))
    print("  逐帧差分 (相邻帧对, 标后一帧的帧号):")
    print("    " + "  ".join("f%d %.2f" % (f, d) for f, d in diffs))
    peak_f, peak_v = max(diffs, key=lambda x: x[1])
    print("  峰值帧 f%d (值 %.2f), 给定 f%d, 相差 %d 帧  [%s]"
          % (peak_f, peak_v, f0, abs(peak_f - f0),
             "卡点对齐" if peak_f == f0 else "有偏移"))
    for _, p, _ in frames:
        if os.path.exists(p):
            os.remove(p)
    return {"n": anchor_n, "t": t, "frame": f0, "peak": peak_f, "mae": m, "ratio": ratio}


def main(argv=None):
    ap = argparse.ArgumentParser(description="按计划逐屏抽帧与总览, 输入给成片或帧目录")
    ap.add_argument("video", help="成片 mp4, 或帧目录 (帧序列模式, 编码前的逐屏终检用)")
    ap.add_argument("--plan", default=os.path.join("temp", "plan.json"), help="计划 json")
    ap.add_argument("--out", default=os.path.join("temp", "qa"), help="产物目录")
    ap.add_argument("--anchor", nargs="*", type=int, default=[], help="锚点屏号, 可多个, 仅成片模式")
    ap.add_argument("--sheet", type=int, default=24, help="每页拼图的屏帧数")
    ap.add_argument("--fps", type=float, default=30.0, help="计划缺 fps 时的兜底帧率")
    ap.add_argument("--bg", default=None,
                    help="纯背景图片路径; 给定时每屏帧与它逐像素相减, 报显著差异的包围盒")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    frames_mode = os.path.isdir(a.video)
    if not frames_mode and not os.path.exists(a.video):
        print("找不到成片: %s" % a.video)
        return 2
    if not os.path.exists(a.plan):
        print("找不到计划: %s" % a.plan)
        return 2
    if a.bg and not os.path.exists(a.bg):
        print("找不到纯背景图: %s" % a.bg)
        return 2
    if a.sheet <= 0:
        print("--sheet 必须是正数, 收到 %d" % a.sheet)
        return 2
    if a.anchor and frames_mode:
        print("帧序列模式下没有成片可抽锚点帧, 忽略 --anchor; 锚点对比在编码后的成片上做")
        a.anchor = []
    plan = load_plan(a.plan)
    if not plan["screens"]:
        print("计划里没有任何屏, 检查 %s 的 scenes[].screens" % a.plan)
        return 2
    fps = plan["fps"] or a.fps
    info = {"path": a.video, "plan_path": a.plan, "screens": plan["screens"],
            "streams": "", "width": 0, "height": 0, "fps": None, "duration": None}
    bad = []
    if frames_mode:
        plan_dur = plan["duration"]
        if plan_dur is None:
            print("帧序列模式要求计划里有 duration (timing.py 一直会写), 检查 %s" % a.plan)
            return 2
        dur = plan_dur
        print("")
        print("模式: 帧序列 (逐屏终检, 编码前); 时长与帧率以计划为准, 不做 ffprobe 对照")
    else:
        try:
            probe = ffprobe(a.video)
        except RuntimeError as e:
            print("%s" % e)
            return 2
        info.update(probe)
        fps, bad = report_clip(info, plan, a.fps)
        dur = info["duration"] or (plan["duration"] if plan["duration"] is not None else 0.0)
    os.makedirs(a.out, exist_ok=True)

    print("")
    print("逐屏抽帧: 时间取 屏幕起点 + 0.8 * 屏时长, 宽 %d" % SCREEN_W)
    if frames_mode:
        # 先查帧目录是不是正在被重渲, 免得拿新旧混合的帧出一张假阳性的表
        warn_if_rewriting(a.video)
        got, skipped = extract_from_frames(a.video, plan["screens"], fps, dur)
    else:
        got, skipped = extract_screens(a.video, plan["screens"], dur, a.out, fps)
    print("  抽到 %d 帧 / 计划 %d 屏" % (len(got), len(plan["screens"])))
    if skipped:
        print("  跳过清单:")
        for n, t, why in skipped:
            print("    屏 %d  t=%.3f s  %s" % (n, t, why))

    rows = []
    if not HAVE_PIL:
        print("")
        print("[警告] 没有 Pillow, 跳过亮度读数, 锚点 MAE 与拼图")
    else:
        rows = screen_table(got)
        if a.bg:
            bg_diff_table(got, a.bg)
        if not frames_mode:
            first_frame_check(a.video, a.out, fps)
        anchors = []
        for n in a.anchor:
            r = anchor_check(a.video, n, plan["screens"], a.out, fps, dur)
            if r:
                anchors.append(r)
        if a.anchor and not anchors:
            print("  锚点全部未通过, 检查锚点屏号是否落在计划内, 或切点是否离片头片尾不足 %d 帧"
                  % ANCHOR_SPAN)
        items = [(it["n"], it["t"], it["path"]) for it in got]
        if items:
            try:
                pages = build_sheets(items, a.out, a.sheet)
                print("")
                print("拼图: 每页 %d 张, %d 列, 共 %d 页" % (a.sheet, SHEET_COLS, len(pages)))
                for p in pages:
                    print("  %s" % p)
            except Exception as e:
                print("[警告] 拼图失败, 已跳过: %s" % e)

    print("")
    if bad:
        print("结论: 不合格, %s" % "; ".join(bad))
        return 1
    if frames_mode:
        print("结论: 逐屏终检表已产出 (编码前); 拼图供肉眼过片, 异常屏用 scene_module.py screen N 反查")
        return 0
    if HAVE_PIL:
        print("结论: 时长与帧率达标; 视觉判据见表与锚点数列")
    else:
        print("结论: 时长与帧率达标; 没有 Pillow, 视觉判据未产出")
    return 0


if __name__ == "__main__":
    sys.exit(main())

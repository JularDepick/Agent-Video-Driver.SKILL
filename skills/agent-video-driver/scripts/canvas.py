# -*- coding: utf-8 -*-
"""
Agent-Video-Driver 通用画面引擎

Pillow 程序化绘制, SS 倍超采样后降采样, 逐拍驱动
本文件只含引擎与通用 UI 组件, 具体分镜写进项目自己的场景模块
用法见 templates/scene_module.py, 风格参考见 references/styles.md

约定
  设计坐标系固定为 W x H px, 实际按 SS 倍渲染再 reduce 降采样得到抗锯齿
  G(x, y) 把数学单位坐标映射到设计 px, 画函数曲线/向量时用它
  lb = (t - 段落起点) / BEAT 是局部拍数, 所有入场动画都以拍为单位触发
"""
import os
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageChops

# Windows 的中文控制台默认是 GBK: 字形审计报告会原样打印上屏文本, 遇到 GBK 打不出的字符
# (例如下标数字) print 会直接抛 UnicodeEncodeError 把渲染流程打断, 所以先把输出流降级
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

# ----------------------------------------------------------------- 全局配置
# 项目模块 import 后调用 configure() 覆盖, 不要 from canvas import *
W, H = 1920, 1080
SS = 2
FPS = 30
DUR = 30.0
BPM = 120.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
CUTS = []
OX, OY = W / 2.0, H / 2.0
U = 100.0
FRAMES = os.path.join("temp", "frames")
# 帧文件命名的唯一来源: 外部脚本 (编码, 验收, 抽帧) 一律引用它, 不要各写一份字面量
FRAME_PATTERN = "n%05d.png"


def frame_path(i):
    """第 i 帧的落盘路径: FRAMES 目录加 FRAME_PATTERN, 外部脚本统一用它"""
    return os.path.join(FRAMES, FRAME_PATTERN % i)


# ----------------------------------------------------------------- 画幅派生
# 以下布局量全部由画幅派生, 1920x1080 下逐像素等于历史值, 组件的缺省坐标不再写死
# 派生基准统一取画幅短边: 三档预设 (16:9, 9:16, 1:1) 的短边都是 1080, 结果与 16:9 相同
def margin_px():
    """四角安全边距, 16:9 时等于既有的 112"""
    return round(min(W, H) * 112.0 / 1080.0)


def caption_y():
    """底部字幕的缺省 y, 距底边 180 (16:9 时的既有值)"""
    return H - round(min(W, H) * 180.0 / 1080.0)


def footer_y():
    """底部进度线的缺省 y, 距底边 34"""
    return H - round(min(W, H) * 34.0 / 1080.0)

FONT_PATH = {
    "cnb": r"C:\Windows\Fonts\msyhbd.ttc",
    "cn": r"C:\Windows\Fonts\msyh.ttc",
    "mono": r"C:\Windows\Fonts\consolab.ttf",
    "monor": r"C:\Windows\Fonts\consola.ttf",
}
_fc = {}
BG = None

# ----------------------------------------------------------------- 字形回退
# 某个字体键缺字符字形时, 按这张表依次尝试链上的下一个字体键
# 中文字体常常缺上下标与数学符号, 等宽字体反而有; 等宽字体缺中文字形, 回退到中文
# 不回退的话 Pillow 会静默画成空心方框, 而且不报错, 所以回退是默认行为, 不是可选项
FALLBACK = {
    "mono": ("cnb", "cn"),
    "monor": ("cn", "cnb"),
    "cnb": ("monor", "mono"),
    "cn": ("monor", "mono"),
}
# 字形体检用的字号与画布边长, 只用于判断字形是否存在, 与实际上屏字号无关
GLYPH_SIZE = 64
GLYPH_BOX = 96
# 私用区字符: 字体里几乎不会有它的字形, 拿它渲染出的位图就是豆腐块的样子
PUA_CHAR = "\ue000"

_glyph_cache = {}
_tofu_cache = {}
_plan_cache = {}
_gf = {}
# 逐字排版结果缓存: (字符串, 字体键, 字号, 字距) -> (逐字偏移与宽度, 总宽)
_layout_cache = {}
# 字高带缓存: (字体键, 字号) -> (相对基线的上偏移, 下偏移)
_cap_cache = {}


def _font_of(kind, size):
    key = (kind, int(size))
    f = _gf.get(key)
    if f is None:
        f = ImageFont.truetype(FONT_PATH[kind], max(6, int(size)))
        _gf[key] = f
    return f


def _bitmap(ch, font):
    im = Image.new("L", (GLYPH_BOX, GLYPH_BOX), 0)
    ImageDraw.Draw(im).text((16, 16), ch, font=font, fill=255)
    return np.asarray(im)


def _tofu(kind):
    """某个字体键渲染私用区字符的位图, 也就是它的豆腐块长相"""
    t = _tofu_cache.get(kind)
    if t is None:
        t = _bitmap(PUA_CHAR, _font_of(kind, GLYPH_SIZE))
        _tofu_cache[kind] = t
    return t


def glyph_ok(kind, ch):
    """
    判断某个字体键是否有该字符的字形, 结果缓存

    判据是位图精确比对, 不用字宽: 上下标这类窄字符的字宽与豆腐块很接近, 用宽度阈值会大量误报
    """
    key = (kind, ch)
    v = _glyph_cache.get(key)
    if v is None:
        if ch.isspace() or ch == "":
            v = True
        else:
            try:
                v = not np.array_equal(_bitmap(ch, _font_of(kind, GLYPH_SIZE)), _tofu(kind))
            except Exception:
                v = False
        _glyph_cache[key] = v
    return v


def resolve_kind(kind, ch):
    """给单个字符挑字体键: 本字体有就用本字体, 否则沿 FALLBACK 链找, 全都没有就返回原键"""
    if glyph_ok(kind, ch):
        return kind
    for k in FALLBACK.get(kind, ()):
        if k in FONT_PATH and glyph_ok(k, ch):
            return k
    return kind


def text_plan(s, kind):
    """
    把一个字符串拆成若干 (片段, 字体键) 运行段, 同键的相邻字符合并成一段, 结果缓存

    无回退时返回长度 1 且键等于 kind 的元组, 调用方据此走原路径保证历史帧逐像素不变
    """
    key = (s, kind)
    p = _plan_cache.get(key)
    if p is not None:
        return p
    runs = []
    cur = ""
    cur_kind = None
    for ch in s:
        k = resolve_kind(kind, ch)
        if k == cur_kind:
            cur += ch
        else:
            if cur:
                runs.append((cur, cur_kind))
            cur = ch
            cur_kind = k
    if cur:
        runs.append((cur, cur_kind))
    p = tuple(runs)
    _plan_cache[key] = p
    return p


def _char_layout(s, kind, size, track=0.0):
    """
    逐字排版, 返回 ((字符, 字体键, x 偏移, 宽度), ...) 与总宽, 单位都是设计 px

    字体按 size * SS 加载, 所以调用方只需按镜头缩放乘 zoom 即可, 不必重算布局.
    字距 track 是字号的倍数, 于是字距随字号缩放而不是固定像素, 大字号不会显松散, 小字号不会挤死.
    每个字符的 x 偏移由同字体片段内的累计 advance 得出, 于是字体自身的字偶距被保留下来.
    """
    key = (s, kind, round(float(size), 2), round(float(track), 4))
    v = _layout_cache.get(key)
    if v is not None:
        return v
    fs = max(6, int(round(size * SS)))
    adv = float(track) * size * SS
    items = []
    x = 0.0
    for t, k in text_plan(s, kind):
        f = F(k, fs)
        prev = 0.0
        for i, ch in enumerate(t):
            cur = f.getlength(t[:i + 1])
            w = cur - prev
            items.append((ch, k, x / SS, w / SS))
            prev = cur
            x += w + adv
    total = (x - adv) / SS if items else 0.0
    out = (tuple(items), total)
    if len(_layout_cache) > 4096:
        _layout_cache.clear()
    _layout_cache[key] = out
    return out


# ----------------------------------------------------------------- 渲染期字形审计
class TextAudit:
    """
    渲染期劫持 text() 收集真实上屏的 (字符串, 字体键) 组合, 再报告哪些需要回退

    为什么要在渲染期收集: 只有真正被画出来的字符串才算数, 静态扫描源码会漏掉拼接出来的文本,
    也会把从不执行的分支算进来. 全片渲染时每个帧区间都会各自收集并报告一次
    """

    def __init__(self):
        self.calls = {}
        self.fell_back = {}
        self.missing = {}

    def record(self, s, kind, runs):
        key = (s, kind)
        self.calls[key] = self.calls.get(key, 0) + 1
        for t, k in runs:
            if k == kind:
                continue
            for ch in t:
                self.fell_back.setdefault(key, {})[ch] = k
        for ch in s:
            if not glyph_ok(kind, ch) and resolve_kind(kind, ch) == kind and not ch.isspace():
                self.missing.setdefault(key, [])
                if ch not in self.missing[key]:
                    self.missing[key].append(ch)

    def summary(self):
        return {
            "text_calls": sum(self.calls.values()),
            "distinct": len(self.calls),
            "fell_back": len(self.fell_back),
            "missing": len(self.missing),
        }

    def report(self, title=""):
        s = self.summary()
        print("-" * 62)
        print("渲染期字形审计 %s" % title)
        print("  text() 调用 %d 次, 去重后 %d 个 (字符串, 字体键) 组合"
              % (s["text_calls"], s["distinct"]))
        if s["fell_back"] == 0 and s["missing"] == 0:
            print("  未发现缺字形, 全部组合都用原字体键渲染")
        if self.fell_back:
            print("  发生回退 %d 个组合:" % s["fell_back"])
            for (text, kind), chs in sorted(self.fell_back.items(), key=lambda kv: -len(kv[1])):
                detail = " ".join("%s(U+%04X)->%s" % (c, ord(c), k) for c, k in sorted(chs.items()))
                print("    [%s] %s" % (kind, detail))
                print("        出现该组合的字符串: %r" % text)
        if self.missing:
            print("  警告: %d 个组合里有回退链也找不到字形的字符, 这些会画成豆腐块:"
                  % s["missing"])
            for (text, kind), chs in sorted(self.missing.items()):
                print("    [%s] %s   字符串 %r"
                      % (kind, " ".join("%s(U+%04X)" % (c, ord(c)) for c in chs), text))
            print("  处置: 改成 ASCII 写法, 或换一个确实有该字形的字体键, 见 references/text-and-encoding.md")
        print("-" * 62)
        return s


AUDIT = None


def audit_start():
    """打开渲染期字形审计"""
    global AUDIT
    AUDIT = TextAudit()
    return AUDIT


def audit_stop():
    """关闭审计并返回它, 便于自定义驱动自行取用"""
    global AUDIT
    a = AUDIT
    AUDIT = None
    return a


def audit_report(title=""):
    """打印当前审计结果, 没开审计时返回 None"""
    if AUDIT is None:
        return None
    return AUDIT.report(title)


def configure(**kw):
    """
    覆盖全局配置, 典型调用
      canvas.configure(BPM=100, DUR=108.0, CUTS=[...], FRAMES=r"...", FONT_PATH={...})
    覆盖 W 或 H 时数学原点 OX/OY 自动落到新画幅中点; 覆盖 BPM 时拍长与小节长自动重派生
    """
    g = globals()
    for k in kw:
        if k not in g:
            raise KeyError("unknown canvas config: %s" % k)
    g.update(kw)
    if "W" in kw or "H" in kw:
        g["OX"], g["OY"] = g["W"] / 2.0, g["H"] / 2.0
    if "BPM" in kw:
        g["BEAT"] = 60.0 / float(kw["BPM"])
        g["BAR"] = 4 * g["BEAT"]
    return g


def aspect_preset(name):
    """
    画幅预设: 返回 (W, H); 名称不认识时抛 KeyError

    16:9 是横屏缺省; 9:16 竖屏与 1:1 方屏都以短边 1080 为基准, 与 16:9 的短边一致
    """
    presets = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
    if name not in presets:
        raise KeyError("画幅预设只有 %s, 收到 %r" % (", ".join(presets), name))
    return presets[name]


def nframes():
    return int(round(DUR * FPS))


def F(kind, size):
    key = (kind, int(size))
    f = _fc.get(key)
    if f is None:
        f = ImageFont.truetype(FONT_PATH[kind], max(6, int(size)))
        _fc[key] = f
    return f


def measure_width(s, size, kind="cnb", track=0.0, zoom=1.0):
    """
    量文本宽度, 单位设计 px, 与真正画出来的宽度一致

    走的是与绘制同一份逐字排版结果, 所以按回退后的实际字体累加, 也把字距算进去.
    """
    if not s:
        return 0.0
    return _char_layout(s, kind, size, track)[1] * zoom


def fit_size(s, target_w, kind="cnb", track=0.0, lo=12.0, hi=240.0, iters=24):
    """
    反解字号: 让 s 量出来的宽度逼近 target_w, 二分求解

    硬写字号是最常见的翻车点, 标题换一个词就撑出画幅. 指定"这一行要占多宽", 字号由它反解.
    返回的字号可能贴着 hi, 说明 target_w 相对内容过宽, 调用方可以据此判断是否需要换行.
    """
    if not s or target_w <= 0:
        return float(lo)
    a, b = float(lo), float(hi)
    if measure_width(s, b, kind, track) <= target_w:
        return b
    for _ in range(max(1, int(iters))):
        m = (a + b) / 2.0
        if measure_width(s, m, kind, track) < target_w:
            a = m
        else:
            b = m
    return (a + b) / 2.0


def cap_metrics(kind, size):
    """
    大写字母 H 的字高带相对基线的上下偏移, 单位设计 px, 上偏移为负

    Pillow 的 getbbox 返回的 y 相对上伸线, 而绘制锚点 'ls' 与 'la' 相对基线,
    所以必须减掉 ascent, 否则按字高对齐会让整段文字低一个字身.
    """
    key = (kind, round(float(size), 2))
    v = _cap_cache.get(key)
    if v is None:
        f = F(kind, size * SS)
        ascent = f.getmetrics()[0]
        _x0, y0, _x1, y1 = f.getbbox("H")
        v = ((y0 - ascent) / SS, (y1 - ascent) / SS)
        _cap_cache[key] = v
    return v


def baseline_for_cap_centre(kind, size, cy):
    """让大写字母的字高带中心落在 cy 上的基线 y"""
    top, bot = cap_metrics(kind, size)
    return cy - (top + bot) / 2.0


def baseline_for_cap_top(kind, size, cy):
    """让大写字母的字高带上边落在 cy 上的基线 y"""
    return cy - cap_metrics(kind, size)[0]


def cap_band(kind, size, cy):
    """字高带上下边, 字高带中心落在 cy 上"""
    top, bot = cap_metrics(kind, size)
    h = bot - top
    return cy - h / 2.0, cy + h / 2.0


def C3(r, g, b):
    return (r, g, b)


CYAN = C3(56, 225, 255)
PINK = C3(255, 77, 157)
AMBER = C3(255, 201, 60)
GREEN = C3(77, 255, 184)
WHITE = C3(234, 242, 255)
DIM = C3(122, 142, 178)
AXIS = C3(228, 240, 255)
GRID = C3(78, 132, 214)
GRID5 = C3(104, 166, 246)
GHOST = C3(96, 124, 164)
EDGE = C3(58, 82, 118)
PANEL = C3(14, 22, 38)
INK = WHITE
MUTE = DIM


# ----------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0):
    return a if x < a else (b if x > b else x)


def seg(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else (1.0 if t >= b else 0.0)


def eo(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def eo5(x):
    x = clamp(x)
    return 1 - (1 - x) ** 5


def eio(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def back(x, s=1.7):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def lerp(a, b, p):
    return a + (b - a) * p


def keyframes(p, ks):
    p = clamp(p)
    for i in range(len(ks) - 1):
        p0, v0 = ks[i]
        p1, v1 = ks[i + 1]
        if p <= p1:
            q = 0.0 if p1 <= p0 else (p - p0) / (p1 - p0)
            return lerp(v0, v1, q * q * (3 - 2 * q))
    return ks[-1][1]


def beat_phase(t):
    x = t / BEAT
    return x - math.floor(x)


def pulse(t, decay=6.0):
    return math.exp(-beat_phase(t) * decay)


def across(t0, dur, t, ease=None):
    """
    子区间进度: 从 t0 起持续 dur 秒, 返回缓动后的 0..1

    dur 传 0 或负数时退化成阶跃. 与 beat_on 的分工是: beat_on 以拍为单位定位入场,
    across 用秒定位段内的子区间, 例如一段转场里的某半步.
    """
    if dur <= 0:
        return 1.0 if t >= t0 else 0.0
    return (ease or eo)(clamp((t - t0) / dur))


def stagger(i, n, t, t0=0.0, span=0.30, every=0.045, ease=None):
    """
    逐项错帧入场: 第 i 项从 t0 加 i 乘 every 起, 用 span 秒走完

    整块一起出现最死板, 逐字或逐元素延迟 0.04 到 0.06 秒就能读出"被依次放上去"的感觉.
    n 只用于让调用方读起来完整, 计算里不参与.
    """
    return across(t0 + i * every, span, t, ease)


def impact(x, k=1.25, at=0.35, width=0.14, s=8.0):
    """
    落位压印: 在 0..1 的进度上返回先过冲再回落的标量, 峰值约为 k, 落在 x 约等于 at 处

    用途是乘到光晕强度, 线宽或缩放上, 让元素"按下去"一下再稳住.
    起点严格为 0, 终点收敛到 1; 不要直接当 alpha 用, alpha 的上限是 1, 请自行 clamp.
    """
    x = clamp(x)
    rise = 1.0 - math.exp(-s * x)
    bump = math.exp(-((x - at) / width) ** 2)
    return rise * (1.0 + (k - 1.0) * bump)


# ----------------------------------------------------------------- geometry
def G(x, y=None):
    """unit space -> design px (also accepts a list of points)."""
    if y is None:
        if isinstance(x, (list, tuple)):
            if len(x) and isinstance(x[0], (list, tuple)):
                return [G(*p) for p in x]
            return G(x[0], x[1])
        raise TypeError("G needs (x, y)")
    return (OX + x * U, OY - y * U)


# ----------------------------------------------------------------- canvas
def _bbox(mask):
    """布尔或浮点遮罩的非空包围盒, 返回 (y0, y1, x0, x1); 全空时返回 None"""
    if not mask.any():
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


def _paste_rgb(img, out, box):
    x0, y0 = box[2], box[0]
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB"), (x0, y0))


class C:
    def __init__(self):
        ensure_bg()
        self.img = BG.copy()
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self.zoom = 1.0
        self.dx = 0.0
        self.dy = 0.0

    def cam(self, z=1.0, dx=0.0, dy=0.0):
        self.zoom = z
        self.dx = dx
        self.dy = dy

    def P(self, x, y):
        z = self.zoom
        cx, cy = W * 0.5, H * 0.5
        sx = cx + (x - cx) * z + self.dx
        sy = cy + (y - cy) * z + self.dy
        return (sx * SS, sy * SS)

    def pw(self, w):
        return max(1, int(round(w * SS * self.zoom)))

    def line(self, p0, p1, color, w=2.0, alpha=1.0):
        if alpha <= 0.004:
            return
        self.d.line([self.P(*p0), self.P(*p1)], fill=color + (int(255 * clamp(alpha)),), width=self.pw(w))

    def gline(self, p0, p1, color, w=2.0, alpha=1.0, glow=1.0):
        if glow > 0:
            for k, a in ((7.0, 0.06), (4.0, 0.10), (2.3, 0.17)):
                self.line(p0, p1, color, w * k, alpha * a * glow)
        self.line(p0, p1, color, w, alpha)

    def poly(self, pts, color, alpha=1.0, outline=None, ow=1.0, oalpha=1.0):
        pp = [self.P(*p) for p in pts]
        if color is not None and alpha > 0.004:
            self.d.polygon(pp, fill=color + (int(255 * clamp(alpha)),))
        if outline is not None and oalpha > 0.004:
            self.d.line(pp + [pp[0]], fill=outline + (int(255 * clamp(oalpha)),), width=self.pw(ow), joint="curve")

    def disc(self, p, r, color, alpha=1.0):
        if alpha <= 0.004:
            return
        x, y = self.P(*p)
        rr = r * SS * self.zoom
        self.d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=color + (int(255 * clamp(alpha)),))

    def gdisc(self, p, r, color, alpha=1.0, glow=1.0):
        if glow > 0:
            for k, a in ((3.6, 0.07), (2.2, 0.12), (1.5, 0.19)):
                self.disc(p, r * k, color, alpha * a * glow)
        self.disc(p, r, color, alpha)

    def ring(self, p, r, color, w=2.0, alpha=1.0):
        if alpha <= 0.004:
            return
        x, y = self.P(*p)
        rr = r * SS * self.zoom
        self.d.ellipse([x - rr, y - rr, x + rr, y + rr],
                       outline=color + (int(255 * clamp(alpha)),), width=self.pw(w))

    def rrect(self, box, r, fill=None, falpha=1.0, outline=None, ow=1.5, oalpha=1.0):
        x0, y0, x1, y1 = box
        rad = max(1, int(r * SS * self.zoom))
        self.d.rounded_rectangle(
            [self.P(x0, y0), self.P(x1, y1)], radius=rad,
            fill=(fill + (int(255 * clamp(falpha)),)) if fill else None,
            outline=(outline + (int(255 * clamp(oalpha)),)) if outline else None,
            width=self.pw(ow) if outline else 0)

    def dashed(self, p0, p1, color, w=2.0, dash=14.0, gap=10.0, alpha=1.0, offset=0.0, glow=0.0):
        x0, y0 = p0
        x1, y1 = p1
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1e-6 or alpha <= 0.004:
            return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        s = -(offset % (dash + gap))
        while s < L:
            a = max(0.0, s)
            b = min(L, s + dash)
            if b > a:
                q0 = (x0 + ux * a, y0 + uy * a)
                q1 = (x0 + ux * b, y0 + uy * b)
                if glow > 0:
                    self.gline(q0, q1, color, w, alpha, glow)
                else:
                    self.line(q0, q1, color, w, alpha)
            s += dash + gap

    def arrow(self, p0, p1, color, w=4.0, head=22.0, alpha=1.0, glow=1.0):
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-6 or alpha <= 0.004:
            return
        ux, uy = dx / L, dy / L
        hl = min(head, L * 0.75)
        bx, by = x1 - ux * hl, y1 - uy * hl
        self.gline((x0, y0), (bx, by), color, w, alpha, glow)
        px, py = -uy, ux
        hw = hl * 0.44
        pts = [(x1, y1), (bx + px * hw, by + py * hw), (bx - px * hw, by - py * hw)]
        if glow > 0:
            cx = sum(p[0] for p in pts) / 3.0
            cy = sum(p[1] for p in pts) / 3.0
            for k, a in ((2.1, 0.08), (1.5, 0.13)):
                self.poly([(cx + (p[0] - cx) * k, cy + (p[1] - cy) * k) for p in pts], color, alpha * a * glow)
        self.poly(pts, color, alpha)

    def arc(self, center, r, a0, a1, color, w=3.0, alpha=1.0, glow=0.0):
        cx, cy = self.P(*center)
        rr = r * SS * self.zoom
        box = [cx - rr, cy - rr, cx + rr, cy + rr]
        if glow > 0:
            for k, a in ((3.0, 0.08), (1.8, 0.13)):
                self.d.arc(box, a0, a1, fill=color + (int(255 * clamp(alpha * a * glow)),), width=self.pw(w * k))
        self.d.arc(box, a0, a1, fill=color + (int(255 * clamp(alpha)),), width=self.pw(w))

    def wash(self, a, color=None):
        """
        整幅盖一层色: a 从 0 到 1 时画面逐渐洗成该色, 缺省洗成亮场底色

        用途是整场反白的过渡: 暗场末尾洗到亮场底色, 亮场开头再从同一色洗回来,
        两边接得上就不会出现硬切. 它与 fade_to_black 是同一个动作的两种取色.
        它不是逐像素取反: 取反会把品牌色与人物肤色翻成互补色, 读起来像故障而不是换场.
        """
        if a <= 0.004:
            return
        col = color if color is not None else LIGHT_PLATE
        self.d.rectangle([0, 0, W * SS, H * SS], fill=col + (int(255 * clamp(a)),))

    def cloud(self, cov, lum, color=(200, 220, 255), alpha=1.0, depth=None, fog=0.0):
        """
        把 3D 点云的覆盖率与明暗缓冲合成到画面, 缓冲尺寸必须是 (H * SS, W * SS)

        cov, lum, depth 由 scripts/three.py 的 render 给出. 这一步工作在画布像素网格上,
        不受 2D 镜头 cam() 影响: 3D 的机位由 three.Camera 自己定.
        fog 大于 0 且给了 depth 时越远的点越淡, 用来做空气透视.
        """
        cov = np.asarray(cov, np.float32)
        if cov.shape != (H * SS, W * SS):
            raise ValueError("点云缓冲尺寸要是 (%d, %d), 收到 %s"
                             % (H * SS, W * SS, tuple(cov.shape)))
        a = np.clip(cov, 0.0, 1.0) * clamp(alpha)
        if fog > 0 and depth is not None:
            a = a * np.clip(1.0 - fog * np.clip(np.asarray(depth, np.float32), 0.0, 1.0), 0.0, 1.0)
        # 只在覆盖率的包围盒内做合成: 全画幅是 830 万像素, 而物体通常只占几个百分点,
        # 全画幅做一次 float 混合要两秒以上, 收进包围盒后是几十毫秒
        box = _bbox(a > 0.002)
        if box is None:
            return
        y0, y1, x0, x1 = box
        base = np.asarray(self.img.crop((x0, y0, x1, y1)), np.float32)
        aa = a[y0:y1, x0:x1][..., None]
        shade = np.clip(np.asarray(lum, np.float32)[y0:y1, x0:x1], 0.0, 1.2)[..., None]
        tint = np.asarray(color, np.float32)[None, None, :] * shade
        _paste_rgb(self.img, base * (1.0 - aa) + np.clip(tint, 0.0, 255.0) * aa, box)

    def composite(self, rgb, alpha=None, mode="over"):
        """
        把一整块 numpy 着色缓冲合成到画面, 尺寸必须是 (H * SS, W * SS)

        mode 取 over 时按 alpha 混合, 取 multiply 时相乘. 印刷原语都输出这种缓冲,
        用它可以一次把整块版面压上来, 而不必逐块 stamp.
        """
        rgb = np.asarray(rgb, np.float32)
        if rgb.shape[:2] != (H * SS, W * SS):
            raise ValueError("着色缓冲尺寸要是 (%d, %d), 收到 %s"
                             % (H * SS, W * SS, tuple(rgb.shape[:2])))
        if alpha is None:
            a = np.ones(rgb.shape[:2], np.float32)
        else:
            a = np.clip(np.asarray(alpha, np.float32), 0.0, 1.0)
        box = _bbox(a > 0.002)
        if box is None:
            return
        y0, y1, x0, x1 = box
        base = np.asarray(self.img.crop((x0, y0, x1, y1)), np.float32)
        aa = a[y0:y1, x0:x1][..., None]
        src = np.clip(rgb[y0:y1, x0:x1], 0.0, 255.0)
        if mode == "over":
            out = base * (1.0 - aa) + src * aa
        elif mode == "multiply":
            out = base * (1.0 - aa * (1.0 - src / 255.0))
        else:
            raise ValueError("mode 只支持 over 或 multiply, 收到 %r" % (mode,))
        _paste_rgb(self.img, out, box)

    def stamp(self, mask, color, mode="multiply", alpha=1.0):
        """
        把一块遮罩当成一块油墨版压上去, 颜色单一, 缺省用乘法叠印

        与 composite 的分工: 整块版面已经算好颜色时用 composite, 只有一块遮罩与一个
        油墨色时用 stamp, 后者不必先铺一张全画幅的着色缓冲.
        """
        m = np.clip(np.asarray(mask, np.float32), 0.0, 1.0)
        if m.shape != (H * SS, W * SS):
            raise ValueError("遮罩尺寸要是 (%d, %d), 收到 %s"
                             % (H * SS, W * SS, tuple(m.shape)))
        m = m * clamp(alpha)
        box = _bbox(m > 0.002)
        if box is None:
            return
        y0, y1, x0, x1 = box
        base = np.asarray(self.img.crop((x0, y0, x1, y1)), np.float32)
        aa = m[y0:y1, x0:x1][..., None]
        k = np.asarray(color, np.float32)[None, None, :]
        if mode == "multiply":
            out = base * (1.0 - aa * (1.0 - k / 255.0))
        elif mode == "over":
            out = base * (1.0 - aa) + k * aa
        else:
            raise ValueError("mode 只支持 over 或 multiply, 收到 %r" % (mode,))
        _paste_rgb(self.img, out, box)

    def engrave(self, runs, color, w=1.0, alpha=1.0):
        """
        把 three.contour_grid 给出的可见折线段画成线, 做刻版效果

        折线坐标与 cloud 同一套口径, 都是画布像素网格坐标, 不受 cam() 影响.
        传整条等参线会把背面的线也画出来, 所以一定要用 visible_grid 过滤过的段.
        """
        if alpha <= 0.004 or not runs:
            return
        fill = color + (int(255 * clamp(alpha)),)
        width = self.pw(w)
        for pts in runs:
            if len(pts) < 2:
                continue
            self.d.line([(float(x), float(y)) for x, y in pts], fill=fill, width=width)

    def multiply_img(self, screen):
        """
        与一张 uint8 屏图做乘法混合, 屏图由 printkit.screen_u8 生成

        乘法在 PIL 里做(C 实现), 比 numpy 浮点混合快一个数量级, 这是印刷风格能逐帧
        渲染的关键. 屏图是"无墨处 255, 满墨处油墨色", 于是结果等于把这块油墨版
        乘上去. 尺寸必须与画布像素网格一致.
        """
        if screen.size != (W * SS, H * SS):
            raise ValueError("屏图尺寸要是 (%d, %d), 收到 %s"
                             % (W * SS, H * SS, tuple(screen.size)))
        self.img = ImageChops.multiply(self.img, screen.convert("RGB"))
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def bloom(self, cp, r, color, alpha=1.0):
        """additive radial glow (screen blend) centred on a design-px point"""
        if alpha <= 0.006:
            return
        d = int(r * SS * self.zoom * 2)
        if d < 6:
            return
        d = min(d, 1600)
        tile = bloom_tile(color).resize((d, d), Image.BILINEAR)
        if alpha < 0.995:
            tile = tile.point(lambda v: int(v * alpha))
        x, y = int(cp[0] * SS), int(cp[1] * SS)
        x0, y0 = x - d // 2, y - d // 2
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(W * SS, x0 + d), min(H * SS, y0 + d)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        sub = tile.crop((cx0 - x0, cy0 - y0, cx1 - x0, cy1 - y0))
        region = self.img.crop((cx0, cy0, cx1, cy1))
        self.img.paste(ImageChops.screen(region, sub), (cx0, cy0))

    # -- text -------------------------------------------------------------
    def text(self, p, s, size, color, alpha=1.0, anchor="la", kind="cnb", track=0.0):
        """
        画一段文字, 逐字做字形回退

        无回退且不给字距时走 Pillow 原生的 anchor 定位; 需要回退或给了字距时,
        按逐字排版算出的偏移自己定位, 纵向仍交给 Pillow 的 anchor.
        track 是字号的倍数, 负值收紧, 正值放宽.
        """
        if alpha <= 0.004 or not s:
            return
        runs = text_plan(s, kind)
        if AUDIT is not None:
            AUDIT.record(s, kind, runs)
        fill = color + (int(255 * clamp(alpha)),)
        if track == 0.0 and len(runs) == 1 and runs[0][1] == kind:
            self.d.text(self.P(*p), s, font=F(kind, size * SS * self.zoom),
                        fill=fill, anchor=anchor)
            return
        items, total = _char_layout(s, kind, size, track)
        px, py = self.P(*p)
        if len(anchor) >= 2:
            h, v = anchor[0], anchor[1:]
        else:
            h, v = "l", "a"
        z = SS * self.zoom
        total_px = total * z
        if h == "m":
            px -= total_px / 2.0
        elif h == "r":
            px -= total_px
        a = "l" + v
        font = None
        font_key = None
        for ch, k, x0, _w in items:
            if k != font_key:
                font_key = k
                font = F(k, size * SS * self.zoom)
            self.d.text((px + x0 * z, py), ch, font=font, fill=fill, anchor=a)

    def text_fit(self, p, s, target_w, color, alpha=1.0, anchor="la", kind="cnb",
                 track=0.0, lo=12.0, hi=240.0):
        """
        画一段文字, 字号由目标宽度反解, 返回用到的字号

        版面里凡是要"这一行占满多宽"的地方都用它, 不要硬写字号.
        """
        size = fit_size(s, target_w, kind=kind, track=track, lo=lo, hi=hi)
        self.text(p, s, size, color, alpha, anchor=anchor, kind=kind, track=track)
        return size

    def text_cap(self, p, s, size, color, alpha=1.0, cap="center", kind="cnb",
                 track=0.0, halign="l"):
        """
        按大写字母的字高带对齐画一段文字, 而不是按 Pillow 的 ascender 锚点

        cap 取 center 时字高带中心落在 p 的 y 上, 取 top 时字高带上边落在 p 的 y 上.
        halign 取 l / m / r, 分别以 p 的 x 为左端, 中点, 右端.
        多行, 多字号混排时用它能保证视觉基线一致; 单行大字用 text() 的 mm 锚点也可以.
        """
        x, cy = p
        if cap == "center":
            by = baseline_for_cap_centre(kind, size, cy)
        elif cap == "top":
            by = baseline_for_cap_top(kind, size, cy)
        else:
            raise ValueError("cap 只支持 center 或 top, 收到 %r" % (cap,))
        if halign not in ("l", "m", "r"):
            raise ValueError("halign 只支持 l / m / r, 收到 %r" % (halign,))
        self.text((x, by), s, size, color, alpha, anchor=halign + "s", kind=kind, track=track)

    def text_runs(self, s, kind="cnb"):
        """返回该字符串的回退方案, 供场景脚本自查, 返回 (片段, 字体键) 元组"""
        return text_plan(s, kind)

    def measure(self, s, size, kind="cnb", track=0.0):
        """量文本宽度, 与真正画出来的宽度一致; 按回退后的实际字体累加, 并把字距算进去"""
        return measure_width(s, size, kind, track, self.zoom)

    def rich(self, p, parts, size, alpha=1.0, track=0.0):
        x, y = p
        for s, kind, col in parts:
            self.text((x, y), s, size, col, alpha, anchor="la", kind=kind, track=track)
            x += self.measure(s, size, kind, track)
        return x


# ----------------------------------------------------------------- background
_bt = {}


def bloom_tile(color, size=256):
    key = (color, size)
    t = _bt.get(key)
    if t is None:
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        d = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (size / 2)
        a = np.clip(1.0 - d, 0, 1) ** 2.4
        arr = np.zeros((size, size, 3), np.uint8)
        for k, ch in enumerate(color):
            arr[..., k] = np.clip(ch * a, 0, 255).astype(np.uint8)
        t = Image.fromarray(arr, "RGB")
        _bt[key] = t
    return t


def build_bg(top=(9, 17, 35), bot=(2, 4, 9), light=(8, 19, 38), light_r=1.0,
             vignette=0.10, cx=0.46, cy=0.50):
    """
    预渲染静态背景, 每帧只做一次 copy 而不是逐像素重算
    改这几个颜色就能换整体色调, 风格参考见 references/styles.md
    """
    yy, xx = np.mgrid[0:H * SS, 0:W * SS].astype(np.float32)
    u = xx / (W * SS)
    v = yy / (H * SS)
    t_ = np.array(top, np.float32)
    b_ = np.array(bot, np.float32)
    g = t_[None, None, :] * (1 - v)[..., None] + b_[None, None, :] * v[..., None]
    dx = (u - cx) * 1.6
    dy = (v - cy) * 1.05
    r = np.sqrt(dx * dx + dy * dy)
    g += (np.clip(1.0 - r / light_r, 0, 1) ** 2.6)[..., None] * np.array(light, np.float32)
    d2 = np.sqrt(((u - 0.5) * 1.25) ** 2 + ((v - 0.5) * 1.0) ** 2)
    vig = np.clip(1.0 - np.clip((d2 - 0.45) / 0.72, 0, 1) ** 1.8, vignette, 1.0)
    g *= vig[..., None]
    return Image.fromarray(np.clip(g, 0, 255).astype(np.uint8), "RGB")


def ensure_bg(force=False, **kw):
    """懒构建背景, 换色调时用 ensure_bg(force=True, top=..., bot=...)"""
    global BG
    if BG is None or force:
        BG = build_bg(**kw)
    return BG


# 亮场底色: 整场反白的那一场用它, 不要在暗场背景上直接压白
LIGHT_PLATE = (247, 248, 250)


def light_plate_bg():
    """
    亮场背景三色与配套参数, 展开给 ensure_bg 用

      cv.ensure_bg(force=True, **cv.light_plate_bg())

    亮场的暗角必须减弱, 否则白底四角会发灰; build_bg 的 vignette 是四角的亮度下限,
    取 0.9 左右是"几乎不压角", 取 0.04 会把四角压成近黑, 那是暗场的取值.
    光晕也要关掉或大幅降低: 浅底上按暗场的阈值给, 底色自己就够格当高光, 整帧会泛白.
    """
    return dict(top=(249, 250, 252), bot=(232, 235, 240), light=(255, 255, 255),
                light_r=0.9, vignette=0.90)


# ----------------------------------------------------------------- shared art
def draw_grid(c, t, alpha=1.0, prog=1.0, yext=5.5, xext=9.4):
    if alpha <= 0.004:
        return
    b = 1.0 + 0.30 * pulse(t, 7.0)
    for i in range(-int(xext), int(xext) + 1):
        if i == 0:
            continue
        a = clamp((prog - 0.035 * abs(i)) * 2.2)
        if a <= 0:
            continue
        major = (i % 5 == 0)
        col = GRID5 if major else GRID
        c.line(G(i, -yext), G(i, yext), col, 1.3 if major else 1.0,
               alpha * a * (0.40 if major else 0.26) * b)
    for j in range(-5, 6):
        if j == 0:
            continue
        a = clamp((prog - 0.035 * abs(j)) * 2.2)
        if a <= 0:
            continue
        major = (j % 5 == 0)
        col = GRID5 if major else GRID
        c.line(G(-xext, j), G(xext, j), col, 1.3 if major else 1.0,
               alpha * a * (0.40 if major else 0.26) * b)


def draw_axes(c, prog=1.0, alpha=1.0, ticks=True, labels=True):
    if alpha <= 0.004:
        return
    p = clamp(prog)
    xl = 9.3 * p
    yl = 5.5 * p
    c.bloom(G(0, 0), 420, CYAN, 0.10 * alpha)
    c.gline(G(-xl, 0), G(xl, 0), AXIS, 2.6, alpha * 0.95, glow=0.9)
    c.gline(G(0, -yl), G(0, yl), AXIS, 2.6, alpha * 0.95, glow=0.9)
    if p > 0.97:
        c.poly([G(9.3 + 0.20, 0), G(9.3 - 0.14, 0.26), G(9.3 - 0.14, -0.26)], AXIS, alpha)
        c.poly([G(0, 5.5 + 0.20), G(0.26, 5.5 - 0.14), G(-0.26, 5.5 - 0.14)], AXIS, alpha)
    if ticks and p > 0.9:
        tp = eo(seg(prog, 0.9, 1.3))
        for i in range(-9, 10):
            if i == 0:
                continue
            a = clamp((tp - 0.05 * abs(i)) * 3.0)
            if a <= 0:
                continue
            ln = 0.17 if (i % 5 == 0) else 0.10
            c.line(G(i, -ln), G(i, ln), AXIS, 1.7, alpha * a * 0.8)
        for j in range(-5, 6):
            if j == 0:
                continue
            a = clamp((tp - 0.07 * abs(j)) * 3.0)
            if a <= 0:
                continue
            ln = 0.17 if (j % 5 == 0) else 0.10
            c.line(G(-ln, j), G(ln, j), AXIS, 1.7, alpha * a * 0.8)
    if labels and p > 0.95:
        a = eo(seg(prog, 0.95, 1.2))
        c.text(G(9.62, -0.05), "x", 42, CYAN, alpha * a, anchor="lm", kind="monor")
        c.text(G(-0.05, 5.85), "y", 42, CYAN, alpha * a, anchor="mm", kind="monor")
        c.text(G(-0.34, -0.38), "O", 34, DIM, alpha * a, anchor="mm", kind="monor")


def chapter(c, t, text, sub=None, accent=CYAN, appear=0.0, x=None, y=None, alpha=1.0):
    if x is None:
        x = round(min(W, H) * 126.0 / 1080.0)
    if y is None:
        y = round(min(W, H) * 112.0 / 1080.0)
    a = eo(seg(t, appear, appear + 0.45)) * alpha
    if a <= 0.004:
        return
    xo = lerp(-34, 0, a)
    c.gline((x + xo, y - 27), (x + xo, y + 27), accent, 4.0, a, glow=0.8)
    c.text((x + 24 + xo, y), text, 40, WHITE, a, anchor="lm")
    if sub:
        c.text((x + 26 + xo, y + 42), sub, 22, DIM, a * 0.9, anchor="lm", kind="monor")


def beat_bar(c, t, alpha=1.0):
    if alpha <= 0.004:
        return
    n = 60
    m = margin_px()
    x0, x1, y = float(m + 138), W - m - 138.0, H - 64.0
    cur = t / BEAT
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        past = i < cur
        now = (i <= cur < i + 1)
        h = 16.0 if now else (9.0 if past else 4.5)
        col = WHITE if now else (CYAN if past else DIM)
        a = alpha * (1.0 if now else (0.75 if past else 0.20))
        c.line((x, y - h), (x, y + h), col, 2.0 if now else 1.4, a)
    px = lerp(x0, x1, clamp(t / DUR))
    c.gdisc((px, y), 5.0, CYAN, alpha, glow=1.0)


def beat_ring(c, t, color=CYAN, base=70.0, span=330.0, alpha=0.22):
    """expanding ring from the origin, one per beat"""
    ph = beat_phase(t)
    a = alpha * (1 - ph) ** 2.2
    if a <= 0.006:
        return
    c.ring(G(0, 0), base + span * ph, color, 2.0, a)


def fade_to_black(c, a):
    if a > 0.004:
        c.d.rectangle([0, 0, W * SS, H * SS], fill=(0, 0, 0, int(255 * clamp(a))))


# ----------------------------------------------------------------- 通用 UI 组件
# 以下组件与题材无关, 任何风格都能直接用或改参数
def beat_on(lb, k, d=0.4):
    """
    拍触发入场: lb 是局部拍数, k 是起始拍, d 是持续拍数
    返回 0..1 的缓动值, 用它保证元素恰好落在第 k 拍上
    """
    return eo(seg(lb, k, k + d))


def beat_pulse(t, decay=6.0):
    x = (t / BEAT) % 1.0
    return math.exp(-x * decay)


def motes(c, t, alpha=1.0, count=46, color=(150, 190, 230)):
    """缓慢上浮的微粒, 让静止画面有呼吸感, 比加噪点便宜得多"""
    if alpha <= 0.01:
        return
    for i in range(count):
        a = (i * 2654435761) % 100000 / 100000.0
        b = (i * 40503) % 997 / 997.0
        x = 40 + a * (W - 80)
        y = (b * H - t * (5 + (i % 7) * 1.6)) % (H + 60) - 30
        s = 1.0 + (i % 3) * 0.7
        al = (0.05 + 0.07 * ((i * 7) % 5) / 4.0) * alpha
        c.disc((x, y), s, color, al)


def section(c, t, num, title, sub=None, accent=CYAN, appear=0.0, x=None, y=None):
    """左上角章节标签, 编号 + 标题 + 扫出的强调线; 坐标缺省由画幅短边派生"""
    if x is None:
        x = float(margin_px())
    if y is None:
        y = round(min(W, H) * 96.0 / 1080.0)
    lb = (t - appear) / BEAT
    a = beat_on(lb, 0.0, 0.5)
    if a <= 0.004:
        return
    xo = lerp(-26, 0, a)
    c.text((x + xo, y), num, 30, accent, a * 0.95, anchor="lm", kind="mono")
    c.text((x + 74 + xo, y), title, 38, WHITE, a, anchor="lm")
    rw = 250 * beat_on(lb, 0.5, 0.6)
    c.gline((x + xo, y + 34), (x + xo + rw, y + 34), accent, 2.6, a * 0.9, glow=0.8)
    if sub:
        sa = beat_on(lb, 0.75, 0.5)
        c.text((x + 74 + xo, y + 64), sub, 22, DIM, a * sa, anchor="lm", kind="monor")


def caption(c, lb, k, text, color=WHITE, size=36, y=None, alpha=1.0, kind="cnb"):
    """底部字幕, 第 k 拍入场; y 缺省由画幅派生"""
    a = beat_on(lb, k, 0.5) * alpha
    if a <= 0.004:
        return
    c.text((W / 2, caption_y() if y is None else y), text, size, color, a, anchor="mm", kind=kind)


def progress_footer(c, t, alpha=1.0, label=None, y=None, x0=None, x1=None):
    """底部进度线 + 四拍指示灯, 让观众随时知道处在哪一拍; 坐标缺省由画幅派生"""
    if alpha <= 0.01:
        return
    if y is None:
        y = footer_y()
    if x0 is None:
        x0 = float(margin_px())
    if x1 is None:
        x1 = W - margin_px()
    p = clamp(t / DUR)
    c.line((x0, y), (x1, y), EDGE, 2.0, 0.55 * alpha)
    c.gline((x0, y), (x0 + (x1 - x0) * p, y), CYAN, 2.4, 0.85 * alpha, glow=0.7)
    c.gdisc((x0 + (x1 - x0) * p, y), 4.5, CYAN, alpha, glow=1.0)
    ph = (t / BEAT) % 1.0
    for i in range(4):
        x = W / 2 - 33 + i * 22
        lit = 1 - abs(ph * 4 - i - 0.5) * 1.4
        lit = max(0.0, lit) if abs(ph * 4 - i - 0.5) < 0.72 else 0.0
        c.disc((x, y), 3.2 + 2.0 * lit, CYAN if lit > 0.2 else EDGE, alpha * (0.35 + 0.65 * lit))
    if label:
        c.text((x1, y), label, 17, DIM, 0.75 * alpha, anchor="rm", kind="monor")


def cut_sweep(c, t, cuts=None, dur=0.75, alpha=0.075, color=(170, 215, 255)):
    """段落切换时的横向柔光扫过, 比白闪温和, 适合纪录片风格"""
    for cu in (cuts if cuts is not None else CUTS):
        dt = t - cu
        if 0 <= dt < dur:
            p = dt / dur
            a = (1 - p) ** 1.5
            xc = lerp(-200, W + 200, eo(p))
            for k in range(26):
                xx = xc - 130 + k * 10
                al = a * alpha * math.exp(-((k - 13) ** 2) / 26.0)
                c.line((xx, 0), (xx, H), color, 10.0, al)
            c.bloom((W / 2, H / 2), 1500, (60, 120, 190), 0.16 * a)
            break


def cut_flash(c, t, cuts=None, dur=0.11, peak=128, color=(190, 240, 255)):
    """段落切换时的硬白闪, 适合节奏型/燃向风格"""
    for cu in (cuts if cuts is not None else CUTS):
        dt = t - cu
        if 0 <= dt < dur:
            a = (1 - dt / dur) ** 1.6
            c.d.rectangle([0, 0, W * SS, H * SS], fill=color + (int(peak * a),))
            break


def camera_settle(t, cuts=None, amount=0.05, tau=0.22, drift=0.0):
    """切点后轻微推进 + 全片缓慢漂移, 让硬切不显得干"""
    z = 1.0
    for cu in (cuts if cuts is not None else CUTS):
        if t >= cu:
            z = 1.0 + amount * math.exp(-(t - cu) / tau)
    if drift:
        z *= 1.0 + drift * (t / DUR)
    return z


def fade_to_black(c, a):
    if a > 0.004:
        c.d.rectangle([0, 0, W * SS, H * SS], fill=(0, 0, 0, int(255 * clamp(a))))


# ----------------------------------------------------------------- 渲染驱动
def render_frame(scene_pick, t, cam=None):
    """
    scene_pick(t) 返回一个接受 (canvas, t) 的场景函数

    cam 既可以是标量缩放值, 也可以是以时间为参数的相机函数 (例如场景模块里的 cam(t)),
    传函数时按当前帧时间求值. 传错类型时报的是
    TypeError: unsupported operand type(s) for *: 'float' and 'function', 见到就查这里
    """
    c = C()
    if cam is not None:
        c.cam(cam(t) if callable(cam) else cam)
    scene_pick(t)(c, t)
    return c.img.reduce(SS)


def render_range(scene_pick, a, b, cam=None, quiet=False):
    """
    渲染帧区间 [a, b) 到 FRAMES/FRAME_PATTERN
    分区间并行时把区间拆成多段分别调用, 每个进程写自己那段, 避免共享队列
    cam 的取值与 render_frame 一致: 标量或相机函数都行

    渲染期自动开启字形审计, 区间渲完打印一份报告; 调用方自己开过审计时沿用它的那份,
    于是分区间并行时每个进程各报自己那一段, 合起来覆盖全片
    """
    import time
    own = AUDIT is None
    if own:
        audit_start()
    os.makedirs(FRAMES, exist_ok=True)
    t0 = time.time()
    for k, i in enumerate(range(a, b)):
        img = render_frame(scene_pick, i / FPS, cam)
        img.save(frame_path(i), compress_level=3)
        if not quiet and k % 60 == 0:
            el = time.time() - t0
            print("frame %d  %d/%d  %.2fs/frame  eta %.0fs"
                  % (i, k + 1, b - a, el / (k + 1), el / (k + 1) * (b - a - k - 1)), flush=True)
    if own:
        audit_report("帧区间 [%d, %d)" % (a, b))
        audit_stop()
    return time.time() - t0



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

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageChops

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
OX, OY = 960.0, 540.0
U = 100.0
FRAMES = os.path.join("temp", "frames")

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
    """
    g = globals()
    for k in kw:
        if k not in g:
            raise KeyError("unknown canvas config: %s" % k)
    g.update(kw)
    if "BPM" in kw:
        g["BEAT"] = 60.0 / float(kw["BPM"])
        g["BAR"] = 4 * g["BEAT"]
    return g


def nframes():
    return int(round(DUR * FPS))


def F(kind, size):
    key = (kind, int(size))
    f = _fc.get(key)
    if f is None:
        f = ImageFont.truetype(FONT_PATH[kind], max(6, int(size)))
        _fc[key] = f
    return f


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
    def text(self, p, s, size, color, alpha=1.0, anchor="la", kind="cnb"):
        """
        画一段文字, 逐字做字形回退

        无回退时走 Pillow 原生的 anchor 定位, 保证历史帧逐像素不变;
        需要回退时按回退后的实际宽度自己算横向起点, 纵向仍交给 Pillow 的 anchor
        """
        if alpha <= 0.004 or not s:
            return
        runs = text_plan(s, kind)
        if AUDIT is not None:
            AUDIT.record(s, kind, runs)
        fill = color + (int(255 * clamp(alpha)),)
        if len(runs) == 1 and runs[0][1] == kind:
            self.d.text(self.P(*p), s, font=F(kind, size * SS * self.zoom),
                        fill=fill, anchor=anchor)
            return
        widths = [self.d.textlength(t, font=F(k, size * SS * self.zoom)) for t, k in runs]
        px, py = self.P(*p)
        if len(anchor) >= 2:
            h, v = anchor[0], anchor[1:]
        else:
            h, v = "l", "a"
        total = sum(widths)
        if h == "m":
            px -= total / 2.0
        elif h == "r":
            px -= total
        a = "l" + v
        for (t, k), w in zip(runs, widths):
            self.d.text((px, py), t, font=F(k, size * SS * self.zoom), fill=fill, anchor=a)
            px += w

    def text_runs(self, s, kind="cnb"):
        """返回该字符串的回退方案, 供场景脚本自查, 返回 (片段, 字体键) 元组"""
        return text_plan(s, kind)

    def measure(self, s, size, kind="cnb"):
        """量文本宽度, 按回退后的实际字体逐段累加; 无回退时与改造前完全一致"""
        runs = text_plan(s, kind)
        if len(runs) == 1 and runs[0][1] == kind:
            return self.d.textlength(s, font=F(kind, size * SS * self.zoom)) / (SS * self.zoom)
        w = 0.0
        for t, k in runs:
            w += self.d.textlength(t, font=F(k, size * SS * self.zoom))
        return w / (SS * self.zoom)

    def rich(self, p, parts, size, alpha=1.0):
        x, y = p
        for s, kind, col in parts:
            self.text((x, y), s, size, col, alpha, anchor="la", kind=kind)
            x += self.measure(s, size, kind)
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


def chapter(c, t, text, sub=None, accent=CYAN, appear=0.0, x=126.0, y=112.0, alpha=1.0):
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
    x0, x1, y = 250.0, 1670.0, 1016.0
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


def section(c, t, num, title, sub=None, accent=CYAN, appear=0.0, x=112.0, y=96.0):
    """左上角章节标签, 编号 + 标题 + 扫出的强调线"""
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


def caption(c, lb, k, text, color=WHITE, size=36, y=900.0, alpha=1.0, kind="cnb"):
    """底部字幕, 第 k 拍入场"""
    a = beat_on(lb, k, 0.5) * alpha
    if a <= 0.004:
        return
    c.text((W / 2, y), text, size, color, a, anchor="mm", kind=kind)


def progress_footer(c, t, alpha=1.0, label=None, y=1046.0, x0=112.0, x1=1808.0):
    """底部进度线 + 四拍指示灯, 让观众随时知道处在哪一拍"""
    if alpha <= 0.01:
        return
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
    渲染帧区间 [a, b) 到 FRAMES/n%05d.png
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
        img.save(os.path.join(FRAMES, "n%05d.png" % i), compress_level=3)
        if not quiet and k % 60 == 0:
            el = time.time() - t0
            print("frame %d  %d/%d  %.2fs/frame  eta %.0fs"
                  % (i, k + 1, b - a, el / (k + 1), el / (k + 1) * (b - a - k - 1)), flush=True)
    if own:
        audit_report("帧区间 [%d, %d)" % (a, b))
        audit_stop()
    return time.time() - t0



# -*- coding: utf-8 -*-
"""
印刷与 riso 原语

核心观念: **颜色不是给像素指定颜色, 而是把几块油墨版叠印算出来的**.
粉压蓝是真紫, 黄压蓝是真绿; 颜色来自乘法, 不是赋值.

  纸底:    paper_field  fiber_field
  网点:    halftone  cell_for_width
  油墨:    ink_coverage  plate  separate  TONES  INK
  明暗:    density  outline

口径: 所有函数都在**画布像素网格**上算, 也就是 (H * SS, W * SS).
网点是细节, 必须按交付尺寸排版, 所以 cell 要跟着画布宽度放大, 用 cell_for_width() 取.
"""
import math

import numpy as np

from imgnp import blur, min_filter, shift2, unit

# 四色 riso 油墨: 荧光系, 压在暖米纸上
INK = {
    "YELLOW": (255, 224, 77),
    "PINK": (255, 88, 145),
    "BLUE": (63, 122, 214),
    "INK": (28, 32, 40),
}

# 默认分色表: (明暗轴中心, 半宽, 网线角度, 油墨)
# 角度错开的真实理由见 separate() 的说明: 不是"同角度必出摩尔纹", 而是叠印能出中间调
TONES = [
    (0.82, 0.30, 75.0, "YELLOW"),
    (0.58, 0.32, 15.0, "PINK"),
    (0.33, 0.32, 45.0, "BLUE"),
    (0.09, 0.26, 75.0, "INK"),
]


def cell_for_width(w, ref_cell=6.0, ref_width=1280.0):
    """
    由画布宽度换算网点密度

    网点是细节: 1280px 宽时 cell 约 6 对应 133 lpi, 交付 3840px 宽要保持同样的网线
    就要取约 18. 按参考宽度等比放大即可, 不要照抄别的宽度的 cell.
    """
    return max(2.0, float(ref_cell) * float(w) / float(ref_width))


def fiber_field(w, h, seed=12, long_sigma=9.0, short_sigma=1.2, cross=0.5):
    """
    各向异性拉长的噪声: 同一份噪声沿一个方向狠糊, 垂直方向只轻糊

    纸的纤维就是这样. 少了这一层, 纸底只是"加了噪点的纯色", 像屏幕不像纸.

    两路噪声叠加而不是把同一份噪声的两个方向都加进来: 后者相加之后又变回各向同性,
    实测纵向与横向的梯度比只有 1.01, 等于白做. 主路取横向纤维, 副路取纵向短纤维,
    cross 控制副路的权重, 缺省 0.5 时实测梯度比约 1.5.
    """
    rng = np.random.default_rng(seed)
    a = rng.standard_normal((h, w)).astype(np.float32)
    b = rng.standard_normal((h, w)).astype(np.float32)
    hx = blur(blur(a, long_sigma, axis=1), short_sigma, axis=0)
    hy = blur(blur(b, long_sigma * 0.6, axis=0), short_sigma, axis=1)
    return unit(unit(hx) + float(cross) * unit(hy))


def low_noise(w, h, sigma, seed=0, scale=8):
    """
    低频噪声: 在小网格上生成再放大

    纸浆斑块这类几十像素的低频层不必在全分辨率上做 FFT: 先按 scale 倍缩小生成,
    在小数组上糊一次, 再双三次放大回来. 全画幅省下的时间以秒计, 而视觉上看不出差别.
    """
    from PIL import Image
    sw = max(2, int(w) // int(scale))
    sh = max(2, int(h) // int(scale))
    rng = np.random.default_rng(seed)
    small = rng.standard_normal((sh, sw)).astype(np.float32)
    small = blur(small, max(1.0, float(sigma) / max(1, int(scale))))
    up = Image.fromarray(small).resize((int(w), int(h)), Image.BICUBIC)
    return unit(np.asarray(up, np.float32))


def paper_field(w, h, base=(243, 238, 229), seed=11, tooth=0.020, mottle=0.016,
                fibre=0.012, warm=(1.0, 0.985, 0.955)):
    """
    纸底: 低频斑块(纸浆不匀)加每像素细粒(纸面粗糙)加各向异性纤维, 三层缺一不可

    返回 (h, w, 3) float32 的 0 到 255, 直接铺进画面缓冲.

    这是**一次性**产物: 全画幅约十几秒, 生成后存成 PNG 或直接复用缓冲, 不要每帧重算.
    """
    rng = np.random.default_rng(seed)
    mot = low_noise(w, h, max(2.0, min(w, h) / 24.0), seed=seed + 7)
    grain = unit(rng.standard_normal((h, w)).astype(np.float32))
    fib = fiber_field(w, h, seed + 1)
    k = 1.0 + mottle * mot + tooth * grain + fibre * fib
    col = np.asarray(base, np.float32) * np.asarray(warm, np.float32)
    return np.clip(col[None, None, :] * k[..., None], 0.0, 255.0)


def ink_coverage(w, h, amount=0.20, scale=13.0, seed=21):
    """
    油墨覆盖率: 低频起伏的乘数, 落在 [1 - amount, 1]

    平涂的色块是最大的"数码味"来源. 真实印刷的网点与实地永远不是 100% 均匀,
    这一层就是那点不匀.
    """
    rng = np.random.default_rng(seed)
    u = unit(blur(rng.standard_normal((h, w)).astype(np.float32), scale))
    s = 1.0 / (1.0 + np.exp(-u))
    return (1.0 - float(amount) * (1.0 - s)).astype(np.float32)


def dot_field(w, h, cell=9.0, angle=15.0):
    """
    网点距离场: 每个像素到最近网点中心的距离, 单位像素

    它**只与 cell 与角度有关, 与画面无关**, 所以要在项目开始时按用到的角度各算一次,
    之后每帧只做"由明暗求半径, 再与距离场比"这两步. 全画幅算一次约 0.6 秒, 每帧省下
    同样的量; 四块版就是每帧省 2 秒以上.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(float(angle))
    u = xx * math.cos(a) + yy * math.sin(a)
    v = -xx * math.sin(a) + yy * math.cos(a)
    du = np.abs((u / cell) % 1.0 - 0.5)
    dv = np.abs((v / cell) % 1.0 - 0.5)
    return (np.sqrt(du * du + dv * dv) * cell).astype(np.float32)


# 距离场缓存: 键是 (宽, 高, cell, 角度), 全画幅一张 33MB, 上限 6 张
_DIST_CACHE = {}


def cached_dot_field(w, h, cell=9.0, angle=15.0):
    """
    带缓存的距离场: 同一组参数只算一次

    逐帧渲染时必须走这里(或自己把 dot_field 的结果存下来), 否则每帧都要重算旋转点阵.
    """
    key = (int(w), int(h), round(float(cell), 4), round(float(angle), 4))
    d = _DIST_CACHE.get(key)
    if d is None:
        d = dot_field(w, h, cell=cell, angle=angle)
        if len(_DIST_CACHE) >= 6:
            _DIST_CACHE.clear()
        _DIST_CACHE[key] = d
    return d


def halftone(field, cell=9.0, angle=15.0, soft=0.5, dist=None):
    """
    网点: 用 field 控制网点面积, 返回这块版的覆盖率 0 到 1

    field 是这块版的连续调 0 到 1. 半径取 `cell * sqrt(field / pi)`: 网点的面积是
    圆周率乘半径平方, 而每个网点分到的格子面积是 cell 平方, 两者相等才让"覆盖率等于
    field"成立. 少除这个圆周率会让 f=0.25 量出 0.39 的覆盖率, 中间调整体偏重.

    半径超过约 0.4 倍 cell 时相邻网点开始相接, 覆盖率随之饱和, 这是网点的正常行为,
    不是误差: 实地就是靠点连成片. 实测 f=0.75 时覆盖率 0.749, f=1.0 时 0.908.

    soft 是抗锯齿宽度(像素): 0.4 太硬(点发方), 0.6 太糊(丢网点感), 0.48 到 0.52 最像.

    dist 是 dot_field 预计算的距离场, 逐帧调用时一定要传, 否则每帧都要重算一遍
    旋转点阵; 传了之后每帧只剩两次逐元素运算.
    """
    f = np.clip(np.asarray(field, np.float32), 0.0, 1.0)
    if dist is None:
        h, w = f.shape[:2]
        dist = cached_dot_field(w, h, cell=cell, angle=angle)
    # 原地运算: 全画幅一次临时数组就是 33MB, 少铺几个临时数组每帧能省下百毫秒量级
    out = np.multiply(f, cell * cell / math.pi)
    np.sqrt(out, out=out)
    np.subtract(out, dist, out=out)
    out *= 1.0 / max(float(soft), 1e-3)
    out += 0.5
    return np.clip(out, 0.0, 1.0, out=out)


def screen_img(scr, ink, white=None, ink_img=None):
    """
    把覆盖率转成可直接相乘的 PIL 屏图, 用 PIL 的 blend 在 C 里做

    屏图的语义是"无墨处为 255, 满墨处为油墨色", 也就是 `255 - scr * (255 - 墨色)`,
    这正是 `Image.composite(墨, 白, scr)` 的定义. 它在 C 里做, 比逐通道 numpy 生成
    uint8 快约一倍, 逐帧渲染走这条路径; white 与 ink_img 可以按版预建一次复用.

    用法:

    ```python
    from PIL import Image
    scr = pk.halftone(lum, cell=cell, angle=15.0)
    c.multiply_img(pk.screen_img(scr, pk.INK["PINK"]))
    ```
    """
    from PIL import Image
    s = np.clip(np.asarray(scr, np.float32), 0.0, 1.0)
    size = (int(s.shape[1]), int(s.shape[0]))
    a = Image.fromarray((s * 255.0).astype(np.uint8), "L")
    w = white if white is not None else Image.new("RGB", size, (255, 255, 255))
    k = ink_img if ink_img is not None else Image.new(
        "RGB", size, tuple(int(round(v)) for v in np.asarray(ink, np.float32)))
    return Image.composite(k, w, a)


def screen_u8(scr, ink, out=None):
    """
    把覆盖率转成可直接相乘的 uint8 屏图: 无墨处为 255, 满墨处为油墨色

    逐通道算而不是先铺一张三通道的 float32 大图: 全画幅三通道 float32 是 100MB,
    逐通道只要 33MB, 实测快三成.

    用法是配合 PIL 的乘法, 让混合在 C 里做, 比 numpy 浮点混合快一个数量级:

    ```python
    from PIL import Image, ImageChops
    scr = pk.halftone(lum, dist=dist)
    img = ImageChops.multiply(img, Image.fromarray(pk.screen_u8(scr, pk.INK["PINK"]), "RGB"))
    ```
    """
    s = np.clip(np.asarray(scr, np.float32), 0.0, 1.0)
    h, w = s.shape[:2]
    if out is None:
        out = np.empty((h, w, 3), np.uint8)
    ik = np.asarray(ink, np.float32)
    for c in range(3):
        out[..., c] = np.clip(255.0 - s * (255.0 - ik[c]), 0.0, 255.0).astype(np.uint8)
    return out


def plate(rgb, scr, ink, alpha=0.95):
    """
    把一块油墨版叠印到已有着色的画面上, 用乘法

    颜色来自乘法不是赋值: 粉压蓝是真紫, 黄压蓝是真绿. 换成赋值就成了贴色块, 立刻是数码味.
    scr 是这块版的覆盖率 0 到 1, ink 是这块油墨的 RGB.
    """
    a = np.clip(np.asarray(scr, np.float32), 0.0, 1.0)[..., None] * float(alpha)
    k = np.asarray(ink, np.float32)[None, None, :] / 255.0
    return np.clip(np.asarray(rgb, np.float32), 0.0, 255.0) * (1.0 - a * (1.0 - k))


def density(cov, lum, floor=0.0, gamma=1.0, lo=0.0, hi=1.0):
    """
    明暗窗口映射: 把连续调压进一个窗口, 得到"纸号"

    同一张明暗图只改窗口就能从平的工作样片变成收紧的终片. floor 表达潜影(大片未曝光),
    lo 与 hi 是窗口上下端. 浅底片上"最深的黑"靠的就是这个窗口, 不是靠换墨色.
    """
    l = (np.asarray(lum, np.float32) - float(lo)) / max(float(hi) - float(lo), 1e-6)
    l = np.clip(l, 0.0, 1.0)
    d = float(floor) + (1.0 - float(floor)) * l ** max(float(gamma), 1e-6)
    return np.clip(d, 0.0, 1.0) * np.clip(np.asarray(cov, np.float32), 0.0, 1.0)


def outline(cov, w=1.0):
    """
    内侧剪影线: 覆盖率减去腐蚀后的覆盖率

    一条细主版线能让形体从"照片"变成"版画". w 是线宽, 单位像素.
    """
    c = np.clip(np.asarray(cov, np.float32), 0.0, 1.0)
    return np.clip(c - min_filter(c, max(1, int(round(w)))), 0.0, 1.0)


def separate(lum, cov=None, tones=None, cell=None, alpha=0.95, misreg=(0.0, 0.0),
             soft=0.5, paper=(243, 238, 229)):
    """
    把连续调的明暗图分成几块油墨版再叠印, 返回 (h, w, 3) 的 RGB

    每块版取明暗轴上的一段三角隶属度, 相邻版刻意重叠一点, 重叠处叠印生成中间调.

    **角度为什么要错开**: 实测(两块 0.5 覆盖率的版相乘, 低频标准差)

    | 组合 | 低频标准差 |
    |:---:|:---:|
    | 同角度同网线 (9.0 与 9.0) | 0.0004 |
    | 同角度异网线 (9.0 与 9.3) | 0.0737 |
    | 错开角度 (15 度与 45 度) | 0.0015 |

    两点结论: 一, "同角度必出摩尔纹"在数字管线里不成立, 同角度同网线自己不会打架;
    真正的摩尔纹来自**同角度但网线不同**, 低频起伏高出两个数量级, 而网线不同很容易
    被误用(交付尺寸换算不一致, 或者给两块版取了不同的 cell). 二, 角度错开的真正好处是
    **叠印能出中间调**: 落在中间值的像素比例从 6.1% 升到 7.9%; 同角度同网线时两块版的点
    完全重合, 重叠区要么都盖要么都不盖, 第四色就没有了.

    cell 不给就按画布宽度换算, 但**所有版必须用同一个 cell**, 这是上面第一条的直接要求.
    misreg 是套印偏移幅度(像素), 偶数版与奇数版反向偏; 平时给 0, 编排上要"拉开再归位"
    时把它拉到几个像素再回 0.
    """
    lum = np.asarray(lum, np.float32)
    h, w = lum.shape[:2]
    tones = tones or TONES
    if cell is None:
        cell = cell_for_width(w)
    rgb = np.asarray(paper, np.float32)[None, None, :] * np.ones((h, w, 1), np.float32)
    mx, my = float(misreg[0]), float(misreg[1])
    for i, (centre, width, angle, ink_name) in enumerate(tones):
        mem = np.clip(1.0 - np.abs(lum - centre) / max(width, 1e-6), 0.0, 1.0)
        scr = halftone(mem, cell=cell, angle=angle, soft=soft)
        if cov is not None:
            scr = scr * np.clip(np.asarray(cov, np.float32), 0.0, 1.0)
        if mx or my:
            s = 1.0 if i % 2 == 0 else -1.0
            scr = shift2(scr, (mx * s, my * s))
        rgb = plate(rgb, scr, INK[ink_name], alpha=alpha)
    return np.clip(rgb, 0.0, 255.0)

# -*- coding: utf-8 -*-
"""
单帧成本探针: 一帧的时间花在哪

在本机实测并把单帧成本按部件拆开. 四段口径:
  A  Pillow 矢量与文字绘制通道, 画在 SS 倍画布上
  B  numpy 后期通道, 用 imgnp 的模糊与邻域滤波
  C  3D 点云通道, 用 three 的采样, 渲染, 与画布合成
  D  帧写盘, 与 canvas.render_range 同一个 PNG 落盘调用
最后按一次真实渲染的顺序把上面四段与帧组装串成"整帧"再量一遍, 用来核对差额.

命令行
  python scripts/perf_probe.py
  python scripts/perf_probe.py --repeat 5 --size 1280x720
  python scripts/perf_probe.py --size 960x540 --out temp/perf_probe

口径与六点约定
  一, 数字是热缓存后的稳态: 每项先空跑一次预热 (背景预渲染, 字体加载, 字形位图缓存,
      逐字排版缓存, FFT 内部缓冲, numpy 分配器), 再重复计时. 冷首帧单独量一次.
  二, 同一张表的各项放在同一轮里交替计时, 而不是一项一项分开量. 本机测量期间别的进程
      随时在抢内存带宽, 分开量会把负载差异记成算子差异; 同一轮里所有项面对同一段负载.
      每张表都带一行 np.cumsum 参照, 跨表比较前先看两张表的参照行差多少.
  三, 单次成本取重复里的最小值, 均值一并打印. 外部争用只会让结果变慢不会变快, 所以最小值
      最接近无争用成本; 均值比最小值大得多就说明这一轮受了干扰. 占比一律按最小值算.
  四, 每帧口径只收真实逐帧的算子. 大半径 FFT 模糊属于纸底这类一次性产物, 亚像素平移只在
      套印偏移那一拍跑, 两者都标成 [变体], 不进 B 段每帧合计; 依据见 references/print-engine.md
      的逐帧管线一节. 这一步是"算子级倍数不等于整帧倍数"的直接来源.
  五, 段级行与段内明细行在同一轮里测出, 两者可以直接对照; 标了 [参照] 与 [变体] 的行
      不进段合计, 它们的口径与每帧口径不同.
  六, 画面内容是本探针自己的图元清单, 不是任何真实分镜; 改图元清单或改画幅, 数字就不可比.
      换机器必须重测, 耗时不带机器信息就没有意义.

产物只有一张 PNG, 写在 --out 目录下并覆盖同名文件, 不写任何别的路径.
全画幅缓冲用完就释放 (print-engine.md 的第四条纪律): 留着若干张 SS=2 大缓冲会把后面
同一段代码拖慢数倍, 那会把成本记到错误的段上.
"""
import argparse
import ctypes
import gc
import math
import os
import platform
import sys
import time
import unicodedata

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import canvas as cv
import imgnp as ig
import three as th

# --------------------------------------------------------------- 测量参数
# 每张表的轮数: 表一表二按 --repeat 轮, 表三表四里有几秒级的算子, 压到 SLOW_ROUNDS 轮
SLOW_ROUNDS = 2

# 一帧的图元清单: 数量与一屏信息量中等的分镜相当, 改这些常量数字就不可比
N_LINE = 18
N_DISC = 10
N_RRECT = 6
N_POLY = 4
N_DASHED = 5
N_ARC = 4
N_GLOW_LINE = 2
N_GLOW_DISC = 2
N_TEXT = 6

# 3D 段取小参数: 形体采样密度与点在画幅里占的高度都压小, 探针只量成本不比画质
# OBJ_R_RATIO 是物体投影半径占画幅高度的比例, 它决定覆盖率包围盒多大, soften 与 cloud 都按它走
SAMPLE_NU = 96
SAMPLE_NV = 48
OBJ_R_RATIO = 0.16
SPLAT = 2
SOFTEN = 2

# 亚像素平移的偏移量, 单位像素; 与 printkit.separate 的 misreg 同一量级
SHIFT_D = (1.4, -0.9)

# 一次性纸底用的低频层模糊半径; 只进对照表与变体行, 不进每帧口径
ONESHOT_SIGMA = 9.0

# 帧写盘的压缩档: canvas.render_range 用的就是 3
PNG_COMPRESS = 3
PNG_COMPRESS_ALT = 6

# 覆盖率包围盒的判定阈值, 与 canvas.C.cloud 内部一致
COV_THRESHOLD = 0.002

# 每张表都带的参照行: 全网格单轴前缀和, 只做内存读写, 用来判断这张表跑在多重的负载下
BW_LABEL = "内存带宽参照 np.cumsum 单轴"

# 本轮测量里各行的 均值/最小值 倍数, 用作"这次测量受了多少外部干扰"的自查
_RATIOS = []


# --------------------------------------------------------------- 终端表格
def _disp(text):
    """字符串的终端显示宽度, 东亚宽字符按两列算"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(text))


def pad(text, width):
    text = str(text)
    return text + " " * max(0, width - _disp(text))


def table(head, rows, widths):
    """打印一张左对齐的表, 列宽按显示宽度对齐"""
    print("  ".join(pad(c, w) for c, w in zip(head, widths)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(pad(c, w) for c, w in zip(row, widths)))


# --------------------------------------------------------------- 机器信息
def cpu_name():
    """CPU 型号: Windows 读注册表, 其他平台退回 platform.processor()"""
    if os.name == "nt":
        try:
            import winreg
            path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
            try:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
            finally:
                winreg.CloseKey(key)
        except OSError:
            pass
    return platform.processor() or "unknown"


class _MemStatus(ctypes.Structure):
    """GlobalMemoryStatusEx 的入参结构, 只用标准库 ctypes"""
    _fields_ = [("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem_status():
    """返回 (总内存 GB, 可用内存 GB, 内存负载百分比); 取不到的一项给 None"""
    gb = 1024.0 ** 3
    if os.name == "nt":
        try:
            st = _MemStatus()
            st.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return st.ullTotalPhys / gb, st.ullAvailPhys / gb, int(st.dwMemoryLoad)
        except (AttributeError, OSError):
            pass
        return None, None, None
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / gb
        return total, None, None
    except (ValueError, OSError, AttributeError):
        return None, None, None


def module_versions():
    parts = ["python %s" % platform.python_version(), "numpy %s" % np.__version__]
    try:
        import PIL
        parts.append("Pillow %s" % PIL.__version__)
    except Exception as e:
        parts.append("Pillow unavailable (%s)" % type(e).__name__)
    return ", ".join(parts)


# --------------------------------------------------------------- 计时
def bench_rounds(rows, rounds):
    """
    把同一张表的若干项放进同一轮里交替计时

    rows 是 [(名字, 无参函数), ...]; 先给每一项各预热一次, 再逐轮把每一项各跑一遍.
    返回 {名字: (最小值毫秒, 轮数, 均值毫秒)}.
    放在同一轮里是为了让这些项面对同一段外部负载: 本机测量期间别的进程随时在抢内存带宽,
    一项一项分开量会把负载差异记成算子差异, 同一轮里各项的读数才彼此可比.
    单次成本取各轮的最小值, 均值一并返回作干扰自查.
    """
    for _name, fn in rows:
        fn()
    acc = {name: [] for name, _fn in rows}
    n = max(1, int(rounds))
    for _ in range(n):
        for name, fn in rows:
            t0 = time.perf_counter()
            fn()
            acc[name].append((time.perf_counter() - t0) * 1000.0)
    out = {}
    for name, times in acc.items():
        lo = min(times)
        avg = sum(times) / len(times)
        out[name] = (lo, n, avg)
        if lo > 0.05:
            _RATIOS.append((name, avg / lo))
    return out


# --------------------------------------------------------------- 帧内容
class FrameSpec:
    """
    一帧画什么: 固定随机种子生成一次, 之后每遍重复画同一套

    坐标一次算好存起来, 保证每次重复的工作量与像素覆盖完全相同, 免得随机参数
    把测量噪声当成成本差异. 清单口径见文件头的常量.
    """

    def __init__(self, seed=7):
        rng = np.random.default_rng(seed)
        m = float(cv.margin_px())
        x0, x1 = m, float(cv.W) - m
        y0, y1 = m, float(cv.H) - m

        def fx():
            return float(rng.uniform(x0, x1))

        def fy():
            return float(rng.uniform(y0, y1))

        self.lines = [((fx(), fy()), (fx(), fy()),
                       float(rng.uniform(1.5, 5.0)), float(rng.uniform(0.35, 0.95)))
                      for _ in range(N_LINE)]
        self.discs = [((fx(), fy()), float(rng.uniform(6.0, 26.0)),
                       float(rng.uniform(0.40, 1.0))) for _ in range(N_DISC)]
        self.rrects = []
        for _ in range(N_RRECT):
            ax, ay = fx(), fy()
            bx, by = fx(), fy()
            self.rrects.append(((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)),
                                float(rng.uniform(8.0, 26.0)), float(rng.uniform(0.30, 0.80))))
        self.polys = []
        for _ in range(N_POLY):
            cx, cy = fx(), fy()
            r = float(rng.uniform(40.0, 120.0))
            n = int(rng.integers(5, 9))
            ph = float(rng.uniform(0.0, math.pi))
            self.polys.append(([(cx + r * math.cos(ph + 2.0 * math.pi * k / n),
                                 cy + r * math.sin(ph + 2.0 * math.pi * k / n))
                                for k in range(n)],
                               float(rng.uniform(0.40, 0.90))))
        self.dashes = [((fx(), fy()), (fx(), fy()), float(rng.uniform(2.0, 5.0)),
                        float(rng.uniform(10.0, 22.0)), float(rng.uniform(8.0, 16.0)),
                        float(rng.uniform(0.0, 40.0))) for _ in range(N_DASHED)]
        self.arcs = [((fx(), fy()), float(rng.uniform(50.0, 160.0)),
                      float(rng.uniform(0.0, 180.0)), float(rng.uniform(200.0, 350.0)),
                      float(rng.uniform(2.0, 6.0))) for _ in range(N_ARC)]
        self.glow_lines = [((fx(), fy()), (fx(), fy()),
                            float(rng.uniform(2.0, 4.0)), float(rng.uniform(0.5, 0.9)))
                           for _ in range(N_GLOW_LINE)]
        self.glow_discs = [((fx(), fy()), float(rng.uniform(8.0, 18.0)),
                            float(rng.uniform(0.5, 0.9))) for _ in range(N_GLOW_DISC)]

    def draw_lines(self, c):
        for p0, p1, w, a in self.lines:
            c.line(p0, p1, cv.CYAN, w, a)

    def draw_discs(self, c):
        for p, r, a in self.discs:
            c.disc(p, r, cv.WHITE, a)

    def draw_rrects(self, c):
        for box, r, a in self.rrects:
            c.rrect(box, r, fill=cv.PANEL, falpha=a, outline=cv.EDGE, ow=2.0, oalpha=a)

    def draw_polys(self, c):
        for pts, a in self.polys:
            c.poly(pts, cv.PINK, a, outline=cv.WHITE, ow=1.5, oalpha=a)

    def draw_dashes(self, c):
        for p0, p1, w, dash, gap, off in self.dashes:
            c.dashed(p0, p1, cv.AMBER, w, dash, gap, 0.8, off)

    def draw_arcs(self, c):
        for center, r, a0, a1, w in self.arcs:
            c.arc(center, r, a0, a1, cv.GREEN, w, 0.9)

    def draw_glows(self, c):
        for p0, p1, w, a in self.glow_lines:
            c.gline(p0, p1, cv.CYAN, w, a)
        for p, r, a in self.glow_discs:
            c.gdisc(p, r, cv.CYAN, a)

    def draw_vectors(self, c):
        self.draw_lines(c)
        self.draw_discs(c)
        self.draw_rrects(c)
        self.draw_polys(c)
        self.draw_dashes(c)
        self.draw_arcs(c)
        self.draw_glows(c)

    def draw_title(self, c):
        """原生路径: 不回退也不给字距, 走 Pillow 自己的 anchor 定位"""
        c.text((cv.margin_px(), 190), "不对称有机催化", 96, cv.WHITE, 1.0, anchor="lm", kind="cnb")

    def draw_tracked(self, c):
        """逐字路径: 给了字距, 引擎按逐字排版自己算横向起点"""
        c.text((cv.W * 0.5, 300), "手性分子有两种镜像", 52, cv.CYAN, 0.92,
               anchor="mm", kind="cnb", track=0.02)

    def draw_fitted(self, c):
        """字号反解: 二分多次量宽, 是文字段里最贵的一种调用"""
        c.text_fit((cv.margin_px(), 420), "一个分子为什么有两种手性", cv.W * 0.60,
                   cv.WHITE, 1.0)

    def draw_cap(self, c):
        """字高带对齐: 多行混排用, 每次要查字高带缓存"""
        c.text_cap((cv.margin_px(), 520), "Section Title", 44, cv.DIM, 1.0,
                   cap="center", kind="cnb")

    def draw_rich(self, c):
        """多字体混排: 每一段都要量宽才能接着画"""
        parts = (("CO", "cnb", cv.WHITE), ("2", "mono", cv.AMBER),
                 (" + H", "cnb", cv.WHITE), ("2", "mono", cv.AMBER),
                 ("O", "cnb", cv.WHITE))
        c.rich((cv.margin_px(), 600), parts, 40, 1.0, 0.01)

    def draw_readout(self, c):
        """等宽读数: 版面家具那一类小字"""
        c.text((cv.W - cv.margin_px(), cv.H - 120), "t=12.40s  f=372", 30, cv.DIM, 1.0,
               anchor="rm", kind="monor")

    def draw_text(self, c):
        self.draw_title(c)
        self.draw_tracked(c)
        self.draw_fitted(c)
        self.draw_cap(c)
        self.draw_rich(c)
        self.draw_readout(c)


# --------------------------------------------------------------- 四段与整帧
def cloud_camera():
    """3D 机位: 物体投影半径占画幅高度的 OBJ_R_RATIO, 于是包围盒与真实分镜同一量级"""
    w, h = cv.W * cv.SS, cv.H * cv.SS
    eye_z = th.fit_camera(30.0, h, 1.0, want_radius_px=h * OBJ_R_RATIO)
    return th.Camera(eye=(0.0, 0.55, eye_z), target=(0.0, 0.0, 0.0), fov=30.0, w=w, h=h)


def cloud_pass(c):
    """3D 段的一帧工作量: 采样, 渲染, 合成到画布三步; 返回覆盖率缓冲供后期段用"""
    P, N, _shape = th.sample(th.mobius(), SAMPLE_NU, SAMPLE_NV)
    cov, lum, dep = th.render(cloud_camera(), P, N, splat=SPLAT, soften=SOFTEN, depth_cue=0.25)
    c.cloud(cov, lum, cv.CYAN, 0.85, depth=dep, fog=0.35)
    return cov


def cov_box(cov, thr=COV_THRESHOLD):
    """覆盖率非空包围盒 (y0, y1, x0, x1), 与 canvas 的 _bbox 同一判据; 全空时给整幅"""
    m = cov > thr
    if not m.any():
        return 0, cov.shape[0], 0, cov.shape[1]
    rows = np.flatnonzero(m.any(axis=1))
    cols = np.flatnonzero(m.any(axis=0))
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


def post_chain(cov):
    """
    后期段的一帧工作量: 两个真实逐帧算子

    箱式模糊 sigma=1.2 在覆盖率包围盒内, 这是 three.render(soften=) 的路径;
    min_filter r=1 在全网格上, 这是 printkit.outline 的内侧剪影线.
    大半径 FFT 模糊与亚像素平移不在这条链上: 前者是纸底这类一次性产物, 后者只在套印偏移
    那一拍为非零, 两者分别由 post_chain_oneshot 与 post_chain_offset 单独量.
    产物在本探针里不进画面, 只计时; 真正上屏的合成成本属于调用方, 不在四段口径里.
    """
    y0, y1, x0, x1 = cov_box(cov)
    a = ig.blur(cov[y0:y1, x0:x1], 1.2)
    b = ig.min_filter(cov, 1)
    return a, b


def post_chain_offset(cov):
    """变体: 套印偏移那一拍的亚像素平移, 全网格单通道; misreg 为 0 的帧不跑这一步"""
    return ig.shift2(cov, SHIFT_D)


def whole_frame(spec, path):
    """
    整帧口径: 按一次真实渲染的顺序把四段与帧组装串起来

    画布初始化 -> 矢量与文字 -> 3D 采样渲染合成 -> numpy 后期 -> 降采样 -> 写盘.
    返回降采样后的成品图, 供帧写盘段单独计时用.
    """
    c = cv.C()
    spec.draw_vectors(c)
    spec.draw_text(c)
    cov = cloud_pass(c)
    post_chain(cov)
    img = c.img.reduce(cv.SS)
    img.save(path, compress_level=PNG_COMPRESS)
    return img


# --------------------------------------------------------------- CLI
def parse_size(text):
    """把 WxH 解析成两个正整数, 非法时抛 ValueError"""
    low = text.lower().replace("*", "x").replace(",", "x")
    parts = low.split("x")
    if len(parts) != 2:
        raise ValueError("画幅要写成 WxH, 例如 1920x1080, 收到 %r" % text)
    w, h = int(parts[0]), int(parts[1])
    if w < 64 or h < 64:
        raise ValueError("画幅两边都不要小于 64, 收到 %d x %d" % (w, h))
    return w, h


def build_parser():
    p = argparse.ArgumentParser(
        description="单帧成本探针: 在本机实测 Pillow 绘制, numpy 后期, 3D 点云与帧写盘各占多少")
    p.add_argument("--repeat", type=int, default=9,
                   help="表一表二的计时轮数, 缺省 9; 表三表四有几秒级的算子, 压到 %d 轮."
                        " 轮数越多, 每轮的最小值越有机会落在外部干扰小的时候"
                        % SLOW_ROUNDS)
    p.add_argument("--size", default="1920x1080",
                   help="设计画幅 WxH, 缺省 1920x1080; 超采样倍数沿用 canvas 的 SS=2")
    p.add_argument("--out", default=os.path.join("temp", "perf_probe"),
                   help="帧写盘段的落盘目录, 缺省 temp/perf_probe, 只写这一个目录")
    return p


# --------------------------------------------------------------- 主流程
def main():
    args = build_parser().parse_args()
    if args.repeat < 1:
        print("--repeat 要大于等于 1")
        return 2
    try:
        w, h = parse_size(args.size)
    except ValueError as e:
        print(str(e))
        return 2

    cv.configure(W=w, H=h)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    frame_png = os.path.join(out_dir, "frame_%dx%d.png" % (w, h))

    gw, gh = cv.W * cv.SS, cv.H * cv.SS
    spec = FrameSpec()
    repeat = int(args.repeat)
    total0, avail0, load0 = mem_status()

    # 冷首帧: 背景预渲染, 字体加载, 字形位图缓存, 逐字排版缓存都要在这一帧里付掉,
    # 所以它在任何预热之前量, 与后面的稳态数字不是一回事
    t0 = time.perf_counter()
    img_cold = whole_frame(spec, frame_png)
    cold_ms = (time.perf_counter() - t0) * 1000.0

    # ---------------------------------------------------------- 测量前的准备
    # 下面这些缓冲在计时开始前建好: 它们的分配成本属于帧组装, 不计进各算子的单次成本
    grid = np.zeros((gh, gw), np.float32)
    grid[:] = np.linspace(0.0, 1.0, gw, dtype=np.float32)[None, :]
    cA = cv.C()
    cC = cv.C()
    img_ss = cv.C().img
    P0, N0, _shape0 = th.sample(th.mobius(), SAMPLE_NU, SAMPLE_NV)
    cam0 = cloud_camera()
    cov0, lum0, dep0 = th.render(cam0, P0, N0, splat=SPLAT, soften=SOFTEN, depth_cue=0.25)
    by0, by1, bx0, bx1 = cov_box(cov0)
    box_w, box_h = bx1 - bx0, by1 - by0

    # ---------------------------------------------------------- 表一与表二: 一张轮次表里跑完
    # 段级行与段内明细行放在同一轮里: 四段读数, 明细读数与整帧读数面对同一段负载,
    # 于是明细能与段对上, 差额也才有意义
    rows_main = [
        (BW_LABEL, lambda: np.cumsum(grid, axis=1)),
        ("A", lambda: (spec.draw_vectors(cA), spec.draw_text(cA))),
        ("B", lambda: post_chain(cov0)),
        ("C", lambda: cloud_pass(cC)),
        ("D", lambda: img_cold.save(frame_png, compress_level=PNG_COMPRESS)),
        ("画布初始化", lambda: cv.C()),
        ("降采样", lambda: img_ss.reduce(cv.SS)),
        ("整帧", lambda: whole_frame(spec, frame_png)),
        ("A-1", lambda: spec.draw_lines(cA)),
        ("A-2", lambda: spec.draw_discs(cA)),
        ("A-3", lambda: spec.draw_rrects(cA)),
        ("A-4", lambda: spec.draw_polys(cA)),
        ("A-5", lambda: spec.draw_dashes(cA)),
        ("A-6", lambda: spec.draw_arcs(cA)),
        ("A-7", lambda: spec.draw_glows(cA)),
        ("A-8", lambda: spec.draw_text(cA)),
        ("B-1", lambda: cov_box(cov0)),
        ("B-2", lambda: ig.blur(cov0[by0:by1, bx0:bx1], 1.2)),
        ("B-3", lambda: ig.min_filter(cov0, 1)),
        ("C-1", lambda: th.sample(th.mobius(), SAMPLE_NU, SAMPLE_NV)),
        ("C-2", lambda: th.render(cam0, P0, N0, splat=SPLAT, soften=SOFTEN, depth_cue=0.25)),
        ("C-3", lambda: cC.cloud(cov0, lum0, cv.CYAN, 0.85, depth=dep0, fog=0.35)),
        ("C-4", lambda: (th.sample(th.mobius(), SAMPLE_NU, SAMPLE_NV),
                         th.render(cam0, P0, N0, splat=SPLAT, soften=SOFTEN, depth_cue=0.25),
                         cC.cloud(cov0, lum0, cv.CYAN, 0.85, depth=dep0, fog=0.35))),
    ]
    r_main = bench_rounds(rows_main, repeat)
    a_ms, a_n, a_avg = r_main["A"]
    b_ms, b_n, b_avg = r_main["B"]
    c_ms, c_n, c_avg = r_main["C"]
    d_ms, d_n, d_avg = r_main["D"]
    u1_ms, u1_n, u1_avg = r_main["画布初始化"]
    u2_ms, u2_n, u2_avg = r_main["降采样"]
    whole_ms, whole_n, whole_avg = r_main["整帧"]
    bw1 = r_main[BW_LABEL]
    asm_ms = u1_ms + u2_ms
    png_mb = os.path.getsize(frame_png) / 1024.0 ** 2

    # ---------------------------------------------------------- 表三: 不进每帧口径的两项
    rows_variant = [
        (BW_LABEL, lambda: np.cumsum(grid, axis=1)),
        ("[变体] 亚像素平移 shift2, 全网格", lambda: post_chain_offset(cov0)),
        ("[变体] FFT 模糊 sigma=%.1f, 全网格" % ONESHOT_SIGMA, lambda: ig.blur(grid, ONESHOT_SIGMA)),
    ]
    r_variant = bench_rounds(rows_variant, min(repeat, SLOW_ROUNDS))

    # ---------------------------------------------------------- 表四: 逐算子对照
    # 这一段的算子最重, 全画幅缓冲用完立刻释放, 不让它们拖慢别的行
    rgb3 = np.zeros((gh, gw, 3), np.float32)
    rgb3[:] = grid[..., None]
    rows_contrast = [
        (BW_LABEL, lambda: np.cumsum(grid, axis=1)),
        ("模糊 箱式 sigma=1.0 (r=1), 全网格", lambda: ig.blur(grid, 1.0)),
        ("模糊 箱式 sigma=2.0 (r=2), 全网格", lambda: ig.blur(grid, 2.0)),
        ("模糊 前缀和箱式 box_blur r=9, 全网格", lambda: ig.box_blur(grid, 9)),
        ("模糊 覆盖率包围盒 %d x %d 内 sigma=1.2" % (box_h, box_w),
         lambda: ig.blur(cov0[by0:by1, bx0:bx1], 1.2)),
        ("邻域 min_filter r=1, 全网格", lambda: ig.min_filter(grid, 1)),
        ("邻域 min_filter r=2, 全网格", lambda: ig.min_filter(grid, 2)),
        ("邻域 max_filter r=1, 全网格", lambda: ig.max_filter(grid, 1)),
        ("平移 shift2 单通道, 全网格", lambda: ig.shift2(grid, SHIFT_D)),
        ("平移 shift2 三通道, 全网格", lambda: ig.shift2(rgb3, SHIFT_D)),
        ("写盘 img.save compress_level=%d" % PNG_COMPRESS,
         lambda: img_cold.save(frame_png, compress_level=PNG_COMPRESS)),
        ("写盘 img.save compress_level=%d" % PNG_COMPRESS_ALT,
         lambda: img_cold.save(frame_png, compress_level=PNG_COMPRESS_ALT)),
    ]
    r_contrast = bench_rounds(rows_contrast, min(repeat, SLOW_ROUNDS))
    del rgb3
    gc.collect()

    # ---------------------------------------------------------- 汇总
    seg_sum = a_ms + b_ms + c_ms + d_ms
    resid_ms = whole_ms - seg_sum - asm_ms
    total1, avail1, load1 = mem_status()
    seg_pct = [ms / whole_ms * 100.0 for ms in (a_ms, b_ms, c_ms, d_ms)]
    detail = {
        "A": [("线 line", "%d 条" % N_LINE, "A-1"),
              ("实心圆 disc", "%d 个" % N_DISC, "A-2"),
              ("圆角矩形 rrect", "%d 个" % N_RRECT, "A-3"),
              ("多边形 poly", "%d 个" % N_POLY, "A-4"),
              ("虚线 dashed", "%d 条" % N_DASHED, "A-5"),
              ("圆弧 arc", "%d 条" % N_ARC, "A-6"),
              ("发光线与发光圆 glow", "%d 个" % (N_GLOW_LINE + N_GLOW_DISC), "A-7"),
              ("文字 text/text_fit/text_cap/rich", "%d 次" % N_TEXT, "A-8")],
        "B": [("覆盖率包围盒扫描 (全网格比较)", "每帧 1 次", "B-1"),
              ("箱式模糊 sigma=1.2, 覆盖率包围盒内", "每帧 1 次", "B-2"),
              ("邻域 min_filter r=1, 全网格", "每帧 1 次", "B-3")],
        "C": [("曲面采样 sample %dx%d" % (SAMPLE_NU, SAMPLE_NV), "1 次", "C-1"),
              ("点云渲染 render splat=%d soften=%d" % (SPLAT, SOFTEN), "1 次", "C-2"),
              ("点云合成 canvas.cloud", "1 次", "C-3"),
              ("[参照] 三步复用同一批缓冲串一遍", "1 次", "C-4")],
        "D": [("PNG 落盘 compress_level=%d" % PNG_COMPRESS, "1 张", "D")],
    }
    worst = max(_RATIOS, key=lambda kv: kv[1]) if _RATIOS else ("", 1.0)

    # ---------------------------------------------------------- 打印
    print("=" * 96)
    print("单帧成本探针 (perf_probe.py)")
    print("=" * 96)
    print("CPU            %s" % cpu_name())
    print("逻辑核数       %d" % (os.cpu_count() or 0))
    if total0 is not None:
        print("物理内存       总 %.2f GB, 可用 %.2f GB, 负载 %d%%"
              % (total0, avail0 if avail0 is not None else float("nan"), load0))
    print("解释器与库     %s" % module_versions())
    print("画幅           设计 %d x %d px, 超采样 SS=%d, 画布网格 %d x %d"
          % (cv.W, cv.H, cv.SS, gw, gh))
    print("矢量图元       %d 条线, %d 圆, %d 圆角矩形, %d 多边形, %d 虚线, %d 圆弧, %d 发光"
          % (N_LINE, N_DISC, N_RRECT, N_POLY, N_DASHED, N_ARC, N_GLOW_LINE + N_GLOW_DISC))
    print("文字           %d 次调用 (原生, 逐字, 反解字号, 字高带, 混排, 等宽读数)" % N_TEXT)
    print("3D             采样 %d x %d 点, splat=%d, soften=%d, 投影半径占画幅高度 %.0f%%,"
          " 覆盖率包围盒 %d x %d"
          % (SAMPLE_NU, SAMPLE_NV, SPLAT, SOFTEN, OBJ_R_RATIO * 100.0, box_w, box_h))
    print("计时口径       同一张表各项同轮交替, 每项预热 1 次后取各轮最小值; 表一表二 %d 轮,"
          " 表三表四 %d 轮" % (repeat, min(repeat, SLOW_ROUNDS)))
    print("落盘           %s" % frame_png)

    print()
    print("一. 四段汇总 (占比的分母是整帧最小值 %.1f ms)" % whole_ms)
    print("-" * 96)
    rows = [
        (BW_LABEL, "全网格 %d x %d" % (gh, gw), "%.2f" % bw1[0], "%.2f" % bw1[2], bw1[1], "-"),
        ("A Pillow 矢量与文字",
         "%d 图元 + %d 文字" % (N_LINE + N_DISC + N_RRECT + N_POLY + N_DASHED + N_ARC
                                + N_GLOW_LINE + N_GLOW_DISC, N_TEXT),
         "%.2f" % a_ms, "%.2f" % a_avg, a_n, "%.1f%%" % seg_pct[0]),
        ("B numpy 后期", "包围盒箱式模糊 + 全网格 min_filter", "%.2f" % b_ms,
         "%.2f" % b_avg, b_n, "%.1f%%" % seg_pct[1]),
        ("C 3D 点云", "采样 + 渲染 + 合成", "%.2f" % c_ms, "%.2f" % c_avg, c_n,
         "%.1f%%" % seg_pct[2]),
        ("D 帧写盘", "PNG 1 张", "%.2f" % d_ms, "%.2f" % d_avg, d_n, "%.1f%%" % seg_pct[3]),
        ("帧组装", "画布初始化 + reduce 降采样", "%.2f" % asm_ms,
         "%.2f" % (u1_avg + u2_avg), min(u1_n, u2_n), "%.1f%%" % (asm_ms / whole_ms * 100.0)),
        ("整帧", "四段 + 帧组装串一遍", "%.2f" % whole_ms, "%.2f" % whole_avg, whole_n,
         "100.0%"),
    ]
    table(("段", "一帧工作量", "min ms", "mean ms", "轮数", "占整帧"), rows,
          (24, 34, 9, 10, 6, 8))
    print("  单次成本取各轮最小值; mean 明显大于 min 说明这一行的轮次受了外部争用")

    print()
    print("二. 段内明细 (单次调用 = 该行一帧批量的一次运行; [参照] 行不进段合计)")
    print("    本表与表一同一轮测出, 该轮 %s %.2f ms" % (BW_LABEL, bw1[0]))
    print("-" * 96)
    for key, title in (("A", "A Pillow 矢量与文字通道"), ("B", "B numpy 后期通道"),
                       ("C", "C 3D 点云通道"), ("D", "D 帧写盘")):
        base = {"A": a_ms, "B": b_ms, "C": c_ms, "D": d_ms}[key]
        print("[%s]" % title)
        rows = []
        sub = 0.0
        for name, qty, key_row in detail[key]:
            lo, n, avg = r_main[key_row]
            if not name.startswith("[参照]"):
                sub += lo
            rows.append((name, qty, "%.2f" % lo, "%.2f" % avg, n,
                         "%.1f%%" % (lo / base * 100.0), "%.1f%%" % (lo / whole_ms * 100.0)))
        table(("算子", "一帧批量", "min ms", "mean ms", "轮数", "占本段", "占整帧"), rows,
              (34, 12, 9, 10, 6, 8, 8))
        print("  本段明细合计 %.2f ms, 段级实测 %.2f ms, 差 %+.2f ms (%+.1f%%)"
              % (sub, base, base - sub, (base - sub) / base * 100.0))
        print()

    print("三. 不进每帧口径的两项 (每帧都跑的那条后期链上没有它们)")
    print("-" * 96)
    rows = []
    for label in ("[变体] 亚像素平移 shift2, 全网格",
                  "[变体] FFT 模糊 sigma=%.1f, 全网格" % ONESHOT_SIGMA):
        lo, n, avg = r_variant[label]
        rows.append((label, "%.2f" % lo, "%.2f" % avg, n,
                     "%.1f%%" % (lo / whole_ms * 100.0)))
    lo, n, avg = r_variant[BW_LABEL]
    rows.append((BW_LABEL, "%.2f" % lo, "%.2f" % avg, n, "-"))
    table(("算子", "min ms", "mean ms", "轮数", "占整帧"), rows, (40, 9, 10, 6, 8))
    print("  前两项只在该拍或一次性产物里跑, 段级口径不含它们; 与整帧之比仅供参考")

    print()
    print("四. 整帧合成与差额 (表一同一轮内的读数)")
    print("-" * 96)
    print("整帧实测 (预热后)                  %.2f ms   min of %d, 均值 %.2f ms"
          % (whole_ms, whole_n, whole_avg))
    print("冷首帧 (任何预热之前)              %.2f ms   含背景预渲染与字体加载" % cold_ms)
    print("四段之和 A+B+C+D                   %.2f ms   占整帧 %.1f%%"
          % (seg_sum, seg_sum / whole_ms * 100.0))
    print("帧组装 (画布 %.2f + 降采样 %.2f)      %.2f ms   占整帧 %.1f%%"
          % (u1_ms, u2_ms, asm_ms, asm_ms / whole_ms * 100.0))
    print("差额 = 整帧 - 四段之和 - 帧组装    %+.2f ms   占整帧 %+.1f%%"
          % (resid_ms, resid_ms / whole_ms * 100.0))
    print("落盘 PNG 体积                      %.3f MB" % png_mb)

    print()
    print("五. 逐算子对照 (画布网格 %d x %d, float32 单通道, 同一轮内取最小值为准)" % (gh, gw))
    print("-" * 96)
    for label, _fn in rows_contrast:
        lo, n, avg = r_contrast[label]
        print("%-46s %9.2f %10.2f %6d" % (label, lo, avg, n))
    print("  第一行是内存带宽参照: 换机器先比这一行, 它差得多说明两张表的机器不可比")

    print()
    print("六. 判读")
    print("-" * 96)
    order = sorted((("A Pillow 矢量与文字", a_ms), ("B numpy 后期", b_ms),
                    ("C 3D 点云", c_ms), ("D 帧写盘", d_ms)), key=lambda kv: -kv[1])
    for rank, (name, ms) in enumerate(order, 1):
        print("%d. %-22s %8.2f ms   占整帧 %.1f%%" % (rank, name, ms, ms / whole_ms * 100.0))
    print("占比之和 (四段 + 帧组装)          %.1f%%"
          % (seg_sum / whole_ms * 100.0 + asm_ms / whole_ms * 100.0))
    print("最大段的算子级加速对整帧的影响上限就是该段占比, 不是算子级的倍数")
    print("差额 %+.1f%% 是同一轮内的实测差, 来自整帧里各段缓冲的分配与访问次序"
          % (resid_ms / whole_ms * 100.0))
    print("本次测量 均值/最小值 的最大倍数   %.2f (在 \"%s\" 一行)" % (worst[1], worst[0]))
    if total1 is not None:
        print("测量结束时可用内存 %.2f GB, 负载 %d%%" % (avail1, load1))

    print()
    print("=" * 96)
    print("数字是本机本次实测值, 与本机负载有关; 换机器或换画幅必须重测")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())

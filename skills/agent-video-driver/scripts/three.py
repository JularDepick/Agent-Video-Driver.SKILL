# -*- coding: utf-8 -*-
"""
纯 Python 3D 点云渲染

不是三角形光栅化器, 也不打算是. 逐三角形循环在 Python 里太慢, 而"用 numpy 批量处理"
在三角光栅化上很难做对(三角形大小不一, 边界要插值重心坐标). 点云方案把问题换成
numpy 擅长的形状:

  曲面密采样 -> 投影 -> 按深度排序后散射(远的先写, 近的后写)
  numpy 对重复下标保留最后一次写入, 这正好是画家算法, 遮挡是精确的
  密集点云自带轻微颗粒感, 印出来拍出来都好看

代价是分辨率靠采样密度堆: 掠射角(面几乎侧对镜头)处点会稀, 需要用 soften 做亚像素模糊.

  曲面:      sample  mobius  knot_tube  box_surface  supershape  sweep_ellipse  spiral_ribbon
  相机:      Camera
  渲染:      render  ->  (cov 覆盖率, lum 明暗, depth 归一化深度)
  刻版:      visible_grid  contour_grid  ->  可见段折线, 远的半边自动被挡住

与画布引擎的接法: cov 与 lum 的尺寸就是画布像素网格 (W * SS, H * SS),
交给 canvas.C 的 cloud() 合成, 折线交给 engrave(). 这两步不受 2D 镜头 cam() 影响.

邻域滤波与箱式模糊从 scripts/imgnp.py 取, 与印刷原语共用同一套实现.
"""
import math

import numpy as np

from imgnp import box_blur, min_filter

# 曲面法线用中心差分求, 微小量取 8e-4: 太大法线会糊, 太小会被浮点噪声放大
_E = 8e-4


def clip01(x):
    return np.clip(x, 0.0, 1.0)


def norm(v, axis=-1):
    return v / np.maximum(np.linalg.norm(v, axis=axis, keepdims=True), 1e-9)


def cross(a, b):
    return np.cross(a, b)


def rot_x(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.stack([p[..., 0], c * p[..., 1] - s * p[..., 2],
                     s * p[..., 1] + c * p[..., 2]], -1)


def rot_y(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * p[..., 0] + s * p[..., 2], p[..., 1],
                     -s * p[..., 0] + c * p[..., 2]], -1)


def rot_z(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * p[..., 0] - s * p[..., 1],
                     s * p[..., 0] + c * p[..., 1], p[..., 2]], -1)


def fit_radius(p, r=1.0):
    """等比缩放到最远顶点落在半径 r 上, 于是同一个相机距离对所有形体含义一致"""
    m = float(np.linalg.norm(p.reshape(-1, 3), axis=1).max())
    return p * (r / max(m, 1e-9))


def sample(fn, nu, nv):
    """
    在网格上采样参数曲面 fn(u, v) -> (..., 3), 返回 (P, N, (nu, nv))

    法线来自偏导数的叉积, 不需要网格拓扑也不需要顶点法线插值, 天然光滑
    """
    u = np.linspace(0, 1, nu, dtype=np.float32)
    v = np.linspace(0, 1, nv, dtype=np.float32)
    U, V = np.meshgrid(u, v, indexing="ij")
    P = np.asarray(fn(U, V), np.float32)
    du = np.asarray(fn(U + _E, V), np.float32) - np.asarray(fn(U - _E, V), np.float32)
    dv = np.asarray(fn(U, V + _E), np.float32) - np.asarray(fn(U, V - _E), np.float32)
    return P, norm(cross(du, dv)), (nu, nv)


# ------------------------------------------------------------------ 形体生成器
def mobius(width=0.42, radius=1.0):
    """单侧曲面带: 讲"只有一面"这类隐喻时用"""
    def fn(u, v):
        phi = 2 * np.pi * u
        vv = (v - 0.5) * 2.0
        r = radius + vv * width * np.cos(phi * 0.5)
        return np.stack([r * np.cos(phi), r * np.sin(phi),
                         vv * width * np.sin(phi * 0.5)], -1)

    return lambda u, v: fit_radius(fn(u, v), 1.0)


def knot_tube(tube=0.24, p=2, q=3, scale=1.0):
    """(p, q) 环面结扫掠成实心管: 遮挡关系明确, 最上镜的雕塑形"""
    def curve(t):
        return np.stack([(2 + np.cos(q * t)) * np.cos(p * t),
                         (2 + np.cos(q * t)) * np.sin(p * t),
                         np.sin(q * t)], -1)

    def fn(u, v):
        t = 2 * np.pi * u
        a = 2 * np.pi * v
        h = 1e-3
        tng = norm(curve(t + h) - curve(t - h))
        ref = np.stack([np.zeros_like(t), np.zeros_like(t), np.ones_like(t)], -1)
        n1 = norm(cross(tng, ref))
        n2 = norm(cross(tng, n1))
        off = np.cos(a)[..., None] * n1 + np.sin(a)[..., None] * n2
        return fit_radius(curve(t) + off * tube, 1.0 * scale)

    return fn


def box_surface(centre, size, nu=64, nv=64, front_bias=3.0):
    """
    长方体点云: 六个面各自采样

    前面板采样得比其它面密, 才能在不加网格与贴图的情况下让机柜显出栅格与硬盘位
    """
    cx, cy, cz = centre
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    u = np.linspace(0, 1, nu, dtype=np.float32)
    v = np.linspace(0, 1, nv, dtype=np.float32)
    U, V = np.meshgrid(u, v, indexing="ij")
    X = cx - hx + 2 * hx * U
    Y = cy - hy + 2 * hy * V
    Z = cz - hz + 2 * hz * U
    Wd = cz - hz + 2 * hz * V
    faces = [
        np.stack([X, Y, np.full_like(X, cz + hz)], -1),
        np.stack([X, Y, np.full_like(X, cz - hz)], -1),
        np.stack([np.full_like(X, cx + hx), Y, Wd], -1),
        np.stack([np.full_like(X, cx - hx), Y, Wd], -1),
        np.stack([X, np.full_like(X, cy + hy), Wd], -1),
        np.stack([X, np.full_like(X, cy - hy), Wd], -1),
    ]
    normals = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    P = np.concatenate(faces, 0)
    N = np.concatenate([np.broadcast_to(np.asarray(n, np.float32).reshape(1, 1, 3),
                                        f.shape).copy()
                        for f, n in zip(faces, normals)], 0)
    dw = np.concatenate([np.full(f.shape[:2], front_bias if i == 0 else 1.0, np.float32)
                         for i, f in enumerate(faces)], 0)
    return P, N, dw


def supershape(m1=7.0, m2=9.0, n1=0.32, n2=1.7, n3=1.1, scale=1.0):
    """
    Gielis 超形球: 有机尖刺体

    尖刺参数下会自交, 细瓣还会走样成点线; 当花饰用就换成温和形体,
    非要尖刺就把 n1 调大并把采样密度提上去
    """
    def rr(a, m, n1_, n2_, n3_):
        return (np.abs(np.cos(m * a / 4.0)) ** n2_
                + np.abs(np.sin(m * a / 4.0)) ** n3_) ** (-1.0 / n1_)

    def fn(u, v):
        theta = np.pi * (u - 0.5)
        phi = 2 * np.pi * v
        r = rr(theta, m1, n1, n2, n3) * rr(phi, m2, n1, n2, n3)
        q = np.stack([r * np.cos(theta) * np.cos(phi),
                      r * np.cos(theta) * np.sin(phi),
                      r * np.sin(theta)], -1)
        return fit_radius(q, 1.45 * scale)

    return fn


def sweep_ellipse(curve_fn, half_w_fn, half_t=0.045, twist=0.5):
    """
    沿空间曲线扫掠一个扁椭圆截面, 得到有厚度的缎带

    零厚度带子转到与镜头平行时投影宽度趋零, 相邻采样点散开, 形体会碎成尖刺;
    闭合的扁椭圆截面不会退化, 所以数据缎带用它而不是用零厚度带
    """
    def fn(u, v):
        t = u
        h = 1e-3
        p = curve_fn(t)
        tng = norm(curve_fn(np.clip(t + h, 0, 1)) - curve_fn(np.clip(t - h, 0, 1)))
        ref = np.stack([np.zeros_like(t), np.zeros_like(t), np.ones_like(t)], -1)
        n1 = norm(cross(tng, ref))
        n2 = norm(cross(tng, n1))
        ang = 2 * np.pi * twist * u
        e1 = np.cos(ang)[..., None] * n1 + np.sin(ang)[..., None] * n2
        e2 = -np.sin(ang)[..., None] * n1 + np.cos(ang)[..., None] * n2
        a = 2 * np.pi * v
        return (p + e1 * (np.cos(a) * half_w_fn(u))[..., None]
                + e2 * (np.sin(a) * half_t)[..., None])

    return fn


def spiral_ribbon(radius=1.25, height=2.2, turns=1.6, width=0.55):
    """锥面上盘旋的宽缎带, 形体大而好读, 适合当主角"""
    def curve(t):
        a = 2 * np.pi * turns * t
        r = radius * (1.0 - 0.45 * t)
        return np.stack([r * np.cos(a), r * np.sin(a), (t - 0.5) * height], -1)

    def width_fn(t):
        return width * (0.55 + 0.45 * np.sin(np.pi * t))

    return curve, width_fn


# ------------------------------------------------------------------ 相机
class Camera:
    """
    针孔相机, 视图空间朝 +z 看

    shift 是画面内的平移偏移, 用来把物体挪到构图位置而不动镜头朝向, 比调 target 直观
    """

    def __init__(self, eye=(0, 0, 4), target=(0, 0, 0), up=(0, 1, 0),
                 fov=34.0, w=1920, h=1080, shift=(0.0, 0.0)):
        eye = np.asarray(eye, np.float32)
        self.eye = eye
        fwd = norm(np.asarray(target, np.float32) - eye)
        right = norm(cross(fwd, np.asarray(up, np.float32)))
        self.basis = np.stack([right, cross(right, fwd), fwd], 0)
        self.f = (h / 2.0) / math.tan(math.radians(fov) / 2.0)
        self.cx, self.cy = w / 2.0 + shift[0], h / 2.0 + shift[1]
        self.near = 0.08
        self.w, self.h = w, h

    def view(self, p):
        q = p - self.eye
        return np.stack([q @ self.basis[0], q @ self.basis[1], q @ self.basis[2]], -1)

    def project(self, p):
        """投影到像素坐标, 返回 (x, y, z); z 为负表示在镜头背后"""
        q = self.view(p)
        z = q[..., 2]
        ok = z > self.near
        zz = np.where(ok, z, 1.0)
        sx = self.cx + q[..., 0] / zz * self.f
        sy = self.cy - q[..., 1] / zz * self.f
        return np.stack([sx, sy, np.where(ok, z, -1.0)], -1)


def fit_camera(fov, h, obj_radius=1.0, want_radius_px=None, eye_z=None):
    """
    由"想让物体在画面里占多大"反推相机距离

    物体统一归一化到半径 1.0, 投影半径约等于 1.0 / eye_z * (h / 2 / tan(fov / 2)),
    所以先算再调, 不要试错
    """
    f = (h / 2.0) / math.tan(math.radians(fov) / 2.0)
    if eye_z is not None:
        return float(eye_z)
    if not want_radius_px:
        return 4.0
    return float(f * obj_radius / float(want_radius_px))


# ------------------------------------------------------------------ 光照与渲染
# 相机空间的主光方向: 左上, 朝镜头. 定义在相机空间, 于是同一个物体在任何机位都成立
KEY = norm(np.asarray([-0.46, 0.58, -0.67], np.float32))


def luminance(nv, key=KEY, ambient=0.17, key_gain=1.0, rim_gain=0.52,
              rim_power=2.3, floor=0.0):
    """
    由相机空间法线算明暗: 主光加环境光加边缘光

    rim 是把"平的剪影"变成"有体积"的那一项, 权重不要省. 双面光照,
    因为莫比乌斯带这类单侧曲面没有"里面"可以剔除.
    """
    n = norm(nv)
    n = np.where((n[:, 2] > 0)[:, None], -n, n)
    lam = np.clip(n @ np.asarray(key, np.float32), 0.0, None)
    rim = (1.0 - np.clip(np.abs(n[:, 2]), 0.0, 1.0)) ** rim_power
    return clip01(floor + ambient + key_gain * lam + rim_gain * rim)


def render(cam, P, N, splat=2, ambient=0.17, key_gain=1.0, rim_gain=0.52,
           clip_pad=0, depth_cue=0.0, soften=0, weights=None):
    """
    投影, 排序, 散射, 返回 (覆盖率, 明暗, 归一化深度) 三个缓冲

    weights 是每个采样点的相对密度(例如 box_surface 的 front_bias), 它会乘进覆盖率,
    于是前面板可以画得更实; 传 None 表示各点等权.
    """
    w, h = cam.w, cam.h
    P = P.reshape(-1, 3)
    N = N.reshape(-1, 3)
    q = cam.view(P)
    z = q[:, 2]
    ok = z > cam.near
    if clip_pad:
        sx = cam.cx + q[:, 0] / np.maximum(z, 1e-6) * cam.f
        sy = cam.cy - q[:, 1] / np.maximum(z, 1e-6) * cam.f
        ok &= (sx > -clip_pad) & (sx < w + clip_pad) & (sy > -clip_pad) & (sy < h + clip_pad)
    if not ok.any():
        z0 = np.zeros((h, w), np.float32)
        return z0, z0.copy(), z0.copy()

    q, nn, zz = q[ok], N[ok], z[ok]
    nv = np.stack([nn @ cam.basis[0], nn @ cam.basis[1], nn @ cam.basis[2]], -1)
    lum = luminance(nv, ambient=ambient, key_gain=key_gain, rim_gain=rim_gain)
    if depth_cue:
        dz = (zz - zz.min()) / max(1e-6, zz.max() - zz.min())
        lum = clip01(lum * (1.0 - depth_cue * dz))

    sx = cam.cx + q[:, 0] / zz * cam.f
    sy = cam.cy - q[:, 1] / zz * cam.f
    ix = np.round(sx).astype(np.int32)
    iy = np.round(sy).astype(np.int32)

    # 先把每个采样点展开成它的 splat 足迹, 再做一次由远到近的散射;
    # 对整个展开集只排一次序, 而不是每个 tap 各排一次, 足迹重叠处的深度顺序也准确
    s = max(1, int(splat))
    offs = np.array([(dx, dy) for dy in range(s) for dx in range(s)], np.int32)
    px = (ix[:, None] + offs[None, :, 0]).ravel()
    py = (iy[:, None] + offs[None, :, 1]).ravel()
    zr = np.repeat(zz, len(offs))
    lr = np.repeat(lum, len(offs))
    wr = (np.repeat(np.asarray(weights, np.float32)[ok], len(offs))
          if weights is not None else np.ones_like(zr))

    m = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    cove = np.zeros(h * w, np.float32)
    shad = np.zeros(h * w, np.float32)
    dept = np.zeros(h * w, np.float32)
    if m.any():
        sel = np.flatnonzero(m)
        o = sel[np.argsort(-zr[sel])]
        idx = py[o].astype(np.int64) * w + px[o].astype(np.int64)
        cove[idx] = np.clip(wr[o], 0.0, 1.0)
        shad[idx] = lr[o]
        dept[idx] = zr[o]
    cove = cove.reshape(h, w)
    shad = shad.reshape(h, w)
    dept = dept.reshape(h, w)
    if soften:
        # 只在覆盖率的包围盒内做模糊: 全画幅是 830 万像素, 而物体通常只占几个百分点,
        # 全画幅跑四次箱式模糊要接近一秒, 收进包围盒后是几十毫秒
        mk = cove > 0.002
        if mk.any():
            r = max(1, int(round(soften)))
            rows = np.flatnonzero(mk.any(axis=1))
            cols = np.flatnonzero(mk.any(axis=0))
            y0 = max(0, int(rows[0]) - r - 1)
            y1 = min(h, int(rows[-1]) + r + 2)
            x0 = max(0, int(cols[0]) - r - 1)
            x1 = min(w, int(cols[-1]) + r + 2)
            csub = np.clip(box_blur(cove[y0:y1, x0:x1], r) * 1.35, 0.0, 1.0)
            m2 = csub > 0.02
            ssub = np.where(m2,
                            box_blur(shad[y0:y1, x0:x1], r)
                            / np.maximum(box_blur(m2.astype(np.float32), r), 1e-3),
                            0.0)
            cove[y0:y1, x0:x1] = csub
            shad[y0:y1, x0:x1] = np.clip(ssub, 0.0, 1.2)
    zmax = max(1e-6, float(zz.max()))
    return cove, shad, dept / zmax


def visible_grid(cam, Pgrid, depth, tol=0.002, neigh=1, N=None, backface=True):
    """
    逐点可见性: 背面剔除加深度缓冲比对, 得到布尔网格

    用它画等参线做隐藏线消除, 于是只画形体的近侧半边, 这就是刻版效果.

    两个判据分工不同, 缺一不可:

      背面剔除  给了法线 N 且 backface 为真时, 直接把背对镜头的点剔掉. 闭合曲面上
                被挡住的那一半正好就是背面, 这一条零成本且零漏判
      深度比对  处理"正面但被别的部分挡住"的自遮挡. 它依赖深度缓冲, 而点云在像素级
                一定留有空隙, 所以要看邻域的最小深度 (neigh), 否则穿过空隙看到的背面
                会被当成可见; 邻域内完全没有覆盖时按可见处理, 因为无从判断被挡

    参数取值:
      tol    归一化深度上的容差, 世界量纲约等于 tol 乘深度范围. 它要明显小于同一像素上
             近面与远面的深度差, 也就是形体厚度; 细管上这个差很小, 给到 0.01 会让七成
             背面被判成可见. 缺省 0.002
      neigh  邻域半径, 缺省 1 (3x3). 它把深度图里的空隙用邻近的最近深度填上, 代价是
             邻近其它部分的最近深度也会被拉进来, 正面点被误挡的比例升高; 点云够密时
             取 0 更干净, 点云很稀时才调大
      N      法线网格, 形状与 Pgrid 相同. 单侧曲面(莫比乌斯带这类)或开放曲面要传
             backface=False, 否则会把它唯一的那一面剔掉

    返回布尔网格, 形状与 Pgrid 的前两维一致.
    """
    nu, nv = Pgrid.shape[:2]
    pr = cam.project(Pgrid.reshape(-1, 3))
    zmax = max(1e-6, float(pr[:, 2].max()))
    z = pr[:, 2].reshape(nu, nv) / zmax
    sx = pr[:, 0].reshape(nu, nv)
    sy = pr[:, 1].reshape(nu, nv)
    ix = np.clip(np.round(sx).astype(np.int32), 0, cam.w - 1)
    iy = np.clip(np.round(sy).astype(np.int32), 0, cam.h - 1)
    covered = depth > 0
    filled = np.zeros_like(depth)
    if covered.any():
        # 同样只在覆盖范围内做邻域最小值, 全画幅的平移与填充太贵
        rows = np.flatnonzero(covered.any(axis=1))
        cols = np.flatnonzero(covered.any(axis=0))
        r = max(0, int(neigh))
        y0 = max(0, int(rows[0]) - r)
        y1 = min(cam.h, int(rows[-1]) + r + 1)
        x0 = max(0, int(cols[0]) - r)
        x1 = min(cam.w, int(cols[-1]) + r + 1)
        sub = depth[y0:y1, x0:x1]
        f = min_filter(np.where(sub > 0, sub, np.inf), r)
        filled[y0:y1, x0:x1] = np.where(np.isfinite(f), f, 0.0)
    d = filled[iy, ix]
    vis = (pr[:, 2].reshape(nu, nv) > 0) & ((d <= 0) | (z <= d + tol))
    if N is not None and backface:
        nn = N.reshape(-1, 3)
        nview = np.stack([nn @ cam.basis[0], nn @ cam.basis[1], nn @ cam.basis[2]], -1)
        q = cam.view(Pgrid.reshape(-1, 3))
        dist = np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
        to_cam = -q / dist
        front = (np.sum(nview * to_cam, axis=1) < 0).reshape(nu, nv)
        vis = vis & front
    return vis


def contour_grid(cam, Pgrid, vis, max_lines=42):
    """
    可见段折线: 把等参线上连续可见的部分切成一段段折线

    返回的是若干段可见折线, 远的半边自动被挡住, 所以不要用整条线去画
    """
    nu, nv = Pgrid.shape[:2]
    pr = cam.project(Pgrid.reshape(-1, 3)).reshape(nu, nv, 3)
    runs = []
    for axis in (0, 1):
        n_lines = nu if axis == 0 else nv
        for i in range(0, n_lines, max(1, n_lines // max_lines)):
            pts = pr[i, :, :2] if axis == 0 else pr[:, i, :2]
            v = vis[i, :] if axis == 0 else vis[:, i]
            start = None
            for j, good in enumerate(v):
                if good and start is None:
                    start = j
                elif not good and start is not None:
                    if j - start > 2:
                        runs.append([tuple(pts[k]) for k in range(start, j)])
                    start = None
            if start is not None and len(v) - start > 2:
                runs.append([tuple(pts[k]) for k in range(start, len(v))])
    return runs

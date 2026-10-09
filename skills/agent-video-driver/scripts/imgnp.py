# -*- coding: utf-8 -*-
"""
共享 numpy 图像基元

画面引擎是 Pillow 的, 而 3D 点云与印刷原语都在 numpy 缓冲上算. 两者都要用到的
邻域滤波与模糊放在这里, 避免各写一份: 同一套语义的滤波器有两份实现, 迟早会不一致.

  归一化:  unit
  模糊:    blur (FFT 高斯, 适合大半径)   box_blur (前缀和箱式, 适合小半径)
  邻域:    min_filter  max_filter
  平移:    shift2 (亚像素, FFT 相位斜坡)
"""
import math

import numpy as np


def unit(a):
    """零均值单位标准差, 便于把噪声层按幅度叠加"""
    a = np.asarray(a, np.float32)
    s = float(a.std())
    return (a - float(a.mean())) / (s if s > 1e-9 else 1.0)


def _box_axis(a, r, axis):
    """单轴箱式模糊, 前缀和实现, 边界按边缘复制"""
    r = int(r)
    if r < 1:
        return np.asarray(a, np.float32)
    out = np.asarray(a, np.float32)
    k = 2 * r + 1
    n = out.shape[axis]
    pad = [(0, 0)] * out.ndim
    pad[axis] = (r, r)
    p = np.pad(out, pad, mode="edge")
    c = np.cumsum(p, axis=axis)
    zshape = list(c.shape)
    zshape[axis] = 1
    c = np.concatenate([np.zeros(zshape, c.dtype), c], axis=axis)
    hi = [slice(None)] * out.ndim
    lo = [slice(None)] * out.ndim
    hi[axis] = slice(k, k + n)
    lo[axis] = slice(0, n)
    return (c[tuple(hi)] - c[tuple(lo)]) / float(k)


def box_blur(a, r):
    """
    半径 r 的可分离箱式模糊, 用前缀和做, 边界按边缘复制

    小半径上比 FFT 高斯便宜得多, 适合只抹掉亚像素采样结构或做细粒纹理.
    """
    out = np.asarray(a, np.float32)
    for axis in (0, 1):
        out = _box_axis(out, r, axis)
    return out


def blur(a, sigma, axis=None):
    """
    高斯模糊

    小半径(小于 3 像素)走箱式: 前缀和比 FFT 快一个量级, 而这一档的视觉差异可以忽略.
    大半径走 FFT 域乘高斯窗: 它的代价与半径无关, 而箱式的代价随半径线性增长,
    纸浆斑块这类几十像素的低频层用 FFT 才划算.

    axis 传 None 做二维, 传 0 或 1 只沿该轴做; 只沿一轴做是各向异性纹理的来源,
    例如纸的纤维就是"沿一个方向很糊, 垂直方向很锐".
    """
    a = np.asarray(a, np.float32)
    if sigma <= 0:
        return a
    if sigma < 3.0:
        r = max(1, int(round(sigma)))
        if axis is None:
            return box_blur(a, r)
        return _box_axis(a, r, int(axis))
    out = a
    for ax in ((0, 1) if axis is None else (int(axis),)):
        n = out.shape[ax]
        freqs = np.fft.rfftfreq(n) if ax == 0 else np.fft.fftfreq(n)
        g = np.exp(-2.0 * (math.pi * sigma * freqs) ** 2)
        shape = [1] * out.ndim
        shape[ax] = len(freqs)
        g = g.reshape(shape)
        if ax == 0:
            out = np.fft.irfft(np.fft.rfft(out, axis=0) * g, n, axis=0)
        else:
            out = np.real(np.fft.ifft(np.fft.fft(out, axis=1) * g, axis=1))
    return out.astype(np.float32)


def _shift(a, d, axis):
    """沿 axis 平移 d 个像素, 空出来的边用边缘值补, 不环绕"""
    if d == 0:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (max(d, 0), max(-d, 0))
    p = np.pad(a, pad, mode="edge")
    n = a.shape[axis]
    sl = [slice(None)] * a.ndim
    sl[axis] = slice(0, n) if d >= 0 else slice(-d, n - d)
    return p[tuple(sl)]


def _rank_filter(a, r, keep_max):
    out = np.asarray(a, np.float32)
    r = int(r)
    if r < 1:
        return out
    op = np.maximum if keep_max else np.minimum
    for axis in (0, 1):
        for d in range(1, r + 1):
            out = op(out, _shift(out, d, axis))
            out = op(out, _shift(out, -d, axis))
    return out


def min_filter(a, r=1):
    """
    半径 r 的滑窗最小值, 边界按边缘复制

    两个用途: 把深度图里的空隙用邻近的最近深度填上(点云渲染),
    以及从覆盖率里腐蚀出内侧剪影线(印刷主版线).
    """
    return _rank_filter(a, r, False)


def max_filter(a, r=1):
    """半径 r 的滑窗最大值, 边界按边缘复制; 用于把笔画加粗或补掉细缝"""
    return _rank_filter(a, r, True)


def shift2(a, d):
    """
    亚像素平移, 用 FFT 相位斜坡实现, 边界按环绕处理

    环绕在印刷原语里可以接受: 套印偏移只有几个像素, 而纸底与网点屏本来就是平铺的.
    二维输入与三维输入(逐通道)都支持.
    """
    dx, dy = d
    a = np.asarray(a, np.float32)
    h, w = a.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    ph = np.exp(-2j * math.pi * (fx * dx + fy * dy))
    if a.ndim > 2:
        ph = ph[..., None]
    return np.fft.irfft(np.fft.rfft(a, axis=1) * ph, w, axis=1).astype(np.float32)

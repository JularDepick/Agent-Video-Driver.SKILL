# -*- coding: utf-8 -*-
"""
共享 DSP 基元

各配乐脚本从这里取底层工具, 避免每个音色库各写一份
只放与题材无关的纯函数, 不放任何编排逻辑
"""
import wave

import numpy as np

SR = 48000


def add(dst, sig, at):
    """把 sig 叠加到 dst 的 at 秒处, 超出部分自动截断"""
    n = len(dst)
    i = int(round(at * SR))
    if i >= n or i + len(sig) <= 0:
        return
    j0 = max(0, i)
    s0 = j0 - i
    m = min(len(sig) - s0, n - j0)
    if m > 0:
        dst[j0:j0 + m] += sig[s0:s0 + m]


def lp_fft(x, cutoff, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    H = 1.0 / np.sqrt(1.0 + (f / max(cutoff, 1.0)) ** (2 * order))
    return np.fft.irfft(X * H, n=len(x))


def hp_fft(x, cutoff, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    r = f / max(cutoff, 1.0)
    H = r ** order / np.sqrt(1.0 + r ** (2 * order))
    return np.fft.irfft(X * H, n=len(x))


def bp_fft(x, lo, hi, order=2):
    return hp_fft(lp_fft(x, hi, order), lo, order)


def sat(x, drive=1.0):
    return np.tanh(x * drive) / np.tanh(drive)


def hz(semi):
    """MIDI 半音号转频率, 60 号是中央 C"""
    return 440.0 * 2 ** ((semi - 69) / 12.0)


def scale(root, mode="minor"):
    """返回一个八度内的半音偏移表"""
    if mode == "minor":
        return [root + s for s in (0, 2, 3, 5, 7, 8, 10)]
    if mode == "major":
        return [root + s for s in (0, 2, 4, 5, 7, 9, 11)]
    if mode == "dorian":
        return [root + s for s in (0, 2, 3, 5, 7, 9, 10)]
    raise ValueError(mode)


def make_ir(dur=2.2, decay=0.7, cutoff=2400, order=3, rng=None):
    """生成混响脉冲响应, 必须低通, 否则混响会把高频铺满全片"""
    rng = rng or np.random.default_rng(7)
    n = int(dur * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t / decay)
    ir = lp_fft(ir, cutoff, order)
    a = int(0.012 * SR)
    ir[:a] *= np.linspace(0, 1, a)
    return ir / np.sqrt(np.sum(ir ** 2))


def reverb(x, ir, amount=0.4):
    L = len(x) + len(ir) - 1
    nfft = 1 << (L - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)[:len(x)]
    return x + y * amount


def bus_compress(st, thr=0.16, power=0.55, tau=0.09):
    """总线软压缩, 让整体电平平稳, 避免忽大忽小"""
    env = np.abs(st).mean(axis=0)
    n = int(0.35 * SR)
    kern = np.exp(-np.arange(n) / (SR * tau))
    kern /= kern.sum()
    nfft = 1 << (len(env) + n - 2).bit_length()
    env = np.fft.irfft(np.fft.rfft(env, nfft) * np.fft.rfft(kern, nfft), nfft)[:len(env)]
    gain = np.ones_like(env)
    over = env > thr
    gain[over] = (thr / env[over]) ** power
    return st * gain


def warm_master(st, warm_lo=220, warm_hi=900, warm=0.40,
                cut1=3000, cut1_amt=0.45, cut2=6000, cut2_amt=0.35,
                lpf=4600, lpf_order=3, hpf=32, peak=0.95, drive=0.9):
    """
    暖调母带链: 补温暖区, 压高频, 去隆隆声, 归一化后软限幅
    高频处理是防刺耳的关键, 不要为了亮而省掉
    """
    L, R = st[0], st[1]
    st = np.stack([L + warm * bp_fft(L, warm_lo, warm_hi, 2),
                   R + warm * bp_fft(R, warm_lo, warm_hi, 2)])
    st = st - cut1_amt * np.stack([hp_fft(st[0], cut1), hp_fft(st[1], cut1)])
    st = st - cut2_amt * np.stack([hp_fft(st[0], cut2), hp_fft(st[1], cut2)])
    st = st - 0.85 * np.stack([lp_fft(st[0], hpf), lp_fft(st[1], hpf)])
    st = np.stack([lp_fft(st[0], lpf, lpf_order), lp_fft(st[1], lpf, lpf_order)])
    st = st / max(np.max(np.abs(st)), 1e-9) * peak
    return sat(st * drive, 1.05) * 0.92


def write_wav(path, st):
    pcm = (np.clip(st, -1, 1).T * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return pcm.shape

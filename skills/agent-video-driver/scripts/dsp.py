# -*- coding: utf-8 -*-
"""
共享 DSP 基元

各配乐脚本从这里取底层工具, 避免每个音色库各写一份
只放与题材无关的纯函数, 不放任何编排逻辑
"""
import math
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


def peak_db(st):
    """采样峰值, dBFS"""
    return 20.0 * math.log10(max(float(np.max(np.abs(st))), 1e-12))


def true_peak_db(st, os=4, block=1 << 16, pad=64):
    """
    真峰, dBTP: 分块做 os 倍 FFT 补零过采样后取峰值

    采样峰值只保证采样点不超, 编码器在采样之间照样顶上去, 所以真峰必须在过采样之后量.
    真峰是局部量, 分块量与整段量等价; 分块是为了避免整段过采样把内存吃满,
    108 秒 48kHz 立体声整段 4 倍过采样需要上 GB.
    """
    if os <= 1:
        return peak_db(st)
    x = np.atleast_2d(st)
    n = x.shape[-1]
    peak = 0.0
    for ch in x:
        for a in range(0, n, block):
            b = min(n, a + block)
            seg = ch[max(0, a - pad):min(n, b + pad)]
            m = len(seg)
            nfft = 1 << int(math.ceil(math.log2(max(2, m))))
            spec = np.fft.rfft(seg, nfft)
            up = np.zeros(nfft * os // 2 + 1, dtype=complex)
            up[:len(spec)] = spec
            # 频域补零等于时域插值, numpy 的 irfft 按输出长度归一, 所以要乘回 os
            y = np.fft.irfft(up, nfft * os) * os
            peak = max(peak, float(np.max(np.abs(y))))
    return 20.0 * math.log10(max(peak, 1e-12))


def soft_clip(x, ceil=0.95):
    """
    软限幅: 小信号保持单位增益, 逼近 ceil 时按 tanh 曲线压缩

    只压瞬态, 主体电平不动, 所以它比整体降增益更能保住响度
    """
    return ceil * np.tanh(x / ceil)


def fade_edges(st, dur=None, fade_in=1.0, fade_out=2.4, curve=1.3):
    """
    首尾淡入淡出, 必须在归一化之前做

    顺序反了的话开头的瞬态会把整首的天花板顶掉, 整片偏轻
    """
    n = st.shape[-1]
    d = float(dur) if dur else n / SR
    t = np.arange(n) / SR
    a = np.ones(n)
    if fade_in > 0:
        a = a * np.clip(t / fade_in, 0.0, 1.0)
    if fade_out > 0:
        a = a * np.clip((d - t) / fade_out, 0.0, 1.0) ** curve
    return st * a


def normalize(st, peak=0.95):
    """归一化到目标峰值; 它是母带链的倒数第二步, 真峰压制之后才是最后一步"""
    return st / max(float(np.max(np.abs(st))), 1e-9) * peak


def true_peak_limit(st, ceil_dbtp=-1.0, os=4, block=1 << 16, pad=64):
    """
    过采样真峰压制: 逐块 os 倍过采样, 在过采样域做 tanh 膝软限幅, 低通回原带宽再抽取,
    最后按实测真峰精确回抬到目标天花板

    三点设计理由:
      1 在过采样域压, 压的是编码器真正看到的采样间峰值, 不是采样点
      2 软限幅只压瞬态, 主体电平不动, 所以比整体降增益更能保住响度
      3 压完再按实测真峰等比回抬, 于是主体被抬回来而真峰正好落在天花板上;
        这一步是线性的, 不会引入新的削波
    压完必须低通再抽取, 否则抽取会把压出来的高频折回可听带内.
    返回 (处理后的信号, 压制后的实测真峰 dBTP).
    """
    ceil = 10.0 ** (ceil_dbtp / 20.0)
    two_d = np.ndim(st) > 1
    x = np.atleast_2d(st).copy()
    n = x.shape[-1]
    for ci in range(x.shape[0]):
        ch = x[ci]
        for a in range(0, n, block):
            b = min(n, a + block)
            a0, b0 = max(0, a - pad), min(n, b + pad)
            seg = ch[a0:b0]
            m = len(seg)
            nfft = 1 << int(math.ceil(math.log2(max(2, m))))
            spec = np.fft.rfft(seg, nfft)
            up = np.zeros(nfft * os // 2 + 1, dtype=complex)
            up[:len(spec)] = spec
            y = np.fft.irfft(up, nfft * os) * os
            y = ceil * np.tanh(y / ceil)
            spec2 = np.fft.rfft(y)
            spec2[nfft // 2 + 1:] = 0.0
            ch[a0:b0] = np.fft.irfft(spec2, nfft * os)[::os][:m]
    out = x if two_d else x[0]
    tp = true_peak_db(out, os)
    if tp > ceil_dbtp:
        out = out * (10.0 ** ((ceil_dbtp - tp) / 20.0))
        tp = true_peak_db(out, os)
    elif tp < ceil_dbtp - 0.05:
        # 软限幅压掉的那部分电平抬回来, 主体因此不吃亏
        out = out * (10.0 ** ((ceil_dbtp - tp) / 20.0))
        tp = true_peak_db(out, os)
    return out, tp


def tape_wow(st, depth=0.0018, rate=0.63):
    """
    磁带抖晃: 用一条缓慢游走的读指针重采样, 做慢速音高漂移

    比加噪声有效得多, 它改的是时间轴而不是叠加信号. depth 是最大相对漂移量, 千分之二以内听不出跑调.
    两个不同速率的正弦叠加, 避免听出周期.
    """
    two_d = np.ndim(st) > 1
    x = np.atleast_2d(st)
    n = x.shape[-1]
    t = np.arange(n) / SR
    warp = depth * (np.sin(2 * np.pi * rate * t)
                    + 0.5 * np.sin(2 * np.pi * rate * 1.7 * t + 1.1))
    src = np.clip(np.arange(n) - warp * SR, 0.0, n - 1.0)
    i0 = np.floor(src).astype(np.int64)
    i1 = np.minimum(i0 + 1, n - 1)
    f = (src - i0).astype(np.float32)
    out = np.stack([ch[i0] * (1.0 - f) + ch[i1] * f for ch in x])
    return out if two_d else out[0]


def vinyl_bed(n, level=0.005, seed=7, rate=9.0):
    """
    黑胶底噪: 稀疏爆点加高通嘶声

    它是氛围不是内容, 电平不要超过千分之五, 否则会盖住弱奏段落
    """
    rng = np.random.default_rng(seed)
    hiss = hp_fft(rng.standard_normal(n), 1200.0)
    hiss = hiss / max(float(np.max(np.abs(hiss))), 1e-9)
    crackle = np.zeros(n)
    k = max(1, int(n / SR * rate))
    for i in rng.integers(0, max(1, n - 64), size=k):
        w = int(rng.integers(4, 40))
        crackle[i:i + w] += (np.exp(-np.arange(w) / max(1.0, w / 3.0))
                             * float(rng.uniform(0.3, 1.0)))
    return (hiss * 0.6 + crackle) * level


def fm_piano(f, dur=1.4, amp=1.0, ratio=3.01, index=2.6, decay=3.2, trem=5.0):
    """
    FM 电钢: 载波加指数衰减的调制指数, 再叠 5Hz 慢颤音, 就是 Rhodes 味

    调制比取 3.01 而不是整数 3, 让边带不与基频重合, 听感偏铃而不是偏木
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    env = np.exp(-t * decay)
    mi = index * np.exp(-t * 6.0)
    y = np.sin(2 * np.pi * f * t + np.sin(2 * np.pi * f * ratio * t) * mi) * env
    y = y * (1.0 + 0.06 * np.sin(2 * np.pi * trem * t))
    a = int(0.004 * SR)
    if a > 1:
        y[:a] = y[:a] * np.linspace(0, 1, a)
    return y * amp / max(float(np.max(np.abs(y))), 1e-9)


def warm_master(st, dur=None, fade_in=1.0, fade_out=2.4, fade_curve=1.3,
                warm_lo=220, warm_hi=900, warm=0.40,
                cut1=3000, cut1_amt=0.45, cut2=6000, cut2_amt=0.35,
                lpf=4600, lpf_order=3, hpf=32,
                ceil=0.95, clip_ceil=None, true_peak=-1.0, os=4):
    """
    暖调母带链, 顺序固定, 不要调换:

      1 滤波: 补温暖区, 压高频, 去隆隆声; 高频处理是防刺耳的关键, 不要为了亮而省掉
      2 软限幅: 只削掉顶端几个 dB, 防止单个瞬态决定归一化的天花板
      3 首尾淡入淡出
      4 归一化: 必须排在淡入淡出之后, 否则开头的瞬态会顶掉整首的天花板
      5 过采样真峰压制: 编码器看的是采样之间的峰, 不是采样点

    软限幅的膝盖不能压在最终目标电平上. 若把它设成 ceil 本身, 等于把整个混音
    按 0.95 硬削, 鼓点瞬态被压平, 拍点峰值比会掉到 1.0 附近, 卡点全毁;
    缺省取 ceil 的 1.5 倍, 只吃掉顶端约 3.5dB.

    返回 (处理后的立体声, 母带报告字典)
    """
    clip_at = clip_ceil if clip_ceil else ceil * 1.5
    L, R = st[0], st[1]
    y = np.stack([L + warm * bp_fft(L, warm_lo, warm_hi, 2),
                  R + warm * bp_fft(R, warm_lo, warm_hi, 2)])
    y = y - cut1_amt * np.stack([hp_fft(y[0], cut1), hp_fft(y[1], cut1)])
    y = y - cut2_amt * np.stack([hp_fft(y[0], cut2), hp_fft(y[1], cut2)])
    y = y - 0.85 * np.stack([lp_fft(y[0], hpf), lp_fft(y[1], hpf)])
    y = np.stack([lp_fft(y[0], lpf, lpf_order), lp_fft(y[1], lpf, lpf_order)])
    raw_peak = float(np.max(np.abs(y)))
    y = soft_clip(y, clip_at)
    y = fade_edges(y, dur=dur, fade_in=fade_in, fade_out=fade_out, curve=fade_curve)
    y = normalize(y, ceil)
    y, tp = true_peak_limit(y, true_peak, os)
    report = {
        "samples": int(y.shape[-1]),
        "raw_peak_db": round(20.0 * math.log10(max(raw_peak, 1e-12)), 2),
        "clip_ceil": round(clip_at, 3),
        "peak_db": round(peak_db(y), 2),
        "true_peak_db": round(tp, 2),
        "true_peak_ok": bool(tp <= true_peak + 1e-6),
    }
    return y, report


def write_wav(path, st):
    pcm = (np.clip(st, -1, 1).T * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return pcm.shape

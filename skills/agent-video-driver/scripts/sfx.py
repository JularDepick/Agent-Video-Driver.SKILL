# -*- coding: utf-8 -*-
"""
音效轨混音: 自产拟音与用户素材按 cue 表叠成一条 48kHz 立体声 WAV

  python scripts/sfx.py cues.json audio/sfx.wav --duration 108

cues.json 三种写法 (同一个 cue 可以两者都给, 有 file 且文件存在时用 file):
  [
    {"t": 8.507, "synth": "swell", "notes": [57, 60, 64], "peak": 0.26},
    {"t": 16.8, "synth": "thump", "peak": 0.40, "file": "assets/thud.wav"},
    {"t": 24.0, "file": "assets/custom.wav"}
  ]

  t      落点秒数, 唯一必填项
  synth  自产拟音名, 见下面的音色表; 不认识的名字会报错并列出可用名字
  file   用户自备素材路径 (相对 cues.json 解析); 与 synth 同时给时 file 优先, 文件缺失才回退 synth
  peak   归一化之后的峰值, 不填用音色表的缺省值
  dur    只对 noise_bed 有效, 氛围床长度秒数
  notes  MIDI 半音号数组, 只对和弦类音色 (swell, bloom, harp) 有效

自产音色表 (峰值是归一化之后的相对响度, 可直接照抄):

  转场类 (推荐用这四个, 不要用噪声 whoosh):
    swell 0.26  反向渐强后急停的和弦, 压在章节切点上
    bloom 0.30  软钟声和弦, 用于光圈式转场
    glide 0.20  安静的三角波上滑, 用于穿元素式转场
    harp  0.26  快速拨弦走句, 用于条带式转场
  动作类 (跟着画面动作走, 材质要对得上):
    click 0.16 纸卡轻点 | tick 0.14 极短高频 | paper 0.30 纸与卡片
    shaker 0.18 沙锤 | thump 0.40 低频落地 | stamp 0.42 橡皮图章
    ding 0.24 单音铃 | riser 0.28 上滑提示
  氛围类:
    noise_bed 0.05 房间底噪, 全片或整段连续, 电平必须很低
  已弃用:
    whoosh 0.22 噪声扫过, 实测"一开始酷后来烦", 只在没有别的选择时用, 且全片不超过两次

两条纪律 (来自实测反馈):
  a 音效要稀疏: 约一半的切点什么都不放, 由下一场的入场声自己把切点带出来; 每屏不超过 1 到 2 个.
     全片至少安排两处真实静默, 放在转折或情绪最高点之前
  b 混入配乐后必须重跑响度验收: 集成响度 -16 到 -14 LUFS, 真峰值不高于 -1.0 dBFS,
     命令见 references/verification.md; 换音轨不必重渲画面, 用 `-map 0:v -map 1:a -c:v copy`

只依赖标准库加 numpy, 不联网. 采样率固定 48000 立体声, 与 dsp.py 一致.
用户素材不是 48k 立体声 pcm_s16le 时用 ffmpeg 转一次临时 WAV.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

import dsp

SR = dsp.SR
TMPDIR = os.path.join("temp", "sfx_tmp")

WHOOSH_WARN = 2
DENSITY_MIN_SECONDS = 6.0
SILENCE_HINT_SECONDS = 6.0


class SfxError(Exception):
    """可预期的输入问题, 只打印一句说明, 不抛栈"""


# ----------------------------------------------------------------- 样本读写
def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True)
    err = p.stderr
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return p.returncode, (err or "").strip()


def read_wav_raw(path):
    """读成 (2, n) 浮点数组, 不是 48k 立体声 pcm_s16le 时返回 None"""
    with wave.open(path, "rb") as w:
        conf = (w.getnchannels() == 2 and w.getsampwidth() == 2
                and w.getframerate() == SR and w.getcomptype() == "NONE")
        if not conf:
            return None
        raw = w.readframes(w.getnframes())
    if len(raw) < 4 or len(raw) % 4:
        return None
    return np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float64).T / 32768.0


def load_sample(path):
    """返回 (2, n) 浮点数组, 不合规的先用 ffmpeg 转临时 WAV, 读完即删"""
    try:
        a = read_wav_raw(path)
    except Exception:
        a = None
    if a is not None and a.shape[1] > 0:
        return a
    ff = shutil.which("ffmpeg")
    if not ff:
        raise SfxError("样本 %s 不是 48k 立体声 pcm_s16le, 而 PATH 里找不到 ffmpeg, 无法转码" % path)
    os.makedirs(TMPDIR, exist_ok=True)
    tmp = os.path.join(TMPDIR, "t%08d.wav" % (abs(hash(path)) % 10 ** 8))
    try:
        code, err = run_cmd([ff, "-y", "-v", "error", "-i", path, "-ar", str(SR), "-ac", "2",
                             "-c:a", "pcm_s16le", tmp])
        if code != 0:
            raise SfxError("样本 %s 转码失败: %s" % (path, err or "ffmpeg 返回非零"))
        a = read_wav_raw(tmp)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        try:
            os.rmdir(TMPDIR)
        except OSError:
            pass
    if a is None or a.shape[1] == 0:
        raise SfxError("样本 %s 转码后仍读不出 48k 立体声 pcm_s16le" % path)
    return a


def write_wav(path, st):
    """写 pcm_s16le 立体声, st 形状 (2, n), 与 dsp.write_wav 的写法一致"""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    pcm = (np.clip(st, -1, 1).T * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return pcm.shape


# ----------------------------------------------------------------- 拟音基元
def _noise(n, seed):
    return np.random.default_rng(seed).standard_normal(n)


def _t(dur):
    return np.arange(int(round(dur * SR))) / SR


def _env_exp(n, decay):
    return np.exp(-np.arange(n) / max(1.0, decay * SR))


def _stereo(mono, spread=0.004):
    """单声道素材轻微去相关成两声部: 右声道延迟几毫秒, 避免听起来贴在正中"""
    d = int(spread * SR)
    if d <= 0 or d >= len(mono):
        return np.stack([mono, mono])
    r = np.concatenate([np.zeros(d), mono[:-d]])
    return np.stack([mono, 0.85 * r])


def _norm_mono(y):
    m = float(np.max(np.abs(y)))
    if m <= 0:
        return y
    return y / m


def synth_click(dur=0.035, seed=1):
    n = int(round(dur * SR))
    t = _t(dur)
    body = dsp.hp_fft(_noise(n, seed), 1800.0) * _env_exp(n, 0.006)
    tone = np.sin(2 * np.pi * 1150 * t) * _env_exp(n, 0.004)
    return _stereo(_norm_mono(body * 0.8 + tone * 0.4))


def synth_tick(dur=0.022, seed=2):
    n = int(round(dur * SR))
    body = dsp.hp_fft(_noise(n, seed), 3200.0) * _env_exp(n, 0.0035)
    return _stereo(_norm_mono(body))


def synth_thump(dur=0.55, seed=3):
    t = _t(dur)
    f = 120.0 * np.exp(-t * 7.0) + 42.0
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env_exp(len(t), 0.10)
    n = len(t)
    dust = dsp.lp_fft(_noise(n, seed), 260.0) * _env_exp(n, 0.03) * 0.35
    return _stereo(_norm_mono(tone + dust))


def synth_stamp(dur=0.38, seed=4):
    t = _t(dur)
    f = 150.0 * np.exp(-t * 9.0) + 55.0
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env_exp(len(t), 0.07)
    n = len(t)
    click = dsp.hp_fft(_noise(n, seed), 1500.0) * _env_exp(n, 0.008) * 0.6
    return _stereo(_norm_mono(dsp.sat(thump + click, 1.4)))


def synth_paper(dur=0.28, seed=5):
    n = int(round(dur * SR))
    x = dsp.bp_fft(_noise(n, seed), 900.0, 4200.0)
    crinkle = 0.6 + 0.4 * np.sin(2 * np.pi * 13.0 * np.arange(n) / SR)
    return _stereo(_norm_mono(x * crinkle * _env_exp(n, 0.05)))


def synth_shaker(dur=0.16, seed=6):
    n = int(round(dur * SR))
    x = dsp.hp_fft(_noise(n, seed), 4000.0)
    return _stereo(_norm_mono(x * _env_exp(n, 0.03)))


def synth_whoosh(dur=0.6, seed=7):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    # 升后降的钟形包络, 频带随包络上移再回落
    bell = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    x = dsp.bp_fft(_noise(n, seed), 500.0, 3000.0) * bell
    return _stereo(_norm_mono(x))


def synth_riser(dur=1.5, seed=8):
    t = _t(dur)
    n = len(t)
    f = np.linspace(180.0, 1100.0, n)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
    air = dsp.bp_fft(_noise(n, seed), 900.0, 3600.0) * 0.35
    return _stereo(_norm_mono((tone + air) * (t / max(dur, 1e-6)) ** 1.2))


def _chord_notes(notes):
    return notes if notes else [57, 60, 64]


def synth_swell(dur=1.2, seed=9, notes=None):
    """反向渐强后急停的和弦, 压在切点上: 实测比噪声 whoosh 耐听, 且不糊掉拍点"""
    t = _t(dur)
    n = len(t)
    y = np.zeros(n)
    for k, semi in enumerate(_chord_notes(notes)):
        y += np.sin(2 * np.pi * dsp.hz(semi) * t + 0.3 * k)
    y = dsp.lp_fft(y, 2600.0)
    rise = np.clip(t / max(dur - 0.02, 1e-6), 0, 1) ** 1.8
    y = y * rise
    cut = int(0.02 * SR)
    if 0 < cut < n:
        y[n - cut:] *= np.linspace(1, 0, cut)
    return _stereo(_norm_mono(y))


def synth_bloom(dur=1.6, seed=10, notes=None):
    """软钟声和弦: 用于光圈式转场"""
    t = _t(dur)
    n = len(t)
    y = np.zeros(n)
    for k, semi in enumerate(_chord_notes(notes)):
        f = dsp.hz(semi)
        for j, (ratio, amp, dec) in enumerate([(1.0, 1.0, 0.45), (2.01, 0.35, 0.25),
                                               (3.02, 0.16, 0.16)]):
            y += amp * np.sin(2 * np.pi * f * ratio * t) * np.exp(-t / dec) * (1.0 - 0.08 * k * j)
    atk = int(0.012 * SR)
    if atk > 1:
        y[:atk] *= np.linspace(0, 1, atk)
    return _stereo(_norm_mono(dsp.lp_fft(y, 5200.0)))


def synth_glide(dur=0.8, seed=11, notes=None):
    """安静的三角波上滑: 用于穿元素式转场"""
    t = _t(dur)
    n = len(t)
    base = dsp.hz(_chord_notes(notes)[0]) / 2
    f = np.linspace(base, base * 2.4, n)
    ph = 2 * np.pi * np.cumsum(f) / SR
    tri = 2 / np.pi * np.arcsin(np.sin(ph))
    y = tri * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.2 * 0.5
    return _stereo(_norm_mono(dsp.lp_fft(y, 3000.0)))


def synth_harp(dur=0.9, seed=12, notes=None):
    """快速拨弦走句: 用于条带式转场, 上行或下行由 notes 顺序决定"""
    seq = _chord_notes(notes)
    step = dur / (len(seq) + 1)
    n = int(round(dur * SR))
    y = np.zeros(n)
    for i, semi in enumerate(seq):
        t0 = i * step
        nn = int(round((dur - t0) * SR))
        if nn <= 0:
            continue
        tt = np.arange(nn) / SR
        f = dsp.hz(semi + 12)
        v = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * f * 2 * tt)) \
            * np.exp(-tt / 0.28)
        dsp.add(y, v, t0)
    return _stereo(_norm_mono(y))


def synth_ding(dur=1.3, seed=13, notes=None):
    t = _t(dur)
    f = dsp.hz(_chord_notes(notes)[0] + 12)
    y = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.76 * t)
         + 0.18 * np.sin(2 * np.pi * f * 5.4 * t)) * np.exp(-t / 0.5)
    atk = int(0.004 * SR)
    if atk > 1:
        y[:atk] *= np.linspace(0, 1, atk)
    return _stereo(_norm_mono(y))


def synth_noise_bed(dur=8.0, seed=14, notes=None):
    """氛围床: 房间底噪, 电平必须很低 (缺省峰值 0.05), 全片或整段连续"""
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    base = dsp.lp_fft(_noise(n, seed), 700.0) * 0.7
    base += dsp.bp_fft(_noise(n, seed + 1), 1200.0, 4200.0) * 0.12
    wander = 0.75 + 0.25 * np.sin(2 * np.pi * 0.07 * t + 0.6)
    fade = int(0.5 * SR)
    if 0 < fade < n // 2:
        base[:fade] *= np.linspace(0, 1, fade)
        base[n - fade:] *= np.linspace(1, 0, fade)
    return _stereo(_norm_mono(base * wander))


SYNTH_TABLE = {
    "swell": (synth_swell, 0.26, "反向渐强后急停的和弦 (推荐用于章节切点)"),
    "bloom": (synth_bloom, 0.30, "软钟声和弦 (推荐用于光圈式转场)"),
    "glide": (synth_glide, 0.20, "安静的三角波上滑 (推荐用于穿元素式转场)"),
    "harp": (synth_harp, 0.26, "快速拨弦走句 (推荐用于条带式转场)"),
    "click": (synth_click, 0.16, "纸卡轻点"),
    "tick": (synth_tick, 0.14, "极短高频点"),
    "paper": (synth_paper, 0.30, "纸与卡片"),
    "shaker": (synth_shaker, 0.18, "沙锤"),
    "thump": (synth_thump, 0.40, "低频落地"),
    "stamp": (synth_stamp, 0.42, "橡皮图章"),
    "ding": (synth_ding, 0.24, "单音铃"),
    "riser": (synth_riser, 0.28, "上滑提示"),
    "noise_bed": (synth_noise_bed, 0.05, "房间底噪, 电平很低, 用 dur 给长度"),
    "whoosh": (synth_whoosh, 0.22, "噪声扫过 (已弃用, 全片不超过两次)"),
}

FILE_PEAK_HINT = {"whoosh": 0.22, "pop": 0.20, "tick": 0.16, "paper": 0.34,
                  "thud": 0.40, "stamp": 0.42, "riser": 0.28}


def synth_names():
    return ", ".join(sorted(SYNTH_TABLE))


CHORD_SYNTHS = ("swell", "bloom", "glide", "harp", "ding")
LEN_SYNTHS = ("swell", "bloom", "glide", "harp", "riser")


def build_synth(name, dur=None, notes=None):
    """按名字合成一条拟音, 返回 (2, n) 浮点数组, 峰值归一化到 1"""
    if name not in SYNTH_TABLE:
        raise SfxError("不认识的拟音名 %s; 可用: %s" % (name, synth_names()))
    fn = SYNTH_TABLE[name][0]
    if name == "noise_bed":
        return fn(dur if dur else 8.0)
    if name in CHORD_SYNTHS:
        if dur is not None and name in LEN_SYNTHS:
            return fn(float(dur), notes=notes)
        return fn(notes=notes)
    return fn()


# ----------------------------------------------------------------- 混音
def add_track(dst, sig, at):
    """把 sig 叠加到 dst 的 at 秒处, 超出末尾截断, 返回 (落点是否有重叠, 是否被截断)"""
    n = dst.shape[1]
    i = int(round(at * SR))
    truncated = (i < 0) or (i + sig.shape[1] > n)
    if i >= n or i + sig.shape[1] <= 0:
        return False, truncated
    j0 = max(0, i)
    s0 = j0 - i
    m = min(sig.shape[1] - s0, n - j0)
    if m <= 0:
        return False, truncated
    dst[:, j0:j0 + m] += sig[:, s0:s0 + m]
    return True, truncated


def load_cues(path):
    if not os.path.exists(path):
        raise SfxError("找不到音效清单: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            js = json.load(f)
    except Exception as e:
        raise SfxError("音效清单 %s 读不动: %s" % (path, e))
    if isinstance(js, dict):
        js = js.get("cues")
    if not isinstance(js, list) or not js:
        raise SfxError("音效清单 %s 应当是一个非空的 cue 数组" % path)
    base = os.path.dirname(os.path.abspath(path))
    cues = []
    for k, c in enumerate(js):
        if not isinstance(c, dict):
            raise SfxError("音效清单 %s 第 %d 项不是对象" % (path, k + 1))
        t = c.get("t", c.get("time"))
        if t is None:
            raise SfxError("音效清单 %s 第 %d 项缺 t" % (path, k + 1))
        fn = c.get("file", c.get("path"))
        sy = c.get("synth")
        if fn is None and sy is None:
            raise SfxError("音效清单 %s 第 %d 项既没有 file 也没有 synth" % (path, k + 1))
        resolved = None
        if fn is not None:
            f = str(fn)
            if not os.path.isabs(f) and not os.path.exists(f):
                alt = os.path.join(base, f)
                if os.path.exists(alt):
                    f = alt
            if os.path.exists(f):
                resolved = f
        if sy is not None and str(sy) not in SYNTH_TABLE:
            raise SfxError("音效清单 %s 第 %d 项的 synth %s 不认识; 可用: %s"
                           % (path, k + 1, sy, synth_names()))
        cues.append({"t": float(t), "file": resolved,
                     "file_raw": None if fn is None else str(fn),
                     "synth": None if sy is None else str(sy),
                     "peak": c.get("peak"), "dur": c.get("dur"), "notes": c.get("notes")})
    return cues


def cue_source(c):
    if c["file"]:
        return "file"
    return "synth"


def peak_of(c):
    if c["peak"] is not None:
        return float(c["peak"])
    if c["synth"]:
        return SYNTH_TABLE[c["synth"]][1]
    stem = os.path.splitext(os.path.basename(c["file_raw"] or ""))[0].lower()
    for k, v in FILE_PEAK_HINT.items():
        if k in stem:
            return v
    return 0.30


def density_report(cues, duration):
    """按实测反馈给两条可判定的提醒: 稀疏度与噪声 whoosh 次数"""
    lines = []
    n = len(cues)
    per_min = n / (duration / 60.0) if duration > 0 else 0.0
    lines.append("音效密度: %d 个 / %.1f 秒 = 每 %.1f 秒一个"
                 % (n, duration, duration / n if n else 0.0))
    if duration > 0 and duration / max(n, 1) < DENSITY_MIN_SECONDS:
        lines.append("[偏密] 平均间隔小于 %.0f 秒: 约一半的切点应当什么都不放, "
                     "由下一场的入场声自己把切点带出来" % DENSITY_MIN_SECONDS)
    whoosh = [c for c in cues if c["synth"] == "whoosh"
              or "whoosh" in os.path.basename((c["file_raw"] or "")).lower()]
    if len(whoosh) > WHOOSH_WARN:
        lines.append("[噪声 whoosh %d 次] 实测反馈是\"一开始酷后来烦\": 改用 swell, bloom, "
                     "glide, harp, 全片不超过两次" % len(whoosh))
    elif whoosh:
        lines.append("噪声 whoosh %d 次 (上限 %d 次)" % (len(whoosh), WHOOSH_WARN))
    marks = [c["t"] for c in cues] + [duration]
    gaps = [(marks[i + 1] - marks[i], marks[i]) for i in range(len(marks) - 1)]
    gaps.sort(reverse=True)
    big = [g for g in gaps[:2] if g[0] >= SILENCE_HINT_SECONDS]
    if len(big) < 2:
        lines.append("[缺静默] 全片最大两段留白不足 %.0f 秒: 至少安排两处真实静默 "
                     "(或近似静默), 放在转折或情绪最高点之前" % SILENCE_HINT_SECONDS)
    else:
        lines.append("最长两段留白: %.1f 秒 (在 %.1f 秒处), %.1f 秒"
                     % (big[0][0], big[0][1], big[1][0]))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="音效轨混音: 自产拟音与用户素材")
    ap.add_argument("cues", nargs="?", help="cues.json 路径")
    ap.add_argument("out", nargs="?", help="输出 wav 路径")
    ap.add_argument("--duration", type=float, default=108.0, help="音效轨总时长, 秒")
    ap.add_argument("--default-peak", type=float, default=0.30, help="cue 没写 peak 且用自备素材时的缺省峰值")
    ap.add_argument("--clamp", type=float, default=0.95, help="整轨峰值上限, 超过则等比缩放")
    ap.add_argument("--list-synth", action="store_true", help="只列出可用的自产拟音名与用途")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if a.list_synth:
        for name in sorted(SYNTH_TABLE):
            fn, peak, use = SYNTH_TABLE[name]
            print("%-10s 缺省峰值 %.2f  %s" % (name, peak, use))
        return 0
    if not a.cues or not a.out:
        print("用法: python scripts/sfx.py cues.json out.wav --duration 108")
        print("只看可用拟音名: python scripts/sfx.py --list-synth")
        return 2
    if a.duration <= 0:
        print("--duration 必须是正数, 收到 %g" % a.duration)
        return 2
    if not 0 < a.clamp <= 1.0:
        print("--clamp 应当落在 (0, 1], 收到 %g" % a.clamp)
        return 2
    try:
        cues = load_cues(a.cues)
        cues.sort(key=lambda c: c["t"])
        n = int(round(a.duration * SR))
        track = np.zeros((2, n), dtype=np.float64)
        print("音效轨: %d Hz 立体声  %.3f s  %d 个 cue" % (SR, a.duration, len(cues)))
        print("")
        for k, c in enumerate(cues):
            src = cue_source(c)
            if src == "file":
                raw = load_sample(c["file"])
            else:
                if c["file_raw"]:
                    print("       (cue %d 的素材 %s 不存在, 回退自产拟音 %s)"
                          % (k + 1, c["file_raw"], c["synth"]))
                raw = build_synth(c["synth"], dur=c["dur"], notes=c["notes"])
            peak = peak_of(c)
            m = float(np.abs(raw).max())
            if m <= 0:
                raise SfxError("cue %d 的信号全是静音, 归一化没有意义" % (k + 1))
            sig = raw / m * peak
            landed, cut = add_track(track, sig, c["t"])
            flag = ""
            if not landed:
                flag = "  [整条落在轨外, 已丢弃]"
            elif cut:
                flag = "  [尾部越界, 已截断]"
            label = c["synth"] if src == "synth" else c["file"]
            print("cue %2d  t=%8.3f s  peak %.2f  %-9s %.3f s  %s%s"
                  % (k + 1, c["t"], peak, src, raw.shape[1] / SR, label, flag))
    except SfxError as e:
        print("[错误] %s" % e)
        return 2

    pk = float(np.abs(track).max())
    gain = 1.0
    if pk > a.clamp:
        gain = a.clamp / pk
        track *= gain
    shape = write_wav(a.out, track)
    print("")
    print("叠加后峰值 %.4f, %s" % (pk, "未超过 --clamp, 原样写出" if gain == 1.0
                                  else "超过 --clamp %.2f, 整轨等比缩放 %.4f 倍" % (a.clamp, gain)))
    print("已写出 %s  %d 帧 x %d 声道  = %.3f s  峰值 %.4f"
          % (a.out, shape[0], shape[1], shape[0] / SR, float(np.abs(track).max())))
    print("")
    print("稀疏度与静默自查:")
    for line in density_report(cues, a.duration):
        print("  " + line)
    print("")
    print("别忘了: 混入配乐后重跑响度验收 (集成响度 -16 到 -14 LUFS, 真峰值不高于 -1.0 dBFS),")
    print("换音轨不必重渲画面, 用 `-map 0:v -map 1:a -c:v copy` 直接换流即可.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

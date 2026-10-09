# -*- coding: utf-8 -*-
"""
音频包络导出与取用: 把配乐的实际能量曲线落成按帧索引的文件, 供画面按帧取用

  python scripts/audio_env.py audio/score.wav --fps 30 --out temp/score_env.npz
  python scripts/audio_env.py audio/score.wav --fps 30 --bpm 100 --bars 45 --anchors 6 --md temp/qa/audio_bars.md

两个用途:

1 **画面跟着音频起伏**: 落出来的 npz 里是按帧的 RMS 包络与四段频段能量, 场景模块可以
   `import audio_env` 后 `env = audio_env.Env.load("temp/score_env.npz")`, 再用 `env.at(f)` 取当前帧的
   包络值当振幅或亮度系数. 没有这条通道时, 画面与音乐之间只有"切点"一个接口, 元素只能跟拍号走,
   跟不了音乐实际的强弱.

2 **锚点小节从实测曲线里挑, 而不是自己造**: `--anchors N` 按逐小节 RMS 的相邻变化量排序, 打印最适合
   钉关键句的小节号. 本技能按切点分段配器并加力度弧线, 于是"能量变化必然落在切点上"; 先测出曲线再挑
   小节, 这条判据才是独立证据, 否则它只是被构造性满足.

npz 里的键:
  fps 帧率 | frames 帧数 | duration 秒 | rms 逐帧 RMS (线性) | env 逐帧平滑包络 (归一化 0 到 1)
  peak 逐帧峰值 | bands 四行 [低频低, 中频, 高频, 空气] 的逐帧能量占比
  bpm, bar_frames, bar_rms (给了 --bpm 才有)

fps 必须与画面帧率一致: 包络是按帧索引的, 帧率变了索引就对不上, 取用时 `Env.load` 会直接报错而不是
悄悄错位. 重渲画面而配乐没变时不必重跑本脚本, 改帧率则必须重跑.
只依赖标准库加 numpy, 不联网; 输入不是 48k 时用 ffmpeg 转一次临时 WAV.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

import dsp

SR = dsp.SR
BAND_EDGES = ((0.0, 250.0), (250.0, 2000.0), (2000.0, 6000.0), (6000.0, 20000.0))
BAND_NAMES = ("low", "mid", "high", "air")


class AudioEnvError(Exception):
    """可预期的输入问题, 只打印一句说明, 不抛栈"""


# ----------------------------------------------------------------- 读音频
def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True)
    err = p.stderr
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return p.returncode, (err or "").strip()


def read_mono(path):
    """读成单声道浮点数组; 不是 48k pcm_s16le 时用 ffmpeg 转临时文件"""
    def _raw(p):
        with wave.open(p, "rb") as w:
            if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
                return None
            ch = w.getnchannels()
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
        if not raw:
            return None
        a = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        if sr != SR:
            # 采样率不一致时用最近邻重采样, 只影响包络精度, 不影响判据
            t = np.arange(int(len(a) * SR / sr)) / SR
            a = np.interp(t, np.arange(len(a)) / sr, a)
        return a

    try:
        a = _raw(path)
    except Exception:
        a = None
    if a is not None and len(a):
        return a
    ff = shutil.which("ffmpeg")
    if not ff:
        raise AudioEnvError("输入 %s 不是 48k pcm_s16le, 而 PATH 里找不到 ffmpeg" % path)
    os.makedirs(os.path.join("temp", "audio_env"), exist_ok=True)
    tmp = os.path.join("temp", "audio_env", "in.wav")
    code, err = run_cmd([ff, "-y", "-v", "error", "-i", path, "-ar", str(SR), "-ac", "1",
                         "-c:a", "pcm_s16le", tmp])
    if code != 0:
        raise AudioEnvError("输入 %s 转码失败: %s" % (path, err or "ffmpeg 返回非零"))
    a = _raw(tmp)
    if a is None or not len(a):
        raise AudioEnvError("输入 %s 转码后仍读不出音频" % path)
    return a


# ----------------------------------------------------------------- 包络计算
def frame_rms(x, fps, frames):
    """逐帧 RMS, 长度固定为 frames, 末尾不足一帧的样本并入最后一帧"""
    hop = max(1, int(round(SR / float(fps))))
    out = np.zeros(frames)
    for i in range(frames):
        a = i * hop
        b = min(len(x), a + hop)
        if a >= len(x):
            break
        seg = x[a:b]
        out[i] = math.sqrt(float(np.mean(seg * seg))) if len(seg) else 0.0
    return out


def frame_peak(x, fps, frames):
    hop = max(1, int(round(SR / float(fps))))
    out = np.zeros(frames)
    for i in range(frames):
        a = i * hop
        b = min(len(x), a + hop)
        if a >= len(x):
            break
        out[i] = float(np.max(np.abs(x[a:b]))) if b > a else 0.0
    return out


def frame_bands(x, fps, frames):
    """逐帧四段频段能量占比, 用于看出低频堆积或高频刺耳"""
    hop = max(1, int(round(SR / float(fps))))
    out = np.zeros((len(BAND_NAMES), frames))
    freqs = np.fft.rfftfreq(hop, 1 / SR)
    masks = [(freqs >= lo) & (freqs < hi) for lo, hi in BAND_EDGES]
    for i in range(frames):
        a = i * hop
        b = min(len(x), a + hop)
        if b - a < 32 or a >= len(x):
            continue
        seg = x[a:b] * np.hanning(b - a)
        p = np.abs(np.fft.rfft(seg, n=hop)) ** 2
        total = float(p.sum()) or 1.0
        for k, m in enumerate(masks):
            out[k, i] = float(p[m].sum()) / total
    return out


def smooth_env(rms, fps, attack=0.08, release=0.35):
    """一极平滑的包络, 快起慢落, 画面取用时不会一帧一个台阶"""
    a = math.exp(-1.0 / max(attack * fps, 1e-6))
    r = math.exp(-1.0 / max(release * fps, 1e-6))
    out = np.zeros_like(rms)
    prev = 0.0
    for i, v in enumerate(rms):
        k = a if v > prev else r
        prev = v + (prev - v) * k
        out[i] = prev
    m = float(out.max())
    return out / m if m > 0 else out


def bar_table(rms, fps, bpm, meter=4):
    """逐小节 RMS: 小节长由 BPM 与每小节拍数算出, 返回 (小节数, 数组)"""
    bar_sec = 60.0 / float(bpm) * meter
    bar_frames = max(1, int(round(bar_sec * fps)))
    n = int(math.ceil(len(rms) / bar_frames))
    out = np.zeros(n)
    for b in range(n):
        seg = rms[b * bar_frames:(b + 1) * bar_frames]
        out[b] = math.sqrt(float(np.mean(seg * seg))) if len(seg) else 0.0
    return bar_frames, out


def anchor_candidates(bar_rms, count):
    """按相邻小节 RMS 变化量排序, 给出最适合钉关键句的小节 (1 基)"""
    if len(bar_rms) < 2:
        return []
    delta = np.abs(np.diff(bar_rms))
    order = np.argsort(-delta)[:max(0, count)]
    return [(int(i) + 2, float(delta[i])) for i in order]


# ----------------------------------------------------------------- 取用侧
class Env:
    """场景模块用的只读包络: env.at(frame) 取 0 到 1 的包络值"""

    def __init__(self, data):
        self.fps = float(data["fps"])
        self.frames = int(data["frames"])
        self.duration = float(data["duration"])
        self.rms = data["rms"]
        self.env = data["env"]
        self.peak = data["peak"]
        self.bands = data["bands"]
        self.bpm = float(data["bpm"]) if "bpm" in data else None
        self.bar_frames = int(data["bar_frames"]) if "bar_frames" in data else None
        self.bar_rms = data["bar_rms"] if "bar_rms" in data else None

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            raise AudioEnvError("找不到包络文件 %s, 先跑 scripts/audio_env.py 生成它" % path)
        with np.load(path) as z:
            data = {k: z[k] for k in z.files}
        return cls(data)

    def _idx(self, frame):
        return max(0, min(self.frames - 1, int(frame)))

    def at(self, frame):
        """当前帧的归一化包络 0 到 1"""
        return float(self.env[self._idx(frame)])

    def rms_at(self, frame):
        return float(self.rms[self._idx(frame)])

    def peak_at(self, frame):
        return float(self.peak[self._idx(frame)])

    def band_at(self, frame, name):
        if name not in BAND_NAMES:
            raise AudioEnvError("频段名只能是 %s" % ", ".join(BAND_NAMES))
        return float(self.bands[BAND_NAMES.index(name)][self._idx(frame)])

    def check_fps(self, fps):
        """帧率不一致时必须报错, 不要悄悄错位"""
        if abs(float(fps) - self.fps) > 1e-6:
            raise AudioEnvError("包络是在 %g fps 下导出的, 当前画面是 %g fps; 重跑 "
                                "scripts/audio_env.py 换帧率导出" % (self.fps, fps))

    def bar_of(self, frame):
        if not self.bar_frames:
            raise AudioEnvError("导出时没给 --bpm, 没有逐小节数据")
        return int(frame) // self.bar_frames + 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="音频包络导出: 逐帧 RMS, 频段与逐小节曲线")
    ap.add_argument("audio", help="音频路径 (score.wav 或成片音轨)")
    ap.add_argument("--fps", type=float, default=30.0, help="画面帧率, 包络按帧索引, 必须与画面一致")
    ap.add_argument("--duration", type=float, default=None, help="总时长秒, 缺省按音频长度")
    ap.add_argument("--out", default=None, help="npz 输出路径, 缺省 temp/score_env.npz")
    ap.add_argument("--bpm", type=float, default=None, help="给了就同时算逐小节 RMS 与锚点候选")
    ap.add_argument("--meter", type=int, default=4, help="每小节拍数")
    ap.add_argument("--anchors", type=int, default=0, help="打印 N 个最适合钉关键句的小节")
    ap.add_argument("--md", default=None, help="把逐小节 RMS 表写成 markdown 的路径")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if a.fps <= 0:
        print("--fps 必须是正数, 收到 %g" % a.fps)
        return 2
    try:
        x = read_mono(a.audio)
    except AudioEnvError as e:
        print("[错误] %s" % e)
        return 2
    dur = a.duration if a.duration else len(x) / SR
    if dur <= 0:
        print("音频长度为零")
        return 2
    frames = int(round(dur * a.fps))
    rms = frame_rms(x, a.fps, frames)
    peak = frame_peak(x, a.fps, frames)
    env = smooth_env(rms, a.fps)
    bands = frame_bands(x, a.fps, frames)

    data = {"fps": a.fps, "frames": frames, "duration": dur, "rms": rms,
            "env": env, "peak": peak, "bands": bands}
    if a.bpm:
        bar_frames, brms = bar_table(rms, a.fps, a.bpm, a.meter)
        data["bpm"] = float(a.bpm)
        data["bar_frames"] = bar_frames
        data["bar_rms"] = brms
    out = a.out or os.path.join("temp", "score_env.npz")
    d = os.path.dirname(os.path.abspath(out))
    if d:
        os.makedirs(d, exist_ok=True)
    np.savez(out, **data)

    print("音频包络: %s" % a.audio)
    print("  %d 帧 @ %g fps, 时长 %.3f s, 逐帧 RMS 均值 %.4f, 峰值 %.4f"
          % (frames, a.fps, dur, float(rms.mean()), float(peak.max())))
    print("  频段占比 (全片平均): 低频 %.1f%%  中频 %.1f%%  高频 %.1f%%  空气 %.1f%%"
          % tuple(float(b.mean() * 100) for b in bands))
    print("  已写出 %s" % out)
    print("  取用: import audio_env; env = audio_env.Env.load(%r); env.at(frame)" % out)

    if a.bpm:
        bar_frames, brms = data["bar_frames"], data["bar_rms"]
        print("")
        print("逐小节 RMS (%d 小节, 每小节 %d 帧 = %.3f s):"
              % (len(brms), bar_frames, bar_frames / a.fps))
        if a.md:
            dm = os.path.dirname(os.path.abspath(a.md))
            if dm:
                os.makedirs(dm, exist_ok=True)
            with open(a.md, "w", encoding="utf-8", newline="\n") as f:
                f.write("| 小节 | RMS | 与上一小节变化 |\n|:---:|:---:|:---:|\n")
                prev = None
                for i, v in enumerate(brms, 1):
                    d_prev = "" if prev is None else "%+.4f" % (v - prev)
                    f.write("| %d | %.4f | %s |\n" % (i, v, d_prev))
                    prev = v
            print("  逐小节表已写出 %s" % a.md)
        step = max(1, len(brms) // 12)
        for i in range(0, len(brms), step):
            print("  小节 %3d  RMS %.4f" % (i + 1, brms[i]))
        if a.anchors:
            print("")
            print("建议钉关键句的小节 (按实测相邻变化量排序, 小节号 1 基):")
            for bar, dv in anchor_candidates(brms, a.anchors):
                print("  小节 %3d  变化量 %.4f" % (bar, dv))
            print("  用法: 把这些小节号交给 timing.py 的 --anchor 屏号:小节号, 钉的是原曲小节号")
    return 0


if __name__ == "__main__":
    sys.exit(main())

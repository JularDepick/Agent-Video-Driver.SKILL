# -*- coding: utf-8 -*-
"""
音效轨混音: 把用户自备的音效按时间点叠成一条 48kHz 立体声 WAV

  python scripts/sfx.py cues.json audio/sfx.wav --duration 108 --default-peak 0.30

cues.json
  [
    {"t": 8.507, "file": "assets/whoosh.wav", "peak": 0.22},
    {"t": 16.8, "file": "assets/thud.wav", "peak": 0.40}
  ]

每条样本先归一化到峰值 1, 再乘这条 cue 的 peak. 归一化这一步是控制不同录音之间响度
差异的关键: 用户自备的音效来源杂乱, 有的一声录得贴顶, 有的只剩 -12dB, 不归一化就只能
逐个试听再改 peak, 归一化之后 peak 才是可以直接照抄的相对响度.

峰值参考表 (归一化之后使用):
  whoosh 0.22  pop 0.20  tick 0.16  paper 0.34  thud 0.40  stamp 0.42  大冲击 0.50  riser 0.28

两条纪律
  a 音效要稀疏: 每次转场一个 whoosh, 揭晓与反转各一个关键击, 每屏不超过 1 到 2 个.
    铺满音效会盖住配乐的节拍, 卡点反而糊掉
  b 混入配乐后必须重跑响度验收: 混音后的集成响度仍要在 -16 到 -14 LUFS, 真峰值不高于
    -1.0 dBFS, 命令见 references/verification.md 的 ebur128 那一条.
    换音轨不需要重渲画面, 用 `-map 0:v -map 1:a -c:v copy` 直接换流即可

素材由用户提供, 本脚本只读本地文件, 绝不联网. 采样率固定 48000, 立体声, 与 dsp.py 的 SR 一致.
只依赖标准库 + numpy, 样本不是 48k 立体声 pcm_s16le 时用 ffmpeg 转一次临时 WAV.
"""
import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

SR = 48000
TMPDIR = os.path.join("temp", "sfx_tmp")
_SEQ = itertools.count(1)


class SfxError(Exception):
    """可预期的输入问题, 只打印一句说明, 不抛栈"""


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True)
    err = p.stderr
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return p.returncode, (err or "").strip()


# ----------------------------------------------------------------- 读样本
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
    a = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float64).T / 32768.0
    return a


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
    tmp = os.path.join(TMPDIR, "t%05d.wav" % next(_SEQ))
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
        fn = c.get("file", c.get("path"))
        if t is None or fn is None:
            raise SfxError("音效清单 %s 第 %d 项缺 t 或 file" % (path, k + 1))
        f = str(fn)
        if not os.path.isabs(f) and not os.path.exists(f):
            alt = os.path.join(base, f)
            if os.path.exists(alt):
                f = alt
        cues.append({"t": float(t), "file": f, "peak": c.get("peak")})
    missing = [c["file"] for c in cues if not os.path.exists(c["file"])]
    if missing:
        raise SfxError("缺 %d 个样本文件: %s" % (len(missing), "; ".join(missing)))
    return cues


def main(argv=None):
    ap = argparse.ArgumentParser(description="音效轨混音")
    ap.add_argument("cues", help="cues.json 路径")
    ap.add_argument("out", help="输出 wav 路径")
    ap.add_argument("--duration", type=float, default=108.0, help="音效轨总时长, 秒")
    ap.add_argument("--default-peak", type=float, default=0.30, help="cue 没写 peak 时的缺省峰值")
    ap.add_argument("--clamp", type=float, default=0.95, help="整轨峰值上限, 超过则等比缩放")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

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
            raw = load_sample(c["file"])
            peak = a.default_peak if c["peak"] is None else float(c["peak"])
            m = float(np.abs(raw).max())
            if m <= 0:
                raise SfxError("样本 %s 全是静音, 归一化没有意义" % c["file"])
            sig = raw / m * peak
            landed, cut = add_track(track, sig, c["t"])
            flag = ""
            if not landed:
                flag = "  [整条落在轨外, 已丢弃]"
            elif cut:
                flag = "  [尾部越界, 已截断]"
            print("cue %2d  t=%8.3f s  peak %.2f  样本 %.3f s  归一化增益 %.2f  %s%s"
                  % (k + 1, c["t"], peak, raw.shape[1] / SR, peak / m, c["file"], flag))
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
    print("别忘了: 混入配乐后重跑响度验收 (集成响度 -16 到 -14 LUFS, 真峰值不高于 -1.0 dBFS),")
    print("换音轨不必重渲画面, 用 `-map 0:v -map 1:a -c:v copy` 直接换流即可.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

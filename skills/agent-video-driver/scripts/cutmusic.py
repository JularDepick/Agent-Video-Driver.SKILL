# -*- coding: utf-8 -*-
"""
按小节剪辑用户自备的音乐: 把选中的小节区间拼成一条新音轨

画面段落数常常与用户给的音乐对不上, 直接硬切会在接缝处听到跳变. 先用
scripts/loops.py 找出接得上的小节, 再用本脚本按小节号剪接.

  python scripts/cutmusic.py music.mp3 temp/beats.json --bars 5-21 14-30 75-end -o audio/music-edit.wav
  python scripts/cutmusic.py music.mp3 temp/beats.json --bars 1-8 1-8 1-8 --xfade 0.02 -o audio/loop.wav

接缝做法 (这是本脚本与"直接拼接"的唯一区别):

  输出总长等于各段长度之和, 小节线因此落在精确的累加位置上, 拍网格不被破坏;
  每个接缝处取源音乐里紧接在下一段之前的那一小段素材, 用等功率交叉淡化混进
  上一段的末尾. 于是接缝两侧在源文件里本来就是相邻的, 听不出剪过, 而下一段的
  第一个采样仍然落在原来的小节线上.

小节号约定: 命令行给的 --bars 一律 1 基且两端都含, 与 loops.py 的文本摘要一致;
写进日志与 json 的一律 0 基.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TMP_NAME = "cutmusic_tmp_%d.wav" % os.getpid()


def read_audio(path):
    """返回 (采样率, 二维 float64 数组 (帧, 声道)); 非 WAV 先经 ffmpeg 转成 WAV"""
    ext = os.path.splitext(path)[1].lower()
    tmp = None
    if ext != ".wav":
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found, 请确认它在 PATH 中")
        os.makedirs("temp", exist_ok=True)
        tmp = os.path.join("temp", TMP_NAME)
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path,
                            "-c:a", "pcm_s16le", tmp],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError("ffmpeg 解码失败: %s" % (p.stderr or "").strip()[:200])
        src = tmp
    else:
        src = path
    try:
        with wave.open(src, "rb") as w:
            nch = w.getnchannels()
            sw = w.getsampwidth()
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    if sw == 1:
        a = (np.frombuffer(raw, "<u1").astype(np.float64) - 128.0) / 128.0
    elif sw == 2:
        a = np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, "<u1").reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= (1 << 23), v - (1 << 24), v)
        a = v.astype(np.float64) / float(1 << 23)
    elif sw == 4:
        a = np.frombuffer(raw, "<i4").astype(np.float64) / 2147483648.0
    else:
        raise RuntimeError("不支持的采样位宽 %d 字节" % sw)
    if nch > 1:
        a = a[:len(a) - len(a) % nch].reshape(-1, nch)
    else:
        a = a.reshape(-1, 1)
    return float(sr), a


def write_audio(path, sr, a):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(round(sr)))
        w.writeframes(pcm.tobytes())


def parse_bars(specs, nb):
    """
    解析 --bars 的每一项, 返回 0 基的闭区间列表 [(start, end), ...]

    支持三种写法: a-b (两端都含), a-end (到最后一小节), a (只取一小节)
    """
    out = []
    for sp in specs:
        s = sp.strip().lower()
        if s.endswith("-end"):
            head = s[:-4].rstrip("-")
            if not head.isdigit():
                raise ValueError("写法不对: %s, 应当是 a-end" % sp)
            i, j = int(head), nb
        elif "-" in s:
            head, _, tail = s.partition("-")
            if not head.isdigit() or not tail.isdigit():
                raise ValueError("写法不对: %s, 应当是 a-b" % sp)
            i, j = int(head), int(tail)
        else:
            if not s.isdigit():
                raise ValueError("写法不对: %s, 应当是 a / a-b / a-end" % sp)
            i = j = int(s)
        if i < 1 or j < i or j > nb:
            raise ValueError("小节范围越界: %s, 可用范围是 1 到 %d" % (sp, nb))
        out.append((i - 1, j - 1))
    return out


def crossfade_tail(out, pre, k):
    """
    等功率交叉淡化: 把 pre 混进 out 的末尾 k 个采样

    pre 是源音乐里紧接在下一段之前的那一小段, 所以接缝两侧在源文件里本来就相邻;
    混完之后的最后一个采样与下一段的第一个采样在原文件里是连续的, 不会有 click.
    """
    if k <= 0 or len(out) < k:
        return out
    if len(pre) < k:
        pre = np.concatenate([np.zeros((k - len(pre), out.shape[1])), pre], axis=0)
    pre = pre[-k:]
    w = np.linspace(0.0, 1.0, k, endpoint=False)[:, None]
    out[-k:] = out[-k:] * np.cos(w * np.pi / 2) + pre * np.sin(w * np.pi / 2)
    return out


def main():
    ap = argparse.ArgumentParser(description="按小节剪辑音乐, 接缝落在精确的小节线上")
    ap.add_argument("audio", help="源音频路径")
    ap.add_argument("beats_json", help="beats.py --json 产出的拍表文件")
    ap.add_argument("--bars", nargs="+", required=True, metavar="RANGE",
                    help="要保留的小节区间, 1 基两端都含, 可写 a-b / a-end / a, 按给定顺序拼接")
    ap.add_argument("-o", "--out", required=True, help="输出 WAV 路径")
    ap.add_argument("--xfade", type=float, default=0.02,
                    help="接缝交叉淡化秒数, 缺省 0.02; 给 0 则直接对接, 可能有 click")
    ap.add_argument("--json", dest="json_path", default=None, help="把剪辑清单写成 JSON 的路径")
    a = ap.parse_args()

    for p in (a.audio, a.beats_json):
        if not os.path.exists(p):
            print("找不到文件: %s" % p)
            return 2
    if a.xfade < 0:
        print("--xfade 不能为负")
        return 2

    try:
        with open(a.beats_json, encoding="utf-8") as f:
            d = json.load(f)
        starts = [float(b["start"]) for b in (d.get("bars") or [])]
        if len(starts) < 2:
            raise RuntimeError("beats.json 里的 bar 少于 2 个")
        dur = float(d.get("duration") or starts[-1])
        sr, src = read_audio(a.audio)
    except Exception as e:
        print("读输入失败: %s" % e)
        return 2

    nb = len(starts)
    try:
        ranges = parse_bars(a.bars, nb)
    except ValueError as e:
        print(str(e))
        return 2

    k = int(round(a.xfade * sr))
    print("源音乐 %.3f s / %d Hz / %d 声道   小节 %d 个   小节长 %.3f s"
          % (len(src) / sr, sr, src.shape[1], nb,
             d.get("beat_seconds", 0.0) * d.get("meter", 4)))
    print("将拼接 %d 段, 接缝交叉淡化 %.0f ms:" % (len(ranges), a.xfade * 1000))

    pieces = []
    total = 0
    for n, (i, j) in enumerate(ranges):
        t0 = starts[i]
        t1 = starts[j + 1] if j + 1 < nb else dur
        s0 = int(round(t0 * sr))
        s1 = min(len(src), int(round(t1 * sr)))
        seg = src[s0:s1].copy()
        pieces.append(seg)
        total += len(seg)
        print("  段 %02d  第 %d 到 %d 小节  %.3f 到 %.3f 秒  输出位置 %.3f 秒  共 %d 采样"
              % (n, i + 1, j + 1, t0, t1, (total - len(seg)) / sr, len(seg)))

    out = pieces[0]
    for n in range(1, len(pieces)):
        t0 = starts[ranges[n][0]]
        s0 = int(round(t0 * sr))
        pre = src[max(0, s0 - k):s0] if k > 0 else src[0:0]
        out = crossfade_tail(out, pre, k)
        out = np.concatenate([out, pieces[n]], axis=0)

    write_audio(a.out, sr, out)
    print("wrote %s  %.3f s  %d 采样  峰值 %.3f"
          % (a.out, len(out) / sr, len(out), float(np.max(np.abs(out)))))
    print("提醒: 小节线落在累加位置上, 拍网格未被破坏; 剪完请对输出再跑一次 beats.py 复测拍表")
    if k == 0:
        print("提醒: --xfade 为 0, 接缝是直接对接, 若听到 click 请给 0.01 到 0.03")

    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as fp:
            json.dump({"source": a.audio, "out": a.out, "xfade": a.xfade,
                       "ranges": [{"start_bar": i, "end_bar": j} for i, j in ranges],
                       "duration": round(len(out) / sr, 4),
                       "sample_rate": sr}, fp, ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
拍表分析: 从音频反推 BPM, 拍点, 首拍相位, 小节线, 逐小节响度

两个用途:
  1 用户自带一首配乐时, 用它把音频变成一张可卡点的拍表, 供画面按拍驱动
  2 对本技能自产的 score.wav 做双向验证: 独立测出的 BPM 与首拍相位应当与配乐脚本里的
    常量一致. 这是比自相关更强的证据, 因为走的是另一条独立链路来复算同一张拍表

  python scripts/beats.py audio/score.wav
  python scripts/beats.py music.mp3 --json temp/beats.json
  python scripts/beats.py audio/score.wav --bpm 100 --min-bpm 80 --max-bpm 140 --meter 4

判据 (与本技能自产配乐对照):
  测出 BPM 与配乐脚本常量的误差应在 1 BPM 内, 首拍相位误差应在 40ms 内
  超出说明配乐脚本的拍点没落在设计位置, 先查配乐再查画面

小节号基数约定:
  人看的文本摘要一律 1 基 (第 N 小节从 1 开始, 不会出现第 0 小节)
  机器读的 json 一律 0 基 (bars[].bar 与 changes[].bar 从 0 开始, 方便直接做下标)

算法:
  分帧 SR 22050, NFFT 2048, HOP 128, Hann 窗, 时间戳取窗口末端 (i*HOP+NFFT)/SR
  三路特征: 对数谱正向通量, 150Hz 以下低频能量, 逐帧 RMS
  起始包络: 正向通量减 1 秒滑动均值, 半波整流, 除以标准差
  拍速: 对起始包络做自相关, 只在 min-bpm 到 max-bpm 内搜索
        用中心 120 BPM, sigma 0.9 倍频程的高斯权重压半速与倍速, 再抛物线插值取小数 lag
  网格: 先在周期上以 2ms 步长搜相位, 再在每条网格线正负 60ms 内找真实起音峰
        对 (拍序号, 实测时间) 做最小二乘直线拟合, 用斜率与截距修正 BPM 与首拍相位
  下拍: meter 个相位里拍点处低频能量均值最大者, 小节线 = beats[off::meter]
  响度: 逐小节 RMS 转 dB, 与前两小节均值差 3dB 以上标 louder 或 thinner
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

SR = 22050
NFFT = 2048
HOP = 128
LOW_HZ = 150.0
MEAN_SEC = 1.0
PHASE_STEP = 0.002
SEARCH_SEC = 0.060
ONSET_MIN = 1.0
FIT_MIN_POINTS = 8
CTR_BPM = 120.0
OCT_SIGMA = 0.9
CHANGE_DB = 3.0
BLOCK = 2048

TMP_NAME = "beats_tmp_%d.wav" % os.getpid()


def read_wav(path):
    """标准库读 WAV, 多声道取均值, 返回 (采样率, 单声道 float64)"""
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
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
        a = a[:len(a) - len(a) % nch].reshape(-1, nch).mean(axis=1)
    return float(sr), a


def to_wav(path):
    """非 WAV 一律经 ffmpeg 转到 temp 下的临时单声道 22050Hz WAV, 读完即删"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found, 请确认它在 PATH 中")
    os.makedirs("temp", exist_ok=True)
    tmp = os.path.join("temp", TMP_NAME)
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1",
                            "-ar", str(SR), "-c:a", "pcm_s16le", tmp],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError("ffmpeg 解码失败: %s" % (p.stderr or "").strip()[:200])
        return read_wav(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def decode(path):
    """返回 (采样率, 单声道 float64). WAV 直接读原采样率, 其他格式统一转 22050"""
    if os.path.splitext(path)[1].lower() == ".wav":
        try:
            return read_wav(path)
        except Exception as e:
            print("WAV 直读失败 (%s), 改用 ffmpeg 解码" % e)
    return to_wav(path)


def frame_count(mono):
    """按 NFFT 与 HOP 能切出多少帧"""
    return 1 + (len(mono) - NFFT) // HOP


def windowed(mono, a, b):
    """取第 a 到第 b 帧的加窗数据, 形状 (b-a, NFFT); features 与 log_spectra 共用它"""
    ii = np.arange(a, b)[:, None] * HOP + np.arange(NFFT)[None, :]
    return mono[ii] * np.hanning(NFFT)


def log_spectra(mono, sr):
    """
    逐帧对数谱, 形状 (帧数, NFFT/2+1), 与 features 用同一套分帧与窗

    给接缝检测用: scripts/loops.py 拿它比较各小节的频谱相似度.
    """
    n = frame_count(mono)
    if n < 8:
        raise RuntimeError("音频太短, 至少需要 %.2f 秒" % (NFFT / sr))
    out = np.empty((n, NFFT // 2 + 1), np.float32)
    for a in range(0, n, BLOCK):
        b = min(n, a + BLOCK)
        out[a:b] = np.log1p(10.0 * np.abs(np.fft.rfft(windowed(mono, a, b), axis=1)))
    return out


def features(mono, sr):
    """返回 (时间戳, 对数谱正向通量, 低频能量, 逐帧 RMS), 时间戳取窗口末端"""
    n = frame_count(mono)
    if n < 8:
        raise RuntimeError("音频太短, 至少需要 %.2f 秒" % (NFFT / sr))
    times = (np.arange(n) * HOP + NFFT) / sr
    freqs = np.fft.rfftfreq(NFFT, 1.0 / sr)
    low_mask = freqs < LOW_HZ
    flux = np.zeros(n)
    low = np.zeros(n)
    rms = np.zeros(n)
    prev = None
    for a in range(0, n, BLOCK):
        b = min(n, a + BLOCK)
        frames = windowed(mono, a, b)
        S = np.abs(np.fft.rfft(frames, axis=1))
        L = np.log1p(10.0 * S)
        d = np.empty_like(L)
        d[0] = L[0] - prev if prev is not None else 0.0
        if b - a > 1:
            d[1:] = np.diff(L, axis=0)
        prev = L[-1]
        d[d < 0] = 0.0
        flux[a:b] = d.sum(axis=1)
        low[a:b] = (S[:, low_mask] ** 2).sum(axis=1)
        rms[a:b] = np.sqrt((frames ** 2).mean(axis=1))
    return times, flux, low, rms


def onset_env(flux, sr):
    """正向通量减 1 秒滑动均值, 半波整流, 除以标准差"""
    w = max(3, int(round(MEAN_SEC * sr / HOP)) // 2 * 2 + 1)
    base = np.convolve(flux, np.ones(w) / w, mode="same")
    e = flux - base
    e[e < 0] = 0.0
    sd = float(e.std())
    return e / (sd if sd > 1e-9 else 1.0)


def detect_bpm(env, fps, min_bpm, max_bpm):
    """自相关搜拍, 高斯权重压半速与倍速, 抛物线插值取小数 lag"""
    x = env - env.mean()
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac = ac / max(float(ac[0]), 1e-12)
    lo = max(2, int(math.ceil(60.0 * fps / max_bpm)))
    hi = min(len(ac) - 2, int(math.floor(60.0 * fps / min_bpm)))
    if hi <= lo:
        raise RuntimeError("拍速搜索范围太窄, 请放宽 --min-bpm 与 --max-bpm")
    lags = np.arange(lo, hi + 1)
    bpms = 60.0 * fps / lags
    weight = np.exp(-0.5 * (np.log2(bpms / CTR_BPM) / OCT_SIGMA) ** 2)
    score = ac[lags] * weight
    lag = int(lags[int(np.argmax(score))])
    y0, y1, y2 = float(ac[lag - 1]), float(ac[lag]), float(ac[lag + 1])
    den = y0 - 2.0 * y1 + y2
    delta = 0.0 if abs(den) < 1e-12 else float(np.clip(0.5 * (y0 - y2) / den, -1.0, 1.0))
    fine = float(np.clip(lag + delta, lo, hi))
    return 60.0 * fps / fine, y1


def frame_of(t, fps):
    """时间到帧号的换算, 与 times = (i*HOP+NFFT)/sr 严格互逆"""
    return t * fps - NFFT / HOP


def search_phase(env, times, fps, period):
    """在周期上以 2ms 步长搜相位, 取网格处起始包络均值最大者"""
    dur = float(times[-1])
    step = max(1, int(round(period / PHASE_STEP)))
    phases = np.arange(step) * (period / step)
    nk = int(math.floor((dur - 1e-9) / period)) + 1
    grid = phases[:, None] + np.arange(nk)[None, :] * period
    tt = grid.ravel()
    vals = np.interp(tt, times, env, left=0.0, right=0.0)
    vals = vals.reshape(grid.shape)
    ok = (grid >= times[0]) & (grid <= times[-1])
    score = np.where(ok, vals, 0.0).sum(axis=1) / np.maximum(ok.sum(axis=1), 1)
    best = int(np.argmax(score))
    return float(phases[best])


def fit_grid(env, times, fps, first, period):
    """每条网格线正负 60ms 内找真实起音峰, 返回 (有效点, 拟合结果或 None)"""
    dur = float(times[-1])
    span = int(round(SEARCH_SEC * fps))
    pts = []
    k = 0
    while True:
        t = first + k * period
        if t > dur:
            break
        c = int(round(frame_of(t, fps)))
        i0, i1 = max(0, c - span), min(len(env), c + span + 1)
        if i1 > i0:
            seg = env[i0:i1]
            j = int(np.argmax(seg))
            if float(seg[j]) > ONSET_MIN:
                pts.append((k, float(times[i0 + j])))
        k += 1
    if len(pts) < FIT_MIN_POINTS:
        return pts, None
    A = np.array([[float(p[0]), 1.0] for p in pts])
    b = np.array([p[1] for p in pts], dtype=np.float64)
    slope, intercept = np.linalg.lstsq(A, b, rcond=None)[0]
    if slope <= 1e-6:
        return pts, None
    res = A @ np.array([slope, intercept]) - b
    fit = {
        "beats_used": len(pts),
        "mean_error_ms": round(float(np.abs(res).mean()) * 1000.0, 2),
        "max_error_ms": round(float(np.abs(res).max()) * 1000.0, 2),
        "bpm": 60.0 / float(slope),
        "first_beat": float(intercept),
    }
    return pts, fit


def beat_list(first, period, dur):
    """按 k*period 一次算出拍点, 不做浮点累加. 网格原点可以微负, 拍点只取落在音频里的"""
    k0 = 0 if first >= 0.0 else int(math.ceil(-first / period))
    n = int(math.floor((dur - first) / period + 1e-9)) + 1
    ks = np.arange(k0, max(n, k0), dtype=np.int64)
    return [first + int(k) * period for k in ks], ks


def find_downbeat(low, times, beats, ks, meter):
    """meter 个相位里拍点处低频能量均值最大者即下拍. 相位按拍序号 k 取模, 与列表起点无关"""
    best_off, best_val = 0, -1e18
    for off in range(meter):
        vals = []
        for t in np.asarray(beats)[ks % meter == off]:
            m = (times >= t - 0.05) & (times <= t + 0.05)
            if m.any():
                vals.append(float(low[m].mean()))
        v = float(np.mean(vals)) if vals else 0.0
        if v > best_val:
            best_off, best_val = off, v
    return best_off


def bar_levels(rms, times, bars, dur):
    """逐小节 RMS 均值转 dB"""
    out = []
    for i, t0 in enumerate(bars):
        t1 = bars[i + 1] if i + 1 < len(bars) else dur + 1e-6
        m = (times >= t0) & (times < t1)
        v = float(rms[m].mean()) if m.any() else 0.0
        out.append(20.0 * math.log10(max(v, 1e-6)))
    return out


def bar_changes(dbs):
    """与前两小节均值比较, 差 3dB 以上记一次变化"""
    out = []
    for i in range(1, len(dbs)):
        prev = float(np.mean(dbs[max(0, i - 2):i]))
        d = dbs[i] - prev
        if d >= CHANGE_DB:
            tag = "louder"
        elif d <= -CHANGE_DB:
            tag = "thinner"
        else:
            continue
        out.append({"bar": i, "prev_db": round(prev, 2), "db": round(dbs[i], 2),
                    "delta_db": round(d, 2), "tag": tag})
    return out


def report(res):
    """人能读的文本摘要"""
    print("=" * 62)
    print("拍表分析 %s" % res["file"])
    print("=" * 62)
    print("时长 %.3f s   采样率 %d Hz   单声道 RMS %.4f" % (res["duration"], res["sr"], res["rms"]))
    if res["bpm_source"] == "given":
        print("BPM %.2f (由 --bpm 指定, 跳过检测)   拍长 %.1f ms" % (res["bpm"], res["beat_seconds"] * 1000))
    else:
        print("BPM %.2f   拍长 %.1f ms   自相关 %.3f   搜索区间 %.0f 到 %.0f"
              % (res["bpm"], res["beat_seconds"] * 1000, res["ac_peak"], res["min_bpm"], res["max_bpm"]))
    if res["phase_only"] is not None:
        print("网格相位搜索 (仅相位) %.4f s" % res["phase_only"])
    print("首拍 %.4f s (网格原点, 可微负)   音频内第一拍 %.4f s"
          % (res["first_beat"], res["beats"][0]))
    print("下拍相位 %d/%d (拍序号模 %d 的那一拍)   首个小节线 %.4f s   小节长 %.3f s"
          % (res["first_downbeat_phase"], res["meter"], res["meter"],
             res["first_downbeat"], res["beat_seconds"] * res["meter"]))
    f = res["fit"]
    if f["beats_used"] < FIT_MIN_POINTS:
        print("起音拟合: 有效点只有 %d 个 (少于 %d 个), 跳过直线拟合, BPM 与首拍保持检测值"
              % (f["beats_used"], FIT_MIN_POINTS))
    else:
        print("起音拟合: 用 %d 点, 平均残差 %.1f ms, 最大残差 %.1f ms"
              % (f["beats_used"], f["mean_error_ms"], f["max_error_ms"]))
    print("拍点 %d 个, 小节 %d 个, 每小节 %d 拍"
          % (len(res["beats"]), len(res["bars"]), res["meter"]))
    head = res["bars"][:12]
    print("逐小节 RMS (dB, 小节号从 1 开始): "
          + "  ".join("%d:%.1f" % (b["bar"] + 1, b["db"]) for b in head)
          + ("  ..." if len(res["bars"]) > len(head) else ""))
    if res["changes"]:
        print("响度变化 (与前两小节均值比, 正负 %.0f dB 以上):" % CHANGE_DB)
        for c in res["changes"]:
            print("  第 %d 小节 %.1f dB, 前两小节 %.1f dB, %+.1f dB -> %s"
                  % (c["bar"] + 1, c["db"], c["prev_db"], c["delta_db"], c["tag"]))
    else:
        print("响度变化: 无 (没有小节超过正负 %.0f dB)" % CHANGE_DB)
    print("-" * 62)
    print("与自产配乐对照的判据: BPM 误差小于 1, 首拍相位误差小于 40ms")


def main():
    ap = argparse.ArgumentParser(description="拍表分析: 反推 BPM, 拍点, 首拍相位, 小节线, 逐小节响度")
    ap.add_argument("audio", help="音频路径, WAV 直读, 其他格式经 ffmpeg 转 22050 单声道")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="把结果写成 JSON 的路径, json 里的 bars[].bar 与 changes[].bar 都是 0 基")
    ap.add_argument("--bpm", type=float, default=None, help="已知 BPM, 给了就跳过拍速检测")
    ap.add_argument("--min-bpm", dest="min_bpm", type=float, default=70.0)
    ap.add_argument("--max-bpm", dest="max_bpm", type=float, default=180.0)
    ap.add_argument("--meter", type=int, default=4, help="每小节拍数, 决定下拍相位与小节线")
    a = ap.parse_args()

    if not os.path.exists(a.audio):
        print("找不到音频文件: %s" % a.audio)
        return 2
    if a.meter < 1:
        print("--meter 至少为 1")
        return 2
    if a.min_bpm >= a.max_bpm:
        print("--min-bpm 必须小于 --max-bpm")
        return 2

    try:
        sr, mono = decode(a.audio)
    except RuntimeError as e:
        print(str(e))
        return 2
    except Exception as e:
        print("音频读不出来: %s" % e)
        return 2
    if len(mono) < NFFT * 2:
        print("音频太短, 至少需要 %.2f 秒" % (NFFT * 2 / sr))
        return 2

    d = len(mono) / sr
    times, flux, low, rms = features(mono, sr)
    fps = sr / HOP
    env = onset_env(flux, sr)

    if a.bpm:
        bpm, ac_peak, src = float(a.bpm), 0.0, "given"
    else:
        bpm, ac_peak = detect_bpm(env, fps, a.min_bpm, a.max_bpm)
        src = "auto"
    period = 60.0 / bpm
    phase = search_phase(env, times, fps, period)
    pts, fit = fit_grid(env, times, fps, phase, period)
    if fit:
        bpm = fit["bpm"]
        first = fit["first_beat"]
        period = 60.0 / bpm
    else:
        first = phase
    beats, ks = beat_list(first, period, float(times[-1]))
    if not beats:
        print("没有推出任何拍点, 请检查音频是否有节奏")
        return 2

    off = find_downbeat(low, times, beats, ks, a.meter)
    bars = [t for t, k in zip(beats, ks) if int(k) % a.meter == off]
    dbs = bar_levels(rms, times, bars, d)
    changes = bar_changes(dbs)

    f = {"beats_used": len(pts), "mean_error_ms": None, "max_error_ms": None}
    if fit:
        f = {"beats_used": fit["beats_used"], "mean_error_ms": fit["mean_error_ms"],
             "max_error_ms": fit["max_error_ms"]}
    res = {
        "file": a.audio,
        "sr": int(sr),
        "duration": d,
        "rms": math.sqrt(float((mono ** 2).mean())),
        "bpm": round(bpm, 4),
        "beat_seconds": round(period, 6),
        "first_beat": round(first, 6),
        "meter": a.meter,
        "first_downbeat": round(bars[0], 6) if bars else round(first, 6),
        "first_downbeat_phase": off,
        "fit": f,
        "beats": [round(t, 4) for t in beats],
        "bars": [{"bar": i, "start": round(t, 4), "db": round(dbs[i], 2)} for i, t in enumerate(bars)],
        "changes": changes,
        "bpm_source": src,
        "ac_peak": round(ac_peak, 4),
        "min_bpm": a.min_bpm,
        "max_bpm": a.max_bpm,
        "phase_only": round(phase, 4),
        "points": len(pts),
    }
    report(res)

    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        out = {k: res[k] for k in ("duration", "bpm", "beat_seconds", "first_beat", "meter",
                                   "first_downbeat", "fit", "beats", "bars", "changes")}
        with open(a.json_path, "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

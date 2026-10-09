# -*- coding: utf-8 -*-
"""
编码路线对比: 同一段帧序列跑几种编码配置, 量耗时, 体积, 码率与 PSNR

  python scripts/bench_encode.py --frames temp/frames_proj --count 240
  python scripts/bench_encode.py --frames temp/frames_proj --count 240 --only "x264 medium" "nvenc p6"
  python scripts/bench_encode.py --list

先看三条已经踩过的结论, 再决定要不要换路线:
  1 preset 从 slow 降到 medium 的收益很小, 体积与 PSNR 几乎不变; 它不该被当作主要提速手段
  2 把编码线程数加上去不一定有收益, 瓶颈不在 x264 的并行度时加线程只是白占 CPU
  3 硬件编码器的收益经常被输入侧开销掩盖: PNG 解码与颗粒滤镜可能占掉总时间的一半以上,
    不先扣掉这部分, 量出来的"编码器速度"是失真的

所以本脚本除了各配置的整段耗时, 还会单独量两件事:
  仅解码:   帧序列 -> null, 只有 image2 解码的开销
  解码加滤镜: 帧序列 -> null 再加 noise 颗粒, 差值就是滤镜的开销
  编码开销约等于 "整段耗时减去解码加滤镜耗时", 换路线前先看这一栏

输出产物落在 --out-dir (缺省 temp/_bench), 属于中间产物, 可以直接删.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

# 配置表: 名称, 编码器, preset, 颗粒强度, 线程数倍数
CONFIGS = [
    ("x264 veryfast", "libx264", "veryfast", 2, 1),
    ("x264 medium", "libx264", "medium", 2, 1),
    ("x264 medium 去颗粒", "libx264", "medium", 0, 1),
    ("x264 medium 线程加倍", "libx264", "medium", 2, 2),
    ("x264 slow", "libx264", "slow", 2, 1),
    ("nvenc p6", "h264_nvenc", "p6", 2, 1),
    ("nvenc p1", "h264_nvenc", "p1", 2, 1),
    ("nvenc p6 去颗粒", "h264_nvenc", "p6", 0, 1),
]


def ffmpeg_bin(name="ffmpeg"):
    local = os.path.join(HERE, name + ".exe" if os.name == "nt" else name)
    if os.path.exists(local):
        return local
    return shutil.which(name) or name


FFMPEG = ffmpeg_bin("ffmpeg")
FFPROBE = ffmpeg_bin("ffprobe")


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def available_encoders():
    code, out = run([FFMPEG, "-hide_banner", "-encoders"])
    return set(re.findall(r"^\s*[VAS][^\s]*\s+(\S+)", out, re.M))


def suggest_threads():
    """复用 resources.py 的限额建议; 导入不到就退回 floor(核数/4) 夹到 1 到 8"""
    try:
        sys.path.insert(0, HERE)
        import resources
        return int(resources.suggest_limits(scope="encode")["threads"])
    except Exception:
        return max(1, min((os.cpu_count() or 4) // 4, 8))


def encoder_args(encoder, preset, crf, threads):
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-threads", str(threads)]
    if encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", preset, "-rc", "vbr", "-cq", str(crf),
                "-b:v", "0", "-threads", str(threads)]
    if encoder.endswith("_qsv"):
        return ["-c:v", encoder, "-preset", "medium", "-global_quality", str(crf),
                "-threads", str(threads)]
    return ["-c:v", encoder, "-crf", str(crf), "-threads", str(threads)]


def vf_args(noise):
    if noise <= 0:
        return ["-vf", "format=yuv420p"]
    return ["-vf", "noise=alls=%d:allf=t,format=yuv420p" % noise]


def timed(cmd):
    t0 = time.monotonic()
    code, out = run(cmd)
    return time.monotonic() - t0, code, out


def probe_duration(path):
    code, out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", path])
    try:
        return float((out or "0").strip())
    except ValueError:
        return 0.0


def measure_psnr(pattern, fps, video, count):
    """与 assemble.ps1 的质检同口径: 源帧与成片逐帧比对, 取最后一条 average"""
    code, out = run([FFMPEG, "-hide_banner", "-nostats",
                     "-framerate", str(fps), "-i", pattern,
                     "-i", video, "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"])
    hits = re.findall(r"average:(\d+(?:\.\d+)?|inf)", out)
    if not hits:
        return None
    return float("inf") if hits[-1] == "inf" else float(hits[-1])


def main(argv=None):
    ap = argparse.ArgumentParser(description="同一段帧序列对比几种编码配置的耗时, 体积, 码率与 PSNR")
    ap.add_argument("--frames", default=os.path.join("temp", "frames"), help="帧目录, 里面是 n%%05d.png")
    ap.add_argument("--count", type=int, default=240, help="每种配置编多少帧, 缺省 240")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=19, help="x264 的 crf, 也是硬件编码器的 cq")
    ap.add_argument("--threads", type=int, default=0, help="线程数, 0 表示取 resources.py 的建议")
    ap.add_argument("--out-dir", default=os.path.join("temp", "_bench"), help="产物目录")
    ap.add_argument("--only", nargs="*", default=None, help="只跑名称里含这些字样的配置")
    ap.add_argument("--list", action="store_true", help="只列出配置表")
    a = ap.parse_args(argv)

    if a.list:
        for name, enc, preset, noise, mult in CONFIGS:
            print("%-20s %-12s preset %-9s 颗粒 %d" % (name, enc, preset, noise))
        return 0

    frames = a.frames
    pattern = os.path.join(frames, "n%05d.png")
    if not os.path.isdir(frames):
        print("找不到帧目录: %s" % frames)
        return 2
    have = sum(1 for n in os.listdir(frames)
               if n.startswith("n") and n.endswith(".png") and n[1:-4].isdigit())
    count = min(int(a.count), have) if have else int(a.count)
    if count <= 0:
        print("帧目录里没有 n%%05d.png: %s" % frames)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)
    threads = int(a.threads) or suggest_threads()
    encs = available_encoders()
    print("帧目录 %s, 取前 %d 帧, 帧率 %d, crf/cq %d, 基准线程数 %d"
          % (frames, count, a.fps, a.crf, threads))

    # 输入侧开销: 先量解码与滤镜, 否则量到的"编码器速度"会被它们掩盖
    print("-" * 78)
    print("输入侧开销 (这部分与编码器无关, 换路线之前必须先扣掉)")
    t_decode, code, _ = timed([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                               "-framerate", str(a.fps), "-i", pattern,
                               "-frames:v", str(count), "-f", "null", "-"])
    t_filter, code2, _ = timed([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                                "-framerate", str(a.fps), "-i", pattern,
                                "-frames:v", str(count)] + vf_args(2) + ["-f", "null", "-"])
    print("  仅解码 (image2)          %7.1f 秒" % t_decode)
    print("  解码加颗粒滤镜           %7.1f 秒   (滤镜开销约 %.1f 秒)"
          % (t_filter, max(0.0, t_filter - t_decode)))

    rows = []
    for name, enc, preset, noise, mult in CONFIGS:
        if a.only and not any(k in name for k in a.only):
            continue
        if enc not in encs:
            print("跳过 %-22s 本机 ffmpeg 没有 %s" % (name, enc))
            continue
        out = os.path.join(a.out_dir, "%s.mp4" % re.sub(r"[^0-9A-Za-z]+", "_", name))
        use_threads = max(1, threads * int(mult))
        cmd = ([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-filter_threads", str(use_threads),
                "-framerate", str(a.fps), "-i", pattern, "-frames:v", str(count)]
               + vf_args(noise) + encoder_args(enc, preset, a.crf, use_threads)
               + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
        t, code, tail = timed(cmd)
        if code != 0:
            print("失败 %-22s %s" % (name, tail.strip()[-120:]))
            continue
        size_mb = os.path.getsize(out) / 1048576.0
        dur = probe_duration(out) or (count / float(a.fps))
        kbps = size_mb * 8 * 1024 / max(dur, 1e-6)
        psnr = measure_psnr(pattern, a.fps, out, count)
        rows.append((name, t, size_mb, kbps, psnr, use_threads))
        print("  %-22s %7.1f 秒  %6.2f MB  %6.0f kbps  线程 %d"
              % (name, t, size_mb, kbps, use_threads))

    print("-" * 78)
    print("%-24s %8s %9s %10s %8s" % ("配置", "耗时秒", "体积MB", "码率kbps", "PSNRdB"))
    for name, t, size_mb, kbps, psnr, _th in rows:
        print("%-24s %8.1f %9.2f %10.0f %8s"
              % (name, t, size_mb, kbps, "inf" if psnr == float("inf") else
                 ("--" if psnr is None else "%.2f" % psnr)))

    if rows:
        print("-" * 78)
        print("怎么读这张表")
        print("  1 先看 PSNR: 低于 45dB 说明这一档码率给少了, 不要拿它当基准")
        print("  2 再看 编码开销: 编码开销约等于 耗时 减去 解码加颗粒滤镜的 %.1f 秒" % t_filter)
        print("     输入侧占比过半时, 换编码器带来的差别会被它掩盖, 先解决输入侧")
        print("  3 颗粒那一行与非颗粒行的差值就是滤镜的代价; 它可能比换编码器更值得动")
        print("  4 x264 是纯 CPU 编码器, CUDA 加速不了它; 选 nvenc 是换编码器, 不是加开关")
        best = min(rows, key=lambda r: r[1])
        print("  本次最快的一档是 %s (%.1f 秒), 体积 %.2f MB, 是否采用要结合 PSNR 与体积判据"
              % (best[0], best[1], best[2]))
    print("产物目录 %s (中间产物, 可以直接删)" % a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

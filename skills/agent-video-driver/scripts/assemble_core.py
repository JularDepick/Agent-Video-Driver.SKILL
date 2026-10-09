# -*- coding: utf-8 -*-
"""
分批编码合成的后端核心: 切片编码 -> 无损拼接 -> 混音与响度 -> 真峰与 PSNR 验收

长片一次编码会把 CPU 长时间打满, 中途被打断就得整段重来; 这个脚本把视频流切成若干批,
每批独立编码成一个小 mp4, 最后用 concat 无损拼接, 中途任何时刻都能停下并按断点续跑.

  python scripts/assemble_core.py --frames temp\\frames_proj --audio audio\\score.wav \\
      --out out\\成片.mp4 --batches 8 --preset medium --yes
  python scripts/assemble_core.py --state scripts\\assemble_state.json --redo 7 --yes
  python scripts/assemble_core.py --probe-only          只探测并打印确认门, 不编码

编码完成后质检实测值 (真峰, 集成响度, PSNR) 会写进状态文件; 视频流 _video_only.mp4
只在质检时存在, 之后想单独复测 PSNR 用 scripts/psnr_check.py 对成片量.

配套的前端是 scripts/assemble_progress.py, 它只读状态文件画进度, 不启停本脚本.

三条硬约束 (都是实测踩过的坑):
  切片一律用 -start_number 让解复用器直接从该批第一帧开始读, 不要用 -vf select
    select 是解码之后才丢帧, 每一批都会把整段 PNG 全解码一遍, 实测慢一倍以上
  分批只切视频流, 音频必须整条一次处理
    集成响度只能在整条音轨上量测, 分成几段各自归一化会让响度验收失效
  concat 列表里只写 basename, 列表与分段同目录
    列表里的相对路径是按"列表文件所在目录"解析的, 不是按进程的工作目录

状态文件 (缺省是脚本同目录的 assemble_state.json) 每完成一批原子写入一次, 内容含配置快照,
批次表, 当前阶段, 已完成帧数与 pid; 重跑时自动跳过已完成批次, 配置与上次不一致时拒绝续跑,
要重来必须显式加 --restart. --redo N 用来重做指定批次, 源帧改过时必须重编对应批次,
否则视频里是旧帧, 磁盘上是新帧, PSNR 验收会假性崩掉.

退出码: 0 成功; 2 用法错误; 3 等待用户二次确认; 4 探测判定应拦截; 5 真峰不合格;
        6 编码或混音失败; 7 状态文件与本次配置不一致; 130 被中断 (断点已保留)
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_NAME = "assemble_state.json"
STATE_VERSION = 1
# 与 canvas.FRAME_PATTERN 保持一致; 不 import canvas, 单独复制走也能跑
FRAME_PATTERN = "n%05d.png"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def ffmpeg_bin(name):
    """找 ffmpeg 或 ffprobe, 优先用同目录下的副本, 找不到就直接交给 PATH"""
    local = os.path.join(HERE, name + ".exe" if os.name == "nt" else name)
    if os.path.exists(local):
        return local
    return shutil.which(name) or name


FFMPEG = ffmpeg_bin("ffmpeg")
FFPROBE = ffmpeg_bin("ffprobe")


def run(cmd, cwd=None):
    """跑一条命令, 返回 (退出码, 合并后的输出); ffmpeg 的量测结果都写在 stderr, 所以合并读"""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def count_frames(frames):
    """数帧目录里 n%05d.png 的个数; 帧数与编码参数不一致时整条片会缺尾或重复"""
    if not os.path.isdir(frames):
        return 0
    n = 0
    for name in os.listdir(frames):
        if name.startswith("n") and name.endswith(".png") and name[1:-4].isdigit():
            n += 1
    return n


def missing_frames(frames, total):
    """返回 [0, total) 里缺掉的那个别帧号; 中间缺帧会让某一批编码中途失败"""
    return [i for i in range(int(total))
            if not os.path.exists(os.path.join(frames, FRAME_PATTERN % i))]


def plan_batches(total, n):
    """把 [0, total) 均分成 n 批, 余数分给靠前的批; 每批至少 1 帧"""
    n = max(1, min(int(n), max(1, int(total))))
    base, rem = divmod(int(total), n)
    out = []
    a = 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append({"index": i, "start": a, "end": a + size})
        a += size
    return out


def write_state(path, state):
    """
    原子写: 先写 .tmp 再 os.replace
    直接改原文件会让轮询的前端读到半个 JSON, 解析失败就以为进度丢了
    """
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_state(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def set_priority(name):
    """把本进程优先级降下来让子进程继承, 失败不中断; 只在 Windows 上有效"""
    if os.name != "nt" or not name:
        return False
    import ctypes
    table = {"Idle": 0x40, "BelowNormal": 0x4000, "Normal": 0x20,
             "AboveNormal": 0x8000, "High": 0x80}
    flag = table.get(name)
    if not flag:
        return False
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), flag))
    except OSError:
        return False


def probe_limits(cfg):
    """
    复用 resources.py 的探测: 原样打印它的报告, 再把 JSON 读回来取建议值
    探测不可用时退回内置规则, 与 assemble.ps1 的口径一致
    """
    script = os.path.join(HERE, "resources.py")
    json_path = os.path.join("temp", "resources_encode.json")
    total = cfg["total_frames"]
    if not os.path.exists(script):
        return None, json_path
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    if os.path.exists(json_path):
        os.remove(json_path)
    cmd = [sys.executable, script, "--for", "encode", "--json", json_path,
           "--out-dir", os.path.dirname(os.path.abspath(cfg["out"])) or ".",
           "--frames", str(total)]
    if cfg["audio"] and os.path.exists(cfg["audio"]):
        cmd += ["--audio", cfg["audio"]]
    code, out = run(cmd)
    print(out.rstrip())
    if code not in (0, 1):
        print("警告: 探测脚本退出码 %d (正常是 0, 建议拦截是 1), 这次结果可能不完整" % code)
    report = read_state(json_path)
    if code == 1 and report is None:
        return {"blocked": True, "reasons": ["探测脚本退出码 1, 但没读到 JSON 报告"],
                "warnings": [], "threads": 0, "preset": ""}, json_path
    return report, json_path


def resolve_limits(cfg, report):
    """命令行优先, 其次探测建议, 最后内置规则"""
    advice = (report or {}).get("advice") or {}
    cores = os.cpu_count() or 1
    fallback_threads = max(1, min(cores // 4, 8))
    threads = cfg["threads"] or int(advice.get("threads") or fallback_threads)
    preset = cfg["preset"] or str(advice.get("preset") or "slow")
    priority = cfg["priority"] or str(advice.get("priority") or "BelowNormal")
    blocked = bool(advice.get("blocked"))
    reasons = [x for x in (advice.get("reasons") or []) if x]
    warnings = [x for x in (advice.get("warnings") or []) if x]
    if not advice:
        warnings.append("探测不可用, 已退回内置规则: 线程数 = floor(核数/4) 夹到 1 到 8 "
                        "(本机 %d 核 -> %d), preset 取 slow, 优先级取 BelowNormal, 不做拦截判定"
                        % (cores, fallback_threads))
    free_gb = ((report or {}).get("disk") or {}).get("free_gb")
    return {"threads": int(threads), "preset": preset, "priority": priority,
            "blocked": blocked, "reasons": reasons, "warnings": warnings,
            "free_gb": free_gb}


def print_gate(cfg, lim):
    """打印合成确认门; 内容与 assemble.ps1 的门保持一致, 换脚本不该换口径"""
    free_text = "%s GB" % lim["free_gb"] if lim["free_gb"] is not None else "未知 (探测不可用)"
    print("=" * 62)
    print("合成确认门 (分批)")
    print("  帧数                  %d" % cfg["total_frames"])
    print("  分批数                %d" % cfg["batches"])
    print("  目标盘剩余空间        %s" % free_text)
    print("  建议编码线程数        -threads %d" % lim["threads"])
    print("  建议编码预设          %s" % lim["preset"])
    print("  编码器                %s%s" % (cfg["encoder"],
                                           "" if cfg["encoder"] == "libx264"
                                           else " (换了编码器, 换完必须重新量 PSNR)"))
    print("  进程优先级            %s" % lim["priority"])
    print("  是否建议拦截          %s" % ("是, 建议先处理下面的原因" if lim["blocked"] else "否"))
    print("  拦截原因:" if lim["blocked"] else "  限额说明:")
    for r in lim["reasons"] or ["无"]:
        print("    - %s" % r)
    print("  警告:")
    for w in lim["warnings"] or ["无"]:
        print("    - %s" % w)
    print("=" * 62)


def encode_filter(cfg):
    return "noise=alls=%d:allf=t,format=yuv420p" % cfg["noise"]


def encoder_args(cfg, lim):
    """
    把 CPU 侧的 preset 与 crf 映射到所选编码器

    换编码器不等于给同一个编码器加开关: x264 是纯 CPU 编码器, CUDA 加速不了它; 用 NVENC
    是换成另一个编码器, 画质与体积都会变, 换完必须用下面的 PSNR 质检重新量一遍
    """
    name = cfg["encoder"]
    preset = lim["preset"]
    if name == "libx264":
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(cfg["crf"])]
    if name.endswith("_nvenc"):
        table = {"slow": "p7", "medium": "p6", "fast": "p5", "veryfast": "p4"}
        # NVENC 用 vbr 加 cq, 并把目标码率交给 cq 决定, 否则它按固定码率跑, 体积会失控
        return ["-c:v", name, "-preset", table.get(preset, "p6"),
                "-rc", "vbr", "-cq", str(cfg["crf"]), "-b:v", "0"]
    if name.endswith("_qsv"):
        return ["-c:v", name, "-preset", "medium", "-global_quality", str(cfg["crf"])]
    if name.endswith("_amf"):
        return ["-c:v", name, "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(cfg["crf"]), "-qp_p", str(cfg["crf"])]
    # 其余硬件编码器 (例如 vaapi) 参数语义差别更大, 只透传编码器与 crf, 由使用者自己核对
    return ["-c:v", name, "-crf", str(cfg["crf"])]


def encode_batch(cfg, lim, batch, seg_path, state, state_path):
    """
    编一批; 进度写进状态文件, 前端轮询它就够了, 不需要读 ffmpeg 的日志

    -start_number 让 image2 解复用器直接从该批第一帧开始读, -frames:v 限制输出帧数;
    两者配合才不会像 select 那样把整段帧全解码一遍
    """
    start = batch["start"]
    count = batch["end"] - batch["start"]
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "warning",
           "-filter_threads", str(lim["threads"]),
           "-framerate", str(cfg["fps"]),
           "-start_number", str(start),
           "-i", cfg["pattern"],
           "-frames:v", str(count),
           "-vf", encode_filter(cfg)] + encoder_args(cfg, lim) + [
           "-threads", str(lim["threads"]), "-pix_fmt", "yuv420p",
           "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", seg_path]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    tail = []
    last_write = time.time()
    for line in p.stdout:
        line = line.rstrip("\n")
        key, _, val = line.partition("=")
        if key == "frame":
            try:
                done = int(val)
            except ValueError:
                continue
            batch["frames_done"] = done
            state["current_frame"] = start + min(done, count)
            state["done_frames"] = start + min(done, count)
            if time.time() - last_write > 1.5:
                write_state(state_path, state)
                last_write = time.time()
        elif key in ("out_time_ms", "speed", "progress"):
            if key == "speed":
                state["speed"] = val
        elif line.strip():
            tail.append(line)
            if len(tail) > 20:
                tail.pop(0)
    code = p.wait()
    batch["frames_done"] = count if code == 0 else batch.get("frames_done", 0)
    return code, "\n".join(tail)


def concat(cfg, lim, state, state_path):
    """
    无损拼接各批; 列表只写 basename 并与分段同目录

    concat demuxer 按列表文件所在目录解析相对路径, 写相对工作目录的路径会拼出一个
    不存在的路径 (实测报 Impossible to open); 列表用 basename 还是纯 ASCII,
    中文项目路径也不必额外处理
    """
    list_path = os.path.join(cfg["seg_dir"], "list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for b in state["batches"]:
            f.write("file '%s'\n" % os.path.basename(b["seg"]))
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-filter_threads", str(lim["threads"]),
           "-f", "concat", "-safe", "0", "-i", list_path,
           "-c", "copy", cfg["video_only"]]
    return run(cmd)


def measure_lufs(path):
    """从波形或成片量集成响度 I; 量产测结果写在 stderr, 拿不到就返回 None"""
    code, out = run([FFMPEG, "-hide_banner", "-nostats", "-i", path,
                     "-map", "0:a", "-af", "ebur128=peak=true", "-f", "null", "-"])
    hits = re.findall(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", out, re.M)
    return float(hits[-1]) if hits else None


def measure_true_peak_on_text(out):
    """从已捕获的 ebur128 摘要文本里解析真峰, 供测试直接喂文本"""
    m = re.search(r"^\s*True peak:(.*)$", out, re.M)
    if m is None:
        return None
    hit = re.search(r"(-?\d+(?:\.\d+)?)\s*dBFS", m.group(1))
    if hit:
        return float(hit.group(1))
    nxt = re.search(r"^\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", out[m.end():], re.M)
    return float(nxt.group(1)) if nxt else None


def measure_true_peak(path):
    """
    真峰必须从成片解码回来量: AAC 重建波形的采样间峰值可以超过原采样点

    ebur128 摘要的行格式随 ffmpeg 版本不同: 有的版本数值直接跟在 True peak: 后面,
    有的版本 (本机实测) True peak: 是单独的标题行, 数值在下一行的 Peak: 上.
    两种都解析, 都解析不到才返回 None, 不要让真峰验收静默失效
    """
    code, out = run([FFMPEG, "-hide_banner", "-nostats", "-i", path,
                     "-map", "0:a", "-af", "ebur128=peak=true", "-f", "null", "-"])
    return measure_true_peak_on_text(out)


def mix_and_normalize(cfg, lim, state, state_path):
    """音频整条一次处理: 单遍 loudnorm, 或 --exact-loudness 的量测加补偿加限幅闭环"""
    if cfg["exact_loudness"]:
        state["note"] = "精确响度: 量测待混音频"
        write_state(state_path, state)
        mix_audio = os.path.join(cfg["seg_dir"], "_mix_measure.m4a")
        code, out = run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                         "-i", cfg["audio"], "-ar", "48000",
                         "-c:a", "aac", "-b:a", "%dk" % cfg["audio_bitrate"],
                         mix_audio])
        if code != 0:
            return code, "生成量测音频失败\n" + out
        i0 = measure_lufs(mix_audio)
        if i0 is None:
            return 1, "量测集成响度失败"
        gain = round(cfg["lufs"] - i0, 2)
        lim_level = round(10 ** (-1.5 / 20.0), 4)
        print("      混音前实测集成响度 I = %.2f LUFS, 差值 %.2f dB, 限幅阈值 %s (-1.5 dBFS)"
              % (i0, gain, lim_level))
        if abs(gain) > 12:
            print("      注意: 补偿量超过 12dB, 限幅器会明显介入, 建议先修配乐电平")
        af = "volume=%.2fdB,alimiter=limit=%s:level=false" % (gain, lim_level)
        code, out = run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                         "-filter_threads", str(lim["threads"]),
                         "-i", cfg["video_only"], "-i", cfg["audio"],
                         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", af,
                         "-ar", "48000", "-c:a", "aac", "-b:a", "%dk" % cfg["audio_bitrate"],
                         "-threads", str(lim["threads"]),
                         "-movflags", "+faststart", "-shortest", cfg["out"]])
        if os.path.exists(mix_audio):
            os.remove(mix_audio)
        return code, out
    af = "loudnorm=I=%s:TP=-1.5:LRA=11" % cfg["lufs"]
    return run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-filter_threads", str(lim["threads"]),
                "-i", cfg["video_only"], "-i", cfg["audio"],
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", af,
                "-ar", "48000", "-c:a", "aac", "-b:a", "%dk" % cfg["audio_bitrate"],
                "-threads", str(lim["threads"]),
                "-movflags", "+faststart", "-shortest", cfg["out"]])


def psnr_against_frames(cfg):
    """编码前后 PSNR; 源帧改过而没重编对应批次时, 这里的均值会明显掉下来"""
    code, out = run([FFMPEG, "-hide_banner", "-nostats",
                     "-framerate", str(cfg["fps"]), "-i", cfg["pattern"],
                     "-i", cfg["video_only"],
                     "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"])
    hits = re.findall(r"average:(\d+(?:\.\d+)?)", out)
    return float(hits[-1]) if hits else None


def build_config(a, total):
    out = os.path.abspath(a.out)
    stem = os.path.splitext(os.path.basename(out))[0]
    seg_dir = a.seg_dir or os.path.join("temp", "_seg_%s" % stem)
    frames = a.frames
    return {
        "frames": frames,
        "pattern": os.path.join(frames, FRAME_PATTERN),
        "audio": a.audio,
        "out": out,
        "seg_dir": os.path.abspath(seg_dir),
        "video_only": os.path.abspath(os.path.join(seg_dir, "_video_only.mp4")),
        "state": os.path.abspath(a.state) if a.state else os.path.join(HERE, STATE_NAME),
        "fps": int(a.fps), "crf": int(a.crf), "noise": int(a.noise),
        "lufs": float(a.lufs), "audio_bitrate": int(a.audio_bitrate),
        "true_peak_ceiling": float(a.true_peak_ceiling),
        "encoder": a.encoder,
        "threads": int(a.threads), "preset": a.preset, "priority": a.priority,
        "batches": int(a.batches), "total_frames": total,
        "exact_loudness": bool(a.exact_loudness),
        "skip_quality_check": bool(a.skip_quality_check),
    }


def snapshot(cfg):
    """状态文件里用来判断能不能续跑的那一份配置; 只留影响产物的字段"""
    keep = ("frames", "pattern", "audio", "out", "seg_dir", "fps", "crf", "noise",
            "lufs", "audio_bitrate", "true_peak_ceiling", "encoder", "batches",
            "total_frames", "exact_loudness")
    return {k: cfg[k] for k in keep}


def new_state(cfg):
    batches = plan_batches(cfg["total_frames"], cfg["batches"])
    for b in batches:
        b["seg"] = os.path.abspath(os.path.join(
            cfg["seg_dir"], "seg_%02d.mp4" % b["index"]))
        b["status"] = "pending"
        b["frames_done"] = 0
        b["seconds"] = 0.0
        b["bytes"] = 0
    return {
        "version": STATE_VERSION,
        "config": snapshot(cfg),
        "stage": "probe",
        "note": "",
        "error": "",
        "pid": os.getpid(),
        "done_frames": 0,
        "current_frame": 0,
        "speed": "",
        "batches": batches,
        "out": cfg["out"],
    }


def merge_state(state, cfg):
    """
    续跑: 保留已完成批次与它们的分段文件, 只把剩下的重排
    配置与上次不一致时返回 None, 由调用方要求 --restart
    """
    if state.get("version") != STATE_VERSION:
        return None
    if state.get("config") != snapshot(cfg):
        return None
    return state


def parse_args(argv):
    ap = argparse.ArgumentParser(description="分批编码合成的后端核心, 支持断点续跑")
    ap.add_argument("--frames", default=os.path.join("temp", "frames"),
                    help="帧目录, 里面是 n%%05d.png")
    ap.add_argument("--audio", default=os.path.join("audio", "score.wav"), help="配乐 WAV")
    ap.add_argument("--out", default=os.path.join("out", "video.mp4"), help="输出成片")
    ap.add_argument("--batches", type=int, default=1, help="批次数, 缺省 1 (不分批)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=19)
    ap.add_argument("--noise", type=int, default=2, help="轻颗粒强度, 0 表示不加")
    ap.add_argument("--lufs", type=float, default=-15.0)
    ap.add_argument("--audio-bitrate", type=int, default=384, help="AAC 码率, 不要低于 384")
    ap.add_argument("--true-peak-ceiling", type=float, default=-1.0)
    ap.add_argument("--encoder", default="libx264", help="视频编码器, 例如 libx264 或 h264_nvenc")
    ap.add_argument("--threads", type=int, default=0, help="编码线程数, 0 表示取探测建议")
    ap.add_argument("--preset", default="", help="编码预设, 空表示取探测建议")
    ap.add_argument("--priority", default="", help="进程优先级, 空表示取探测建议")
    ap.add_argument("--seg-dir", default=None, help="分段目录, 缺省 temp/_seg_<成片名>")
    ap.add_argument("--state", default=None, help="状态文件路径, 缺省脚本同目录")
    ap.add_argument("--exact-loudness", action="store_true", help="走精确响度闭环")
    ap.add_argument("--skip-quality-check", action="store_true", help="跳过 PSNR 质检")
    ap.add_argument("--redo", default="", help="重做指定批次, 逗号分隔, 例如 3 或 3,7")
    ap.add_argument("--restart", action="store_true", help="忽略上次进度, 全部重来")
    ap.add_argument("--probe-only", action="store_true", help="只探测并打印确认门")
    ap.add_argument("--yes", action="store_true", help="已经拿到用户确认, 直接开工")
    ap.add_argument("--force", action="store_true", help="探测判定应拦截时强行开工")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    total = count_frames(a.frames)
    if total == 0:
        if a.probe_only:
            print("仅探测: 帧目录 %s 还没有 %s 命名的帧, 帧齐后再来探测与编码"
                  % (a.frames, FRAME_PATTERN))
            return 0
        print("错误: 在 %s 下没数到 %s 命名的帧, 先确认帧目录与命名" % (a.frames, FRAME_PATTERN))
        return 2
    cfg = build_config(a, total)
    os.makedirs(os.path.dirname(cfg["out"]) or ".", exist_ok=True)
    os.makedirs(cfg["seg_dir"], exist_ok=True)

    miss = missing_frames(a.frames, total)
    if miss:
        head = ", ".join(str(x) for x in miss[:8])
        more = "" if len(miss) <= 8 else " 等 %d 处" % len(miss)
        print("错误: 帧目录缺帧, 帧号 [0, %d) 有空洞, 共 %d 处: %s%s"
              % (total, len(miss), head, more))
        print("  中间缺帧会让对应批次编码中途失败; 补渲缺的帧, 或把完整帧目录放回来")
        return 2

    report, _ = probe_limits(cfg)
    lim = resolve_limits(cfg, report)

    state_path = cfg["state"]
    old = None if a.restart else read_state(state_path)
    state = merge_state(old, cfg) if old else None
    if old is not None and state is None and not a.restart:
        print("状态文件与本次配置不一致, 不能直接续跑: %s" % state_path)
        print("  要么把参数改回上次的值, 要么加 --restart 全部重来")
        return 7
    if state is not None:
        # 批次表自洽检查: 批次表是启动时按当时帧数算出的, 帧目录后来补齐或变动过的话
        # 旧表就与实际帧数对不上, 继续编会报"找不到序列"; 有差额就打印两个数字并要求重启
        planned = sum(b["end"] - b["start"] for b in state["batches"])
        if planned != cfg["total_frames"]:
            print("批次表与实际帧数不一致, 不能直接续跑: %s" % state_path)
            print("  批次表按 %d 帧算出, 帧目录现在是 %d 帧, 差 %+d 帧"
                  % (planned, cfg["total_frames"], cfg["total_frames"] - planned))
            print("  加 --restart 重算批次表; 只想重编某几批先 --restart 再 --redo")
            return 7
    fresh = state is None
    if fresh:
        state = new_state(cfg)
    state["pid"] = os.getpid()
    state["stage"] = "gate"
    state["note"] = "打印合成确认门"
    write_state(state_path, state)
    print("状态文件: %s" % state_path)
    print_gate(cfg, lim)

    if a.probe_only:
        print("仅探测: 未做任何编码, 退出 0")
        return 0

    if not a.yes:
        interactive = sys.stdin is not None and sys.stdin.isatty()
        if interactive:
            try:
                reply = input("确认开始合成? 输入 YES 继续: ")
            except EOFError:
                reply = ""
            if reply.strip().lower() != "yes":
                print("没有拿到确认, 已取消合成")
                state["stage"] = "waiting"
                write_state(state_path, state)
                return 3
        else:
            print("正在等待用户二次确认, 拿到同意后加 --yes 重跑")
            state["stage"] = "waiting"
            write_state(state_path, state)
            return 3

    if lim["blocked"] and not a.force:
        print("探测判定应拦截, 未给 --force, 已停止, 不做任何编码")
        for r in lim["reasons"]:
            print("  原因: %s" % r)
        state["stage"] = "blocked"
        state["error"] = "; ".join(lim["reasons"])
        write_state(state_path, state)
        return 4

    if set_priority(lim["priority"]):
        print("已把本进程优先级设为 %s, 子进程会继承" % lim["priority"])
    print("限额: -threads %d -preset %s -filter_threads %d"
          % (lim["threads"], lim["preset"], lim["threads"]))

    redo = set()
    for token in str(a.redo).replace(" ", ",").split(","):
        if token.strip().isdigit():
            redo.add(int(token.strip()))
    for b in state["batches"]:
        if fresh or b["index"] in redo:
            b["status"] = "pending"
            b["frames_done"] = 0
            b["seconds"] = 0.0
            b["bytes"] = 0
            if os.path.exists(b["seg"]):
                os.remove(b["seg"])

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, interrupted)
    except (ValueError, OSError):
        pass

    try:
        todo = [b for b in state["batches"] if b["status"] != "done"]
        skipped = len(state["batches"]) - len(todo)
        if not todo:
            if state.get("stage") == "done" and os.path.exists(cfg["out"]):
                print("上一轮已经全部完成: %s" % cfg["out"])
                print("  要整条重来请加 --restart; 只重编某几批请加 --redo N")
                return 0
            print("所有批次都已完成, 直接从拼接阶段继续")
        state["stage"] = "encode"
        state["note"] = "编码第 %d 批起, 跳过已完成 %d 批" % (
            todo[0]["index"] if todo else 0, skipped)
        write_state(state_path, state)
        print("[1/4] 编码帧序列 -> %s (%d 批, 跳过已完成 %d 批)"
              % (cfg["seg_dir"], len(state["batches"]), skipped))
        for b in todo:
            b["status"] = "running"
            b["t0"] = time.time()
            state["note"] = "编码第 %02d 批, 帧 %d 到 %d" % (b["index"], b["start"], b["end"])
            write_state(state_path, state)
            code, tail = encode_batch(cfg, lim, b, b["seg"], state, state_path)
            b["seconds"] = round(time.time() - b["t0"], 1)
            b["t0"] = None  # 结算完清成显式 None: 硬杀后前端见到 running 无 t0 就知道是残留
            if code != 0:
                b["status"] = "failed"
                state["stage"] = "failed"
                state["note"] = "第 %02d 批编码失败" % b["index"]
                state["error"] = tail[-600:]
                write_state(state_path, state)
                print("编码失败: 第 %02d 批 (帧 %d 到 %d), 退出码 %d"
                      % (b["index"], b["start"], b["end"], code))
                print(tail[-1200:])
                return 6
            b["status"] = "done"
            b["frames_done"] = b["end"] - b["start"]
            b["bytes"] = os.path.getsize(b["seg"]) if os.path.exists(b["seg"]) else 0
            state["done_frames"] = b["end"]
            state["note"] = "第 %02d 批完成 (%.1f 秒, %.1f MB)" % (
                b["index"], b["seconds"], b["bytes"] / 1048576.0)
            write_state(state_path, state)
            print("  批 %02d 帧 %d 到 %d 完成, %.1f 秒, %.1f MB"
                  % (b["index"], b["start"], b["end"], b["seconds"], b["bytes"] / 1048576.0))

        state["stage"] = "concat"
        state["note"] = "无损拼接 %d 批" % len(state["batches"])
        write_state(state_path, state)
        print("[2/4] 无损拼接 -> %s" % cfg["video_only"])
        code, out = concat(cfg, lim, state, state_path)
        if code != 0:
            state["stage"] = "failed"
            state["error"] = out[-600:]
            write_state(state_path, state)
            print("拼接失败, 退出码 %d" % code)
            print(out[-1200:])
            return 6

        state["stage"] = "mux"
        state["note"] = "混音与响度归一"
        write_state(state_path, state)
        print("[3/4] 混音并归一响度到 %s LUFS (%s) -> %s"
              % (cfg["lufs"], "精确响度闭环" if cfg["exact_loudness"] else "单遍 loudnorm",
                 cfg["out"]))
        code, out = mix_and_normalize(cfg, lim, state, state_path)
        if code != 0:
            state["stage"] = "failed"
            state["error"] = out[-600:]
            write_state(state_path, state)
            print("混音失败, 退出码 %d" % code)
            print(out[-1200:])
            return 6

        state["stage"] = "verify"
        state["note"] = "流信息, 真峰与 PSNR"
        write_state(state_path, state)
        print("[4/4] 流信息")
        print(run([FFPROBE, "-v", "error", "-show_entries", "format=duration,size",
                   "-show_entries",
                   "stream=codec_name,codec_type,width,height,r_frame_rate,channels,sample_rate",
                   "-of", "default=nw=1", cfg["out"]])[1].rstrip())

        peak_failed = False
        tp = measure_true_peak(cfg["out"])
        state["true_peak"] = tp
        if tp is None:
            print("警告: 成片里没有量到 True peak 行, 真峰未能核对")
        elif tp > cfg["true_peak_ceiling"]:
            print("真峰不合格: 实测 %s dBFS, 判据是不高于 %s dBFS"
                  % (tp, cfg["true_peak_ceiling"]))
            print("  处置: 降配乐峰值, 提高 --audio-bitrate, 或改用 --exact-loudness 的精确响度路径")
            peak_failed = True
        else:
            print("真峰合格: 实测 %s dBFS, 判据是不高于 %s dBFS"
                  % (tp, cfg["true_peak_ceiling"]))
        lufs = measure_lufs(cfg["out"])
        state["lufs_measured"] = lufs
        if lufs is not None:
            print("集成响度: %s LUFS (目标 %s)" % (lufs, cfg["lufs"]))

        if not cfg["skip_quality_check"]:
            print("[质检] 编码前后 PSNR (高于 45dB 为视觉无损)")
            v = psnr_against_frames(cfg)
            state["psnr"] = v
            if v is None:
                print("警告: 没量到 PSNR, 质检未完成")
            else:
                print("  average %.2f dB" % v)
                print("  提醒: 源帧改过而没重编对应批次时, 这里的均值会假性掉下来; "
                      "该批必须用 --redo 重编")
        write_state(state_path, state)
        print("质检实测值 (真峰, 响度, PSNR) 已写进状态文件: %s" % state_path)
        print("提醒: 视频流已删, 之后想复测 PSNR 用 "
              "python scripts/psnr_check.py --frames <帧目录> --video <成片>")

        if os.path.exists(cfg["video_only"]):
            os.remove(cfg["video_only"])

        state["stage"] = "done"
        state["done_frames"] = cfg["total_frames"]
        state["note"] = "完成: %s" % cfg["out"]
        state["error"] = ""
        write_state(state_path, state)
        print("分段保留在 %s: --redo N 可以只重编某几批 (源帧改过时必须重编对应批次), "
              "验收完可以整个目录删掉" % cfg["seg_dir"])
        if peak_failed:
            print("完成但有不合格项: %s" % cfg["out"])
            return 5
        print("完成: %s" % cfg["out"])
        return 0
    except KeyboardInterrupt:
        state["stage"] = "interrupted"
        state["note"] = "收到中断, 断点已保留; 直接重跑本命令即可续跑"
        for b in state["batches"]:
            if b["status"] == "running":
                b["status"] = "pending"
                b["frames_done"] = 0
        write_state(state_path, state)
        print()
        print("已中断: 断点与批次表保留在 %s, 重跑同一命令即可续跑" % state_path)
        return 130


if __name__ == "__main__":
    sys.exit(main())

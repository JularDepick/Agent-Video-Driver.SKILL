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

两道帧完整性硬闸 (实测踩过: 宿主强杀渲染进程会留下 0 字节 PNG, 而 ffmpeg 的 image2
解复用器读到坏帧是**静默停止**的, 编码器只编到坏帧就退出 0, 数文件个数完全拦不住):
  编码前按字节大小体检帧目录, 0 字节与明显偏小的帧直接点名并拒绝开工 (退出码 6)
  编码后按 -progress 的 frame 计数逐批核对, 再对拼接结果核一次 nb_read_frames,
    两者都必须等于计划帧数, 不一致即判定残片并拒绝交付 (退出码 6)

成片流信息硬闸: 编码时必须显式写出 bt709 三个色彩标签与限幅范围, 交付前对成片回读一次;
音画必须等长, 不等长在平台上表现为黑尾或静音尾. 任一项不合格 (退出码 9).
标签与 -g/-keyint_min 也参与拼接一致性: 各批参数不一致会在接缝处掉帧或闪一下.

状态文件 (缺省是脚本同目录的 assemble_state.json) 每完成一批原子写入一次, 内容含配置快照,
批次表, 当前阶段, 已完成帧数与 pid; 重跑时自动跳过已完成批次, 配置与上次不一致时拒绝续跑,
要重来必须显式加 --restart. --redo N 用来重做指定批次, 源帧改过时必须重编对应批次,
否则视频里是旧帧, 磁盘上是新帧, PSNR 验收会假性崩掉.

退出码 (与 assemble.ps1 一次编完路线共用同一套语义, 定义在 videoconf.py):
        0 成功; 2 用法错误; 3 等待用户二次确认; 4 探测判定应拦截; 5 真峰不合格;
        6 帧完整性不合格 (残帧或帧数不足); 7 状态文件与本次配置不一致;
        8 编码或混音失败; 9 成片流信息不合格 (色彩标签或音画等长); 130 被中断 (断点已保留)
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
# 帧名, 字节下限与容差取自 videoconf.py: canvas 落盘侧与两条编码路线必须同一份,
# 改一处漏其余几处的症状是静默的 (ffmpeg 读到坏帧会静默停止而退出码仍是 0).
# videoconf 只含常量与纯函数, 不引入依赖, 单独复制走本文件也能跑.
sys.path.insert(0, HERE)
try:
    import videoconf
except ImportError:      # pragma: no cover - 只有缺文件时才会走到
    videoconf = None
FRAME_PATTERN = videoconf.FRAME_PATTERN
MIN_FRAME_BYTES = videoconf.MIN_FRAME_BYTES
FRAME_TOLERANCE = videoconf.FRAME_TOLERANCE

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


# 每条子进程调用的超时上限 (秒). 量测类命令 (ffprobe / nb_read_frames) 正常几秒内返回,
# 给一个远大于正常值的上限, 它的作用不是"卡得久就掐", 而是"永远卡住就掐":
# 少了它, ffmpeg 挂死会让整条合成流程无限期停在那里, 而宿主强杀进程还会留下
# 半写状态文件与孤儿子进程, 断点续跑也救不回来.
PROBE_TIMEOUT = 120          # ffprobe 与帧数核对
ENCODE_TIMEOUT = 7200        # 单批编码: 2 小时, 远超任何合理批次
MIX_TIMEOUT = 1800           # 混音与响度归一
CONCAT_TIMEOUT = 1800        # 无损拼接
PSNR_TIMEOUT = 1800          # PSNR 复测


def run(cmd, cwd=None, timeout=PROBE_TIMEOUT):
    """
    跑一条命令, 返回 (退出码, 合并后的输出)

    ffmpeg 的量测结果都写在 stderr, 所以合并读. 超时按 (超时退出码, 提示) 返回,
    不抛异常: 调用方本来就只按 code 判断成败, 让它去 catch 超时反而每个调用点都要改.
    """
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        got = ""
        for part in (e.stdout, e.stderr):
            if part is None:
                continue
            got += part.decode("utf-8", "replace") if isinstance(part, bytes) else part
        return 124, got + "\n[超时] 这条命令超过 %d 秒仍未结束, 已掐掉. ffmpeg 挂死的常见原因:\n" \
               "输入帧序列里有读不动的文件 (坏 PNG / 网络盘), 或输出目录不可写; " \
               "先按 assemble_core.py --probe-only 的帧完整性体检过一遍再重试." % timeout
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


def broken_frames(frames, total, min_bytes=None):
    """
    返回 (帧号, 字节数) 列表, 收录 0 字节与小于 min_bytes 的帧

    必须单独做这一道: 数个数与查存在性都拦不住坏帧. ffmpeg 的 image2 解复用器读到
    坏帧是静默停止的, 编码器只编到坏帧就退出 0, 于是"帧数全在"却交付一条半长残片
    """
    if min_bytes is None:
        min_bytes = MIN_FRAME_BYTES
    out = []
    for i in range(int(total)):
        p = os.path.join(frames, FRAME_PATTERN % i)
        try:
            n = os.path.getsize(p)
        except OSError:
            n = 0
        if n < min_bytes:
            out.append((i, n))
    return out


def report_broken(frames, bad, min_bytes=None):
    """把坏帧点名打印出来, 供人工重渲这几个帧号"""
    if min_bytes is None:
        min_bytes = MIN_FRAME_BYTES
    head = ", ".join("%s (%d 字节)" % (FRAME_PATTERN % i, n) for i, n in bad[:8])
    more = "" if len(bad) <= 8 else " 等 %d 处" % len(bad)
    print("错误: 帧目录 %s 里有 %d 个坏帧 (0 字节或小于 %d 字节): %s%s"
          % (frames, len(bad), min_bytes, head, more))
    print("  坏帧通常来自渲染进程被宿主强杀: 文件建了但内容没写完")
    print("  处置: 用 scene_module.py at <段>:<拍> 或分段重渲补上这几个帧号, 再回来编码;")
    print("        坏帧不补就开编, ffmpeg 会静默停在坏帧处并退出 0, 交付的是一条残片")
    print("  阈值可调: --min-frame-bytes N (低分辨率试渲染的合法帧可能只有几百字节)")
    print("  自查命令: python scripts/assemble_core.py --frames %s --probe-only" % frames)


def probe_frame_count(path):
    """
    用 ffprobe 数一条 mp4 视频流里实际解码出的帧数 (nb_read_frames)

    这是编码侧的最终硬闸: -progress 的 frame 计数只能反映编码器自报的进度,
    对拼接结果再数一遍才能证明"计划多少帧, 成片里就是多少帧"
    """
    code, out = run([FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
                     "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path])
    if code != 0:
        return None
    m = re.search(r"(\d+)", out)
    return int(m.group(1)) if m else None


def probe_stream_tags(path):
    """
    回读成片视频流的色彩标签与像素格式

    编码命令里显式写了 bt709 才算数: 不写时由 ffmpeg 按分辨率推断, 推断结果随编码器与
    滤镜链变化, 现象是"本机看着正常, 换台机器或上传到平台后整体偏色发灰"
    """
    code, out = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                     "-show_entries",
                     "stream=pix_fmt,color_range,color_space,color_primaries,color_transfer",
                     "-of", "default=nw=1", path])
    return out.strip() if code == 0 else None


def stream_tag_gaps(tags):
    """列出成片里不是 bt709 的色彩标签; 返回空列表才算合格"""
    want = ("color_space", "color_primaries", "color_transfer")
    missing = [k for k in want if not re.search(r"^%s=bt709$" % k, tags or "", re.M)]
    if not re.search(r"^color_range=tv$", tags or "", re.M):
        missing.append("color_range")
    return missing


def probe_av_durations(path):
    """
    分离读出视频流与音频流的时长, 音画等长只能在成片上核

    混音时已经带了 -shortest, 但容器的流时长会各自取整到自己的时间基, 所以判据留一帧
    容差. 平台上出现黑尾或静音尾的根因就是音轨比视频长, 而在中间产物上看不出来
    """
    def one(sel):
        code, out = run([FFPROBE, "-v", "error", "-select_streams", sel,
                         "-show_entries", "stream=duration", "-of", "csv=p=0", path])
        if code != 0:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)", out)
        return float(m.group(1)) if m else None
    return one("v:0"), one("a:0")


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


# 滤镜链: 先给帧打上色彩标签, 再叠颗粒.
#
# 为什么必须显式打标签: PNG 输入的帧本身没有色彩标签 (ffprobe 对 PNG 报
# color_space=gbr), 而 libx264 只从帧上读标签写进 VUI. 于是只给编码器加命令行参数
# (-colorspace/-color_primaries/-color_trc) 时, 三个标签里只有 color_space 成了
# bt709, primaries 与 transfer 落回 unknown, 交付前的回读闸会判不合格.
#
# 用 setparams 而不是 colorspace 滤镜: colorspace 会真做一次色彩转换, 实测把 PSNR
# 从 55.2 dB 打到 28.1 dB (掉到 45 dB 判据之下); setparams 只写帧头标签不碰像素,
# 三个标签全对而 PSNR 保持 51.8 dB.
COLOR_FILTER = ("format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709"
                ":colorspace=bt709:range=tv")


def encode_filter(cfg):
    return "%s,noise=alls=%d:allf=t" % (COLOR_FILTER, cfg["noise"])


def color_args():
    """bt709 色彩标签与限幅范围; 定义在 videoconf.py, 与一次编完路线共用"""
    return videoconf.color_args()


def gop_args(cfg, name):
    """固定 GOP; 定义在 videoconf.py, 与一次编完路线共用"""
    return videoconf.gop_args(cfg["fps"], name)


def encoder_args(encoder, preset, crf, fps):
    """编码器参数映射; 定义在 videoconf.py, 与一次编完与基准路线共用"""
    return videoconf.encoder_args(encoder, preset, crf, fps)


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
           "-vf", encode_filter(cfg)] + encoder_args(cfg["encoder"], lim["preset"], cfg["crf"], cfg["fps"]) + [
           "-threads", str(lim["threads"]), "-pix_fmt", "yuv420p"] + color_args() + [
           "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", seg_path]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    tail = []
    encoded = 0
    last_write = time.time()
    for line in p.stdout:
        line = line.rstrip("\n")
        key, _, val = line.partition("=")
        if key == "frame":
            try:
                done = int(val)
            except ValueError:
                continue
            encoded = done
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
    return code, "\n".join(tail), encoded


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
                     "-map", "0:a", "-af", "ebur128=peak=true", "-f", "null", "-"], timeout=ENCODE_TIMEOUT)
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
                     "-map", "0:a", "-af", "ebur128=peak=true", "-f", "null", "-"], timeout=ENCODE_TIMEOUT)
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
                         mix_audio], timeout=MIX_TIMEOUT)
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
                         "-movflags", "+faststart", "-shortest", cfg["out"]], timeout=MIX_TIMEOUT)
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
                "-movflags", "+faststart", "-shortest", cfg["out"]], timeout=MIX_TIMEOUT)


def psnr_against_frames(cfg):
    """编码前后 PSNR; 源帧改过而没重编对应批次时, 这里的均值会明显掉下来"""
    code, out = run([FFMPEG, "-hide_banner", "-nostats",
                     "-framerate", str(cfg["fps"]), "-i", cfg["pattern"],
                     "-i", cfg["video_only"],
                     "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"], timeout=PSNR_TIMEOUT)
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
    ap.add_argument("--lufs", type=float, default=videoconf.LUFS_TARGET,
                    help="loudnorm 的目标点, 缺省取验收区间的中值 %s" % videoconf.LUFS_TARGET)
    ap.add_argument("--audio-bitrate", type=int, default=videoconf.AUDIO_BITRATE_K, help="AAC 码率, 不要低于 384")
    ap.add_argument("--true-peak-ceiling", type=float, default=videoconf.TRUE_PEAK_CEILING,
                    help="成片真峰上限 dBTP, 超过判不合格 (缺省 %.1f)" % videoconf.TRUE_PEAK_CEILING)
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
    ap.add_argument("--min-frame-bytes", type=int, default=MIN_FRAME_BYTES,
                    help="帧文件字节数下限, 低于它判为坏帧 (缺省 %d)" % MIN_FRAME_BYTES)
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
        return videoconf.EXIT_USAGE

    # 帧数齐不等于帧可用: 被强杀的渲染进程会留下 0 字节 PNG, 而 ffmpeg 读到坏帧是静默停止的
    bad = broken_frames(a.frames, total, a.min_frame_bytes)
    if bad:
        report_broken(a.frames, bad, a.min_frame_bytes)
        return videoconf.EXIT_FRAME_INTEGRITY

    report, _ = probe_limits(cfg)
    lim = resolve_limits(cfg, report)

    state_path = cfg["state"]
    old = None if a.restart else read_state(state_path)
    state = merge_state(old, cfg) if old else None
    if old is not None and state is None and not a.restart:
        print("状态文件与本次配置不一致, 不能直接续跑: %s" % state_path)
        print("  要么把参数改回上次的值, 要么加 --restart 全部重来")
        return videoconf.EXIT_STATE_MISMATCH
    if state is not None:
        # 批次表自洽检查: 批次表是启动时按当时帧数算出的, 帧目录后来补齐或变动过的话
        # 旧表就与实际帧数对不上, 继续编会报"找不到序列"; 有差额就打印两个数字并要求重启
        planned = sum(b["end"] - b["start"] for b in state["batches"])
        if planned != cfg["total_frames"]:
            print("批次表与实际帧数不一致, 不能直接续跑: %s" % state_path)
            print("  批次表按 %d 帧算出, 帧目录现在是 %d 帧, 差 %+d 帧"
                  % (planned, cfg["total_frames"], cfg["total_frames"] - planned))
            print("  加 --restart 重算批次表; 只想重编某几批先 --restart 再 --redo")
            return videoconf.EXIT_STATE_MISMATCH
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
                return videoconf.EXIT_WAIT_CONFIRM
        else:
            print("正在等待用户二次确认, 拿到同意后加 --yes 重跑")
            state["stage"] = "waiting"
            write_state(state_path, state)
            return videoconf.EXIT_WAIT_CONFIRM

    if lim["blocked"] and not a.force:
        print("探测判定应拦截, 未给 --force, 已停止, 不做任何编码")
        for r in lim["reasons"]:
            print("  原因: %s" % r)
        state["stage"] = "blocked"
        state["error"] = "; ".join(lim["reasons"])
        write_state(state_path, state)
        return videoconf.EXIT_BLOCKED

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
            code, tail, encoded = encode_batch(cfg, lim, b, b["seg"], state, state_path)
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
                return videoconf.EXIT_ENCODE
            # 退出码 0 不代表编满了: image2 解复用器遇到坏帧会静默停止, 编码器照样退出 0
            want = b["end"] - b["start"]
            if encoded != want:
                b["status"] = "failed"
                state["stage"] = "failed"
                state["note"] = "第 %02d 批帧数不足" % b["index"]
                state["error"] = "计划 %d 帧, 实编 %d 帧" % (want, encoded)
                write_state(state_path, state)
                print("错误: 第 %02d 批只编出 %d 帧, 计划 %d 帧 (帧 %d 到 %d), 差 %d 帧"
                      % (b["index"], encoded, want, b["start"], b["end"], want - encoded))
                print("  这是残帧的典型症状: 该批第 %d 帧附近有 0 字节或截断的 PNG,"
                      % (b["start"] + encoded))
                print("  ffmpeg 的 image2 解复用器读到坏帧会静默停止, 但退出码仍是 0")
                print("  处置: 按上面的帧号重渲该帧, 再回来 --redo %d 重编这一批" % b["index"])
                return videoconf.EXIT_FRAME_INTEGRITY
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
            return videoconf.EXIT_ENCODE

        # 拼接后的最终硬闸: 对整条视频流数一次 nb_read_frames, 与计划帧数对齐才允许进入混音
        # 逐批的 frame 计数只看编码器自报, 数拼接结果才能证明成片真的是计划帧数
        got = probe_frame_count(cfg["video_only"])
        want = cfg["total_frames"]
        if got is None:
            print("警告: 拼接结果数不出帧数 (nb_read_frames), 帧完整性未能核对")
        elif abs(got - want) > FRAME_TOLERANCE:
            state["stage"] = "failed"
            state["error"] = "拼接结果 %d 帧, 计划 %d 帧" % (got, want)
            write_state(state_path, state)
            print("错误: 拼接结果只有 %d 帧, 计划 %d 帧, 差 %d 帧"
                  % (got, want, want - got))
            print("  成片会是残片, 拒绝进入混音; 按上面的差量补渲缺的帧或重编对应批次")
            return videoconf.EXIT_FRAME_INTEGRITY
        else:
            state["frames_verified"] = got
            print("[2/4] 帧完整性核对: 拼接结果 %d 帧, 计划 %d 帧, 一致" % (got, want))

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
            return videoconf.EXIT_ENCODE

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

        # 成片流信息硬闸: 色彩标签与音画等长都在成片这一层才能核
        tags = probe_stream_tags(cfg["out"])
        state["stream_tags"] = tags
        tag_failed = False
        if tags is None:
            print("警告: 读不到视频流的色彩标签, 该项未能核对")
        else:
            print(tags.replace("\n", " "))
            gaps = stream_tag_gaps(tags)
            if gaps:
                print("色彩标签不合格: %s 不是 bt709" % ", ".join(gaps))
                print("  处置: 确认编码命令显式写了色彩标签 (见 color_args), 再重编受影响的批次")
                tag_failed = True
            else:
                print("色彩标签合格: bt709 三个标签与 tv 限幅范围都已写入")

        vdur, adur = probe_av_durations(cfg["out"])
        state["video_duration"] = vdur
        state["audio_duration"] = adur
        av_failed = False
        if vdur is None or adur is None:
            print("警告: 音画时长未能分离读出, 等长未核对")
        elif abs(vdur - adur) > 1.0 / cfg["fps"]:
            print("音画不等长: 视频流 %.3fs, 音频流 %.3fs, 差 %.3fs (容差 %.3fs)"
                  % (vdur, adur, abs(vdur - adur), 1.0 / cfg["fps"]))
            print("  处置: 平台侧会表现为黑尾或静音尾, 检查混音步的 -shortest 与音轨实际长度")
            av_failed = True
        else:
            print("音画等长: 视频流 %.3fs, 音频流 %.3fs" % (vdur, adur))

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
            return videoconf.EXIT_TRUE_PEAK
        if tag_failed or av_failed:
            why = []
            if tag_failed:
                why.append("色彩标签不是 bt709")
            if av_failed:
                why.append("音画不等长")
            print("成片流信息不合格 (%s): %s" % (", ".join(why), cfg["out"]))
            return videoconf.EXIT_STREAM_INFO
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

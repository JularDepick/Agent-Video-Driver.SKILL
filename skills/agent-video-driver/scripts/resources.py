# -*- coding: utf-8 -*-
"""
资源占用探测与使用限额: 全量渲染与帧序列编码之前先跑一次

  python scripts/resources.py --for encode --frames 3240 --out-dir out
  python scripts/resources.py --for render --frames 3240
  python scripts/resources.py --for all --frames 3240 --audio audio/score.wav --json temp/resources.json

用途
  逐帧渲染与 FFmpeg 编码是唯一会把 CPU 打满的两步, 在开发机上会造成明显卡顿
  本脚本先探测本机资源, 再给出一组可以直接照用的限额: 编码线程数, x264 preset,
  进程优先级, 并行渲染进程数, 以及磁盘与内存是否够用
  探测不到的项目一律降级并如实标注 unavailable 与原因, 绝不抛栈

限额规则 (全部是模块顶部具名常量, 调策略只改那里)
  THREADS_MIN, THREADS_MAX   编码线程数下限与上限
  THREADS_DIV                编码线程数 = floor(逻辑核数 / THREADS_DIV), 再夹到上下限
  WORKERS_MIN, WORKERS_MAX   并行渲染进程数上下限, 上限 4 与本技能既有约定一致
  LOAD_BUSY_PERCENT          当前负载高于它时, 编码线程数再减半 (最少 1)
  LOAD_SLOW_PERCENT          逻辑核数够多且负载低于它时给 slow preset
  SLOW_MIN_LOGICAL           给 slow preset 所需的最少逻辑核数
  LOAD_BLOCKED_PERCENT       当前负载高于它时判定 blocked
  MEM_BLOCKED_GB             可用内存低于它时判定 blocked
  FRAME_PNG_MB               每帧 PNG 的体积估计
  VIDEO_FPS                  成片帧率, 用来把帧数折成时长
  OUT_MB_PER_30S             成片按 1080p 每 30 秒的体积估计
  DISK_SAFETY                磁盘预估的安全系数
  PRESET_SLOW, PRESET_MEDIUM 允许给出的两档 preset
  PRIORITY                   固定给的进程优先级
  PROC_NAMES                 要统计实例数的进程名

退出码
  0  正常
  1  探测判定应当拦截 (blocked 为真且没给 --force), 报告与 JSON 仍然正常产出
  2  参数错误
"""
import argparse
import ctypes
import importlib
import json
import os
import shutil
import subprocess
import sys

# ----------------------------------------------------------------- 限额规则常量
# 逻辑核数到并行度的换算
THREADS_MIN = 1
THREADS_MAX = 8
THREADS_DIV = 4
WORKERS_MIN = 1
WORKERS_MAX = 4

# 负载阈值, 单位是百分数
LOAD_BUSY_PERCENT = 60.0
LOAD_SLOW_PERCENT = 40.0
LOAD_BLOCKED_PERCENT = 85.0

# preset 与优先级
SLOW_MIN_LOGICAL = 8
PRESET_SLOW = "slow"
PRESET_MEDIUM = "medium"
PRIORITY = "BelowNormal"

# 硬件编码器白名单: 名称与厂商, 只用于报告, 不改变限额口径
HW_ENCODERS = (
    ("h264_nvenc", "NVIDIA NVENC"),
    ("hevc_nvenc", "NVIDIA NVENC"),
    ("av1_nvenc", "NVIDIA NVENC"),
    ("h264_qsv", "Intel Quick Sync"),
    ("h264_amf", "AMD AMF"),
    ("h264_vaapi", "VAAPI"),
)

# 体积估计与安全系数
FRAME_PNG_MB = 0.25
VIDEO_FPS = 30.0
OUT_MB_PER_30S = 15.0
DISK_SAFETY = 1.6
MEM_BLOCKED_GB = 1.5

# 探测相关
PROC_NAMES = ("ffmpeg", "ffprobe", "python")
PS_TIMEOUT = 20
UNAVAILABLE = "unavailable"

GB = 1024.0 ** 3
MB = 1024.0 ** 2


def clamp_int(value, lo, hi):
    v = int(value)
    return lo if v < lo else (hi if v > hi else v)


def fmt_num(value, unit="", nd=1):
    if value is None:
        return UNAVAILABLE
    return ("%%.%df%%s" % nd) % (value, unit)


def parse_int(text):
    if not text:
        return None
    try:
        head = text.strip().splitlines()[0].strip()
        return int(float(head))
    except Exception:
        return None


def parse_float(text):
    if not text:
        return None
    try:
        head = text.strip().splitlines()[0].strip()
        return float(head)
    except Exception:
        return None


def run_powershell(script):
    """
    跑一段 PowerShell 取 stdout, 任何失败都返回 None, 不抛栈
    子进程固定带 -NoProfile -NonInteractive, 超时 PS_TIMEOUT 秒
    可执行文件用 shutil.which 找, 不写绝对路径
    """
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=PS_TIMEOUT)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    return p.stdout or ""


# ----------------------------------------------------------------- 单项探测
def load_psutil():
    """psutil 只作为装了就用的可选项, 用 importlib 试探, 不写成硬依赖"""
    try:
        return importlib.import_module("psutil")
    except Exception:
        return None


def probe_logical():
    try:
        n = os.cpu_count()
    except Exception as e:
        return None, "%s: os.cpu_count 失败 (%s)" % (UNAVAILABLE, str(e)[:60])
    if not n:
        return None, "%s: os.cpu_count 返回空值" % UNAVAILABLE
    return int(n), "os.cpu_count"


def probe_physical(psutil_mod):
    if psutil_mod is not None:
        try:
            n = psutil_mod.cpu_count(logical=False)
            if n:
                return int(n), "psutil"
        except Exception:
            pass
    if sys.platform == "win32":
        out = run_powershell("(Get-CimInstance -ClassName Win32_Processor"
                             " | Measure-Object -Property NumberOfCores -Sum).Sum")
        n = parse_int(out)
        if n:
            return int(n), "powershell-cim"
    return None, "%s: 拿不到物理核数" % UNAVAILABLE


def probe_load(psutil_mod, sample):
    if psutil_mod is not None:
        try:
            v = float(psutil_mod.cpu_percent(interval=max(0.1, float(sample))))
            return round(v, 1), "psutil cpu_percent"
        except Exception:
            pass
    if sys.platform == "win32":
        out = run_powershell("(Get-CimInstance -ClassName Win32_Processor"
                             " | Measure-Object -Property LoadPercentage -Average).Average")
        v = parse_float(out)
        if v is not None:
            return round(v, 1), "powershell-cim Win32_Processor.LoadPercentage"
    return None, "%s: 没有 psutil, 也取不到 Win32_Processor.LoadPercentage" % UNAVAILABLE


class MEMORYSTATUSEX(ctypes.Structure):
    """GlobalMemoryStatusEx 的入参结构, 只用标准库 ctypes, 不依赖第三方也不开子进程"""
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def probe_mem_ctypes():
    if sys.platform != "win32":
        return None
    try:
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return float(st.ullTotalPhys), float(st.ullAvailPhys)
    except Exception:
        return None


def probe_mem_meminfo():
    try:
        kv = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                kv[k.strip()] = v.strip()
        total = float(kv["MemTotal"].split()[0]) * 1024.0
        key = "MemAvailable" if "MemAvailable" in kv else "MemFree"
        avail = float(kv[key].split()[0]) * 1024.0
        return total, avail
    except Exception:
        return None


def probe_mem_cim():
    out = run_powershell("$o = Get-CimInstance -ClassName Win32_OperatingSystem;"
                         " (($o.TotalVisibleMemorySize, $o.FreePhysicalMemory) -join ' ')")
    if not out:
        return None
    parts = out.strip().split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]) * 1024.0, float(parts[1]) * 1024.0
    except Exception:
        return None


def probe_hw_encoders():
    """
    探测可用的硬件编码器, 返回 (找到的列表, 来源说明)

    判断依据一律用 ffmpeg -encoders 的输出: *_nvenc 只需要显卡驱动, 不需要单独装
    CUDA Toolkit, 所以 CUDA 版本号与 nvcc 都说明不了能不能硬件编码
    """
    if not shutil.which("ffmpeg"):
        return [], "%s: ffmpeg 不在 PATH" % UNAVAILABLE
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=25)
        out = (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return [], "%s: %s" % (UNAVAILABLE, str(e)[:40])
    found = [(name, vendor) for name, vendor in HW_ENCODERS if name in out]
    return found, "ffmpeg -encoders"


def probe_busy():
    """
    统计 ffmpeg, ffprobe, python 的实例数, 只报数不阻断
    三个计数都排除本次探测进程自身, 所以 python 计数表示"除自己以外的 python 进程数",
    与 ffmpeg, ffprobe 的语义一致
    剔除依据是本进程的 os.getpid(), 它作为整数字面量显式拼进 PowerShell 脚本;
    不能用那条命令里的 $PID, 因为 $PID 是 PowerShell 自己的 pid 而不是我们的
    """
    script = ("$ours = %d;" % os.getpid()
              + "foreach ($n in 'ffmpeg','ffprobe','python') {"
              " $c = @(Get-Process -Name $n -ErrorAction SilentlyContinue"
              " | Where-Object { $_.Id -ne $ours }).Count;"
              " Write-Output (($n, '=', $c) -join '') }")
    out = run_powershell(script)
    if out is None:
        return None, "%s: 无法用 PowerShell 统计进程实例数" % UNAVAILABLE
    counts = dict((n, 0) for n in PROC_NAMES)
    seen = False
    for line in out.splitlines():
        text = line.strip()
        if "=" not in text:
            continue
        name, value = text.split("=", 1)
        name = name.strip().lower()
        if name in counts:
            counts[name] = parse_int(value)
            seen = True
    if not seen:
        return None, "%s: PowerShell 没返回可解析的进程计数" % UNAVAILABLE
    return counts, "powershell Get-Process"


# ----------------------------------------------------------------- 结果对象
class ResourceReport:
    """
    一次资源探测的完整结果: 探测量, 使用限额, 拦截判定, 以及给人读的原因与警告
    探测项失败一律降级成 None 加原因字符串, 不让异常冒到调用方
    """

    def __init__(self, scope="all", frames=None, out_dir=None, audio=None,
                 sample=1.0, force=False):
        self.scope = scope
        self.frames = frames
        self.out_dir = out_dir or os.getcwd()
        self.audio = audio
        self.sample = sample
        self.force = force
        self.reasons = []
        self.warnings = []
        self.blocked = False
        self.src = {}
        self.need_detail = None
        self.psutil_mod = load_psutil()
        self.cpu = self.probe_cpu()
        self.mem = self.probe_mem()
        self.disk = self.probe_disk()
        self.busy = self.probe_busy()
        self.hw, self.hw_src = probe_hw_encoders()
        self.limits = self.make_limits()
        self.check_blocked()
        if self.force and self.blocked:
            self.reasons.append("已给 --force, 忽略上面的拦截判定, 限额值保持不变")

    def probe_cpu(self):
        logical, s_logical = probe_logical()
        physical, s_physical = probe_physical(self.psutil_mod)
        load, s_load = probe_load(self.psutil_mod, self.sample)
        self.src["logical"] = s_logical
        self.src["physical"] = s_physical
        self.src["load"] = s_load
        if logical is None:
            self.warnings.append("逻辑核数探测失败, 限额按 1 核的最保守值算")
        if load is None:
            self.warnings.append("当前 CPU 负载探测失败, 无法判断机器是否已经在忙")
        if s_physical.startswith(UNAVAILABLE):
            self.warnings.append("物理核数探测失败, 只影响报告展示, 不影响限额")
        return {
            "logical": logical,
            "physical": physical,
            "load_percent": load,
            "source": "logical=%s; physical=%s; load=%s" % (s_logical, s_physical, s_load),
        }

    def probe_mem(self):
        total = avail = None
        src = ""
        got = probe_mem_ctypes()
        if got:
            total, avail = got
            src = "ctypes GlobalMemoryStatusEx"
        if total is None:
            got = probe_mem_meminfo()
            if got:
                total, avail = got
                src = "/proc/meminfo"
        if total is None:
            got = probe_mem_cim()
            if got:
                total, avail = got
                src = "powershell-cim Win32_OperatingSystem"
        if total is None:
            src = "%s: ctypes, /proc/meminfo 与 Win32_OperatingSystem 都拿不到内存" % UNAVAILABLE
            self.warnings.append("内存探测失败, 无法判断可用内存是否够渲染与编码")
        self.src["mem"] = src
        return {
            "total_gb": round(total / GB, 2) if total else None,
            "available_gb": round(avail / GB, 2) if avail is not None else None,
            "source": src,
        }

    def estimate_need_gb(self):
        """帧序列按 PNG 估, 成片按每 30 秒 15MB 估, 音频按实际体积算, 三者求和再乘安全系数"""
        if self.frames is None:
            self.warnings.append("未给 --frames, 跳过磁盘占用预估, 也就不会因磁盘判定拦截")
            return None
        png_mb = float(self.frames) * FRAME_PNG_MB
        out_mb = (float(self.frames) / VIDEO_FPS / 30.0) * OUT_MB_PER_30S
        audio_mb = 0.0
        if self.audio:
            try:
                audio_mb = os.path.getsize(self.audio) / MB
            except Exception as e:
                self.warnings.append("音频 %s 取不到体积 (%s), 未计入磁盘预估"
                                     % (self.audio, str(e)[:60]))
        need_mb = (png_mb + out_mb + audio_mb) * DISK_SAFETY
        self.need_detail = ("帧 %d x %.2f MB + 成片 %.1f MB + 音频 %.1f MB, 安全系数 %.1f"
                            % (self.frames, FRAME_PNG_MB, out_mb, audio_mb, DISK_SAFETY))
        return need_mb / 1024.0

    def probe_disk(self):
        path = os.path.abspath(self.out_dir)
        free_bytes = None
        try:
            free_bytes = float(shutil.disk_usage(path).free)
        except Exception as e:
            self.warnings.append("目标盘 %s 剩余空间探测失败 (%s), 无法做磁盘判定"
                                 % (path, str(e)[:60]))
        need_gb = self.estimate_need_gb()
        return {
            "path": path,
            "free_gb": round(free_bytes / GB, 2) if free_bytes is not None else None,
            "need_gb": round(need_gb, 2) if need_gb is not None else None,
        }

    def probe_busy(self):
        """busy 的 python 字段是除本次探测进程自身以外的 python 进程数, 三个计数都只算别人"""
        counts, src = probe_busy()
        self.src["busy"] = src
        if counts is None:
            self.warnings.append("已有进程数探测失败, 不影响限额")
            return {"ffmpeg": None, "ffprobe": None, "python": None, "source": src}
        hit = [(n, counts[n]) for n in PROC_NAMES if counts[n]]
        if hit:
            self.warnings.append(
                "已有其他任务在跑: %s, 可能已有别的渲染或编码在进行"
                % " ".join("%s=%d" % (n, c) for n, c in hit))
        return {"ffmpeg": counts["ffmpeg"], "ffprobe": counts["ffprobe"],
                "python": counts["python"], "source": src}

    def make_limits(self):
        logical = self.cpu["logical"]
        load = self.cpu["load_percent"]
        n = logical if logical else 1
        if not logical:
            self.reasons.append("逻辑核数探测不到, 线程数与进程数一律按 1 核的最保守值算")
        threads = clamp_int(n // THREADS_DIV, THREADS_MIN, THREADS_MAX)
        if load is not None and load > LOAD_BUSY_PERCENT:
            half = max(THREADS_MIN, threads // 2)
            if half < threads:
                self.reasons.append("当前 CPU 负载 %.1f%% 高于 %.0f%%, 编码线程数由 %d 减半到 %d"
                                    % (load, LOAD_BUSY_PERCENT, threads, half))
            else:
                self.reasons.append("当前 CPU 负载 %.1f%% 高于 %.0f%%, 编码线程数已是下限 %d"
                                    % (load, LOAD_BUSY_PERCENT, threads))
            threads = half
        workers = clamp_int(n // THREADS_DIV, WORKERS_MIN, WORKERS_MAX)
        if logical is not None and logical // THREADS_DIV > WORKERS_MAX:
            self.reasons.append("逻辑核数 %d 可以支撑 %d 个并行渲染进程, 按本技能约定封顶到 %d"
                                % (logical, logical // THREADS_DIV, WORKERS_MAX))
        if logical is not None and logical >= SLOW_MIN_LOGICAL and load is not None \
                and load < LOAD_SLOW_PERCENT:
            preset = PRESET_SLOW
        else:
            preset = PRESET_MEDIUM
            if logical is None:
                self.reasons.append("逻辑核数探测不到, preset 取保守的 %s" % PRESET_MEDIUM)
            elif load is None:
                self.reasons.append("当前 CPU 负载探测不到, preset 取保守的 %s" % PRESET_MEDIUM)
            elif logical < SLOW_MIN_LOGICAL:
                self.reasons.append("逻辑核数 %d 少于 %d, preset 取 %s, 免得渲染与编码互相抢 CPU"
                                    % (logical, SLOW_MIN_LOGICAL, PRESET_MEDIUM))
            else:
                self.reasons.append("当前 CPU 负载 %.1f%% 不低于 %.0f%%, preset 取 %s"
                                    % (load, LOAD_SLOW_PERCENT, PRESET_MEDIUM))
        return {"threads": threads, "preset": preset, "priority": PRIORITY, "workers": workers}

    def check_blocked(self):
        free = self.disk["free_gb"]
        need = self.disk["need_gb"]
        if free is not None and need is not None and free < need:
            self.blocked = True
            self.reasons.append("目标盘 %s 只剩 %.2f GB, 低于预估要用的 %.2f GB,"
                                " 先清理磁盘或换 --out-dir" % (self.disk["path"], free, need))
        avail = self.mem["available_gb"]
        if avail is not None and avail < MEM_BLOCKED_GB:
            self.blocked = True
            self.reasons.append("可用内存只剩 %.2f GB, 低于 %.1f GB 的下限,"
                                " 渲染或编码可能被换页拖死" % (avail, MEM_BLOCKED_GB))
        load = self.cpu["load_percent"]
        if load is not None and load > LOAD_BLOCKED_PERCENT:
            self.blocked = True
            self.reasons.append("当前 CPU 负载 %.1f%% 高于 %.0f%%, 机器已经在忙,"
                                " 现在开重活会让整机明显卡顿"
                                % (load, LOAD_BLOCKED_PERCENT))

    @property
    def advice(self):
        """扁平的一组建议, 方便 PowerShell 的 ConvertFrom-Json 直接取用"""
        return {
            "threads": self.limits["threads"],
            "preset": self.limits["preset"],
            "priority": self.limits["priority"],
            "workers": self.limits["workers"],
            "blocked": self.blocked,
            "reasons": self.reasons,
            "warnings": self.warnings,
        }

    def to_dict(self):
        return {
            "scope": self.scope,
            "cpu": self.cpu,
            "mem": self.mem,
            "disk": self.disk,
            "busy": self.busy,
            "hw_encoders": [{"name": n, "vendor": v} for n, v in self.hw],
            "hw_source": self.hw_src,
            "limits": self.limits,
            "blocked": self.blocked,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "advice": self.advice,
        }

    def conclusion(self):
        if self.blocked and self.force:
            return "已按 --force 忽略拦截判定, 可以开工, 但机器卡顿的风险由使用者承担"
        if self.blocked:
            return "不建议现在开重活, 先按上面的原因处理, 确认要继续时加 --force 再跑一次"
        return "资源够用, 可以按上面的限额开工"

    def format_text(self):
        line = "-" * 62
        out = []
        out.append("=" * 62)
        out.append("资源探测与使用限额   本次目标: %s" % self.scope)
        out.append("=" * 62)
        out.append("%-22s %-22s %s" % ("探测项", "取值", "来源"))
        out.append(line)
        rows = [
            ("逻辑核数", fmt_num(self.cpu["logical"], "", 0), self.src.get("logical", "")),
            ("物理核数", fmt_num(self.cpu["physical"], "", 0), self.src.get("physical", "")),
            ("当前 CPU 负载", fmt_num(self.cpu["load_percent"], " %"), self.src.get("load", "")),
            ("内存总量", fmt_num(self.mem["total_gb"], " GB"), self.src.get("mem", "")),
            ("可用内存", fmt_num(self.mem["available_gb"], " GB"), self.src.get("mem", "")),
            ("目标盘可用", fmt_num(self.disk["free_gb"], " GB"), "shutil.disk_usage"),
            ("磁盘预估需要", fmt_num(self.disk["need_gb"], " GB"), self.need_detail or "未预估"),
            ("已有 ffmpeg 进程", fmt_num(self.busy["ffmpeg"], "", 0), ""),
            ("已有 ffprobe 进程", fmt_num(self.busy["ffprobe"], "", 0), ""),
            ("已有 python 进程", fmt_num(self.busy["python"], "", 0), self.src.get("busy", "")),
            ("可用硬件编码器", (", ".join(n for n, _ in self.hw) if self.hw else "无 (走 CPU)"),
             self.hw_src),
        ]
        for name, value, src in rows:
            out.append("%-22s %-22s %s" % (name, value, src))
        out.append(line)
        out.append("编码路线")
        if self.hw:
            out.append("  CPU 路线 (默认)       libx264 -preset %s -crf 18 到 20: 画质与体积的标定口径,"
                       " PSNR 与体积判据都按它取" % self.limits["preset"])
            out.append("  GPU 路线 (可选)       -Encoder %s: 速度优先, 同画质下体积会大几倍"
                       % self.hw[0][0])
            out.append("  换路线之前必须先做    先量 PSNR 定画质底线, 再分离输入解码与滤镜与编码三者的"
                       "开销, 最后才动 preset 与编码器")
            out.append("  原理提醒              x264 是纯 CPU 编码器, CUDA 加速不了它; 用 NVENC 等于"
                       "换一个编码器, 画质会变")
        else:
            out.append("  可用硬件编码器        无, 编码走 CPU 路线 (libx264), 这是本技能的默认与验收口径")
            out.append("  这只影响速度          画面与配乐的能力完全不受影响, 不要为它改工序")
        out.append(line)
        out.append("使用限额建议")
        out.append("  ffmpeg 编码线程数     -threads %d" % self.limits["threads"])
        out.append("  x264 preset           %s" % self.limits["preset"])
        out.append("  进程优先级            %s" % self.limits["priority"])
        out.append("  并行渲染进程数        %d" % self.limits["workers"])
        out.append("  本次目标用到的        %s" % self.scope_hint())
        out.append(line)
        out.append("警告")
        if self.warnings:
            for w in self.warnings:
                out.append("  - %s" % w)
        else:
            out.append("  无")
        out.append(line)
        out.append("结论")
        if self.reasons:
            for r in self.reasons:
                out.append("  原因: %s" % r)
        else:
            out.append("  原因: 无降级, 无拦截")
        out.append("  %s" % self.conclusion())
        out.append("=" * 62)
        return "\n".join(out)

    def scope_hint(self):
        if self.scope == "encode":
            return "编码合成: threads, preset, priority"
        if self.scope == "render":
            return "逐帧渲染: workers"
        return "全量渲染与编码合成: threads, preset, priority, workers"


def suggest_limits(scope="all", frames=None, out_dir=None, audio=None, sample=0.2):
    """便捷入口: 直接拿扁平建议字典, 供其他脚本 import 复用"""
    return ResourceReport(scope=scope, frames=frames, out_dir=out_dir,
                          audio=audio, sample=sample).advice


def suggest_workers():
    """
    便捷入口: 只要并行渲染进程数
    进程数只由逻辑核数决定, 与当前负载无关, 所以这里不查磁盘也不查进程数
    """
    logical, _ = probe_logical()
    return clamp_int((logical or 1) // THREADS_DIV, WORKERS_MIN, WORKERS_MAX)


# ----------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(
        description="资源占用探测与使用限额: 全量渲染与编码合成之前跑一次")
    p.add_argument("--for", dest="scope", choices=("encode", "render", "all"), default="all",
                   help="本次要做的重活类型, 缺省 all")
    p.add_argument("--frames", type=int, default=None,
                   help="帧序列的帧数, 用于磁盘占用预估, 不给就跳过磁盘预估")
    p.add_argument("--out-dir", dest="out_dir", default=None,
                   help="产物目录, 用于查该盘的剩余空间, 缺省当前工作目录")
    p.add_argument("--audio", default=None, help="配乐或混音 WAV 路径, 计入磁盘预估")
    p.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON 的路径")
    p.add_argument("--sample", type=float, default=1.0, help="CPU 负载采样时长秒数, 缺省 1.0")
    p.add_argument("--force", action="store_true",
                   help="忽略 blocked 判定, 只影响退出码与提示, 不改限额值")
    return p


def write_json(path, data):
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("JSON 已写入 %s" % path)
    except Exception as e:
        print("警告: JSON 写入失败 %s (%s)" % (path, str(e)[:80]))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.frames is not None and args.frames < 0:
        parser.error("--frames 不能为负数")
    if args.sample <= 0:
        parser.error("--sample 必须大于 0")
    rep = ResourceReport(scope=args.scope, frames=args.frames, out_dir=args.out_dir,
                         audio=args.audio, sample=args.sample, force=args.force)
    print(rep.format_text())
    if args.json_path:
        write_json(args.json_path, rep.to_dict())
    if rep.blocked and not args.force:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

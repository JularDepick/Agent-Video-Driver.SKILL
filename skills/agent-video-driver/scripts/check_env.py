# -*- coding: utf-8 -*-
"""
环境探测: 视频任务开工前先跑一次

  python scripts/check_env.py
"""
import glob
import os
import shutil
import subprocess
import sys

OK = "[ok]  "
NO = "[miss]"


def run(cmd, args):
    try:
        p = subprocess.run([cmd] + args, capture_output=True, text=True, timeout=25)
        return p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return False, str(e)


def find_browsers():
    """列出可用的浏览器内核: 先查 PATH, 再查 Playwright 的常见安装目录"""
    found = []
    for exe in ("chrome", "msedge", "chromium"):
        path = shutil.which(exe)
        if path:
            found.append((exe, path))
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        pats = (
            ("playwright chromium",
             os.path.join(local, "ms-playwright", "chromium-*", "chrome-win64", "chrome.exe")),
            ("playwright headless_shell",
             os.path.join(local, "ms-playwright", "chromium_headless_shell-*",
                          "chrome-headless-shell-win64", "chrome-headless-shell.exe")),
        )
        for name, pat in pats:
            hits = sorted(glob.glob(pat), reverse=True)
            if hits:
                found.append((name, hits[0]))
    return found


def probe_browser(path):
    """
    做一次带超时的启动测试, 两条输出流都丢弃, 返回 (是否可启动, 原因摘要)

    必须把工作目录与用户数据目录都指向 temp 下的隔离目录: 浏览器启动失败时会往当前目录
    写 debug.log 与崩溃转储, 不隔离就会把项目根目录弄脏. 隔离目录用完即删.
    """
    args = [path, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-crash-reporter", "--disable-breakpad",
            "--dump-dom", "about:blank"]
    sandbox = os.path.abspath(os.path.join("temp", "browser_probe"))
    cwd = None
    try:
        os.makedirs(sandbox, exist_ok=True)
        args.insert(1, "--user-data-dir=%s" % os.path.join(sandbox, "profile"))
        cwd = sandbox
    except Exception:
        cwd = None
    try:
        p = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, cwd=cwd)
    except subprocess.TimeoutExpired:
        return False, "启动超时 15s"
    except Exception as e:
        return False, str(e)[:60]
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    if p.returncode != 0:
        return False, "退出码 0x%08X" % (p.returncode & 0xFFFFFFFF)
    return True, ""


# 实测遇到过的浏览器启动退出码与对应排查路径
# 0xFFFF7001 与 0x80000003 都出现在 Playwright 自带内核上, 都是宿主环境问题, 不是技能的问题
BROWSER_HINTS = {
    "0xFFFF7001": [
        "Playwright 自带 chromium 的常见症状, 按这个顺序查:",
        "  1 缺 VC++ 运行库: 装 Microsoft Visual C++ 2015-2022 Redistributable (x64) 后重试",
        "  2 依赖没装全: python -m playwright install-deps (Linux) 或 python -m playwright install chromium",
        "  3 杀软或企业策略拦了未签名子进程: 换系统自带的 Edge 或 Chrome 试一次, 能起就说明是拦截",
        "  4 用户数据目录不可写: 探测时已经把 --user-data-dir 指到 temp/browser_probe 下了",
    ],
    "0x80000003": [
        "STATUS_BREAKPOINT, headless_shell 被拦或被改写的典型症状, 按这个顺序查:",
        "  1 杀软或 EDR 拦了 headless_shell 这类无窗口进程, 把它的目录加白名单后重试",
        "  2 换 --headless=old 或改用系统自带的 Edge 试一次, 能起就说明是内核文件被拦",
        "  3 确认 Playwright 版本与内核版本配套: python -m playwright install --force chromium",
    ],
}


def browser_hint(why):
    """按退出码取排查清单; 取不到返回空表"""
    for code, lines in BROWSER_HINTS.items():
        if code in why:
            return lines
    return []


def main():
    print("=" * 62)
    print("Agent-Video-Driver 环境探测")
    print("=" * 62)

    for exe in ("ffmpeg", "ffprobe"):
        path = shutil.which(exe)
        if not path:
            print("%s %s 未在 PATH 中, 编码与质检无法进行" % (NO, exe))
            continue
        ok, out = run(exe, ["-hide_banner", "-version"])
        ver = out.splitlines()[0] if out else ""
        print("%s %s  %s" % (OK, exe, ver[:70]))

    ok, out = run("ffmpeg", ["-hide_banner", "-encoders"])
    for enc in ("libx264", "aac", "pcm_s16le"):
        print("%s 编码器 %-12s %s" % (OK if enc in out else NO, enc,
                                      "" if enc in out else "缺失, 需换编码方案"))
    ok, flt = run("ffmpeg", ["-hide_banner", "-filters"])
    for f in ("loudnorm", "noise", "tblend", "signalstats", "ebur128"):
        print("%s 滤镜   %-12s %s" % (OK if f in flt else NO, f,
                                      "" if f in flt else "缺失, 验收或颗粒处理受影响"))

    print("-" * 62)
    print("硬件编码探测")
    # 判断依据一律用 ffmpeg -encoders 的输出: *_nvenc 只要显卡驱动, 不需要单独装 CUDA Toolkit,
    # 所以 CUDA 版本号与 nvcc 都不能作为能不能硬件编码的依据
    hw = [("h264_nvenc", "NVIDIA NVENC"), ("hevc_nvenc", "NVIDIA NVENC"),
          ("av1_nvenc", "NVIDIA NVENC"), ("h264_qsv", "Intel Quick Sync"),
          ("h264_amf", "AMD AMF"), ("h264_vaapi", "VAAPI")]
    hw_found = [(name, vendor) for name, vendor in hw if name in out]
    if hw_found:
        print("%s 可用硬件编码器 %s" % (OK, ", ".join("%s (%s)" % (n, v) for n, v in hw_found)))
        print("    结论: 可以走 GPU 路线, 但换编码器不等于给同一个编码器加开关:")
        print("          x264 是纯 CPU 编码器, CUDA 加速不了它; 用 NVENC 是换成另一个编码器,")
        print("          画质与体积都会变, 换之前先量 PSNR, 并用 scripts/bench_encode.py 对比")
    else:
        print("%s 未检测到硬件编码器, 编码走 CPU 路线 (libx264), 这是默认口径" % NO)
        print("    这不是缺陷: 本技能的验收判据 (PSNR, 体积, 真峰) 都按 CPU 路线标定")
    if shutil.which("nvidia-smi"):
        gok, gout = run("nvidia-smi", ["--query-gpu=name,driver_version,memory.total",
                                       "--format=csv,noheader"])
        if gok and gout.strip():
            for line in gout.strip().splitlines():
                print("%s 显卡 %s" % (OK, line.strip()))
        else:
            print("%s 有 nvidia-smi 但取不到显卡信息" % NO)
    else:
        print("    nvidia-smi 不在 PATH, 跳过显卡信息 (有 NVENC 也只需要显卡驱动)")

    print("-" * 62)
    print("Python %s" % sys.version.split()[0])
    for mod in ("numpy", "PIL"):
        try:
            m = __import__(mod)
            print("%s %-8s %s" % (OK, mod, getattr(m, "__version__", "?")))
        except Exception as e:
            print("%s %-8s %s" % (NO, mod, e))

    print("-" * 62)
    print("渲染能力")
    # 3D 点云只用 numpy, 没有额外依赖; 这里探的是它能不能真的跑起来
    try:
        import numpy as _np
        import three as _th
        fn = _th.knot_tube(tube=0.25, p=3, q=2)
        P, N, _shape = _th.sample(fn, 48, 16)
        cam = _th.Camera(eye=(0, 0.7, 7.0), target=(0, 0, 0), fov=30, w=320, h=180)
        cov, lum, _depth = _th.render(cam, P, N, splat=1)
        _ = _th.visible_grid(cam, P, _depth, N=N)
        _ = _th.min_filter(cov, 1)
        _ = _np.fft.rfft(_np.zeros(64))
        print("%s %-22s 3D 点云可用 (采样, 渲染, 可见性, 邻域最小值, FFT 全部跑通)" % (OK, "three.py"))
    except Exception as e:
        print("%s %-22s %s" % (NO, "three.py", str(e)[:70]))
        print("    影响: 立体段落不可用, 画面只能走 2D 路线; 其余能力不受影响")

    print("-" * 62)
    # 字体探测走 fonts.py: 同一套探测顺序 (环境变量目录, fc-list, 系统字体目录)
    # 覆盖 Windows 与 Linux/macOS, 不再只看 Windows 的固定路径
    try:
        import fonts as _fonts
        found, missing = _fonts.probe()
        for key, _desc, _pats, required in _fonts.WANTED:
            print("%s %-16s %s" % (OK if found.get(key) else NO, key, found.get(key) or "未找到"))
        if missing:
            print("    影响: 缺必需字体的键会在渲染时静默变豆腐块; 用 fonts.py 的探测结果填 FONT_PATH")
    except Exception as e:
        print("%s 字体探测 %s" % (NO, str(e)[:70]))

    print("-" * 62)
    try:
        free = shutil.disk_usage(os.getcwd()).free / 2 ** 30
        need = 0.7
        print("%s 磁盘可用 %.1f GB, 3000 帧 1080p PNG 约需 %.1f GB" % (OK if free > need else NO, free, need))
    except Exception as e:
        print("%s 磁盘信息不可用 %s" % (NO, e))

    print("-" * 62)
    print("沙箱已知限制 (受限模式下必然出现, 不是环境坏了):")
    print("  multiprocessing 的 Pool 会因命名管道被拒 (WinError 5)")
    print("  结论: 并行渲染请按帧区间开多个独立进程, 不要用共享队列")
    print("  PowerShell 的 Wait-Process 对子进程会 Access is denied")
    print("  结论: 用工具自带的后台作业机制管理长任务")

    print("-" * 62)
    print("渲染路线探测")

    # 管道能力决定后续脚本怎么拿子进程的输出
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-version"], capture_output=True)
        got = bool((p.stdout or b"") + (p.stderr or b""))
        if got:
            print("%s 子进程管道捕获 可用, 脚本可以直接读写子进程输出" % OK)
        else:
            print("%s 子进程管道捕获 拿不到输出, 后续脚本要改用写临时文件再读" % NO)
    except Exception as e:
        print("%s 子进程管道捕获 不可用 (%s)" % (NO, str(e)[:60]))
        print("  结论: 后续脚本要改用写临时文件再读的方式, 不要依赖管道")

    browsers = find_browsers()
    if not browsers:
        print("%s 浏览器内核 未找到 chrome / msedge / chromium 与 Playwright 内核" % NO)
    alive = 0
    hints = []
    for name, path in browsers:
        ok, why = probe_browser(path)
        if ok:
            alive += 1
            print("%s %-26s 可启动" % (OK, name))
        else:
            print("%s %-26s 不可启动 (%s)" % (NO, name, why))
            for h in browser_hint(why):
                if h not in hints:
                    hints.append(h)
        print("    %s" % path)

    if alive:
        print("结论: 浏览器渲染路线可用, 但仍建议优先用 Python + Pillow 逐帧路线, 便于逐帧核对")
    else:
        print("结论: 浏览器不可启动, 画面只能走 Python + Pillow 的逐帧渲染路线 (本技能默认路线)")
        print("      浏览器渲染路线在本环境下不可用, 不要按 HTML/CSS/JS 出片去安排工序")
        print("      影响范围: 十阶段流程一步都不受影响, 全程用 Pillow 路线即可交付;")
        print("                只有想走 HTML/CSS 出片这条路时才需要先修好它")
        if hints:
            print("")
            print("排查清单 (按上面实测到的退出码给):")
            for h in hints:
                print("  %s" % h)


if __name__ == "__main__":
    main()

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
    print("Python %s" % sys.version.split()[0])
    for mod in ("numpy", "PIL"):
        try:
            m = __import__(mod)
            print("%s %-8s %s" % (OK, mod, getattr(m, "__version__", "?")))
        except Exception as e:
            print("%s %-8s %s" % (NO, mod, e))

    print("-" * 62)
    fonts = {
        "中文粗体 msyhbd": r"C:\Windows\Fonts\msyhbd.ttc",
        "中文常规 msyh": r"C:\Windows\Fonts\msyh.ttc",
        "等宽粗 consolab": r"C:\Windows\Fonts\consolab.ttf",
        "等宽 consola": r"C:\Windows\Fonts\consola.ttf",
    }
    for name, p in fonts.items():
        print("%s %-16s %s" % (OK if os.path.exists(p) else NO, name, p))

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
    for name, path in browsers:
        ok, why = probe_browser(path)
        if ok:
            alive += 1
            print("%s %-26s 可启动" % (OK, name))
        else:
            print("%s %-26s 不可启动 (%s)" % (NO, name, why))
        print("    %s" % path)

    if alive:
        print("结论: 浏览器渲染路线可用, 但仍建议优先用 Python + Pillow 逐帧路线, 便于逐帧核对")
    else:
        print("结论: 浏览器不可启动, 画面只能走 Python + Pillow 的逐帧渲染路线 (本技能默认路线)")
        print("      浏览器渲染路线在本环境下不可用, 不要按 HTML/CSS/JS 出片去安排工序")


if __name__ == "__main__":
    main()

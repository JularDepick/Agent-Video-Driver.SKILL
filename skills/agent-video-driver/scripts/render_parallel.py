# -*- coding: utf-8 -*-
"""
并行渲染包装器: 读 resources.py 的建议, 用独立子进程各渲各的帧区间, 轮询汇总进度

  python scripts/render_parallel.py --scene scene_module.py
  python scripts/render_parallel.py --scene scene_module.py --workers 3
  python scripts/render_parallel.py --scene scene_module.py --start 810 --end 1620

为什么用 subprocess 而不是 multiprocessing: 受限沙箱拦命名管道, mp.Pool 直接
WinError 5; Popen 子进程各写各的帧文件, 进程间零通信, 不触发这条限制.
等待子进程结束用轮询 + sleep, 不用 os.waitpid 与 Psutil 句柄等待 (同样受限).

帧目录与总帧数以场景模块为准: 本脚本会加载场景模块本身, 取它 configure 之后的
canvas.FRAMES 与 nframes(), 不自己 import 一份缺省值.
进度判定: 各区间的帧目录里数已落盘的帧数, 汇总成整体进度条; 子进程的 stdout 透传
到本进程控制台, 不做管道捕获.
退出码: 全部区间成功返回 0; 任一区间失败返回 1; Ctrl+C 终止全部子进程, 已落盘的帧
保留, 重跑按区间整段重写.
"""
import argparse
import os
import subprocess
import sys
import time

# 与 canvas.FRAME_PATTERN 保持一致; 不 import canvas, 单独复制走也能跑
FRAME_PATTERN = "n%05d.png"
POLL_SEC = 2.0

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def suggest_workers():
    """取 resources.py 的建议进程数, 导入不到退回内置规则 clamp(核数/4, 1, 4)"""
    try:
        import resources  # noqa: F401
        return max(1, int(resources.suggest_workers()))
    except Exception:
        n = os.cpu_count() or 1
        return max(1, min(4, n // 4))


def load_scene_frames(scene_path):
    """
    加载场景模块本身, 取它配置后的 canvas.FRAMES 与 nframes()

    帧目录与总帧数的权威在场景模块: 它在顶部 configure(DUR, FRAMES), 本包装器
    自己 import canvas 只会拿到缺省值, 区间会算错
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_render_scene", scene_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import canvas
    return canvas.FRAMES, canvas.nframes()


def count_in(frames, lo, hi):
    """帧目录里 [lo, hi) 区间已落盘的帧数"""
    n = 0
    for i in range(lo, hi):
        if os.path.exists(os.path.join(frames, FRAME_PATTERN % i)):
            n += 1
    return n


def split_ranges(total, n):
    """[0, total) 均分 n 段, 余数给靠前; 与 scene_module.split_ranges 同口径"""
    n = max(1, min(int(n), max(1, int(total))))
    base, rem = divmod(int(total), n)
    out = []
    a = 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append((a, a + size))
        a += size
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="并行渲染包装器: 独立进程各渲各的区间")
    ap.add_argument("--scene", default="scene_module.py", help="场景模块路径")
    ap.add_argument("--workers", type=int, default=None,
                    help="并行进程数, 缺省取 resources.py 的建议")
    ap.add_argument("--start", type=int, default=None, help="渲染区间起点帧, 缺省 0")
    ap.add_argument("--end", type=int, default=None, help="渲染区间终点帧, 缺省总帧数")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.exists(a.scene):
        print("找不到场景模块: %s" % a.scene)
        return 2

    # 场景模块 import canvas 时才能拿到帧目录与总帧数; 场景模块可能依赖 sys.path 里的 scripts
    scene_dir = os.path.dirname(os.path.abspath(a.scene)) or "."
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (scene_dir, here):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        frames, total = load_scene_frames(os.path.abspath(a.scene))
    except Exception as e:
        print("加载场景模块失败: %s" % e)
        print("先单独跑一次 python %s segments 核对场景模块本身能否执行" % a.scene)
        return 2
    if not frames or total is None or total <= 0:
        print("从场景模块读不到帧目录或总帧数, 先单独跑一次 python %s segments 核对" % a.scene)
        return 2

    lo = a.start if a.start is not None else 0
    hi = a.end if a.end is not None else total
    if not (0 <= lo < hi <= total):
        print("区间不合法: [%s, %s), 总帧数 %d" % (lo, hi, total))
        return 2

    workers = a.workers or suggest_workers()
    ranges = split_ranges(hi - lo, workers)
    print("并行渲染: %d 个进程, 区间 [%d, %d), 共 %d 帧" % (len(ranges), lo, hi, hi - lo))
    print("帧目录: %s" % frames)

    # 场景模块按 "python scene_module.py render <start> <end>" 接收绝对帧号
    procs = []
    for i, (off_a, off_b) in enumerate(ranges):
        ra, rb = lo + off_a, lo + off_b
        cmd = [sys.executable, a.scene, "render", str(ra), str(rb)]
        print("  进程 %d: [%d, %d)  %s" % (i, ra, rb, " ".join(cmd)))
        procs.append((i, ra, rb, subprocess.Popen(cmd)))

    print("提醒: 全量渲染期间场景源码视为冻结, 必须改先停所有进程 (见铁律 22)")
    try:
        while any(p.poll() is None for _, _, _, p in procs):
            done = sum(count_in(frames, ra, rb) for _, ra, rb, _ in procs)
            bar = "#" * int(30 * done / max(1, hi - lo))
            print("\r  [%-30s] %d/%d 帧" % (bar, done, hi - lo), end="", flush=True)
            time.sleep(POLL_SEC)
        print("")
    except KeyboardInterrupt:
        print("\n收到中断: 保留已渲好的帧, 各进程将被终止")
        for _, _, _, p in procs:
            if p.poll() is None:
                p.terminate()
        return 130

    failed = []
    for i, ra, rb, p in procs:
        code = p.returncode
        print("  进程 %d [%d, %d): 退出码 %d" % (i, ra, rb, code))
        if code != 0:
            failed.append(i)
    done = sum(count_in(frames, ra, rb) for _, ra, rb, _ in procs)
    print("完成: 区间内已落盘 %d / %d 帧" % (done, hi - lo))
    if failed:
        print("失败区间: %s; 用 python %s plan 拿到逐区间命令单独重跑"
              % (failed, a.scene))
        return 1
    print("全部区间成功, 下一步: 逐屏终检 (qa.py 帧序列模式)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
分批合成的前端进度条: 只读轮询状态文件, 不启动也不停止后端

  python scripts/assemble_progress.py                读一次就退出
  python scripts/assemble_progress.py --watch        每 2 秒刷一次, Ctrl+C 只退出本前端
  python scripts/assemble_progress.py --interval 5   改刷新间隔秒数

配套的后端是 scripts/assemble_core.py. 启停权在用户手里: 本脚本只读状态文件, 既不拉起后端,
也不去杀后端进程; 要停下后端请在它自己的窗口按一次 Ctrl+C, 它会写 interrupted 并保留断点.

一条必须守住的实现纪律: 判断后端进程是否存活绝对不能用 os.kill(pid, 0).
Windows 上 os.kill 只支持 CTRL_C_EVENT 与 CTRL_BREAK_EVENT, 其他值一律走 TerminateProcess,
也就是前端一查就把后端杀掉; 这里在 Windows 上用 ctypes 的 OpenProcess 加 GetExitCodeProcess
只读查询, 只有非 Windows 平台才退回 os.kill.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE = os.path.join(HERE, "assemble_state.json")
STILL_ACTIVE = 259
BAR = 40

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def process_alive(pid):
    """只读查询进程是否还在跑; Windows 走 ctypes, 其余平台才用 os.kill 的 0 号信号"""
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def read_state(path):
    """状态文件是原子写的, 但轮询仍可能撞上极短的写入窗口, 读失败就返回 None"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def human(seconds):
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "%.0f 秒" % seconds
    if seconds < 3600:
        return "%.1f 分" % (seconds / 60.0)
    return "%.2f 时" % (seconds / 3600.0)


def bar(done, total, width=BAR):
    if total <= 0:
        return "[" + "-" * width + "]"
    filled = int(round(width * min(1.0, done / float(total))))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def summarize(state):
    """从状态文件算进度, 已用与预计剩余; 只依据状态文件里的实测值, 不做估计

    running 批必须有 t0 才累计耗时; 没有 t0 (上一次运行被硬杀的残留状态) 时按 0 处理,
    宁可 ETA 偏保守也不把"从上次启动到现在"当成这批的耗时
    """
    cfg = state.get("config") or {}
    total = int(cfg.get("total_frames") or 0)
    batches = state.get("batches") or []
    done = 0
    spent = 0.0
    for b in batches:
        if b.get("status") == "done":
            done += int(b.get("end", 0)) - int(b.get("start", 0))
            spent += float(b.get("seconds") or 0.0)
        elif b.get("status") == "running":
            done += int(b.get("frames_done") or 0)
            if b.get("t0"):
                spent += max(0.0, time.time() - float(b["t0"]))
    rate = (done / spent) if (done > 0 and spent > 0) else 0.0
    eta = ((total - done) / rate) if rate > 0 else None
    return total, done, spent, rate, eta


def draw(state, state_path, alive_text):
    total, done, spent, rate, eta = summarize(state)
    cfg = state.get("config") or {}
    print("=" * 62)
    print("分批合成进度   %s" % state_path)
    print("  阶段          %s" % state.get("stage", "?"))
    print("  后端进程      %s" % alive_text)
    if state.get("note"):
        print("  当前          %s" % state["note"])
    if total:
        print("  帧            %d / %d   %s  %5.1f%%"
              % (done, total, bar(done, total), 100.0 * done / total))
    else:
        print("  帧            %d" % done)
    print("  已用 (编码)   %s" % human(spent))
    if rate > 0:
        print("  速率          %.1f 帧每秒" % rate)
    if eta is not None:
        print("  预计剩余      %s" % human(eta))
    if state.get("speed"):
        print("  ffmpeg 速度   %s" % state["speed"])
    batches = state.get("batches") or []
    if batches:
        # running 且无 t0 = 上次运行被硬杀的残留状态, 标出来提醒它的耗时不可信
        stale = [b.get("index", 0) for b in batches
                 if b.get("status") == "running" and not b.get("t0")]
        if stale:
            print("  注意          批 %s 标记 running 但没有计时起点 (上次运行被中断的残留), "
                  "其耗时未计入已用" % stale)
        print("  批次表 (起止帧, 状态, 耗时, 体积):")
        for b in batches:
            size = float(b.get("bytes") or 0) / 1048576.0
            print("    批 %02d  %6d 到 %-6d  %-8s  %8.1f 秒  %7.1f MB"
                  % (b.get("index", 0), b.get("start", 0), b.get("end", 0),
                     b.get("status", "?"), float(b.get("seconds") or 0.0), size))
    if state.get("error"):
        print("  错误          %s" % state["error"])
    print("  提醒          本前端只读; 要停后端请在它的窗口按一次 Ctrl+C, 断点会保留")
    print("=" * 62)


def main(argv=None):
    ap = argparse.ArgumentParser(description="分批合成进度前端, 只读轮询状态文件")
    ap.add_argument("--state", default=None, help="状态文件路径, 缺省取脚本同目录")
    ap.add_argument("--watch", action="store_true", help="持续刷新, 直到状态变成完成或中断")
    ap.add_argument("--interval", type=float, default=2.0, help="刷新间隔秒数, 缺省 2")
    a = ap.parse_args(argv)
    path = os.path.abspath(a.state) if a.state else DEFAULT_STATE

    if not a.watch:
        state = read_state(path)
        if state is None:
            print("读不到状态文件: %s" % path)
            print("先跑一次后端: python scripts/assemble_core.py --frames <帧目录> --out <成片>")
            return 2
        alive = "在跑 (pid %s)" % state.get("pid") if process_alive(state.get("pid")) \
            else "已结束 (pid %s)" % state.get("pid")
        draw(state, path, alive)
        return 0

    print("开始轮询 %s, 每 %s 秒一次; 本前端只读, Ctrl+C 只退出前端" % (path, a.interval))
    last = None
    while True:
        state = read_state(path)
        if state is None:
            print("等待状态文件出现: %s" % path)
        else:
            alive = process_alive(state.get("pid"))
            stage = state.get("stage", "?")
            text = "在跑 (pid %s)" % state.get("pid") if alive else "已结束 (pid %s)" % state.get("pid")
            if last is not None:
                print()
            draw(state, path, text)
            last = state
            if stage in ("done", "failed", "interrupted", "blocked", "waiting") and not alive:
                print("阶段 %s 且后端已结束, 停止轮询" % stage)
                return 0 if stage == "done" else 3
        try:
            time.sleep(max(0.5, float(a.interval)))
        except KeyboardInterrupt:
            print()
            print("已退出前端; 后端仍在跑的话请到它的窗口按 Ctrl+C")
            return 0


if __name__ == "__main__":
    sys.exit(main())

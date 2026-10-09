# -*- coding: utf-8 -*-
"""
字体探测: 找到本机可用的中文字体与等宽字体, 生成 canvas.configure 的 FONT_PATH

  python scripts/fonts.py                       # 打印探测结果与可用字体键
  python scripts/fonts.py --json temp/fonts.json
  python scripts/fonts.py --script              # 打印可直接粘贴的 configure 片段

探测顺序: 环境变量 FVD_FONT_DIR 指定的目录 -> fc-list (有 fontconfig 的系统) ->
Windows 常见字体目录 -> Linux/macOS 常见目录. 每个字体键取第一个找到的; 全部
找不到时报告缺哪些, 不猜路径. 用户的场景模块应当把探测结果写进 FONT_PATH,
不要硬编码任何一个操作系统的路径.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

# 键 -> (用途说明, 候选文件名模式, 是否必需)
WANTED = [
    ("cnb", "中文粗体 (标题与主句)", ("msyhbd.ttc", "msyh-bold.ttc",
                                     "NotoSansCJK-Bold.ttc", "NotoSansSC-Bold.otf",
                                     "wqy-microhei.ttc", "PingFangSC-Semibold.otf"), True),
    ("cn", "中文常规 (正文)", ("msyh.ttc", "msyh-regular.ttc",
                               "NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.otf",
                               "wqy-microhei.ttc", "PingFangSC-Regular.otf"), True),
    ("mono", "等宽粗体 (读数与标签)", ("consolab.ttf", "Consola-Bold.ttf",
                                       "NotoSansMono-Bold.ttf", "Menlo-Bold.ttf",
                                       "DejaVuSansMono-Bold.ttf"), False),
    ("monor", "等宽常规", ("consola.ttf", "Consola.ttf",
                            "NotoSansMono-Regular.ttf", "Menlo-Regular.ttf",
                            "DejaVuSansMono.ttf"), False),
]

WIN_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
NIX_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
            os.path.expanduser("~/.local/share/fonts"),
            "/Library/Fonts", "/System/Library/Fonts"]


def search_dirs():
    """候选目录: 环境变量优先, 然后按系统; 不存在的不列"""
    dirs = []
    extra = os.environ.get("FVD_FONT_DIR")
    if extra and os.path.isdir(extra):
        dirs.append(extra)
    if os.name == "nt":
        dirs.extend(WIN_DIRS)
    else:
        dirs.extend(NIX_DIRS)
    return [d for d in dirs if os.path.isdir(d)]


def fc_list_map():
    """fc-list 输出 {小写文件名: 路径}; 没有 fontconfig 时返回空表"""
    exe = shutil.which("fc-list")
    if not exe:
        return {}
    try:
        p = subprocess.run([exe, "-f", "%{file}\n"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=15)
        out = (p.stdout or "").split()
        return {os.path.basename(x).lower(): x for x in out if x.strip()}
    except Exception:
        return {}


def probe():
    """返回 {键: 路径或 None}, 以及未找到的必需键清单"""
    dirs = search_dirs()
    by_name = {}
    for d in dirs:
        # 单层就够: Windows 字体目录是平的, Noto 在子目录里时靠 fc-list 兜底
        for p in glob.glob(os.path.join(d, "*")):
            if os.path.isfile(p):
                by_name.setdefault(os.path.basename(p).lower(), p)
    for d in dirs:
        for p in glob.glob(os.path.join(d, "**", "*"), recursive=True):
            if os.path.isfile(p):
                by_name.setdefault(os.path.basename(p).lower(), p)
    by_name.update(fc_list_map())

    found = {}
    missing_required = []
    for key, _desc, pats, required in WANTED:
        hit = None
        for pat in pats:
            hit = by_name.get(pat.lower())
            if hit:
                break
        found[key] = hit
        if required and hit is None:
            missing_required.append(key)
    return found, missing_required


def main(argv=None):
    args = sys.argv[1:] if argv is not None else argv
    found, missing = probe()
    print("字体探测:")
    for key, desc, _pats, required in WANTED:
        p = found[key]
        tag = "" if p else ("  [必需]" if required else "  [可选]")
        print("  %-6s %-18s %s%s" % (key, desc, p or "未找到", tag))
    if args and args[0] == "--script":
        print("")
        print("FONT_PATH 片段 (粘进场景模块, 或作为 configure 的实参):")
        print("FONT_PATH = {")
        for key in found:
            if found[key]:
                print('    "%s": r"%s",' % (key, found[key]))
        print("}")
    if args and args[0] == "--json":
        dst = args[1] if len(args) > 1 else os.path.join("temp", "fonts.json")
        parent = os.path.dirname(os.path.abspath(dst))
        os.makedirs(parent, exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            json.dump({"fonts": found, "missing_required": missing}, f,
                      ensure_ascii=False, indent=2)
        print("wrote %s" % dst)
    if missing:
        print("缺少必需字体: %s" % ", ".join(missing))
        print("把字体所在目录写进环境变量 FVD_FONT_DIR 可让探测找到它; Linux 可装 fonts-noto-cjk")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

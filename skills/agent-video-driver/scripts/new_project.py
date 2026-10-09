# -*- coding: utf-8 -*-
"""
起一个新的视频工程: 建目录结构, 把技能脚本复制成自包含副本, 生成四份骨架

手工照抄 templates 容易漏文件, 也容易把顶部常量改错一处; 这个脚本把这几步一次做完,
并把 BPM, 时长, 帧率, 帧目录前缀写进复制出来的场景模块顶部.

  python scripts/new_project.py ..\\my-video --bpm 100 --dur 108 --prefix nobel
  python scripts/new_project.py ..\\my-video --bpm 120 --dur 30 --prefix teaser --style neon-hud

纪律:
  只读技能目录, 只写用户指定的项目目录, 不改技能里的模板真源
  目标目录非空时拒绝开工, 要覆盖必须显式加 --force
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
TEMPLATES = os.path.join(SKILL, "templates")

CREDITS_SKELETON = """# 外部素材署名与许可

采用任何外部素材时填这张表, 字段固定六项. 片内是否出现署名行由用户决定,
但这份文件无论片内是否署名都要写, 它是发布说明的依据. 判定顺序见技能里的
`references/content-and-rights.md`.

| 标题 | 类型 | 来源页链接 | 作者 | 许可 | 是否修改过 |
|:---:|:---:|:---:|:---:|:---:|:---:|
|  |  |  |  |  |  |

## 未采用的候选素材

| 素材 | 未采用的原因 |
|:---:|:---|
|  |  |
"""


def patch_scene_module(text, bpm, dur, fps, prefix):
    """
    改写复制出来的场景模块顶部常量

    每一处替换都要命中, 命中不了就直接报错: 模板改了名字而这里没跟着改,
    静默产出一个 BPM 不对的工程比报错难查得多.
    """
    subs = [
        (r"(?m)^BPM = .*$", "BPM = %s" % bpm, "BPM 常量"),
        (r"(?m)^DUR = .*$", "DUR = %s" % dur, "DUR 常量"),
        (r'FRAMES=os\.path\.join\("temp", "[^"]*"\)',
         'FRAMES=os.path.join("temp", "frames_%s")' % prefix, "FRAMES 前缀"),
    ]
    for pat, rep, name in subs:
        text, n = re.subn(pat, rep, text, count=1)
        if n != 1:
            raise RuntimeError("模板里找不到 %s, 先确认 templates/scene_module.py 是否改过" % name)

    bar = 4 * 60.0 / float(bpm)
    bars = max(1, int(round(float(dur) / bar)))
    # 演示段数不能超过实际小节数: 5 秒的片子只有 2 小节, 硬凑三段会让段表越过片长,
    # 于是末段倒着走, 渲染出来是空段或截断段
    n_seg = max(1, min(3, bars))
    ks = sorted({min(bars, int(round(bars * i / float(n_seg)))) for i in range(n_seg + 1)})
    ks = [k for i, k in enumerate(ks) if i == 0 or k > ks[i - 1]]
    if ks[0] != 0:
        ks.insert(0, 0)
    if ks[-1] != bars:
        ks.append(bars)
    seg = [round(min(float(dur), k * bar), 3) for k in ks[:-1]] + [round(float(dur), 3)]
    if not all(seg[i + 1] > seg[i] for i in range(len(seg) - 1)):
        raise RuntimeError("按 %.1f 秒与 %.1f BPM 推不出可用的演示段边界: %s" % (dur, bpm, seg))

    seg_text = "[%s]" % ", ".join("%.3f" % v for v in seg)
    text, n = re.subn(r"(?m)^SEG = \[k \* BAR for k in \([^)]*\)\]$",
                      "SEG = %s" % seg_text, text, count=1)
    if n != 1:
        raise RuntimeError("模板里找不到 SEG 常量, 先确认 templates/scene_module.py 是否改过")
    text, n = re.subn(r"(?m)^SEG_OF_DEMO = \[.*\]$",
                      "SEG_OF_DEMO = %s" % seg_text, text, count=1)
    if n != 1:
        raise RuntimeError("模板里找不到 SEG_OF_DEMO 常量, 先确认 templates/scene_module.py 是否改过")
    text, n = re.subn(r"(?m)^SCENES = \[.*\]$",
                      "SCENES = [%s]" % ", ".join(["s_title", "s_chart", "s_chart"][:n_seg]),
                      text, count=1)
    if n != 1:
        raise RuntimeError("模板里找不到 SCENES 常量, 先确认 templates/scene_module.py 是否改过")

    # 帧率与画布也在顶部一次定下来, 免得后面靠默认值猜
    pat = r'cv\.configure\(BPM=BPM, DUR=DUR, FRAMES=os\.path\.join\("temp", "[^"]*"\)\)'
    rep = ("cv.configure(BPM=BPM, DUR=DUR, FPS=%d, "
           "FRAMES=os.path.join(\"temp\", \"frames_%s\"))" % (fps, prefix))
    text, n = re.subn(pat, rep, text, count=1)
    if n != 1:
        raise RuntimeError("模板里找不到 cv.configure 那一行, 先确认 templates/scene_module.py 是否改过")
    return text, bars, n_seg


def copy_scripts(dst):
    os.makedirs(dst, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(SCRIPTS)):
        src = os.path.join(SCRIPTS, name)
        if not os.path.isfile(src):
            continue
        if name.endswith(".pyc"):
            continue
        # copy2 是二进制复制, 于是 assemble.ps1 的 UTF-8 BOM 原样带过去
        shutil.copy2(src, os.path.join(dst, name))
        n += 1
    return n


def write_style(project, style_id, seed, tone=None):
    """有 style_lottery.py 就让它把牌面落到项目里, 没有就只留一句提示"""
    lot = os.path.join(SCRIPTS, "style_lottery.py")
    if not os.path.exists(lot):
        print("提示: 还没有 style_lottery.py, 风格牌面需要自己从 references/styles.md 选")
        return
    cmd = [sys.executable, lot, "--write", project]
    if style_id:
        cmd += ["--style", style_id]
    if tone:
        cmd += ["--tone", tone]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    import subprocess
    # 必须显式给 encoding: Windows 上 text=True 会按系统代码页(GBK)解码子进程输出,
    # 而抽签脚本打印的是 UTF-8 中文, 读线程会直接抛 UnicodeDecodeError
    p = subprocess.run(cmd, cwd=project, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("提示: 抽风格没成功 (%s)" % ((p.stderr or p.stdout or "").strip()[:120]))
    elif (p.stdout or "").strip():
        print(p.stdout.strip())


def main():
    ap = argparse.ArgumentParser(description="起一个新的视频工程, 复制技能脚本并生成骨架")
    ap.add_argument("project", help="项目目录, 不存在就新建")
    ap.add_argument("--bpm", type=float, default=100.0, help="配乐 BPM, 缺省 100")
    ap.add_argument("--dur", type=float, default=108.0, help="片长秒数, 缺省 108")
    ap.add_argument("--fps", type=int, default=30, help="帧率, 缺省 30")
    ap.add_argument("--prefix", default=None, help="帧目录前缀, 缺省取项目目录名的小写")
    ap.add_argument("--style", default=None, help="风格牌 id, 交给 style_lottery.py 落成 STYLE.md")
    ap.add_argument("--tone", choices=("loud", "steady", "light"), default=None,
                    help="只在某一档里抽风格牌: loud 响 / steady 稳 / light 轻")
    ap.add_argument("--seed", type=int, default=None, help="抽风格的随机种子, 便于复现")
    ap.add_argument("--force", action="store_true", help="目标目录非空时也继续")
    a = ap.parse_args()

    if a.bpm <= 0 or a.dur <= 0 or a.fps <= 0:
        print("--bpm / --dur / --fps 都要大于 0")
        return 2
    if not os.path.isdir(SCRIPTS) or not os.path.isdir(TEMPLATES):
        print("找不到技能内的 scripts/ 或 templates/, 本脚本要在技能目录里运行")
        return 2

    project = os.path.abspath(a.project)
    if os.path.exists(project) and os.listdir(project) and not a.force:
        print("目标目录非空: %s" % project)
        print("换一个目录, 或显式加 --force 覆盖(已存在的同名文件会被替换)")
        return 2

    prefix = a.prefix or re.sub(r"[^0-9a-zA-Z_]+", "_", os.path.basename(project)).strip("_").lower()
    if not prefix:
        print("推不出帧目录前缀, 请用 --prefix 指定")
        return 2

    for d in ("prompts", "temp", "audio", "out", "scripts"):
        os.makedirs(os.path.join(project, d), exist_ok=True)

    n = copy_scripts(os.path.join(project, "scripts"))
    print("复制脚本 %d 个 -> scripts/" % n)

    src = os.path.join(TEMPLATES, "scene_module.py")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    try:
        text, bars, n_seg = patch_scene_module(text, a.bpm, a.dur, a.fps, prefix)
    except RuntimeError as e:
        print(str(e))
        return 2
    with open(os.path.join(project, "scene_module.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("scene_module.py: BPM %s, 时长 %s 秒, %d fps, %d 小节, %d 个演示段, 帧目录 temp/frames_%s"
          % (a.bpm, a.dur, a.fps, bars, n_seg, prefix))

    pairs = [
        ("brief.md", os.path.join("prompts", "brief.md")),
        ("stage-prompt.md", os.path.join("prompts", "stage-prompt.md")),
        ("screen-script.md", "script.md"),
        ("storyboard.md", "storyboard.md"),
    ]
    for src_name, dst_rel in pairs:
        s = os.path.join(TEMPLATES, src_name)
        if not os.path.exists(s):
            print("提示: 模板缺 %s, 已跳过" % src_name)
            continue
        shutil.copy2(s, os.path.join(project, dst_rel))
    with open(os.path.join(project, "credits.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(CREDITS_SKELETON)
    print("骨架: prompts/brief.md, prompts/stage-prompt.md, script.md, storyboard.md, credits.md")

    write_style(project, a.style, a.seed, a.tone)

    print("-" * 62)
    print("工程已建好: %s" % project)
    print("接下来按这个顺序走:")
    print("  1 填 prompts/brief.md 与 prompts/stage-prompt.md")
    print("  2 写 script.md, 再跑 python scripts/timing.py script.md --bpm %s --bars %d" % (a.bpm, bars))
    print("  3 填 storyboard.md, 过启动确认门")
    print("  4 python scripts/orchestra.py %s %s score.wav \"<切点>\" audio" % (a.dur, a.bpm))
    print("  5 改 scene_module.py 的分镜, 用 python scene_module.py at 0:1.5 逐场审阅")
    print("  6 python scene_module.py segments 核对段数, 再走合成确认门")
    return 0


if __name__ == "__main__":
    sys.exit(main())

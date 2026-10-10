# -*- coding: utf-8 -*-
"""
起一个新的视频工程: 建目录结构, 把技能脚本复制成自包含副本, 生成四份骨架

手工照抄 templates 容易漏文件, 也容易把顶部常量改错一处; 这个脚本把这几步一次做完,
并把 BPM, 时长, 帧率, 画幅, 帧目录前缀写进工程根的 theme.py (唯一配置源),
场景模块顶部的同名回退常量也写同一批值, 于是删掉 theme.py 后工程仍与命令行一致.

  python scripts/new_project.py ..\\my-video --bpm 100 --dur 108 --prefix nobel
  python scripts/new_project.py ..\\my-video --bpm 120 --dur 30 --prefix teaser --style neon-hud

纪律:
  只读技能目录, 只写用户指定的项目目录, 不改技能里的模板真源
  目标目录非空时拒绝开工, 要覆盖必须显式加 --force

画幅: --aspect 16:9 (缺省, 1920x1080) / 9:16 (1080x1920) / 1:1 (1080x1080),
或 --width 与 --height 给自定义偶数宽高; 不给时取模板缺省 1920x1080
"""
import argparse
import os
import random
import re
import shutil
import sys

# Windows 的中文控制台默认是 GBK: 遇到打不出来的字符 (例如子进程输出里被替换成的 U+FFFD)
# print 会直接抛 UnicodeEncodeError 把起工程这一步中断, 所以先把输出流的编码错误降级
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

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


def resolve_aspect(args):
    """
    把 --aspect / --width / --height 解析成 (W, H)

    返回 None 表示未给画幅参数, 用模板缺省; 返回 False 表示参数非法, 调用方退出.
    --aspect 支持三档预设; --width 与 --height 是自定义宽高, 必须是偶数
    (编码器要求偶数尺寸), 两者要么都给要么都不给; 与 --aspect 同时给时拒绝
    """
    if args.aspect and (args.width or args.height):
        print("--aspect 与 --width/--height 不要同时给")
        return False
    if args.aspect:
        presets = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
        if args.aspect not in presets:
            print("--aspect 只支持 %s, 收到 %r" % (", ".join(presets), args.aspect))
            return False
        return presets[args.aspect]
    if bool(args.width) != bool(args.height):
        print("--width 与 --height 要么都给要么都不给")
        return False
    if args.width:
        if args.width <= 0 or args.height <= 0:
            print("--width 与 --height 都要大于 0")
            return False
        if args.width % 2 or args.height % 2:
            print("--width 与 --height 都必须是偶数 (编码器要求)")
            return False
        return (args.width, args.height)
    return None


def seg_tables(bpm, dur):
    """
    按 BPM 与片长推出整小节数与演示段边界

    返回 (整小节数, 演示段数, 段边界字面量); 段数不能超过实际小节数:
    5 秒的片子只有 2 小节, 硬凑三段会让段表越过片长, 于是末段倒着走,
    渲染出来是空段或截断段
    """
    bar = 4 * 60.0 / float(bpm)
    bars = max(1, int(round(float(dur) / bar)))
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
    return bars, n_seg, "[%s]" % ", ".join("%.3f" % v for v in seg)


def patch_input_constants(text, bpm, dur, fps, prefix, wh=None, what="templates/scene_module.py"):
    """
    改写 input 常量: BPM, DUR, FPS, 帧目录前缀, 画幅

    theme.py 与场景模块的回退常量同名同写法, 所以两处共用这一段
    每一处替换都要命中, 命中不了就直接报错: 模板改了名字而这里没跟着改,
    静默产出一个 BPM 不对的工程比报错难查得多
    """
    subs = [
        (r"(?m)^BPM = .*$", "BPM = %s" % bpm, "BPM 常量"),
        (r"(?m)^DUR = .*$", "DUR = %s" % dur, "DUR 常量"),
        (r"(?m)^FPS = .*$", "FPS = %d" % fps, "FPS 常量"),
        (r"(?m)^FRAME_PREFIX = .*$", 'FRAME_PREFIX = "%s"' % prefix, "FRAME_PREFIX 常量"),
    ]
    if wh is not None:
        subs.append((r"(?m)^W, H = .*$", "W, H = %d, %d" % wh, "画幅常量"))
    for pat, rep, name in subs:
        text, n = re.subn(pat, rep, text, count=1)
        if n != 1:
            raise RuntimeError("模板里找不到 %s, 先确认 %s 是否改过" % (name, what))
    return text


def patch_seg_tables(text, seg_text, n_seg, what):
    """
    改写段落表三处: SEG, SEG_OF_DEMO, SCREEN_COUNT

    新工程的每一幕按一屏起步, 幕内确实有多屏时由写场景的人改这个表, 或让 plan.json 接管
    """
    subs = [
        (r"(?m)^SEG = \[k \* BAR for k in \([^)]*\)\]$", "SEG = %s" % seg_text, "SEG 常量"),
        (r"(?m)^SEG_OF_DEMO = \[.*\]$", "SEG_OF_DEMO = %s" % seg_text, "SEG_OF_DEMO 常量"),
        (r"(?m)^SCREEN_COUNT = \[.*\]$",
         "SCREEN_COUNT = [%s]" % ", ".join(["1"] * max(1, n_seg)), "SCREEN_COUNT 常量"),
    ]
    for pat, rep, name in subs:
        text, n = re.subn(pat, rep, text, count=1)
        if n != 1:
            raise RuntimeError("模板里找不到 %s, 先确认 %s 是否改过" % (name, what))
    return text


def patch_theme(text, bpm, dur, fps, prefix, wh=None):
    """
    改写 theme.py: 生成工程后它是唯一要改的配置处

    只写输入常量与段落表, BEAT, BAR, BARS, NFRAMES 这些派生量留在文件里自己算
    """
    text = patch_input_constants(text, bpm, dur, fps, prefix, wh, "templates/theme.py")
    bars, n_seg, seg_text = seg_tables(bpm, dur)
    text = patch_seg_tables(text, seg_text, n_seg, "templates/theme.py")
    return text, bars, n_seg


def patch_scene_module(text, bpm, dur, fps, prefix, wh=None):
    """
    改写复制出来的场景模块顶部的回退常量

    theme.py 才是唯一配置源, 这批常量只在没有 theme.py 时生效; 两处写同一批值,
    于是删掉 theme.py 后工程仍与命令行一致
    """
    text = patch_input_constants(text, bpm, dur, fps, prefix, wh)
    bars, n_seg, seg_text = seg_tables(bpm, dur)
    text = patch_seg_tables(text, seg_text, n_seg, "templates/scene_module.py")
    text, n = re.subn(r"(?m)^SCENES = \[.*\]$",
                      "SCENES = [%s]" % ", ".join(["s_title", "s_chart", "s_chart"][:n_seg]),
                      text, count=1)
    if n != 1:
        raise RuntimeError("模板里找不到 SCENES 常量, 先确认 templates/scene_module.py 是否改过")
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
    """
    有 style_lottery.py 就让它把牌面落到项目里, 没有就只留一句提示

    种子一定传下去: 不给时这里自己生成一个. 不传种子时 style_lottery 会用随机种子,
    抽出来的牌无法复现, 而技能对外承诺的是"抽一张, 可复现"; 生成的种子会被
    style_lottery 写进 STYLE.md 或 STYLE_candidates.md 的头部, 于是随机与可复现兼得
    """
    lot = os.path.join(SCRIPTS, "style_lottery.py")
    if not os.path.exists(lot):
        print("提示: 还没有 style_lottery.py, 风格牌面需要自己从 references/styles.md 选")
        return None
    if seed is None:
        seed = random.randrange(1, 100000000)
        print("抽签种子: %s (没给 --seed, 已自动生成; 牌面文件头部会记下它, 便于复现)" % seed)
    cmd = [sys.executable, lot, "--write", project]
    if style_id:
        cmd += ["--style", style_id]
    if tone:
        cmd += ["--tone", tone]
    cmd += ["--seed", str(seed)]
    import subprocess
    # 必须显式给 encoding: Windows 上 text=True 会按系统代码页(GBK)解码子进程输出,
    # 而抽签脚本打印的是 UTF-8 中文, 读线程会直接抛 UnicodeDecodeError
    # 子进程那一侧也要强制 UTF-8 输出: 只指定解码方式而不管编码方式, 在 GBK 控制台下
    # 拿到的是被替换过的 U+FFFD, 再打回控制台就会抛 UnicodeEncodeError 中断起工程
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, cwd=project, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        print("提示: 抽风格没成功 (%s)" % ((p.stderr or p.stdout or "").strip()[:120]))
    elif (p.stdout or "").strip():
        print(p.stdout.strip())
    return seed


def main():
    ap = argparse.ArgumentParser(description="起一个新的视频工程, 复制技能脚本并生成骨架")
    ap.add_argument("project", help="项目目录, 不存在就新建")
    ap.add_argument("--bpm", type=float, default=100.0, help="配乐 BPM, 缺省 100")
    ap.add_argument("--dur", type=float, default=108.0, help="片长秒数, 缺省 108")
    ap.add_argument("--fps", type=int, default=30, help="帧率, 缺省 30")
    ap.add_argument("--aspect", default=None,
                    help="画幅预设: 16:9 (缺省) / 9:16 / 1:1; 与 --width/--height 二选一")
    ap.add_argument("--width", type=int, default=None, help="自定义画幅宽, 偶数, 与 --height 成对")
    ap.add_argument("--height", type=int, default=None, help="自定义画幅高, 偶数, 与 --width 成对")
    ap.add_argument("--prefix", default=None, help="帧目录前缀, 缺省取项目目录名的小写")
    ap.add_argument("--style", default=None, help="风格牌 id, 交给 style_lottery.py 落成 STYLE.md")
    ap.add_argument("--tone", choices=("loud", "steady", "light"), default=None,
                    help="只在某一档里抽风格牌: loud 响 / steady 稳 / light 轻")
    ap.add_argument("--seed", type=int, default=None,
                    help="抽风格的随机种子; 不给时自动生成一个并记进牌面文件头部, 保证可复现")
    ap.add_argument("--force", action="store_true", help="目标目录非空时也继续")
    a = ap.parse_args()

    if a.bpm <= 0 or a.dur <= 0 or a.fps <= 0:
        print("--bpm / --dur / --fps 都要大于 0")
        return 2
    wh = resolve_aspect(a)
    if wh is False:
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

    # theme.py 是唯一配置源, 先落它: BPM 与片长从这里进工程
    theme_src = os.path.join(TEMPLATES, "theme.py")
    if os.path.exists(theme_src):
        with open(theme_src, encoding="utf-8") as f:
            theme_text = f.read()
        try:
            theme_text, bars, n_seg = patch_theme(theme_text, a.bpm, a.dur, a.fps, prefix, wh)
        except RuntimeError as e:
            print(str(e))
            return 2
        with open(os.path.join(project, "theme.py"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(theme_text)
        if wh is not None:
            print("theme.py: 唯一要改的配置处, 写入 BPM %s, 时长 %s 秒, %d fps, 画幅 %dx%d, "
                  "帧目录前缀 %s" % (a.bpm, a.dur, a.fps, wh[0], wh[1], prefix))
        else:
            print("theme.py: 唯一要改的配置处, 写入 BPM %s, 时长 %s 秒, %d fps, "
                  "画幅取模板缺省 1920x1080, 帧目录前缀 %s" % (a.bpm, a.dur, a.fps, prefix))
    else:
        print("提示: 模板缺 theme.py, 已跳过(配置只能改 scene_module.py 顶部的常量)")

    src = os.path.join(TEMPLATES, "scene_module.py")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    try:
        text, bars, n_seg = patch_scene_module(text, a.bpm, a.dur, a.fps, prefix, wh)
    except RuntimeError as e:
        print(str(e))
        return 2
    with open(os.path.join(project, "scene_module.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if wh is not None:
        print("scene_module.py: BPM %s, 时长 %s 秒, %d fps, 画幅 %dx%d, %d 小节, %d 个演示段, 帧目录 temp/frames_%s"
              % (a.bpm, a.dur, a.fps, wh[0], wh[1], bars, n_seg, prefix))
    else:
        print("scene_module.py: BPM %s, 时长 %s 秒, %d fps, 画幅取模板缺省 1920x1080, %d 小节, %d 个演示段, 帧目录 temp/frames_%s"
              % (a.bpm, a.dur, a.fps, bars, n_seg, prefix))

    pairs = [
        ("brief.md", os.path.join("prompts", "brief.md")),
        ("stage-prompt.md", os.path.join("prompts", "stage-prompt.md")),
        ("requirements.md", os.path.join("prompts", "requirements.md")),
        ("coverage.md", os.path.join("prompts", "coverage.md")),
        ("style-and-score.md", os.path.join("prompts", "style-and-score.md")),
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
    print("骨架: prompts/brief.md, prompts/stage-prompt.md, prompts/requirements.md (立项单), "
          "prompts/coverage.md (覆盖度与结构单), prompts/style-and-score.md (风格与配乐单), "
          "script.md, storyboard.md, credits.md")
    print("配置唯一入口: theme.py (身份与署名, 时间网格, 画幅, 色板, 字体与字号, 段落与幕表), "
          "改片只改这一处; scene_module.py 顶部的同名常量只是它的回退")

    write_style(project, a.style, a.seed, a.tone)

    print("-" * 62)
    print("工程已建好: %s" % project)
    print("接下来按这个顺序走:")
    print("  1 填 prompts/requirements.md (立项单), 与代价披露同一次问完")
    print("  2 填 prompts/brief.md 与 prompts/stage-prompt.md")
    print("  3 研究与核查后填 prompts/coverage.md, 用户挑定覆盖方案")
    print("  4 写 script.md, 再跑 python scripts/timing.py script.md --bpm %s --bars %d" % (a.bpm, bars))
    print("  5 取三张风格候选 (python scripts/style_lottery.py --pick 3 --write .) 并出三张样图, 填 prompts/style-and-score.md")
    print("  6 填 storyboard.md, 过启动确认门")
    print("  7 python scripts/orchestra.py %s %s score.wav \"<切点>\" audio" % (a.dur, a.bpm))
    print("  8 改 theme.py 的配置与 scene_module.py 的分镜, 用 python scene_module.py at 0:1.5 逐场审阅")
    print("  9 python scene_module.py segments 核对段数, 再走合成确认门")
    return 0


if __name__ == "__main__":
    sys.exit(main())

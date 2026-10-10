# -*- coding: utf-8 -*-
"""
电子与键盘配乐引擎 (轻而现代)

设计目标: 轻, 暖, 不刺耳, 可卡点
  轻: 只用毛毡钢琴, pad, 正弦低音, 软边击与钟琴, 没有明亮踩镲与失真底鼓
  暖: 母带补 220 到 900Hz 温暖区, 压 3kHz 以上高频, 混响 IR 必先低通
  不刺耳: 音色全部由谐波堆叠而成, 不让宽带噪声铺满全片
  可卡点: 所有重音落在拍栅格上, 段落切点与画面切点共用同一份数据

音色取向: 毛毡钢琴拨奏, 慢起 pad, 正弦低音, 软边击, 钟琴点缀
适用场景: 需要更轻, 更现代, 更电子化的听感时用它, 管弦乐取向优先用 orchestra.py

配器取行有两种口径:
  1 缺省: 八小节循环骨架, 每一小节用哪些音色与多大力度的力度由小节号写死 (旧行为)
    缺点: 段落意图与位置脱钩, 开头与结尾只能靠"第 0 小节特殊处理"这类硬编码
  2 逐小节编排 (推荐): --arrange 给出一小节一行的意图表, 段落意图与小节位置直接绑定,
    不再由小节号写死. 三条经验都能在表里直接表达:
    前 1 到 2 小节写 blank 留白, 中段写 break 抽掉本小节两拍底鼓再回来,
    末 1 到 2 小节写 tail 做减法只留 pad 与一枚干净尾音

  python scripts/music.py <时长秒> <BPM> <输出文件名> <切点逗号分隔> [输出目录]
  python scripts/music.py 108 100 score_nobel.wav "7.2,16.8,26.4,36,50.4,64.8,79.2,91.2,103.2"
  python scripts/music.py 12 100 demo.wav "7.2" temp/demo
  python scripts/music.py 16 120 score_arr.wav "8" temp --arrange "blank,intro,bed,drive,break,full,rise,tail"
  python scripts/music.py 16 120 score_arr.wav "8" temp --arrange-file plan.txt

选项 (参数名与语义与 orchestra.py 完全一致):
  --arrange 表   逐小节编曲意图表, 逗号分隔, 一小节一项. 名字见打印出的图例;
                 表长于小节数时报错退出 2 并列出多余的项, 短于小节数时按
                 --arrange-fill 处理 (缺省 loop 循环, 并在打印里说明)
  --arrange-file 文件  同上, 从文件读: 一行一个名字, 允许逗号分隔与 # 注释
  --arrange-fill loop|hold  短表的取舍: loop 循环取用, hold 沿用最后一小节到结尾

给了意图表时切点仍参与转场 swell/thump 与钟琴, 但不再决定配器; 结尾的收束和弦也不再
自动叠加, 收尾由 out 与 tail 两行意图决定. 母带链与客观判据不受本选项影响.

输出目录缺省为相对当前工作目录的 audio, 目录不存在会自动建
底层 DSP 基元统一从 dsp.py 取用, 本脚本只放音色与编排
音区口径上与 dsp.hz 相差 60 个半音, 原因与修正办法见下方 HZ_OFFSET 处的说明
"""
import argparse
import os
import sys
from collections import namedtuple

import numpy as np

import dsp
from dsp import (SR, add, lp_fft, hp_fft, bp_fft, sat, reverb, make_ir,
                 bus_compress, warm_master, write_wav, tape_wow, vinyl_bed,
                 fm_piano as _fm_piano)


def _parse_args(argv):
    """前 5 个位置参数保持旧口径, 其后接选项; 选项名与 orchestra.py 逐字对齐"""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("dur", nargs="?", type=float, default=108.0)
    ap.add_argument("bpm", nargs="?", type=float, default=100.0)
    ap.add_argument("outname", nargs="?", default="score_nobel.wav")
    ap.add_argument("cuts", nargs="?", default="")
    ap.add_argument("out", nargs="?", default="audio")
    ap.add_argument("--arrange", dest="arrange", default=None,
                    help="逐小节编曲意图表, 逗号分隔, 一小节一项, 例如 "
                         "blank,blank,intro,bed,drive,break,full,rise,out,tail; "
                         "表长于小节数时报错退出 2, 短于小节数时按 --arrange-fill 处理")
    ap.add_argument("--arrange-file", dest="arrange_file", default=None,
                    help="从文件读逐小节编曲意图表: 一行一个名字, 允许逗号分隔与 # 注释; "
                         "与 --arrange 不能同时给出")
    ap.add_argument("--arrange-fill", dest="arrange_fill", default="loop",
                    choices=("loop", "hold"),
                    help="编排表短于小节数时的取舍: loop 按表循环取用 (缺省), "
                         "hold 把最后一小节的名字延续到结尾")
    a, unknown = ap.parse_known_args(argv)
    if unknown:
        raise SystemExit("未知参数: %s" % " ".join(unknown))
    return a


_A = _parse_args(sys.argv[1:])
DUR = _A.dur
BPM = _A.bpm
OUTNAME = _A.outname

BEAT = 60.0 / BPM
BAR = 4 * BEAT
N = int(round(SR * DUR))
T = np.arange(N) / SR
OUT = _A.out
os.makedirs(OUT, exist_ok=True)

if _A.cuts:
    CUTS = [float(x) for x in _A.cuts.split(",")]
else:
    CUTS = [round(k * BAR, 4) for k in (3, 7, 11, 15, 21, 27, 33, 38, 43, 45)]

rng = np.random.default_rng(20261008)

# 音区口径说明 (已知缺陷, 本轮刻意保留)
# 本模块的 hz() 以 MIDI 9 号为 440Hz 基准, dsp.hz 以 MIDI 69 号为 A4 基准, 两者相差 60 个半音
# 而下面的和弦表是按标准 MIDI 号书写的 (48 号旁边注释写的就是根音 C3)
# 于是按旧口径渲染时 pad 与 sub_bass 被推到 4186Hz 以上, 又被 900Hz 与 260Hz 低通滤掉
# 全曲实际只剩底鼓与 thump 的低频加钢琴的高频叮当, 中低频几乎是空的
# 为保持与历史产出逐样本一致, 这里用显式偏移 60 沿用旧口径
# 若要修正: 把 HZ_OFFSET 改成 0, 并重新调母带与低频配比, 低频占比与谱心都会大幅变化
HZ_OFFSET = 60


def hz(semi):
    """C4 为 0 号音的半音号转频率, 底层走 dsp.hz 加固定偏移"""
    return dsp.hz(semi + HZ_OFFSET)


# ---------------------------------------------------------------- 音色
def piano(f, dur=1.1, amp=1.0):
    """毛毡钢琴拨奏: 正弦加快速衰减的谐波, 6ms 起音"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) * 1.00
    x += 0.30 * np.sin(2 * np.pi * 2 * f * tt + 0.4) * np.exp(-tt / 0.22)
    x += 0.09 * np.sin(2 * np.pi * 3 * f * tt + 1.1) * np.exp(-tt / 0.13)
    x += 0.03 * np.sin(2 * np.pi * 4.02 * f * tt) * np.exp(-tt / 0.08)
    env = (1 - np.exp(-tt / 0.006)) * np.exp(-tt / (dur * 0.42))
    return x * env * amp / 1.55


def fm_piano(f, dur=1.4, amp=1.0):
    """FM 电钢主奏: 载波加指数衰减的调制指数再叠慢颤音, 实现见 dsp.fm_piano"""
    return _fm_piano(f, dur, amp)


def pad(freqs, dur, amp=0.5, cutoff=900.0):
    """慢起 pad: 每个和弦音三路失谐正弦, 低通 900Hz 保证不刺"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    a = (1 - np.exp(-tt / 0.9)) * np.exp(-np.maximum(tt - (dur - 1.6), 0) / 1.1)
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.09, 0.0, 0.11):
            fd = f * 2 ** (det / 12.0)
            ph = rng.random() * 6.283
            out += np.sin(2 * np.pi * fd * tt + ph) * 0.33
            out += np.sin(2 * np.pi * 2 * fd * tt + ph) * 0.05
    out = lp_fft(out / max(len(freqs), 1), cutoff, 2)
    return out * a * amp


def sub_bass(f, dur=0.9, amp=1.0):
    """正弦低音加二次谐波, 低通 260Hz"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) + 0.18 * np.sin(2 * np.pi * 2 * f * tt)
    env = (1 - np.exp(-tt / 0.02)) * np.exp(-tt / (dur * 0.5))
    return lp_fft(x, 260, 2) * env * amp


def soft_kick(amp=1.0):
    """软底鼓: 正弦扫频 102 降到 62Hz, 无 click 无失真"""
    n = int(0.55 * SR)
    tt = np.arange(n) / SR
    f = 62 + 40 * np.exp(-tt / 0.05)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-tt / 0.17)
    return x * amp / max(np.max(np.abs(x)), 1e-9)


def rim(amp=1.0):
    """软边击: 噪声经 4 阶带通 200 到 900Hz, 加 180Hz 短音, 没有高频嘶声"""
    n = int(0.22 * SR)
    tt = np.arange(n) / SR
    nz = bp_fft(rng.standard_normal(n), 200, 900, 4)
    tone = np.sin(2 * np.pi * 180 * tt) * 0.40 * np.exp(-tt / 0.05)
    x = (nz * np.exp(-tt / 0.045) + tone) * (1 - np.exp(-tt / 0.003))
    return x * amp / max(np.max(np.abs(x)), 1e-9)


def bell(f, dur=2.2, amp=1.0):
    """钟琴: 基频加 2 倍与 3 倍分音, 长衰减, 低通 3.2kHz"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.9)
    x += 0.20 * np.sin(2 * np.pi * 2.0 * f * tt) * np.exp(-tt / 0.40)
    x += 0.04 * np.sin(2 * np.pi * 3.0 * f * tt) * np.exp(-tt / 0.20)
    return lp_fft(x * amp / 1.6, 3200, 2)


def swell(dur=1.8, amp=0.30, lo=160, hi=900):
    """噪声渐强: 带通中心随时间上移, 段落切换前铺一层空气"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    p = tt / dur
    nz = rng.standard_normal(n)
    steps = 18
    out = np.zeros(n)
    for i in range(steps):
        a, b = i / steps, (i + 1) / steps
        i0, i1 = int(a * n), int(b * n)
        if i1 <= i0:
            continue
        f0 = lo + (hi - lo) * a
        out[i0:i1] = bp_fft(nz[i0:i1], max(f0 * 0.6, 80), min(f0 * 1.6, 12000), 4)
    return out * (p ** 2.0) * amp / max(np.max(np.abs(out)), 1e-9)


def thump(amp=1.0):
    """切点低音 thump: 64 降到 34Hz 扫频"""
    n = int(1.1 * SR)
    tt = np.arange(n) / SR
    f = 64 * np.exp(-tt / 0.25) + 34
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.30)
    return x * amp / max(np.max(np.abs(x)), 1e-9)


# ---------------------------------------------------------------- 编排
# 8 小节循环: Cmaj7  Am7  Fmaj7  G6  Cmaj7  Em7  Fmaj7  G6
CHORDS = [
    # Cmaj7  (根音 C3)
    (48, [48, 52, 55, 59]),
    # Am7
    (45, [45, 48, 52, 55]),
    # Fmaj7
    (41, [41, 45, 48, 52]),
    # G6
    (43, [43, 47, 50, 52]),
    (48, [48, 52, 55, 59]),
    # Em7
    (40, [40, 43, 47, 50]),
    (41, [41, 45, 48, 52]),
    (43, [43, 47, 50, 52]),
]


# ------------------------------------------------------- 逐小节编排意图表
# 一小节一行: 意图名 -> 本小节的音色与力度, 让段落意图与小节位置绑定
# 行字段: pad 力度, 低音系数, 钢琴系数, 电钢主奏小节头幅度, 钟琴系数,
#         开场钟琴系数, 底鼓拍位与幅度, 边击拍位与幅度, 力度, 尾音标记
Row = namedtuple("Row", "pad bass piano lead bell intro kick rim dyn tail")

# 底鼓与软边击的拍位形状: 旧口径是底鼓走 0 与 2 拍, 边击走 1 与 3 拍
KICK_2 = ((0, 0.30), (2, 0.21))
KICK_1 = ((0, 0.30),)
RIM_2 = ((1, 0.26), (3, 0.20))
RIM_FULL = ((1, 0.28), (3, 0.22))
RIM_LIGHT = ((1, 0.16), (3, 0.12))


def legacy_row(bar_i):
    """
    旧口径配器行: 改造前写死在循环里的逐小节条件全部搬到这里

    不给 --arrange 时 row_of_bar 走这条分支, 系数与旧版逐字相同, 力度固定 1.0,
    于是每一路的振幅与旧版同一个浮点值, 产出逐样本一致
    """
    if bar_i < 2:
        # 开头两小节只留 pad 与钟琴, 让观众先看清标题
        return Row(0.50 if bar_i == 0 else 0.72, 0.0, 0.0, 0.0, 0.0,
                   1.0 if bar_i == 0 else 0.0, (), (), 1.0, False)
    return Row(0.72, 1.0, 1.0,
               (0.30 if bar_i % 4 == 0 else 0.22) if bar_i >= 4 else 0.0,
               1.0 if bar_i % 4 == 0 else 0.0, 0.0,
               KICK_2, RIM_2, 1.0, False)


# 每项: 配器行, 中文名, 打印用的语义备注 (名字与别名与 orchestra.py 同一套)
# blank 满足"前 1 到 2 小节留白", break 满足"中段抽掉底鼓两拍再回来", tail 满足"减法留干净尾音"
INTENT_ROWS = {
    "blank": (Row(0.20, 0.0, 0.0, 0.0, 0.0, 0.0, (), (), 0.55, False),
              "留白", "只落极弱 pad, 其余六种音色全不落 (切点前 swell 与切点 thump 仍按切点走)"),
    "intro": (Row(0.50, 0.0, 0.0, 0.0, 0.0, 1.0, (), (), 0.62, False),
              "引子", "只有 pad 底与开场两枚钟琴, 没有低音也没有节奏层"),
    "bed": (Row(0.72, 0.50, 0.35, 0.0, 0.0, 0.0, (), (), 0.60, False),
            "铺垫", "pad 上加轻钢琴与低音, 仍不出电钢主奏与底鼓"),
    "drive": (Row(0.72, 1.0, 1.0, 0.22, 0.0, 0.0, KICK_2, RIM_2, 0.80, False),
              "推进", "电钢主奏进场, 软底鼓落 0 与 2 两拍, 软边击落 1 与 3 拍"),
    "full": (Row(0.72, 1.0, 1.0, 0.30, 1.0, 0.0, KICK_2, RIM_FULL, 1.00, False),
             "全奏", "最满的一档: 除转场的 swell 与 thump 之外七种音色全上, 力度 1.0"),
    "break": (Row(0.72, 1.0, 0.85, 0.22, 0.0, 0.0, (), RIM_2, 0.68, False),
              "抽鼓", "相对 drive/full 的两拍底鼓本小节全抽, 钢琴与边击留着, 下一小节回 drive/full 即回来"),
    "fall": (Row(0.72, 0.60, 0.55, 0.0, 0.0, 0.0, (), RIM_LIGHT, 0.62, False),
             "回落", "撤掉电钢主奏与底鼓, 钢琴与边击各收一档"),
    "rise": (Row(0.72, 1.0, 0.80, 0.24, 0.0, 0.0, KICK_1, RIM_2, 0.78, False),
             "起势", "底鼓只落 0 拍, 电钢与钢琴渐起, 给下一小节铺路"),
    "out": (Row(0.72, 1.0, 0.70, 0.0, 1.0, 0.0, KICK_1, RIM_LIGHT, 0.66, False),
            "收束", "成型的结束句: 有底鼓有钟琴但力度收回, 底鼓只落 0 拍"),
    "tail": (Row(0.45, 0.0, 0.0, 0.0, 0.0, 0.0, (), (), 0.42, True),
             "尾音", "做减法: 只留 pad 与一枚小节头钟琴尾音, 其余全撤"),
}

INTENT_ALIAS = {"silence": "blank", "drop": "full"}

# 编排口径的小节数取整, 与 orchestra.py 的 NBARS 同口径: 末尾不足一小节也算一节
ARRANGE_NBARS = max(1, int(-(-DUR // BAR)))
# 旧口径的小节数: 只渲染整小节, 不足一小节的尾巴不配器 (不给编排表时用这个)
LEGACY_NBARS = int(DUR // BAR)


def fail(msg):
    """编排表的口径错误统一走退出码 2, 与 argparse 的错误码一致"""
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def split_names(text):
    """逗号分隔的意图名转成规范名: 去空白, 转小写, 丢掉空项"""
    return [x.strip().lower() for x in text.split(",") if x.strip()]


def names_from_file(path):
    """编排表文件: 一行一个名字, 允许逗号分隔; # 起整行或行尾注释"""
    if not os.path.isfile(path):
        fail("编排表文件不存在: %s" % path)
    names = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            names.extend(split_names(line.split("#", 1)[0]))
    return names


def load_arrange(a):
    """解析 --arrange / --arrange-file: 名字与长度都在这里校验完, 不合法即退出 2"""
    if not a.arrange and not a.arrange_file:
        return None
    if a.arrange and a.arrange_file:
        fail("--arrange 与 --arrange-file 不能同时给出")
    names = names_from_file(a.arrange_file) if a.arrange_file else split_names(a.arrange)
    if not names:
        fail("编排表为空: 至少要有一个意图名")
    bad = sorted({n for n in names if n not in INTENT_ROWS and n not in INTENT_ALIAS})
    if bad:
        fail("未知意图名: %s\n可用名: %s"
             % (", ".join(bad), ", ".join(sorted(INTENT_ROWS))))
    names = [INTENT_ALIAS.get(n, n) for n in names]
    if len(names) > ARRANGE_NBARS:
        extra = names[ARRANGE_NBARS:]
        fail("编排表 %d 项多于小节数 %d (%.2f 秒 / %.1f BPM, 每小节 %.2f 秒), "
             "多余的 %d 项: %s"
             % (len(names), ARRANGE_NBARS, DUR, BPM, BAR, len(extra), ", ".join(extra)))
    return names


FILL = _A.arrange_fill
ARRANGE_NAMES = load_arrange(_A)
ARRANGE_PLAN = None if ARRANGE_NAMES is None else [INTENT_ROWS[n][0] for n in ARRANGE_NAMES]


def arrange_index(bar_i):
    """
    第 bar_i 小节取编排表第几项

    表短于小节数时按 FILL 处理: loop 循环取用 (会把收束与尾音搬到中段, 打印里明确提示),
    hold 把最后一小节的名字延续到结尾
    """
    n = len(ARRANGE_NAMES)
    if bar_i < n:
        return bar_i
    if FILL == "loop":
        return bar_i % n
    return n - 1


def intent_of_bar(bar_i):
    """第 bar_i 小节的意图名, 已解析别名"""
    return ARRANGE_NAMES[arrange_index(bar_i)]


def row_of_bar(bar_i):
    """第 bar_i 小节的配器行: 有编排表按表取, 没有则按旧口径的逐小节条件取"""
    if ARRANGE_PLAN is not None:
        return ARRANGE_PLAN[arrange_index(bar_i)]
    return legacy_row(bar_i)


def print_arrange_plan():
    """编排表总览: 表长与填充取舍, 名字图例, 以及段界落在哪些小节; 逐小节明细在渲染里打"""
    if ARRANGE_PLAN is None:
        return
    print("编排表: %d 小节 (每小节 %.2f 秒, %.2f 秒 / %.1f BPM), 表 %d 项%s"
          % (ARRANGE_NBARS, BAR, DUR, BPM, len(ARRANGE_NAMES),
             ", 一小节一对一" if len(ARRANGE_NAMES) == ARRANGE_NBARS else ", 填充口径 %s" % FILL))
    if len(ARRANGE_NAMES) < ARRANGE_NBARS:
        # 短表的取舍必须在打印里说清选了哪种, 且 loop 会把结尾的收束与尾音提前搬到中段
        if FILL == "loop":
            print("提示: 表 %d 项短于 %d 小节, 采用 loop 循环: 第 %d 项 \"%s\" 之后回到第 0 项, "
                  "收束与尾音会在中段重复出现; 要位置绑定就把表写到 %d 项, "
                  "或改用 --arrange-fill hold"
                  % (len(ARRANGE_NAMES), ARRANGE_NBARS, len(ARRANGE_NAMES) - 1,
                     INTENT_ROWS[ARRANGE_NAMES[-1]][1], ARRANGE_NBARS))
        else:
            print("提示: 表 %d 项短于 %d 小节, 采用 hold 延续: 第 %d 到 %d 小节沿用最后一小节 \"%s\""
                  % (len(ARRANGE_NAMES), ARRANGE_NBARS, len(ARRANGE_NAMES), ARRANGE_NBARS - 1,
                     INTENT_ROWS[ARRANGE_NAMES[-1]][1]))
    print("意图名图例: " + " | ".join(
        "%s %s (%s)" % (n, INTENT_ROWS[n][1], INTENT_ROWS[n][2]) for n in INTENT_ROWS))
    print("别名: " + " | ".join("%s -> %s" % (k, v) for k, v in sorted(INTENT_ALIAS.items())))
    print("段界(小节号 起-止 / 意图 / 小节数):")
    i = 0
    while i < ARRANGE_NBARS:
        name = intent_of_bar(i)
        j = i
        while j + 1 < ARRANGE_NBARS and intent_of_bar(j + 1) == name:
            j += 1
        print("  小节 %03d-%03d  %s(%-8s) %d 小节" % (i, j, INTENT_ROWS[name][1], name, j - i + 1))
        i = j + 1
    if ARRANGE_NBARS != LEGACY_NBARS:
        print("提示: 末尾不足一小节, 编排按整小节口径取 %d 小节 (与 orchestra.py 一致), "
              "最后一小节只有 %.2f 秒" % (ARRANGE_NBARS, DUR - LEGACY_NBARS * BAR))
    print("提示: 有编排表时不再自动叠加结尾收束和弦与 thump, 收尾由 out 与 tail 决定; "
          "切点前的 swell 与切点上的 thump 加钟琴仍按切点走")


def _lv(x):
    """力度列: 0 表示这一小节不落这个声部"""
    return "%.2f" % x if x > 0 else "无"


def print_bar_row(bar_i, name, r, t0):
    """逐小节明细: 意图名与它实际用到的音色与力度, 让 Agent 不靠总数就能核对位置与配器"""
    kick = ",".join(str(b) for b, _ in r.kick) if r.kick else "无"
    rim = ",".join(str(b) for b, _ in r.rim) if r.rim else "无"
    print("  小节 %03d  %7.2f 秒  意图 %s(%-8s) pad %-4s 低音 %-4s 钢琴 %-4s 电钢 %-4s"
          " 钟琴 %-4s 底鼓 %-5s 边击 %-5s 力度 %.2f%s"
          % (bar_i, t0, INTENT_ROWS[name][1], name, _lv(r.pad * r.dyn), _lv(r.bass * r.dyn),
             _lv(r.piano * r.dyn), _lv(r.lead * r.dyn),
             _lv(max(r.bell, r.intro) * r.dyn),
             kick, rim, r.dyn, "  尾音" if r.tail else ""))


print_arrange_plan()


def main():
    drums = np.zeros(N)
    bass = np.zeros(N)
    music = np.zeros(N)
    fx = np.zeros(N)

    # 有编排表时按整小节口径渲染 (末尾不足一小节的也算一节, 与 orchestra.py 一致);
    # 不给表时沿用旧口径只渲染整小节
    nbars = ARRANGE_NBARS if ARRANGE_PLAN is not None else LEGACY_NBARS

    for bar_i in range(nbars):
        t0 = bar_i * BAR
        root_semi, tones = CHORDS[bar_i % 8]
        root = hz(root_semi)
        r = row_of_bar(bar_i)
        if ARRANGE_PLAN is not None:
            print_bar_row(bar_i, intent_of_bar(bar_i), r, t0)

        # pad: 每小节一个和弦, 从第 1 小节就进来
        if r.pad > 0:
            pad_f = [hz(s) for s in tones] + [hz(root_semi + 12)]
            add(music, pad(pad_f, BAR + 1.4, r.pad * r.dyn), t0)

        # 开场两枚固定钟琴: 旧口径只落在第 0 小节, 编排表里由 intro 行决定
        if r.intro > 0:
            add(fx, bell(hz(76), 3.0, 0.16 * r.intro * r.dyn), t0 + 0.05)
            add(fx, bell(hz(83), 3.0, 0.10 * r.intro * r.dyn), t0 + BEAT * 2)

        # 低音落在 1 与 3 拍, 3 拍轻一些
        if r.bass > 0:
            add(bass, sub_bass(root, 1.5, 0.40 * r.bass * r.dyn), t0)
            add(bass, sub_bass(root, 1.3, 0.26 * r.bass * r.dyn), t0 + BEAT * 2)

        # 软底鼓与软边击: 拍位与幅度全部来自本小节的意图行, break 行的底鼓拍位为空即抽掉
        # 先落完所有底鼓再落边击, 与旧版的落音顺序一致
        for beat, ka in r.kick:
            add(drums, soft_kick(ka * r.dyn), t0 + beat * BEAT)
        for beat, ra in r.rim:
            add(drums, rim(ra * r.dyn), t0 + beat * BEAT)

        # 钢琴走八分音符琶音, 1 拍与 3 拍加重
        if r.piano > 0:
            walk = [0, 2, 1, 3, 2, 0, 3, 1]
            for k in range(8):
                lb = k * 0.5
                semi = tones[walk[k] % 4] + (12 if k in (4, 6) else 0)
                amp = (0.55 if (k % 4 == 0) else (0.36 if k % 2 == 0 else 0.24)) * r.piano * r.dyn
                if bar_i % 8 in (0, 4) and k == 0:
                    amp *= 1.15
                add(music, piano(hz(semi), 1.3, amp), t0 + lb * BEAT)

        # 每 4 小节句首一枚钟琴
        if r.bell > 0:
            add(fx, bell(hz(tones[3] + 24), 2.4, 0.09 * r.bell * r.dyn), t0 + 0.02)

        # 尾音: 只在小节头落一枚钟琴单音, 与 tail 行的减法配器一起构成干净收束
        if r.tail:
            add(fx, bell(hz(tones[0] + 12), 2.6, 0.22 * r.dyn), t0 + 0.02)

        # 电钢主奏只落在小节头与第 3 拍, 给全片添一条可跟随的线;
        # 后四小节整体抬二度是位置派生的音级形状, 两种口径共用
        if r.lead > 0:
            la = r.lead * r.dyn
            lead_semi = tones[3] + (0 if bar_i % 8 < 4 else 2)
            add(music, fm_piano(hz(lead_semi), 1.6, la), t0)
            add(music, fm_piano(hz(tones[2] + 12), 1.4, la * 0.8), t0 + BEAT * 2)

    # 段落转场: 切点前起 swell, 切点上落 thump 与钟琴.
    # 给了编排表时这一层照旧: 它与画面切点共用同一份数据, 不属于配器
    for i, cut in enumerate(CUTS[:-1]):
        if cut <= 0.1:
            continue
        add(fx, swell(1.9, 0.26 if i else 0.20), cut - 1.9)
        add(fx, thump(0.50 if i else 0.40), cut)
        add(fx, bell(hz(79 if i % 2 else 76), 2.6, 0.11), cut + 0.02)
    # 结尾收束: 旧口径自动叠加, 有编排表时收尾由 out 与 tail 两行决定, 不再叠加
    if ARRANGE_PLAN is None:
        add(fx, swell(2.4, 0.22), DUR - 3.0)
        add(fx, thump(0.42), DUR - 2.6)
        add(music, pad([hz(s) for s in (48, 52, 55, 59, 64)], 4.0, 0.34), DUR - 4.2)

    # ---- 底鼓侧链闪避: 每个底鼓点把音乐与低音压到 0.72, 50ms 内恢复
    # 闪避跟着本小节的底鼓拍位走: break 行没有底鼓, 该小节也就没有闪避
    duck = np.ones(N)
    for bar_i in range(nbars):
        for beat, _ka in row_of_bar(bar_i).kick:
            i = int((bar_i * BAR + beat * BEAT) * SR)
            m = int(0.45 * SR)
            if i >= N:
                continue
            seg = np.arange(min(m, N - i)) / SR
            env = 0.72 + 0.28 * (1 - np.exp(-seg / 0.05))
            duck[i:i + len(seg)] = np.minimum(duck[i:i + len(seg)], env)
    music *= duck
    bass *= duck

    # ---- 混响: IR 先低通, 否则混响把高频铺满全片
    # IR 必须在这里生成: 它消耗 rng 的时机与改造前一致, 否则随机串会整体错位
    ir = make_ir(1.9, 0.55, 2400, 3, rng)
    music_r = reverb(music, ir, 0.55)
    fx_r = reverb(fx, ir, 0.55)
    bass_r = reverb(bass, ir, 0.10)

    # ---- 声场: 钢琴与 fx 做毫秒级左右错位, 底鼓与低音居中共用
    def widen(x, spread):
        d = int(spread * SR)
        l, r = x.copy(), x.copy()
        if d > 0:
            l[d:] = x[:-d]
            r[:-d] = x[d:]
        return l, r

    ml, mr = widen(music_r, 0.013)
    fl, fr = widen(fx_r, 0.009)
    left = drums + bass_r + 0.55 * (ml + music_r) + 0.5 * (fl + fx_r)
    right = drums + bass_r + 0.55 * (mr + music_r) + 0.5 * (fr + fx_r)

    st = np.stack([left, right])

    # ---- 磁带味: 缓慢游走的读指针做音高漂移, 再垫一层极低的黑胶底噪
    # 底噪是氛围不是内容, 电平压在千分之四以内, 超过就会盖住弱奏段落
    st = tape_wow(st, depth=0.0012, rate=0.63)
    bed = vinyl_bed(st.shape[-1], level=0.004, seed=20261008)
    st = st + np.stack([bed, bed])

    # ---- 总线压缩: 时间常数 0.09s, 阈值 0.16, 超出部分按 0.55 次幂衰减
    st = bus_compress(st, thr=0.16, power=0.55, tau=0.09)

    # ---- 母带链: 滤波 -> 软限幅 -> 淡入淡出 -> 归一化 -> 过采样真峰压制
    # 淡入淡出由母带链统一负责, 顺序不能调换; 归一化必须在淡入淡出之后
    st, mrep = warm_master(st, dur=DUR, fade_in=0.8, fade_out=2.2,
                           warm_lo=220, warm_hi=900, warm=0.40,
                           cut1=3000, cut1_amt=0.45, cut2=6000, cut2_amt=0.35,
                           lpf=4600, lpf_order=3, hpf=32, true_peak=-1.0)

    path = os.path.join(OUT, OUTNAME)
    shape = write_wav(path, st)
    print("wrote", path, shape, "peak %.2f dBFS  true peak %.2f dBTP%s"
          % (mrep["peak_db"], mrep["true_peak_db"],
             "" if mrep["true_peak_ok"] else "  [真峰未压住]"))


if __name__ == "__main__":
    main()

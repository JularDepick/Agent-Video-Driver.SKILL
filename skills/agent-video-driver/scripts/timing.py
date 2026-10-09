# -*- coding: utf-8 -*-
"""
文案到拍表排程器: 把一屏一句的文案排到音乐拍网格上

  python scripts/timing.py script.md --bpm 100 --bars 45 --anchor 8:21 --json temp/plan.json --md temp/plan.md
  python scripts/timing.py script.md --bpm 100 --bars "5-21,14-30,75-end" --anchor 8:21 --source-bars 96
  python scripts/timing.py script.md --bpm 120 --meter 4 --fix 6:5 --fix 11:3

输入格式 (只认二级标题与含 2 列以上的表格行, 其余行忽略, 所以容错):
  ## 01 标题幕              <- 一个 ## 开一幕, 标题文字随意
  | 屏号 | 屏文字 | 画面 |   <- 表头行会被跳过
  |:---:|:---|:---|        <- 分隔行会被跳过
  | 1 | 第一屏文字 | ... |   <- 只取第 2 列为屏文字, 其余列随意
  | 2 | 第二屏文字 | ... |

  ## 02 第二幕
  | 屏号 | 屏文字 |
  |:---:|:---|
  | 1 | 第一屏文字 |

规则:
  屏号只作展示, 排程按表格出现顺序走, 脚本内部用跨幕连续的全局屏号 (从 1 开始)
  第 2 列为空的行, 或第 2 列是常见表头词的行会被跳过, 跳过的行数会报出来
  --anchor 与 --fix 里的屏号优先按全局连续屏号解释, 找不到时再按表内屏号唯一匹配
  人看的小节号一律 1 基: --anchor 的小节号与 plan.md 的 视频小节.拍 都从 1 开始
  机器读的小节号一律 0 基: plan.json 的 bar 与 beat_in_bar 从 0 开始, 与 beats.json 对齐

小节播放表 (--bars 的第二种形式):
  一个整数就是音乐总小节数, 与从前完全一致; 写成 a / a-b / a-end, 或者一串这样的区间,
  就是小节播放表, 解析规则与 scripts/cutmusic.py 的 parse_bars 对齐 (一律 1 基两端都含),
  逗号与空格都作分隔, 顺序即播放顺序, 同一段可以重复出现表示重复播放:
    --bars "5-21,14-30,75-end"   三段依次播放, 末段播到原曲结尾
    --bars 5-21 14-30 75-end     与上面的写法等价 (本参数会吃掉紧随其后的空格分隔值,
                                 所以文案表路径要写在最前面)
  同一份播放表既是 cutmusic.py 的输入也是排程的输入, 剪出来的音乐因此与排程逐小节对齐,
  剪过之后 --anchor 仍然指得回原曲: 给了播放表时 --anchor 的小节号是原曲小节号, 取它在
  播放表里的首次出现位置换算成视频小节, 找不到就停下报错并列出播放表覆盖的原曲区间
  end 的两种解释: 给了 --source-bars N 就与 cutmusic.py 完全一致 (剪到原曲第 N 小节);
  没给则当开放尾段, 长度由排程所需决定 (最少 1 小节), 开放尾段只能写在播放表最后一段
  边界: 起点大于终点 (倒序) 直接报错; 越界只有给了 --source-bars 才能校验; 区间之间重叠
  是允许的, 它表示同一段原曲被播两次, 不是错误; 单独一个整数一律按总小节数解释, 要表达
  只播一小节请写 45-45

plan.json 新增字段 (既有字段一律保留且语义不变, 小节号 0 基):
  bars_plan: 归一化后的播放表 [{video_bar, source_bar, bars, open}, ...]; 整数 --bars 时写 null
  source_bars: 视频小节号到原曲小节号的逐小节映射, 长度等于 bars; 整数 --bars 时是一一对应
  每幕新增 src_bar (该幕首屏起点的原曲小节号), 每屏新增 src_bar 与 src_beat_in_bar

排程规则:
  1 每幕首屏必须落在小节线 (下拍) 上, 幕内屏按公式拍数依次紧排
  2 幕尾自动补齐到整小节, 保证下一幕首屏仍在小节线上
  3 被 --anchor 钉住的屏落在指定小节的下拍上 (小节号从 1 开始, 给了播放表时是原曲小节号), 可重复传
  4 --fix 屏号:拍数 覆盖某屏的公式拍数, 可重复传 (公式见下)
  5 余量摊到全部合格屏上, 不是只摊首末屏: 先按幕的屏数降序排幕, 幕内按 首屏, 末屏,
     其余屏按原顺序 排列, 再按这个顺序每次一个小节 (meter 拍) 逐个轮流分配
     有锚点时只有最后一个锚点之后的屏可以吃余量, 否则会把锚点推离指定小节
     所以任一屏分到的额外小节数不超过 ceil(余量小节数 / 合格屏数), 不会一屏吞掉几十秒
     只有一个合格屏时 (例如锚点钉在末屏, 最后一个锚点之后没有屏) 余量仍然全归它
     不足一小节的余数 (layout 之后恒为 0) 分给顺序里的第一个合格屏
     锚点造成的位移按 同幕内该屏之前的屏 从首屏起逐小节轮流补给
     位移补不够时再往前一幕的屏补, 但绝不补到已钉住的锚点之前, 否则会把它推走
     唯一例外: 两个锚点钉在相邻两屏时, 延长前一个已钉屏自身的拍数 (不移动它的起点),
     让后一屏够到目标小节
     位移不是整小节时, 会再用后续幕的前一屏补回, 保证每幕首屏仍然落在小节线上
  6 文案量撑不起音乐长度时打印醒目告警: 判据是合格屏平均每屏分到的额外时长
     超过 2 小节 (2 * bar); 告警给出内容所需小节, 音乐小节, 余量多少小节多少秒,
     平均每屏多出多少秒, 以及 增加屏数 / 用 --bars 缩短音乐 / 接受长停留 三条解决路径
  7 排不下时停下来报清缺口 (需要多少小节, 音乐只剩多少小节, 缺多少秒) 并给出三条解决路径:
    精简文案, 把总小节数调大, 回头剪音乐 (先用 scripts/loops.py 找可无缝重复或可剪掉的小节
    区间, 再用 scripts/cutmusic.py 按播放表重剪), 第三条打印成可直接复制执行的命令
  8 打印播放表与锚点的换算结果 (视频小节对应哪一原曲小节, 锚点落在哪个视频小节), 排程所需
    与播放表总长的差额, 供 Agent 核对剪过的音乐与排程是否互指

拍数公式: units = 中文字符数 + 拉丁与数字词数, beats = max(3, round((0.6 + units/6) / BEAT + 0.2))
"""
import argparse
import json
import math
import os
import re
import sys

CN = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")
SEP_ROW = re.compile(r"^:?-{2,}:?$")
HEADER_CELLS = ("屏文字", "文字", "文案", "屏文案", "字幕", "屏幕文字")
BARS_SPLIT = re.compile(r"[,\s]+")
BARS_ITEM = re.compile(r"^([0-9]+)(?:-(end|[0-9]+))?$")


class BarsError(Exception):
    """小节播放表的写法或范围不合法, 由 main 捕获后打印并返回 2"""


def parse_script(path):
    """解析文案表, 返回 (幕列表, 跳过的行数). 只认 ## 标题与含 2 列以上的表格行"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    scenes = []
    skipped = 0
    for raw in lines:
        s = raw.strip()
        if s.startswith("##"):
            scenes.append({"title": s.lstrip("#").strip(), "texts": []})
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or all(SEP_ROW.match(c) for c in cells if c):
            skipped += 1
            continue
        text = cells[1]
        if not text or text in HEADER_CELLS:
            skipped += 1
            continue
        if not scenes:
            scenes.append({"title": "", "texts": []})
        scenes[-1]["texts"].append(text)
    return [sc for sc in scenes if sc["texts"]], skipped


def units_of(text):
    """中文按字计, 拉丁与数字按词计"""
    return len(CN.findall(text)) + len(LATIN.findall(text))


def beats_of(text, beat):
    """阅读速度模型: 语速 6 units/s, 0.6 秒起手, 最少 3 拍"""
    return max(3, int(round((0.6 + units_of(text) / 6.0) / beat + 0.2)))


def parse_pairs(items, flag):
    """解析 --anchor 与 --fix 的 屏号:数值 列表"""
    out = {}
    for it in items or []:
        if ":" not in it:
            raise SystemExit("%s 需要写成 屏号:数值, 收到 %s" % (flag, it))
        a, b = it.split(":", 1)
        try:
            out[int(a)] = int(b)
        except ValueError:
            raise SystemExit("%s 需要写成 屏号:数值, 收到 %s" % (flag, it))
    return out


def parse_bars_spec(tokens):
    """拆 --bars 的原始参数, 逗号与空格都作分隔, 容许写成 a-b / a-end / a / 一个总小节数整数.
    返回 (总小节数, None) 或 (None, 规格列表); 规格元素是 (起, 止 或 None), 都是 1 基.
    解析规则与 scripts/cutmusic.py 的 parse_bars 对齐 (两端都含), 只是在拿到源曲总小节数
    之前先不校验上界, end 也先留成 None. 完全没给 --bars 时返回 (None, None)"""
    if not tokens:
        return None, None
    specs = []
    for tok in tokens or []:
        for sp in BARS_SPLIT.split(tok.strip()):
            if sp:
                specs.append(sp)
    if not specs:
        raise BarsError("--bars 没有给出内容")
    if len(specs) == 1 and specs[0].isdigit():
        n = int(specs[0])
        if n < 1:
            raise BarsError("--bars 至少为 1")
        return n, None
    out = []
    for sp in specs:
        m = BARS_ITEM.match(sp.lower())
        if not m:
            raise BarsError("小节播放表写法不对: %s, 每一项应当是 a / a-b / a-end (整份写一个整数就是总小节数)" % sp)
        i = int(m.group(1))
        tail = m.group(2)
        if i < 1:
            raise BarsError("小节号从 1 开始: %s" % sp)
        if tail is None:
            out.append((i, i))
        elif tail == "end":
            out.append((i, None))
        else:
            j = int(tail)
            if j < i:
                raise BarsError("播放表里的区间倒序: %s, 起点不能大于终点" % sp)
            out.append((i, j))
    return None, out


def build_play(specs, source_total):
    """把播放表规格归一化成片段列表, 返回 (片段列表, 固定总小节数, 开放尾段起点 或 None).
    片段元素是 (视频起 0 基, 原曲起 0 基, 长度 或 None). 给了源曲总小节数时 end 与
    cutmusic.py 完全一致地解析成定长; 没给则当开放尾段 (长度由排程所需定), 只能写在最后一段"""
    segs = []
    fixed = 0
    for k, (i, j) in enumerate(specs):
        is_end = j is None
        if j is None:
            if source_total is None:
                if k != len(specs) - 1:
                    raise BarsError("end 只能写在播放表最后一段; 要把它放在中间, 请用 --source-bars 给出原曲总小节数")
                segs.append((fixed, i - 1, None))
                return segs, fixed, i - 1
            j = source_total
        if source_total is not None and (i > source_total or j > source_total):
            if is_end:
                raise BarsError("end 的起点 %d 超过 --source-bars 给的 %d" % (i, source_total))
            raise BarsError("小节范围越界: %d-%d, 原曲可用范围是 1 到 %d" % (i, j, source_total))
        segs.append((fixed, i - 1, j - i + 1))
        fixed += j - i + 1
    return segs, fixed, None


def plan_parts(segs):
    """播放表的文本形式, 每段一项, 开放尾段写成 a-end"""
    out = []
    for _, s0, n in segs:
        if n is None:
            out.append("%d-end" % (s0 + 1))
        elif n == 1:
            out.append("%d" % (s0 + 1))
        else:
            out.append("%d-%d" % (s0 + 1, s0 + n))
    return out


def src_to_video(segs, src_bar):
    """原曲小节号 (0 基) 在播放表里的首次出现位置, 返回视频小节号 (0 基); 找不到返回 None"""
    for v0, s0, n in segs:
        if n is None:
            if src_bar >= s0:
                return v0 + (src_bar - s0)
        elif s0 <= src_bar < s0 + n:
            return v0 + (src_bar - s0)
    return None


def video_to_src(segs, total):
    """视频小节号 (0 基) 到原曲小节号 (0 基) 的逐小节映射, 长度等于 total"""
    out = []
    for v0, s0, n in segs:
        cnt = (total - v0) if n is None else n
        out.extend(s0 + k for k in range(max(cnt, 0)))
    return out


def bars_plan_of(segs, total):
    """bars_plan 的 json 形式, 小节号 0 基, open 标记这一段是不是开放尾段"""
    out = []
    for v0, s0, n in segs:
        out.append({"video_bar": v0, "source_bar": s0,
                    "bars": (total - v0) if n is None else n, "open": n is None})
    return out


def music_cut_cmd(segs, music_bars, miss):
    """缺口处置的第三条: 回头剪音乐, 打印成可直接复制执行的命令.
    空缺的只有 loops.py 报出的可重复区间, 缺口小节数已经代进 --len"""
    parts = plan_parts(segs) if segs is not None else ["1-%d" % music_bars]
    # 开放尾段必须留在最后, 所以重复区间插在它前面
    if segs is not None and segs[-1][2] is None:
        parts = parts[:-1] + ["<loops.py 报出的可重复区间>"] + parts[-1:]
    else:
        parts = parts + ["<loops.py 报出的可重复区间>"]
    return ["     python scripts/beats.py audio/score.wav --json temp/beats.json --bpm <BPM>",
            "     python scripts/loops.py audio/score.wav temp/beats.json --len %d %d" % (miss, miss),
            "     python scripts/cutmusic.py audio/score.wav temp/beats.json --bars \"%s\" -o audio/score-edit.wav"
            % ",".join(parts),
            "     原曲换成用户自备音乐就改上面的音频路径; 剪完对 audio/score-edit.wav 再跑一次",
            "     beats.py 复测拍表, 用新播放表重排本表"]


def resolve(ref, screens):
    """屏号优先按全局连续编号解释, 其次按表内屏号唯一匹配"""
    if 1 <= ref <= len(screens):
        return ref - 1
    hits = [i for i, s in enumerate(screens) if s["disp"] == ref]
    return hits[0] if len(hits) == 1 else None


def report_shortage(screens, music_bars, meter, bar_sec, beat, segs=None):
    """排不下时的缺口报告, 并给出三条解决路径: 精简文案, 调大总小节数, 回头剪音乐"""
    last = len(screens) - 1
    first_bad = last
    for i, s in enumerate(screens):
        if s["start"] + s["beats"] > music_bars * meter:
            first_bad = i
            break
    b0 = screens[first_bad]["start"] // meter
    need = int(math.ceil((screens[last]["start"] + screens[last]["beats"]) / float(meter))) - b0
    avail = music_bars - b0
    miss = max(need - avail, 1)
    cnt = last - first_bad + 1
    rng = "第 %d 屏" % (first_bad + 1) if cnt == 1 else "第 %d 到 %d 屏" % (first_bad + 1, last + 1)
    per = need / float(max(cnt, 1))
    drop = int(math.ceil(miss / max(per, 1e-9)))
    print("排不下: %s需要 %d 小节, 但音乐在这里只剩 %d 小节: 缺 %d 小节 (%.1f 秒)"
          % (rng, need, avail, miss, miss * bar_sec))
    print("缺口从第 %d 小节开始, 音乐共 %d 小节" % (b0 + 1, music_bars))
    print("解决路径:")
    print("  1 精简文案: 把这 %d 屏里偏长的几屏压短, 每屏少 1 拍约省 %.1f 秒; 也可从这 %d 屏里删掉或合并"
          % (cnt, beat, cnt))
    print("     %d 屏 (按平均每屏 %.1f 小节算), 可省出 %d 小节" % (drop, per, miss))
    if segs is None:
        print("  2 把总小节数调大: --bars 从 %d 提到 %d, 同时把配乐时长延长 %.1f 秒"
              % (music_bars, music_bars + miss, miss * bar_sec))
    else:
        print("  2 把总小节数调大: 改用整数 --bars %d (现在是 %d 小节的播放表), 音乐时长延长 %.1f 秒"
              % (music_bars + miss, music_bars, miss * bar_sec))
    print("  3 回头剪音乐: 先用 loops.py 找一段至少 %d 小节 (%.1f 秒) 的可无缝重复区间重复播放,"
          % (miss, miss * bar_sec))
    print("     或找可剪接点剪掉一段并把后面的提前, 让配乐多出这 %d 小节, 文案与屏数都不用动:" % miss)
    for line in music_cut_cmd(segs, music_bars, miss):
        print(line)


def rebase(screens, lead):
    """按拍数顺序重排所有 start. 改过任何一屏的拍数都必须重排, 否则后面的屏会脱节"""
    cursor = lead
    for s in screens:
        s["start"] = cursor
        cursor += s["beats"]
    return cursor


def align_after(screens, scenes, meter, lead, from_index):
    """锚点把后面的幕推离小节线时, 用该幕前一屏补回整拍.
    只补 from_index 之后的幕, 所以不会把锚点自己推走; 补的是前一屏的时长, 不改它的起点"""
    for sc in scenes:
        first = sc["screens"][0]
        if first <= from_index:
            continue
        delta = (-screens[first]["start"]) % meter
        if delta:
            screens[first - 1]["beats"] += delta
            rebase(screens, lead)


def layout(screens, scenes, meter, anchors):
    """整数拍布局, 全程 k*BEAT 一次算出, 不做浮点累加. 返回 (总拍数, 自由区起点, 片头留白)"""
    cursor = 0
    for sc in scenes:
        for gi in sc["screens"]:
            cursor += screens[gi]["beats"]
        rest = (-cursor) % meter
        if rest:
            screens[sc["screens"][-1]]["beats"] += rest
            cursor += rest
    lead = 0
    cursor = rebase(screens, lead)

    lo = -1
    for gi, bar in sorted(anchors.items(), key=lambda kv: kv[1]):
        target = bar * meter
        cur = screens[gi]["start"]
        if cur > target:
            print("锚点冲突: 第 %d 屏最早只能落在第 %d 小节, 但 --anchor 要求第 %d 小节"
                  % (gi + 1, cur // meter + 1, bar + 1))
            print("锚点只能往后挪不能往前压: 把小节号调大, 或把前面屏的文字压短")
            return None, None, None
        if cur < target:
            if gi == 0:
                lead = target
                print("首屏被钉在第 %d 小节, 片头留 %d 小节给标题或静场" % (bar + 1, bar))
            else:
                sc_i = screens[gi]["scene"]
                cand = [j for j in scenes[sc_i]["screens"] if lo < j < gi]
                if not cand:
                    cand = list(range(lo + 1, gi))
                if not cand and lo >= 0 and gi == lo + 1:
                    # 两个锚点钉在相邻两屏: 延长前一个已钉屏自身的拍数不移动它的起点
                    # (锚点钉的是起点不是时长), 它仍钉在原小节, gi 被推到目标小节
                    cand = [lo]
                if not cand:
                    if gi < lo:
                        print("锚点冲突: 第 %d 屏要求第 %d 小节, 但第 %d 屏已钉在更早的小节"
                              % (gi + 1, bar + 1, lo + 1))
                        print("屏序与时间序矛盾: 前面的屏不能排在后面的屏之后, 请检查两个锚点的屏号与小节号")
                    else:
                        print("锚点冲突: 第 %d 屏要求第 %d 小节, 但它与上一个锚点屏之间没有可补位移的屏"
                              % (gi + 1, bar + 1))
                        print("把两个锚点之间的文案加长一拍 (--fix), 或把后一个锚点的小节号调小")
                    return None, None, None
                bars, rem = divmod(target - cur, meter)
                for k in range(bars):
                    screens[cand[k % len(cand)]]["beats"] += meter
                if rem:
                    screens[cand[-1]]["beats"] += rem
            rebase(screens, lead)
            align_after(screens, scenes, meter, lead, gi)
        lo = max(lo, gi)
        cursor = screens[-1]["start"] + screens[-1]["beats"]

    rest = (-cursor) % meter
    if rest:
        screens[-1]["beats"] += rest
        cursor = rebase(screens, lead)
    return cursor, (max(anchors) + 1 if anchors else 0), lead


def rest_targets(scenes, free_start):
    """能吃余量的屏, 按 幕的屏数降序, 幕内 首屏, 末屏, 其余屏按原顺序 排.
    合格屏 = 屏号不小于 free_start, 有锚点时 free_start 就是最后一个锚点之后,
    否则会把锚点推离它被钉住的小节"""
    order = sorted(range(len(scenes)), key=lambda i: (-len(scenes[i]["screens"]), i))
    targets = []
    for si in order:
        gis = scenes[si]["screens"]
        for gi in [gis[0], gis[-1]] + gis[1:-1]:
            if gi >= free_start and gi not in targets:
                targets.append(gi)
    return targets


def fill_rest(screens, scenes, free_start, music_bars, meter, lead):
    """余量摊到全部合格屏上: 每次一个小节逐个轮流分配, 余数给第一个合格屏"""
    total = screens[-1]["start"] + screens[-1]["beats"]
    left = music_bars * meter - total
    if left <= 0:
        return total
    targets = rest_targets(scenes, free_start)
    if not targets:
        targets = [len(screens) - 1]
    bars, rem = divmod(left, meter)
    for step in range(bars):
        screens[targets[step % len(targets)]]["beats"] += meter
    if rem:
        screens[targets[0]]["beats"] += rem
    return rebase(screens, lead)


def warn_thin_content(targets, extra, content_bars, music_bars, meter, beat, bar, segs=None):
    """文案量撑不起音乐长度时的醒目告警, 没有告警时返回 False.
    判据: 合格屏平均每屏分到的额外时长超过 2 小节 (2 * bar), 即平均要多停两小节以上"""
    if extra <= 0:
        return False
    n = max(len(targets), 1)
    avg = extra * beat / float(n)
    # 判据: 合格屏平均每屏分到的额外时长超过 2 小节 (2 * bar), 就判定文案量撑不起音乐长度
    if avg <= 2 * bar:
        return False
    need = int(math.ceil(extra / float(meter) / 2.0))
    scope = "合格屏 %d 屏" % n if targets else "最后一个锚点之后没有合格屏, 余量全归末屏"
    print("")
    print("==== 告警: 文案量撑不起音乐长度, 摊到每屏的停留会明显变长 ====")
    print("判据: 合格屏平均每屏分到 %.1f 秒额外停留, 超过 2 小节 (%.1f 秒)" % (avg, 2 * bar))
    print("内容需要 %d 小节, 音乐 %d 小节, 余量 %d 小节 %d 拍 (%.1f 秒), %s"
          % (content_bars, music_bars, extra // meter, extra % meter, extra * beat, scope))
    print("平均每屏多出 %.1f 秒 (约 %.2f 小节)" % (avg, avg / bar))
    print("解决路径:")
    print("  1 增加屏数: 每屏最多多吃 2 小节的话合格屏要有 %d 屏, 还差 %d 屏"
          % (need, max(need - n, 0)))
    if segs is None:
        print("  2 用 --bars 把音乐缩短到接近内容所需: --bars 从 %d 改成 %d"
              % (music_bars, content_bars))
    else:
        print("  2 把播放表缩短到接近内容所需 (%d 小节): 只留下前 %d 小节对应的区间, 或用 --source-bars 收紧 end 尾段"
              % (content_bars, content_bars))
    print("  3 接受这些屏的停留时间变长: 但必须自行确认没有违反 纯静态段落不超过 2 秒")
    return True


def write_md(path, screens, scenes, beat, meter, fps):
    """可直接粘进分镜表的 markdown 表"""
    title_of = {}
    for sc in scenes:
        for gi in sc["screens"]:
            title_of[gi] = sc["title"] or "第 %d 幕" % (sc["n"])
    lines = ["| 幕 | 屏 | 秒区间 | 帧区间 | 视频小节.拍 | 屏文字 |",
             "|:---:|:---:|:---:|:---:|:---:|:---|"]
    for s in screens:
        t = s["start"] * beat
        dur = s["beats"] * beat
        f0 = int(round(t * fps))
        f1 = int(round((t + dur) * fps))
        cell = s["text"].replace("|", "/")
        lines.append("| %s | %d | %.2f - %.2f | %d - %d | %d.%d | %s |"
                     % (title_of[s["gi"]], s["gi"] + 1, t, t + dur, f0, f1,
                        s["start"] // meter + 1, s["start"] % meter + 1, cell))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description="把一屏一句的文案排到音乐拍网格上, 产出 plan.json 与 plan.md")
    ap.add_argument("script", help="文案表 markdown 路径")
    ap.add_argument("--bpm", type=float, default=100.0, help="配乐 BPM, 拍表唯一来源")
    ap.add_argument("--bars", nargs="+", default=None, metavar="N|RANGE",
                    help="音乐总小节数写一个整数, 或者写与 cutmusic.py 同语法的小节播放表: "
                         "a / a-b / a-end, 逗号与空格都作分隔, 顺序即播放顺序且可重复, "
                         "例如 \"5-21,14-30,75-end\"; 本参数会吃掉紧随其后的空格分隔值, "
                         "所以文案表路径要写在最前面. 不给就按内容所需定")
    ap.add_argument("--source-bars", dest="source_bars", type=int, default=None,
                    help="原曲总小节数, 只用于把播放表里的 end 解析成定长 (与 cutmusic.py 一致) "
                         "并校验越界; 不给时 end 是开放尾段, 长度由排程所需决定")
    ap.add_argument("--meter", type=int, default=4, help="每小节拍数")
    ap.add_argument("--anchor", action="append", default=None,
                    help="屏号:小节号, 小节号从 1 开始, 把该屏钉在指定小节的下拍, 可重复; "
                         "给了播放表时小节号是原曲小节号, 按它在播放表里的首次出现换算")
    ap.add_argument("--fix", action="append", default=None, help="屏号:拍数, 覆盖该屏的公式拍数, 可重复")
    ap.add_argument("--fps", type=int, default=30, help="帧率, 用于换算 frame0 与 frame1")
    ap.add_argument("--json", dest="json_path", default=os.path.join("temp", "plan.json"),
                    help="排程结果 json 的路径, json 里的 bar 与 beat_in_bar 都是 0 基")
    ap.add_argument("--md", dest="md_path", default=os.path.join("temp", "plan.md"),
                    help="分镜表 md 的路径, 表里的 视频小节.拍 是 1 基")
    a = ap.parse_args()

    if not os.path.exists(a.script):
        print("找不到文案表: %s" % a.script)
        return 2
    if a.bpm <= 0 or a.meter < 1 or a.fps < 1:
        print("--bpm --meter --fps 必须是正数")
        return 2
    if a.source_bars is not None and a.source_bars < 1:
        print("--source-bars 至少为 1")
        return 2
    try:
        bars_total, bars_spec = parse_bars_spec(a.bars)
    except BarsError as e:
        print(str(e))
        return 2
    segs, fixed_total, open_src = None, None, None
    if bars_spec is not None:
        try:
            segs, fixed_total, open_src = build_play(bars_spec, a.source_bars)
        except BarsError as e:
            print(str(e))
            return 2

    scenes, skipped = parse_script(a.script)
    if not scenes:
        print("%s 里没有解析到任何屏, 检查是否用了 ## 标题与 | 屏号 | 屏文字 | 表格" % a.script)
        return 2

    beat = 60.0 / a.bpm
    bar = a.meter * beat

    screens = []
    for si, sc in enumerate(scenes):
        sc["n"] = si + 1
        sc["screens"] = []
        for text in sc["texts"]:
            screens.append({"gi": len(screens), "disp": len(sc["screens"]) + 1, "text": text,
                            "units": units_of(text), "beats": beats_of(text, beat),
                            "scene": si, "start": 0})
            sc["screens"].append(screens[-1]["gi"])

    fixes = parse_pairs(a.fix, "--fix")
    for ref, n in fixes.items():
        gi = resolve(ref, screens)
        if gi is None:
            print("--fix %d 找不到对应屏, 全表共 %d 屏" % (ref, len(screens)))
            return 2
        if n < 1:
            print("--fix %d:%d 的拍数至少为 1" % (ref, n))
            return 2
        screens[gi]["beats"] = n

    anchors = {}
    anchor_map = {}
    for ref, b in parse_pairs(a.anchor, "--anchor").items():
        gi = resolve(ref, screens)
        if gi is None:
            print("--anchor %d 找不到对应屏, 全表共 %d 屏" % (ref, len(screens)))
            return 2
        if b < 1:
            print("--anchor %d:%d 的小节号从 1 开始" % (ref, b))
            return 2
        # 有播放表时, --anchor 的小节号是原曲小节号, 取它在播放表里的首次出现位置
        vb = b - 1
        if segs is not None:
            vb = src_to_video(segs, b - 1)
            if vb is None:
                print("--anchor %d:%d 的原曲第 %d 小节不在播放表里, 播放表覆盖的原曲小节: %s"
                      % (ref, b, b, ", ".join(plan_parts(segs))))
                print("锚点的小节号要落在播放表给出的原曲区间内; 想锚到别的原曲小节, "
                      "请把覆盖它的区间写进 --bars, 再按它在播放表里的首次出现换算")
                return 2
        anchors[gi] = vb
        anchor_map[gi] = (vb, b - 1)

    cursor, free_start, lead = layout(screens, scenes, a.meter, anchors)
    if cursor is None:
        return 2
    content_bars = cursor // a.meter
    if bars_total is not None:
        music_bars = bars_total
    elif open_src is None:
        music_bars = fixed_total
    else:
        # 开放尾段: 截到排程所需, 最少留 1 小节, 锚点已经把屏推到更后面时也要够长
        music_bars = max(fixed_total + 1, content_bars)
    if cursor > music_bars * a.meter:
        report_shortage(screens, music_bars, a.meter, bar, beat, segs)
        return 1
    fill_rest(screens, scenes, free_start, music_bars, a.meter, lead)

    src_map = video_to_src(segs, music_bars) if segs is not None else list(range(music_bars))
    duration = music_bars * bar
    plan = {"bpm": a.bpm, "beat": round(beat, 6), "bar": round(bar, 6), "meter": a.meter,
            "bars": music_bars, "fps": a.fps, "duration": round(duration, 6), "scenes": []}
    plan["bars_plan"] = None if segs is None else bars_plan_of(segs, music_bars)
    plan["source_bars"] = src_map
    for sc in scenes:
        item = {"n": sc["n"], "title": sc["title"], "screens": []}
        for gi in sc["screens"]:
            s = screens[gi]
            t = s["start"] * beat
            dur = s["beats"] * beat
            item["screens"].append({
                "n": gi + 1, "text": s["text"], "units": s["units"], "beats": s["beats"],
                "t": round(t, 6), "dur": round(dur, 6),
                "bar": s["start"] // a.meter, "beat_in_bar": s["start"] % a.meter,
                "frame0": int(round(t * a.fps)), "frame1": int(round((t + dur) * a.fps)),
                "src_bar": src_map[s["start"] // a.meter], "src_beat_in_bar": s["start"] % a.meter})
        # 幕上能对回原曲小节号的字段: 该幕首屏起点的原曲小节号
        item["src_bar"] = src_map[screens[sc["screens"][0]]["start"] // a.meter]
        plan["scenes"].append(item)

    for path in (a.json_path, a.md_path):
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
    # plan.json 是场景模块的段落边界唯一来源, 也原子写: 写一半被中断会留下截断 JSON,
    # 场景模块的 load_plan 虽然容错, 但会让整条片退回常量段表, 时间轴全错
    tmp = a.json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    os.replace(tmp, a.json_path)
    write_md(a.md_path, screens, scenes, beat, a.meter, a.fps)

    print("输入 %s: %d 幕 %d 屏, 跳过 %d 行" % (a.script, len(scenes), len(screens), skipped))
    print("BPM %.2f, 拍 %.1f ms, 小节 %.3f s, 每小节 %d 拍" % (a.bpm, beat * 1000, bar, a.meter))
    if bars_total is None and segs is None:
        print("未给 --bars, 按内容所需 %d 小节定总时长" % music_bars)
    print("wrote %s" % a.json_path)
    print("wrote %s" % a.md_path)
    print("总时长 %.2f s (约 %.0f 帧), 内容需要 %d 小节, 音乐 %d 小节, 差额 %+d 小节"
          % (duration, duration * a.fps, content_bars, music_bars, music_bars - content_bars))
    if segs is not None:
        print("播放表 (1 基, 逐小节映射见 plan.json 的 source_bars):")
        for v0, s0, n in segs:
            cnt = (music_bars - v0) if n is None else n
            if n is None:
                src_txt = "%d-end (开放尾段, 按排程所需截到原曲第 %d 小节)" % (s0 + 1, s0 + cnt)
            else:
                src_txt = "%d" % (s0 + 1) if cnt == 1 else "%d-%d" % (s0 + 1, s0 + cnt)
            print("  视频 %d-%d -> 原曲 %s" % (v0 + 1, v0 + cnt, src_txt))
        if open_src is None:
            print("播放表共 %d 小节, 内容需要 %d 小节, 差 %+d 小节"
                  % (music_bars, content_bars, music_bars - content_bars))
        else:
            print("播放表共 %d 小节 (其中开放尾段 %d 小节), 内容需要 %d 小节, 差 %+d 小节"
                  % (music_bars, music_bars - fixed_total, content_bars, music_bars - content_bars))
    for gi in sorted(anchor_map):
        vb, sb = anchor_map[gi]
        print("锚点 第 %d 屏 -> 视频 第 %d 小节 -> 原曲 第 %d 小节" % (gi + 1, vb + 1, sb + 1))
    warn_thin_content(rest_targets(scenes, free_start), music_bars * a.meter - cursor,
                      content_bars, music_bars, a.meter, beat, bar, segs)
    return 0


if __name__ == "__main__":
    sys.exit(main())

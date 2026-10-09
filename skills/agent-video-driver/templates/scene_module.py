# -*- coding: utf-8 -*-
"""
场景模块骨架, 复制到项目里改内容即可

  python scene_module.py probe                 出代表帧做构图核对
  python scene_module.py render 0 810          渲染帧区间, 供分区间并行
  python scene_module.py segments              打印每段起止帧核对
  python scene_module.py plan [进程数]         打印并行渲染的帧区间与逐区间命令
  python scene_module.py at <段号>:<拍号>      渲该拍的单帧全分辨率, 用于逐场审阅
  python scene_module.py stills <段号> [帧数]  该段等距抽若干帧拼一张长图
  python scene_module.py screen <屏号>         屏号反查幕号与场景函数, 不给屏号打全表

plan 不给进程数时取 scripts/resources.py 的建议, 导入不到就退回内置规则
每个区间要用独立的进程各跑各的, 不要用共享队列 (沙箱会拦命名管道)

段落边界有两种来源, 优先级从高到低
  1 temp/plan.json (由 scripts/timing.py 从屏文案表排出), 幕边界即段落边界
  2 本文件顶部的 SEG 常量
无论用哪一种, 渲染前都要跑一次 segments 打印起止帧核对

一个场景函数对应一幕, 不是一屏: 幕内有多屏时必须在函数内部用 sub(t) 取当前屏序再分支,
不分支的话同幕第二屏会被第一屏的画法整个盖掉, 上屏内容永远不出现, 而且不报错.

逐场审阅的顺序建议: 底板与环境光 -> 主体 -> 运动 -> 版面家具, 每一档先用 at 看一帧,
一段做完用 stills 抽多帧看时间轴, 最后才跑 probe 与全量渲染.
"""
import os
import sys
import json
import math

from PIL import Image

import canvas as cv

# scripts/resources.py 是可选的, 单独把这个模板复制走也要能跑
try:
    import resources
except ImportError:
    resources = None

# ----------------------------------------------------------------- 时间栅格
# 画面切点必须与配乐切点完全一致, 两者都从这里取值
BPM = 100.0
DUR = 108.0
cv.configure(BPM=BPM, DUR=DUR, FRAMES=os.path.join("temp", "frames_proj"))
BEAT, BAR = cv.BEAT, cv.BAR

SEG = [k * BAR for k in (0, 3, 7, 11, 15, 21, 27, 33, 38, 43, 45)]
CUTS = SEG[1:]
cv.configure(CUTS=CUTS)

PLAN = os.path.join("temp", "plan.json")

# 并行渲染进程数的内置回退规则: clamp(floor(逻辑核数 / WORKERS_DIV), 1, WORKERS_MAX)
# 上限 4 与本技能既有的并行渲染约定一致, 也见 scripts/resources.py
WORKERS_DIV = 4
WORKERS_MAX = 4

# 段落调度边界, 与音乐栅格 SEG 是两件事
# 没有 plan.json 时用这份演示值: 3 个场景函数对应 3 段
SEG_OF_DEMO = [0.0, SEG[1], SEG[2], DUR]

# 每一幕的屏数, 要与 script.md 的屏数一致; 第 1 幕给 2 屏用来演示幕内多屏的屏序分支
# 有 temp/plan.json 时屏起点直接读它, 这份常量只在读不到时兜底
SCREEN_COUNT = [1, 2, 1]

# ----------------------------------------------------------------- 调色板
# 换风格只改这一块与背景三色, 风格库见 references/styles.md
ACC = cv.CYAN
ACC2 = cv.AMBER
ACC3 = cv.GREEN
TXT = cv.WHITE
DIM = cv.DIM


def setup():
    cv.ensure_bg(force=True, top=(9, 17, 35), bot=(2, 4, 9), light=(8, 19, 38))


def load_plan(path=None):
    """
    有 plan.json 就返回它的幕边界秒数组, 没有就返回 None
    数组长度比幕数多 1, 末项是片尾
    """
    path = path or PLAN
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    starts = []
    for sc in p.get("scenes", []):
        screens = sc.get("screens") or []
        if screens:
            starts.append(float(screens[0]["t"]))
    if not starts:
        return None
    dur = float(p.get("duration") or DUR)
    return starts + [dur]


SEG_OF = load_plan() or SEG_OF_DEMO


def caption(c, lb, k, text, color=TXT, size=36, y=900.0):
    cv.caption(c, lb, k, text, color=color, size=size, y=y)


# ----------------------------------------------------------------- 段落
def s_title(c, t):
    """标题段, 元素分别落在第 1, 3, 5 拍"""
    lb = t / BEAT
    cv.motes(c, t, 0.8)
    a = cv.beat_on(lb, 1.0, 0.7)
    if a > 0:
        # impact 让光晕在落位瞬间过冲一下再回落, 读起来像"按下去"; 它不是 alpha, 用前先 clamp
        imp = cv.impact(a)
        c.bloom((cv.W / 2, 372), 1100, (34, 74, 130), 0.30 * min(imp, 1.6) * a)
        # 字号由目标宽度反解, 换一个更长的标题也不会撑出画幅;
        # 纵向用 text_cap 按字高带对齐, 中英混排时比 mm 锚点稳
        size = cv.fit_size("主标题写这里", cv.W * 0.62)
        c.text_cap((cv.W / 2, 372), "主标题写这里", size, TXT, a, cap="center", halign="m")
    b = cv.beat_on(lb, 3.0, 0.7)
    if b > 0:
        c.text((cv.W / 2, 560), "副标题写这里", 42, ACC, b * 0.95, anchor="mm")
    caption(c, lb, 5.0, "一句点题的短句", DIM, 30, y=800)


def s_chart(c, t):
    """图表段, 曲线按拍生长; 本幕 2 屏, 用 sub(t) 分支 (幕内多屏的写法示范)"""
    k = act_of(t)
    u = t - SEG_OF[k]
    lb = u / BEAT
    cv.motes(c, t, 0.6)
    cv.section(c, t, "01", "小节标题", "section subtitle", ACC, appear=SEG_OF[k])
    if sub(t) == 1:
        # 第二屏换一套画法; 不分支的话这里画的东西会被下面第一屏的内容盖掉
        b2 = cv.beat_on(lb, 1.0, 0.8)
        if b2 > 0:
            c.text_cap((cv.W / 2, 520), "第二屏的内容", 64, ACC2, b2, cap="center", halign="m")
        caption(c, lb, 4.0, "第二屏的结论", TXT, 36, y=884)
        return
    pa = cv.beat_on(lb, 1.0, 0.8)
    if pa > 0:
        c.rrect((300, 236, 1180, 812), 14, fill=cv.PANEL, falpha=0.55 * pa,
                outline=cv.EDGE, ow=1.4, oalpha=0.9 * pa)
        x0, y0, x1, y1 = 330, 266, 1150, 778
        c.gline((x0, y1), (x1, y1), TXT, 2.2, pa * 0.85, glow=0.5)
        c.gline((x0, y0), (x0, y1), TXT, 2.2, pa * 0.85, glow=0.5)
        na = cv.beat_on(lb, 3.0, 1.2)
        if na > 0:
            pts = [(cv.lerp(x0, x1, i / 80.0),
                    cv.lerp(y1, y0, 1 - (1 - i / 80.0) ** 1.9)) for i in range(81)]
            n = max(2, int(81 * cv.eo(cv.seg(lb, 3.0, 7.6))))
            for i in range(n - 1):
                c.gline(pts[i], pts[i + 1], ACC, 4.2, na, glow=1.0)
    caption(c, lb, 8.0, "结论写这里", TXT, 36, y=884)


SCENES = [s_title, s_chart, s_chart]


def act_of(t):
    """
    时间 t 落在第几幕 (从 0 起); 区间左闭右开, pick 与 sub 都走这一套边界
    幕边界只来自 SEG_OF, 不要在这里另算一份
    """
    if t < SEG_OF[1]:
        return 0
    for j in range(len(SEG_OF) - 1):
        if SEG_OF[j] <= t < SEG_OF[j + 1]:
            return j
    return len(SEG_OF) - 2


def pick(t):
    """
    区间映射, 幕号取自 act_of
    区间写成左闭右开, 否则切点那一帧画的会是上一段
    """
    k = act_of(t)
    return SCENES[k] if k < len(SCENES) else SCENES[-1]


def _plan_screens():
    """读 temp/plan.json 的逐幕屏起点秒; 读不到或格式不对时返回 None"""
    if not os.path.exists(PLAN):
        return None
    try:
        with open(PLAN, encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, ValueError):
        return None
    out = []
    for sc in p.get("scenes", []):
        try:
            ts = [float(s["t"]) for s in (sc.get("screens") or [])]
        except (KeyError, TypeError, ValueError):
            continue
        if ts:
            out.append(ts)
    return out or None


def screen_starts(k):
    """
    第 k 幕各屏的起点秒; 优先取 plan.json, 取不到就按该幕时长等分 SCREEN_COUNT[k]
    返回数组长度等于该幕屏数, 至少 1 项
    """
    sp = seg_span(k)
    if sp is None:
        return [0.0]
    ps = _plan_screens()
    if ps is not None and k < len(ps):
        return ps[k]
    n = max(1, int(SCREEN_COUNT[k]) if k < len(SCREEN_COUNT) else 1)
    a, b = sp
    return [a + (b - a) * i / n for i in range(n)]


def sub(t):
    """
    当前是这一幕的第几屏 (从 0 起), 一幕一屏时恒为 0

    一个场景函数对应一幕而不是一屏, 幕内多屏必须按它分支: 同幕第二屏不分支的话
    会被第一屏的画法整个盖掉, 上屏内容永远不出现, 而且不报错
    """
    n = 0
    for i, s in enumerate(screen_starts(act_of(t))):
        if t >= s:
            n = i
    return n


def cam(t):
    return cv.camera_settle(t, CUTS, amount=0.022, tau=0.5, drift=0.012)


def render(a, b):
    cv.render_range(pick, a, b, cam)


def print_segments():
    """
    逐段打印起止秒与起止帧, 差一段整片错位
    段数与 SCENES 长度不一致时必须先改到这里一致再渲染
    段表本身也在这里体检: 非单调或越过片长都是硬错误, 不体检的话会渲出空段或截断段
    """
    src = "temp/plan.json" if os.path.exists(PLAN) else "SEG_OF_DEMO 常量"
    print("段落来源: %s   共 %d 段, %d 个场景函数" % (src, len(SEG_OF) - 1, len(SCENES)))
    if len(SEG_OF) - 1 != len(SCENES):
        print("  警告: 段数与场景函数个数不一致, SCENES 必须先改到与段落表一一对应", flush=True)
    for j in range(len(SEG_OF) - 1):
        if SEG_OF[j + 1] <= SEG_OF[j]:
            print("  错误: 段 %02d 的终点 %.3f 不大于起点 %.3f, 段表必须严格递增"
                  % (j, SEG_OF[j + 1], SEG_OF[j]), flush=True)
    if SEG_OF[-1] > cv.DUR + 1e-6:
        print("  错误: 段表终点 %.3f 秒越过片长 %.3f 秒, 先改段表或改时长"
              % (SEG_OF[-1], cv.DUR), flush=True)
    for j in range(len(SEG_OF) - 1):
        a, b = SEG_OF[j], SEG_OF[j + 1]
        print("  段 %02d  %.3f 到 %.3f 秒   帧 %d 到 %d   共 %d 帧"
              % (j, a, b, int(round(a * cv.FPS)), int(round(b * cv.FPS)),
                 int(round(b * cv.FPS)) - int(round(a * cv.FPS))))


def split_ranges(total, n):
    """
    把 [0, total) 均匀切成 n 段, 余数分给靠前的区间
    每段至少 1 帧, 不会出现空区间
    """
    n = max(1, min(int(n), max(1, int(total))))
    base, rem = divmod(int(total), n)
    out = []
    a = 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append((a, a + size))
        a += size
    return out


def resolve_workers(explicit=None):
    """
    并行渲染进程数: 命令行给定优先, 其次取 scripts/resources.py 的建议
    导入不到 resources 时退回内置规则 clamp(floor(逻辑核数 / 4), 1, 4)
    返回 (进程数, 来源说明)
    """
    if explicit is not None:
        return max(1, int(explicit)), "命令行给定"
    if resources is not None:
        try:
            return max(1, int(resources.suggest_workers())), "resources.py 的建议"
        except Exception as e:
            why = "resources.py 调用失败 (%s)" % str(e)[:50]
    else:
        why = "没有导入到 resources.py"
    n = os.cpu_count() or 1
    return max(1, min(WORKERS_MAX, n // WORKERS_DIV)), "内置规则, %s" % why


def print_plan(explicit=None):
    """
    打印并行渲染的分工: 进程数, 每个进程的帧区间与帧数, 以及可直接复制的命令行
    进程数按 resources.py 的建议或命令行给定值取, 区间按 cv.nframes() 均匀切分
    """
    total = cv.nframes()
    workers, src = resolve_workers(explicit)
    ranges = split_ranges(total, workers)
    print("并行渲染进程数: %d   (%s)" % (len(ranges), src))
    print("总帧数 %d, 区间左闭右开, 拼起来正好是 [0, %d)" % (total, total))
    for i, (a, b) in enumerate(ranges):
        print("  区间 %02d  [%d, %d)   共 %d 帧" % (i, a, b, b - a))
    print("每个区间一条命令, 复制即可:")
    for a, b in ranges:
        print("  python scene_module.py render %d %d" % (a, b))
    print("提醒: 每个区间要用独立的进程各跑各的, 不要用共享队列"
          " (沙箱会拦命名管道, multiprocessing 直接 WinError 5)")
    print("提醒: 机器空闲时可以再提高进程数, 例如 python scene_module.py plan 8")


def seg_span(k):
    """第 k 段的 (起点秒, 终点秒); 段号越界时给出可用范围并返回 None"""
    if k < 0 or k + 1 >= len(SEG_OF):
        print("段号越界: %d, 可用范围是 0 到 %d" % (k, len(SEG_OF) - 2))
        return None
    return SEG_OF[k], SEG_OF[k + 1]


def shot_at(spec):
    """
    渲该拍的单帧全分辨率, spec 形如 3:1.5 (第 3 段第 1.5 拍)

    逐场实现时用它确认底板, 主体, 运动, 版面家具每一档的落点, 比整段渲一遍便宜得多
    """
    if ":" not in spec:
        print("用法: python scene_module.py at <段号>:<拍号>, 例如 3:1.5")
        return 2
    head, _, tail = spec.partition(":")
    try:
        k = int(head)
        beat = float(tail)
    except ValueError:
        print("段号要是整数, 拍号可以是小数: %s" % spec)
        return 2
    sp = seg_span(k)
    if sp is None:
        return 2
    t = sp[0] + beat * cv.BEAT
    if t >= sp[1]:
        print("警告: 第 %s 拍落在段尾之外 (段长 %.3f 拍), 渲的是段尾之前的内容"
              % (beat, (sp[1] - sp[0]) / cv.BEAT))
    frame = int(round(t * cv.FPS))
    os.makedirs("temp", exist_ok=True)
    path = os.path.join("temp", "at_%02d_%s.png" % (k, tail.replace(".", "p")))
    cv.audit_start()
    cv.render_frame(pick, t, cam(t)).save(path)
    cv.audit_report("单帧 段 %02d 第 %s 拍 (帧 %d)" % (k, beat, frame))
    cv.audit_stop()
    print("段 %02d 第 %s 拍 = %.3f 秒 = 第 %d 帧" % (k, beat, t, frame))
    print("wrote %s" % path)
    return 0


def stills(k, n=7, width=480):
    """
    该段等距抽 n 帧横向拼成一张长图, 用来看时间轴

    单帧看不出缓动对不对, 抽帧长图能把入场顺序与错帧一眼看完
    """
    sp = seg_span(k)
    if sp is None:
        return 2
    n = max(2, int(n))
    a, b = sp
    ts = [a + (b - a) * (i + 0.5) / n for i in range(n)]
    cv.audit_start()
    frames = [cv.render_frame(pick, t, cam(t)) for t in ts]
    cv.audit_report("抽帧长图 段 %02d" % k)
    cv.audit_stop()
    h = max(1, int(round(frames[0].height * width / float(frames[0].width))))
    sheet = Image.new("RGB", (width * n, h), (0, 0, 0))
    for i, im in enumerate(frames):
        sheet.paste(im.resize((width, h), Image.LANCZOS), (i * width, 0))
    os.makedirs("temp", exist_ok=True)
    path = os.path.join("temp", "stills_%02d.png" % k)
    sheet.save(path)
    print("段 %02d  %.3f 到 %.3f 秒, 等距抽 %d 帧" % (k, a, b, n))
    for i, t in enumerate(ts):
        print("  第 %d 格  第 %d 帧  %.3f 秒  段内第 %.2f 拍"
              % (i, int(round(t * cv.FPS)), t, (t - a) / cv.BEAT))
    print("wrote %s" % path)
    return 0


def screen_rows():
    """
    全局屏表: 从第 1 幕第 1 屏起跨幕连续编号, 每项含幕号, 幕内序, 起止秒与场景函数名
    屏起点来自 plan.json 或 SCREEN_COUNT 等分, 与 sub(t) 用的是同一份来源
    """
    rows = []
    n = 0
    for k in range(len(SEG_OF) - 1):
        ts = screen_starts(k)
        sp = seg_span(k)
        act_end = sp[1] if sp else cv.DUR
        fn = SCENES[k].__name__ if k < len(SCENES) else "?"
        for i, t in enumerate(ts):
            n += 1
            end = ts[i + 1] if i + 1 < len(ts) else act_end
            rows.append({"n": n, "act": k, "sub": i, "scene": fn,
                         "t0": t, "t1": end})
    return rows


def _plan_screen_texts():
    """从 plan.json 读每幕每屏的上屏文字; 读不到返回 None"""
    if not os.path.exists(PLAN):
        return None
    try:
        with open(PLAN, encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, ValueError):
        return None
    out = []
    for sc in p.get("scenes", []):
        texts = []
        for s in (sc.get("screens") or []):
            texts.append(str(s.get("text", "") or ""))
        out.append(texts)
    return out or None


def print_screen(n=None):
    """
    屏号反查: 回答 第 N 屏属于哪一幕的哪一屏, 对应哪个场景函数

    全局屏号与幕号不是线性对应 (幕内屏数不均), 凭幕号往回推屏号是返工根源;
    改任何一屏之前先跑这条命令确认位置, 不要从验收表行号猜幕号
    """
    rows = screen_rows()
    texts = _plan_screen_texts()
    if n is not None and not (1 <= n <= len(rows)):
        print("屏号越界: %s, 可用范围是 1 到 %d" % (n, len(rows)))
        return 2
    print("段落来源: %s   共 %d 屏" % ("temp/plan.json" if os.path.exists(PLAN)
                                       else "SCREEN_COUNT 等分", len(rows)))
    hdr = "屏号 | 幕 | 幕内序 | 场景函数 | 起止秒 | 起止帧 | 屏文字"
    print(hdr)
    for r in rows:
        if n is not None and r["n"] != n:
            continue
        text = ""
        if texts is not None and r["act"] < len(texts) and r["sub"] < len(texts[r["act"]]):
            text = texts[r["act"]][r["sub"]]
        print("%4d | %2d | %3d | %s | %.3f 到 %.3f | %d 到 %d | %s"
              % (r["n"], r["act"] + 1, r["sub"] + 1, r["scene"],
                 r["t0"], r["t1"], int(round(r["t0"] * cv.FPS)),
                 int(round(r["t1"] * cv.FPS)) - 1, text))
    if n is not None:
        r = rows[n - 1]
        print("改这一屏就改 %s(), 渲染区间是帧 %d 到 %d, 重渲后对对应批次 --redo"
              % (r["scene"], int(round(r["t0"] * cv.FPS)),
                 int(round(r["t1"] * cv.FPS)) - 1))
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    # plan 与 screen 只读表不画帧, 不必构建背景
    if mode == "plan":
        n = None
        if len(sys.argv) > 2:
            try:
                n = int(sys.argv[2])
            except ValueError:
                print("进程数必须是整数: %s" % sys.argv[2])
                sys.exit(2)
        print_plan(n)
        return
    if mode == "screen":
        n = None
        if len(sys.argv) > 2:
            try:
                n = int(sys.argv[2])
            except ValueError:
                print("屏号必须是整数: %s" % sys.argv[2])
                sys.exit(2)
        sys.exit(print_screen(n))
    setup()
    cv.configure(CUTS=SEG_OF[1:])
    if mode == "segments":
        print_segments()
        return
    if mode == "at":
        if len(sys.argv) < 3:
            print("用法: python scene_module.py at <段号>:<拍号>, 例如 3:1.5")
            sys.exit(2)
        sys.exit(shot_at(sys.argv[2]))
    if mode == "stills":
        k = 0
        n = 7
        if len(sys.argv) > 2:
            try:
                k = int(sys.argv[2])
            except ValueError:
                print("段号必须是整数: %s" % sys.argv[2])
                sys.exit(2)
        if len(sys.argv) > 3:
            try:
                n = int(sys.argv[3])
            except ValueError:
                print("帧数必须是整数: %s" % sys.argv[3])
                sys.exit(2)
        sys.exit(stills(k, n))
    if mode == "probe":
        print_segments()
        os.makedirs(os.path.join("temp", "probe"), exist_ok=True)
        # 试渲染也开字形审计: 代表帧只覆盖部分时刻, 但能把大部分缺字形问题提前暴露出来,
        # 比等到全量渲染完再发现便宜得多
        cv.audit_start()
        total = cv.nframes()
        for i in range(0, total, max(1, total // 24)):
            img = cv.render_frame(pick, i / cv.FPS, cam(i / cv.FPS))
            img.save(os.path.join("temp", "probe", "p%05d.png" % i))
            print("probe", i, flush=True)
        cv.audit_report("probe 代表帧")
        cv.audit_stop()
        return
    a = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    b = int(sys.argv[3]) if len(sys.argv) > 3 else cv.nframes()
    print("将渲染 [%d, %d) 共 %d 帧" % (a, b, b - a), flush=True)
    render(a, b)


if __name__ == "__main__":
    main()

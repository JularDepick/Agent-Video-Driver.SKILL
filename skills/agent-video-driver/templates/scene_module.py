# -*- coding: utf-8 -*-
"""
场景模块骨架, 复制到项目里改内容即可

  python scene_module.py probe                 出代表帧做构图核对
  python scene_module.py render 0 810          渲染帧区间, 供分区间并行
  python scene_module.py segments              打印每段起止帧核对
  python scene_module.py plan [进程数]         打印并行渲染的帧区间与逐区间命令

plan 不给进程数时取 scripts/resources.py 的建议, 导入不到就退回内置规则
每个区间要用独立的进程各跑各的, 不要用共享队列 (沙箱会拦命名管道)

段落边界有两种来源, 优先级从高到低
  1 temp/plan.json (由 scripts/timing.py 从屏文案表排出), 幕边界即段落边界
  2 本文件顶部的 SEG 常量
无论用哪一种, 渲染前都要跑一次 segments 打印起止帧核对
"""
import os
import sys
import json
import math

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
        c.bloom((cv.W / 2, 404), 1100, (34, 74, 130), 0.30 * a)
        c.text((cv.W / 2, 404 + cv.lerp(28, 0, a)), "主标题写这里", 96, TXT, a, anchor="mm")
    b = cv.beat_on(lb, 3.0, 0.7)
    if b > 0:
        c.text((cv.W / 2, 492), "副标题写这里", 42, ACC, b * 0.95, anchor="mm")
    caption(c, lb, 5.0, "一句点题的短句", DIM, 30, y=800)


def s_chart(c, t):
    """图表段, 曲线按拍生长"""
    u = t - SEG_OF[1]
    lb = u / BEAT
    cv.motes(c, t, 0.6)
    cv.section(c, t, "01", "小节标题", "section subtitle", ACC, appear=SEG_OF[1])
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


def pick(t):
    """
    区间映射, 首段在 [0, SEG_OF[0]) 内, 其余依次顺延
    区间写成左闭右开, 否则切点那一帧画的会是上一段
    """
    k = 0
    if t >= SEG_OF[1]:
        k = len(SCENES) - 1
        for j in range(len(SEG_OF) - 1):
            if SEG_OF[j] <= t < SEG_OF[j + 1]:
                k = j
                break
    return SCENES[k]


def cam(t):
    return cv.camera_settle(t, CUTS, amount=0.022, tau=0.5, drift=0.012)


def render(a, b):
    cv.render_range(pick, a, b, cam)


def print_segments():
    """
    逐段打印起止秒与起止帧, 差一段整片错位
    段数与 SCENES 长度不一致时必须先改到这里一致再渲染
    """
    src = "temp/plan.json" if os.path.exists(PLAN) else "SEG_OF_DEMO 常量"
    print("段落来源: %s   共 %d 段, %d 个场景函数" % (src, len(SEG_OF) - 1, len(SCENES)))
    if len(SEG_OF) - 1 != len(SCENES):
        print("  警告: 段数与场景函数个数不一致, SCENES 必须先改到与段落表一一对应", flush=True)
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    # plan 只算分工不画帧, 不必构建背景
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
    setup()
    cv.configure(CUTS=SEG_OF[1:])
    if mode == "segments":
        print_segments()
        return
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

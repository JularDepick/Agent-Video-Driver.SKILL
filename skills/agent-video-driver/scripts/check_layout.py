# -*- coding: utf-8 -*-
"""
静态版面体检: 从场景模块里抽出全部文字绘制调用, 两两检查墨迹框是否相交

  python scripts/check_layout.py scene_module.py
  python scripts/check_layout.py scene_module.py --gap-ratio 0.15
  python scripts/check_layout.py scene_module.py --width 1080 --height 1920
  python scripts/check_layout.py scene_module.py --json temp/qa/layout.json
  python scripts/check_layout.py scene_module.py --extra-call caption

为什么要有这一件: 字符图约 20px/列, 45 像素的纵向重叠在字符图上只差 2 列, 无视觉能力时
靠人眼几乎判不出来. 实测有片子出现"标题卡两行文字字高带重叠 3.5px"与"一行调试残留大字
与公式完全叠画"两处压字, 都是另写对账脚本才定位到的, 而构图核对当时显示全部正常.

判据分三档:
  硬撞  两个文本块的墨迹框 x 区间与 y 区间同时相交, 一定压字
  太挤  纵向不相交, 但间隙小于 gap_ratio x 较大那一块的字号
  未解析  位置或字号在静态上算不出来 (变量, f-string, 函数返回值), 列出来供人工核对

几何一律按**真实墨迹**算, 不按 cap 带: 中文字形占满 em 框, 墨迹高约字号的 1.0 倍,
而 cap_metrics 量的是拉丁字母 H 的字高带 (约 0.72em). 用 text_cap 做单行对齐是对的,
但拿 cap 带去反推相邻元素的纵向间距会重叠, 这也是上面第一处压字的成因.

本脚本只做静态检查: 它不执行场景模块, 也不渲染整帧. 抽不到的调用不是漏报, 是列进
未解析清单; 真正的兜底仍然是渲染后逐屏看字符图与拼图.
"""
import argparse
import ast
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 字体表与 canvas.FONT_PATH 同源; 拿不到 canvas 时用这张兜底表
FALLBACK_FONTS = {
    "cnb": r"C:\Windows\Fonts\msyhbd.ttc",
    "cn": r"C:\Windows\Fonts\msyh.ttc",
    "mono": r"C:\Windows\Fonts\consolab.ttf",
    "monor": r"C:\Windows\Fonts\consola.ttf",
}

# 文字绘制调用的参数位置: 0 是位置元组, 1 是字符串, 2 是字号或目标宽度
TEXT_CALLS = {
    "text": {"size": 2},
    "text_cap": {"size": 2},
    "rich": {"parts": 1, "size": 2},
    "text_fit": {"target_w": 2},
}
# 默认留白比例: 两个中文大字块之间的纵向间隙不低于较大那一块字号的这个倍数
DEFAULT_GAP_RATIO = 0.15
DEFAULT_ANCHOR = "la"
DEFAULT_KIND = "cnb"
# 分支排他: 同一个 if 的两侧不可能同时画出来
TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _is_terminating(body):
    """该语句块是不是必然中途离开 (return / raise / continue / break 收尾)"""
    if not body:
        return False
    return isinstance(body[-1], TERMINATORS)


def _stmt_lists(node):
    """该节点下的全部子语句列表 (含 try 的各 handler 体)"""
    out = []
    for field in ("body", "orelse", "finalbody"):
        v = getattr(node, field, None)
        if isinstance(v, list):
            out.append(v)
    for h in getattr(node, "handlers", None) or []:
        out.append(h.body)
    return out


def collect_scopes(tree):
    """
    给每个调用节点标上 (所属函数, 分支标签集合)

    两道过滤都靠它, 缺一条就会满屏误报:
      函数: 不同幕的函数 (s_title 与 s_chart) 从不在同一帧里出现, 不按函数分组会把
            整份场景模块里所有文字两两比一遍, 报出几十对根本没同时出现过的"压字"
      分支: 一幕多屏靠 sub(t) 分支, 同一个 if 的两侧互斥; 更常见的写法是
            `if sub(t) == 1: ...; return` 后面接默认屏, 于是"if 之后的同级语句"
            等价于 orelse, 也是互斥的一侧
    """
    scopes = {}

    def visit_exprs(node, cur, func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                continue  # 语句交给 walk_stmt, 否则嵌套分支里的调用会丢掉标签
            if isinstance(child, ast.Call):
                scopes.setdefault(id(child), (func, cur))
            visit_exprs(child, cur, func)

    def walk_stmts(stmts, cur, func):
        i = 0
        while i < len(stmts):
            st = stmts[i]
            if isinstance(st, ast.If):
                nid = id(st)
                term = _is_terminating(st.body)
                for s2 in st.body:
                    walk_stmt(s2, cur | {("in", nid)}, func)
                for s2 in st.orelse:
                    walk_stmt(s2, cur | {("else", nid)}, func)
                if term:
                    for s2 in stmts[i + 1:]:
                        walk_stmt(s2, cur | {("after", nid)}, func)
                    return
            else:
                walk_stmt(st, cur, func)
            i += 1

    def walk_stmt(st, cur, func):
        inner = func
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = st.name
        visit_exprs(st, cur, inner)
        for lst in _stmt_lists(st):
            walk_stmts(lst, cur, inner)

    walk_stmts(getattr(tree, "body", []), frozenset(), "<module>")
    return scopes


def exclusive(tags_a, tags_b):
    """两个标签集合是不是互斥的 (同一个 if 的两侧)"""
    for side_a, x in tags_a:
        for side_b, y in tags_b:
            if x != y:
                continue
            pair = {side_a, side_b}
            if pair == {"in", "else"} or pair == {"in", "after"}:
                return True
    return False


def load_canvas():
    """能 import canvas 就借它的字体表与画幅默认值, 拿不到就退回内置表"""
    try:
        import canvas as cv
        return cv
    except Exception:
        return None


def module_constants(path):
    """
    读模块级常量赋值, 返回 {名字: 表达式节点}

    返回节点而不是数值: 场景模块里常见 `SIZE_BIG = 120.0` 与 `SIZE_SUB = SIZE_BIG * 0.35`
    这种链式定义, 只收字面量会漏掉一半, 交给 Resolver 递归求值才收得全
    """
    out = {}
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError):
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if isinstance(tgt, ast.Name):
            out[tgt.id] = node.value
    return out


class Resolver:
    """
    把 ast 表达式解析成数值

    查名字的顺序是: 命令行覆盖, 场景模块自己的常量, theme.py 常量, 最后 canvas 全局量.
    场景模块优先于 theme.py: 工程里允许在场景模块顶部覆盖某个主题常量
    """

    def __init__(self, layers, cv, overrides=None):
        self.layers = layers
        self.cv = cv
        self.overrides = overrides or {}
        self.depth = 0

    def value(self, node):
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                return None
            return float(node.value)
        if isinstance(node, ast.Name):
            return self.name(node.id)
        if isinstance(node, ast.Attribute):
            # cv.W / cv.H / cv.OX 这类画幅量
            if self.cv is not None:
                v = getattr(self.cv, node.attr, None)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return float(v)
            return None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = self.value(node.operand)
            if v is None:
                return None
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            a = self.value(node.left)
            b = self.value(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return None if b == 0 else a / b
        return None

    def name(self, key):
        if key in self.overrides:
            return float(self.overrides[key])
        if self.depth > 8:
            return None
        for src in self.layers:
            if key in src:
                self.depth += 1
                try:
                    v = self.value(src[key])
                finally:
                    self.depth -= 1
                if v is not None:
                    return v
        if self.cv is not None:
            v = getattr(self.cv, key, None)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        return None


def kwarg(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def source_line(src_lines, node):
    try:
        return src_lines[node.lineno - 1].strip()
    except (IndexError, AttributeError):
        return ""


def ink_rect(s, x, y, size, kind, anchor, fonts, ss=2):
    """
    把一段文字渲染到局部小图里, 量出它相对锚点 (x, y) 的真实墨迹矩形

    不按公式推 anchor: 纵向有 a/t/m/s/b/d 六种, 横向有三种, 每种差小半个字身;
    直接让 Pillow 在局部图上按同一个 anchor 画一次, 再把墨迹框减回锚点, 结果就是精确的.
    局部图只在锚点附近, 与文字在画幅上的绝对位置无关, 所以开销很小.
    """
    path = fonts.get(kind)
    if not path or not os.path.exists(path):
        return None, "字体键 %s 没有可用字体文件" % kind
    px = max(6, int(round(size * ss)))
    font = ImageFont.truetype(path, px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    adv = int(probe.textlength(s, font=font)) + px
    # 局部图必须留够锚点两侧的余量: 锚点取 m 或 r 时, 墨迹会落在锚点左侧半个到一个行宽处,
    # 只按字号留边会让左边界截断墨迹, 量出来的框就偏了
    mx = adv + 16
    my = px * 2 + 24
    img = Image.new("L", (2 * mx + adv + 16, 4 * my), 0)
    ImageDraw.Draw(img).text((mx, my), s, font=font, fill=255, anchor=anchor)
    box = img.getbbox()
    if box is None:
        return None, "按该字体渲染不出墨迹 (空串或全为空白)"
    if box[0] <= 0 or box[1] <= 0 or box[2] >= img.width or box[3] >= img.height:
        return None, "墨迹顶到局部图边界, 字号或锚点异常"
    x0 = (box[0] - mx) / float(ss)
    y0 = (box[1] - my) / float(ss)
    x1 = (box[2] - mx) / float(ss)
    y1 = (box[3] - my) / float(ss)
    return {"left": x + x0, "top": y + y0, "right": x + x1, "bottom": y + y1}, ""


def fit_size(s, target_w, kind, fonts, track=0.0, lo=12.0, hi=240.0, iters=24):
    """复刻 canvas.fit_size 的二分反解, 让 text_fit 的字号也能静态算出来"""
    path = fonts.get(kind)
    if not path or not os.path.exists(path):
        return None

    def width(sz):
        f = ImageFont.truetype(path, max(6, int(round(sz))))
        return ImageDraw.Draw(Image.new("L", (8, 8))).textlength(s, font=f)

    if width(hi) <= target_w:
        return hi
    a, b = lo, hi
    for _ in range(iters):
        mid = (a + b) / 2.0
        if width(mid) < target_w:
            a = mid
        else:
            b = mid
    return (a + b) / 2.0


def cap_baseline(kind, size, cy, cap, fonts):
    """复刻 canvas.baseline_for_cap_centre / _top: 由字高带反推基线 y"""
    path = fonts.get(kind)
    if not path or not os.path.exists(path):
        return None
    f = ImageFont.truetype(path, max(6, int(round(size))))
    ascent = f.getmetrics()[0]
    _x0, y0, _x1, y1 = f.getbbox("H")
    top, bot = float(y0 - ascent), float(y1 - ascent)
    if cap == "top":
        return cy - top
    return cy - (top + bot) / 2.0


def collect_blocks(path, resolver, fonts, extra_calls, ss):
    """扫出全部文字绘制调用, 返回 (已解析块, 未解析清单)"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    tree = ast.parse(text, filename=path)
    src_lines = text.splitlines()
    scopes = collect_scopes(tree)
    names = dict(TEXT_CALLS)
    for extra in extra_calls:
        names[extra] = {"size": 2}

    blocks = []
    unresolved = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in names:
            continue
        spec = names[fn.attr]
        line = node.lineno
        snippet = source_line(src_lines, node)
        scope = scopes.get(id(node), ("<module>", ()))

        def push(b):
            b["func"] = scope[0]
            b["tags"] = scope[1]
            blocks.append(b)

        def bail(why, s_hint=""):
            unresolved.append({"line": line, "call": fn.attr, "why": why,
                               "text": s_hint, "source": snippet})

        if len(node.args) < 2:
            bail("位置或文本是关键字参数, 静态抽不到")
            continue
        pos = node.args[0]
        if not (isinstance(pos, ast.Tuple) and len(pos.elts) == 2):
            bail("位置不是二元元组字面量")
            continue
        x = resolver.value(pos.elts[0])
        y = resolver.value(pos.elts[1])
        if x is None or y is None:
            bail("位置的 x 或 y 算不出数值")
            continue

        kind_node = kwarg(node, "kind")
        kind = kind_node.value if isinstance(kind_node, ast.Constant) else DEFAULT_KIND
        if not isinstance(kind, str):
            kind = DEFAULT_KIND

        if "parts" in spec:
            parts = node.args[1]
            if not isinstance(parts, (ast.List, ast.Tuple)):
                bail("rich 的 parts 不是列表字面量")
                continue
            size_node = kwarg(node, "size") or (
                node.args[spec["size"]] if len(node.args) > spec["size"] else None)
            size = resolver.value(size_node) if size_node is not None else None
            if size is None:
                bail("rich 的字号算不出数值")
                continue
            cur = x
            for el in parts.elts:
                if not (isinstance(el, ast.Tuple) and len(el.elts) == 3):
                    bail("rich 的 parts 元素不是三元元组")
                    break
                s_el = el.elts[0]
                if not isinstance(s_el, ast.Constant) or not isinstance(s_el.value, str):
                    bail("rich 的 parts 里有非字面量文本")
                    break
                k_el = el.elts[1]
                kk = k_el.value if isinstance(k_el, ast.Constant) else kind
                rect, why = ink_rect(s_el.value, cur, y, size, kk, "ls", fonts, ss)
                if rect is None:
                    bail("rich 片段量不出墨迹: %s" % why, s_el.value)
                    break
                push({"line": line, "call": "rich", "text": s_el.value,
                      "kind": kk, "size": size, "anchor": "ls",
                      "rect": rect, "source": snippet})
                cur = rect["right"]
            continue

        s_node = node.args[1]
        if not isinstance(s_node, ast.Constant) or not isinstance(s_node.value, str):
            bail("文本不是字符串字面量 (拼接或变量)")
            continue
        s = s_node.value
        if not s.strip():
            continue

        track_node = kwarg(node, "track")
        track = resolver.value(track_node) if track_node is not None else 0.0
        track = track or 0.0

        if "target_w" in spec:
            tw_node = kwarg(node, "target_w") or (
                node.args[spec["target_w"]] if len(node.args) > spec["target_w"] else None)
            tw = resolver.value(tw_node) if tw_node is not None else None
            if tw is None:
                bail("text_fit 的目标宽度算不出数值", s)
                continue
            size = fit_size(s, tw, kind, fonts, track)
            if size is None:
                bail("text_fit 的字号反解失败 (字体缺失)", s)
                continue
            anchor_node = kwarg(node, "anchor")
            anchor = anchor_node.value if isinstance(anchor_node, ast.Constant) else DEFAULT_ANCHOR
            rect, why = ink_rect(s, x, y, size, kind, anchor, fonts, ss)
            if rect is None:
                bail("量不出墨迹: %s" % why, s)
                continue
            push({"line": line, "call": "text_fit", "text": s, "kind": kind,
                  "size": size, "anchor": anchor, "rect": rect, "source": snippet})
            continue

        size_node = kwarg(node, "size") or (
            node.args[spec["size"]] if len(node.args) > spec["size"] else None)
        size = resolver.value(size_node) if size_node is not None else None
        if size is None:
            bail("字号算不出数值", s)
            continue

        if fn.attr == "text_cap":
            cap_node = kwarg(node, "cap")
            cap = cap_node.value if isinstance(cap_node, ast.Constant) else "center"
            hal_node = kwarg(node, "halign")
            halign = hal_node.value if isinstance(hal_node, ast.Constant) else "l"
            if cap not in ("center", "top") or halign not in ("l", "m", "r"):
                bail("cap 或 halign 取值不认识", s)
                continue
            by = cap_baseline(kind, size, y, cap, fonts)
            if by is None:
                bail("字高带反推基线失败 (字体缺失)", s)
                continue
            anchor = halign + "s"
            rect, why = ink_rect(s, x, by, size, kind, anchor, fonts, ss)
            if rect is None:
                bail("量不出墨迹: %s" % why, s)
                continue
            push({"line": line, "call": "text_cap", "text": s, "kind": kind,
                  "size": size, "anchor": anchor, "rect": rect,
                  "cap": cap, "source": snippet})
            continue

        anchor_node = kwarg(node, "anchor")
        anchor = anchor_node.value if isinstance(anchor_node, ast.Constant) else DEFAULT_ANCHOR
        if not isinstance(anchor, str) or len(anchor) < 2:
            bail("anchor 取值不认识", s)
            continue
        rect, why = ink_rect(s, x, y, size, kind, anchor, fonts, ss)
        if rect is None:
            bail("量不出墨迹: %s" % why, s)
            continue
        push({"line": line, "call": fn.attr, "text": s, "kind": kind,
              "size": size, "anchor": anchor, "rect": rect, "source": snippet})

    return blocks, unresolved


def overlaps(a, b):
    return (a["left"] < b["right"] and b["left"] < a["right"]
            and a["top"] < b["bottom"] and b["top"] < a["bottom"])


def analyse(blocks, gap_ratio):
    """
    两两比较, 分三类收

    只在同一函数内比: 不同幕的函数不会同时出现在一帧里, 跨函数比全是误报
    同函数内再按分支排他过滤: 同一个 if 的两侧互斥, 分别归进 branch 清单只做提示
    """
    hits = []
    tight = []
    branch = []
    order = sorted(blocks, key=lambda b: b["rect"]["top"])
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            a, b = order[i], order[j]
            if a["func"] != b["func"]:
                continue
            ra, rb = a["rect"], b["rect"]
            x_hit = ra["left"] < rb["right"] and rb["left"] < ra["right"]
            if not x_hit:
                continue
            excl = exclusive(a["tags"], b["tags"])
            if overlaps(ra, rb):
                ox = min(ra["right"], rb["right"]) - max(ra["left"], rb["left"])
                oy = min(ra["bottom"], rb["bottom"]) - max(ra["top"], rb["top"])
                item = {"a": a, "b": b, "overlap_x": ox, "overlap_y": oy}
                (branch if excl else hits).append(item)
                continue
            if excl:
                continue
            gap = rb["top"] - ra["bottom"]
            if gap < 0:
                continue
            need = gap_ratio * max(a["size"], b["size"])
            if need > 0 and gap < need:
                tight.append({"a": a, "b": b, "gap": gap, "need": need})
    return hits, tight, branch


def preview(s, n=18):
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def print_report(blocks, unresolved, hits, tight, branch, gap_ratio):
    print("=" * 84)
    print("版面静态体检: 文字绘制调用 %d 处, 涉及 %d 个函数"
          % (len(blocks), len(set(b["func"] for b in blocks))))
    print("=" * 84)
    print("")
    print("%-5s %-14s %-9s %-18s %-6s %7s %-4s %17s" %
          ("行", "函数", "调用", "文本", "字体", "字号", "锚点", "y 区间"))
    for b in sorted(blocks, key=lambda x: (x["func"], x["rect"]["top"], x["line"])):
        r = b["rect"]
        print("%-5d %-14s %-9s %-18s %-6s %7.1f %-4s %7.1f 到 %-7.1f" %
              (b["line"], b["func"][:14], b["call"], preview(b["text"]), b["kind"],
               b["size"], b["anchor"], r["top"], r["bottom"]))

    print("")
    if hits:
        print("[硬撞] %d 对文本块的墨迹框相交, 一定压字:" % len(hits))
        for h in hits:
            print("  行 %d \"%s\" 与 行 %d \"%s\" (都在 %s 里)"
                  % (h["a"]["line"], preview(h["a"]["text"]),
                     h["b"]["line"], preview(h["b"]["text"]), h["a"]["func"]))
            print("      x 方向重叠 %.1f px, y 方向重叠 %.1f px"
                  % (h["overlap_x"], h["overlap_y"]))
            print("      %s" % h["a"]["source"])
            print("      %s" % h["b"]["source"])
    else:
        print("[硬撞] 无: 同一函数内没有文本块的墨迹框相交")

    print("")
    if tight:
        print("[太挤] %d 对文本块的纵向间隙小于 %.2f x 较大字号:" % (len(tight), gap_ratio))
        for t in tight:
            print("  行 %d \"%s\" 与 行 %d \"%s\" (%s): 间隙 %.1f px, 建议不低于 %.1f px"
                  % (t["a"]["line"], preview(t["a"]["text"]),
                     t["b"]["line"], preview(t["b"]["text"]), t["a"]["func"],
                     t["gap"], t["need"]))
    else:
        print("[太挤] 无: 同一函数内的纵向间隙都够")

    if branch:
        print("")
        print("[分支内撞] %d 对落在互斥分支里, 只做提示不作为不合格:" % len(branch))
        for h in branch:
            print("  行 %d \"%s\" 与 行 %d \"%s\" (%s): y 方向重叠 %.1f px, 请确认两条分支"
                  "确实不会同时走到"
                  % (h["a"]["line"], preview(h["a"]["text"]),
                     h["b"]["line"], preview(h["b"]["text"]), h["a"]["func"],
                     h["overlap_y"]))

    if unresolved:
        print("")
        print("[未解析] %d 处调用算不出几何, 需要人工核对:" % len(unresolved))
        for u in unresolved[:40]:
            print("  行 %d %s: %s" % (u["line"], u["call"], u["why"]))
            if u["source"]:
                print("      %s" % u["source"])
        if len(unresolved) > 40:
            print("  ... 另有 %d 处" % (len(unresolved) - 40))

    print("")
    print("说明: 几何按真实墨迹算 (中文字形墨迹约为字号的 1.0 倍, 而 cap 带只有约 0.72 倍);")
    print("      只在同一函数内两两比较, 互斥分支只提示; 引擎内部画的文字 (cv.section 这类")
    print("      封装) 抽不到, 运行时按数据拼出来的文本也抽不到, 这些仍要靠字符图与拼图兜底")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="静态版面体检: 检查场景模块里的文字块是否互相压字")
    ap.add_argument("scene", help="场景模块路径, 例如 scene_module.py")
    ap.add_argument("--theme", default=None,
                    help="theme.py 路径, 缺省取场景模块同目录下的 theme.py")
    ap.add_argument("--width", type=float, default=None, help="画幅宽, 覆盖 theme 与 canvas")
    ap.add_argument("--height", type=float, default=None, help="画幅高, 覆盖 theme 与 canvas")
    ap.add_argument("--gap-ratio", type=float, default=DEFAULT_GAP_RATIO,
                    help="纵向最小留白, 单位是较大那一块的字号 (缺省 %.2f)" % DEFAULT_GAP_RATIO)
    ap.add_argument("--extra-call", action="append", default=[], metavar="NAME",
                    help="额外当作文字绘制调用的方法名 (与 text 同签名), 可重复")
    ap.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="有未解析项或太挤项时也判不合格 (缺省只报不合格于硬撞)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.scene):
        print("错误: 找不到场景模块 %s" % args.scene)
        return 2

    cv = load_canvas()
    fonts = dict(getattr(cv, "FONT_PATH", FALLBACK_FONTS) if cv else FALLBACK_FONTS)
    ss = int(getattr(cv, "SS", 2) or 2)

    theme_path = args.theme or os.path.join(os.path.dirname(os.path.abspath(args.scene)),
                                            "theme.py")
    # 场景模块自己的常量优先于 theme.py: 工程里允许在场景模块顶部覆盖主题常量
    scene_consts = module_constants(args.scene)
    theme_consts = module_constants(theme_path)
    overrides = {}
    if args.width is not None:
        overrides["W"] = args.width
    if args.height is not None:
        overrides["H"] = args.height

    resolver = Resolver([scene_consts, theme_consts], cv, overrides)
    blocks, unresolved = collect_blocks(args.scene, resolver, fonts,
                                        args.extra_call, ss)
    hits, tight, branch = analyse(blocks, args.gap_ratio)
    print_report(blocks, unresolved, hits, tight, branch, args.gap_ratio)

    if args.json_path:
        parent = os.path.dirname(os.path.abspath(args.json_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump({"scene": args.scene, "theme": theme_path,
                       "blocks": blocks, "unresolved": unresolved,
                       "collisions": [{"a": h["a"]["line"], "b": h["b"]["line"],
                                       "overlap_x": h["overlap_x"],
                                       "overlap_y": h["overlap_y"]} for h in hits],
                       "branch_collisions": [{"a": h["a"]["line"], "b": h["b"]["line"],
                                              "overlap_y": h["overlap_y"]} for h in branch],
                       "tight": [{"a": t["a"]["line"], "b": t["b"]["line"],
                                  "gap": t["gap"], "need": t["need"]} for t in tight]},
                      f, ensure_ascii=False, indent=2)
        print("")
        print("wrote %s" % args.json_path)

    if hits:
        return 1
    if args.strict and (unresolved or tight):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

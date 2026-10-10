# -*- coding: utf-8 -*-
"""
文本字形体检: 渲染前确认字体认不认识你要写的字

  python scripts/check_text.py
  python scripts/check_text.py "坐标系 · 向量" "≈¥0.05" "iPr2Zn"
  python scripts/check_text.py --font cnb "硤 硖 卡甘"
  python scripts/check_text.py --from-plan temp/plan.json
  python scripts/check_text.py --from-source scene_module.py
  python scripts/check_text.py --from-plan temp/plan.json --from-source scene_module.py
  python scripts/check_text.py --from-source scene_module.py --with-docstring
  python scripts/check_text.py --from-source scene_module.py --drawn-only

上屏字符串的真正单一来源是 plan.json 加场景代码里的字面量, 手工整理常量表必然漂移;
--from-plan 读计划里每屏的文字, --from-source 用 ast 抽场景模块里的字符串字面量,
两种来源可以同时给, 合并去重后逐字体体检. 渲染期审计是最后一道兜底, 两者都要用.

--from-source 默认跳过 docstring: 它在 AST 里就是 Expr(Constant(str)), 不过滤时模块级与
每个函数的 docstring 都会被当成上屏文字, 实测一个场景模块因此报出 462 条"缺字形",
全部是注释性文字, 会把真实问题淹掉. 想看含 docstring 的全量字面量时加 --with-docstring.

再加 --drawn-only 可以只收"会被画到画面上"的字面量 (画字调用的实参, 以及被它们引用到的
模块级常量), 把 print 的 CLI 提示与报错文案也滤掉, 并尽量连字体键一起抽出来按键分组体检,
于是"中文文案去撞等宽字体"这类噪声也一并消失; 代价是"先存进局部变量再传给画字调用"的文本
会漏掉, 所以它不是缺省行为. 场景模块较大, 提示语很多时推荐用它.

项目自定义的封装 (例如 caption) 内部用什么字体静态看不出来, 默认按全部字体键体检;
用 --call-kind caption=cnb 声明一次就能把它收进对应的键, 可重复给.

判定方式是位图精确比对: 把待测字符与私用区字符分别渲染成位图, 完全相同即为豆腐块
不要用字宽做判据, 上标下标这类窄字符的字宽与豆腐块接近, 会大量误报
"""
import ast
import json
import os
import sys

# 本脚本会打印字体是否认识 ✓ ₂ 这类特殊字符, GBK 控制台直接 print 会抛
# UnicodeEncodeError 把体检结果变成裸 traceback, 先把输出流转成可容错的 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np
from PIL import Image, ImageDraw

FONTS = {
    "cnb": r"C:\Windows\Fonts\msyhbd.ttc",
    "cn": r"C:\Windows\Fonts\msyh.ttc",
    "mono": r"C:\Windows\Fonts\consolab.ttf",
    "monor": r"C:\Windows\Fonts\consola.ttf",
}
PUA = "\ue000"
DEFAULT_TEXTS = [
    "坐标系 · 向量", "2026 诺贝尔化学奖", "不对称有机合成中的非线性效应与自催化",
    "≈¥0.05  (≈$0.0071)", "a · b = |a||b|cos(θ)", "λ 数乘 旋转",
    "iPr2Zn  嘧啶醛  手性醇", "¹³C / ¹⁸O", "→ ← ↑ ↓ ✓ ✗", "R S meso ee",
]


def bitmap(ch, font, size=96):
    im = Image.new("L", (size, size), 0)
    ImageDraw.Draw(im).text((16, 16), ch, font=font, fill=255)
    return np.asarray(im)


def check(font_path, kind, texts):
    if not os.path.exists(font_path):
        print("[miss] 字体不存在 %s" % font_path)
        return 1
    font = ImageFont_truetype(font_path)
    tofu = bitmap(PUA, font)
    bad = []
    seen = set()
    for t in texts:
        for ch in t:
            if ch in seen or ch.isspace():
                continue
            seen.add(ch)
            if np.array_equal(bitmap(ch, font), tofu):
                bad.append(ch)
    if bad:
        print("[bad]  %-6s 缺字形 %d 个: %s" % (kind, len(bad),
              " ".join("%s(U+%04X)" % (c, ord(c)) for c in bad)))
        return 1
    print("[ok]   %-6s 共 %d 个字符全部有字形" % (kind, len(seen)))
    return 0


def ImageFont_truetype(path):
    from PIL import ImageFont
    return ImageFont.truetype(path, 64)


def texts_from_plan(path):
    """
    从 plan.json 抽每屏文字 (scenes[].screens[].text); 兼容顶层 screens
    """
    with open(path, "r", encoding="utf-8") as f:
        js = json.load(f)
    out = []
    for sc in js.get("scenes") or []:
        for s in sc.get("screens") or []:
            t = s.get("text")
            if t:
                out.append(str(t))
    if not out and isinstance(js.get("screens"), list):
        for s in js["screens"]:
            if isinstance(s, dict) and s.get("text"):
                out.append(str(s["text"]))
    return out


def _docstring_ids(tree):
    """
    收集全部 docstring 字面量节点的 id

    Python 的 docstring 在 AST 里就是一个 Expr(Constant(str)), 与上屏文本无法从类型上区分.
    不过滤时模块级与每个函数的 docstring 都会被当成"要上屏的文字", 实测一个场景模块因此
    报出 462 条"缺字形", 全部来自注释性文字, 会把真实问题淹掉
    """
    ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        body = getattr(node, "body", None) or []
        if body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


# --drawn-only 认的画字调用: 前四个是引擎方法, 其余是场景模块里常见的上屏封装
DRAW_CALLS = frozenset((
    "text", "text_fit", "text_cap", "rich", "measure", "text_runs",
    "caption", "section", "title", "subtitle", "label", "note", "hud",
    "readout", "chip", "badge", "legend", "footer", "credit",
))


def _str_literal_ids(node):
    """收集一个表达式子树里全部字符串字面量节点的 id (含 f-string 的静态部分)"""
    ids = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            ids.add(id(sub))
        elif isinstance(sub, ast.JoinedStr):
            for v in sub.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    ids.add(id(v))
    return ids


def _drawn_literal_ids(tree):
    """
    只留"会被画到画面上"的字面量: 画字调用的实参, 以及模块级常量

    场景模块里还有大量非上屏字面量: `print` 的 CLI 提示, 报错文案, argparse 的 help.
    实测模板的 164 段里, 有 167 个汉字来自这些提示语, 而它们在等宽字体下必然"缺字形",
    于是真问题被淹掉. 上屏文案的两种可靠来源就是"传给画字调用"与"放在模块级常量里"
    """
    keep = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)
        if name not in DRAW_CALLS:
            continue
        for a in list(node.args) + [k.value for k in node.keywords]:
            keep |= _str_literal_ids(a)
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            keep |= _str_literal_ids(node.value)
    return keep


def _drawn_pairs(tree, with_docstring, call_kinds=None):
    """
    返回 [(字面量节点, 字体键或 None), ...]

    收两类: 画字调用的实参, 以及**被画字调用引用到的**模块级常量.
    不无差别地收全部模块级常量: 那里面多数是字体键, 字号与署名配置, 不是上屏文本,
    全收进来等于把 --drawn-only 的精度又还回去了

    字体键的确定顺序是: 调用自己的 kind 关键字 > call_kinds 里为该调用名声明的键 > 未知.
    未知就按全部字体键体检, 这是保守做法: 项目自定义的封装 (例如 caption) 内部用什么字体
    静态看不出来, 宁可多报也不漏报; 嫌吵就用 --call-kind caption=cnb 声明一次
    """
    call_kinds = call_kinds or {}
    skip = set() if with_docstring else _docstring_ids(tree)
    out = []
    seen = set()

    # 模块级字符串常量, 用来解析 kind=FONT_TITLE 这种写法
    # 工程模板的惯例是 FONT_TITLE = tval("FONT_TITLE", "cnb"): 取值函数加兜底字面量,
    # 静态上取最后一个字符串实参当兜底值, 与模板注释里写的语义一致
    str_consts = {}

    def resolve_str(node, depth=0):
        if depth > 4 or node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return str_consts.get(node.id)
        if isinstance(node, ast.Call):
            lits = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if lits:
                return lits[-1]
        return None

    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            v = resolve_str(node.value)
            if v is not None:
                str_consts[node.targets[0].id] = v

    def add(node, kind):
        if id(node) in skip or id(node) in seen:
            return
        if not isinstance(node.value, str) or not node.value.strip():
            return
        seen.add(id(node))
        out.append((node, kind))

    def literals(node):
        """展开一个表达式里的字符串字面量 (含 f-string 的静态部分)"""
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                yield sub
            elif isinstance(sub, ast.JoinedStr):
                for v in sub.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        yield v

    def call_name(node):
        fn = node.func
        if isinstance(fn, ast.Attribute):
            return fn.attr
        if isinstance(fn, ast.Name):
            return fn.id
        return None

    # 第一遍: 画字调用的实参, 并记下被引用的名字
    used = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name not in DRAW_CALLS:
            continue
        kind = call_kinds.get(name)
        for kw in node.keywords:
            if kw.arg == "kind":
                k = resolve_str(kw.value)
                if k is not None:
                    kind = k
        for a in list(node.args) + [k.value for k in node.keywords]:
            for lit in literals(a):
                add(lit, kind)
            for sub in ast.walk(a):
                if isinstance(sub, ast.Name):
                    used.setdefault(sub.id, kind)

    # 第二遍: 只收被上面引用到的模块级常量
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name) or tgt.id not in used:
            continue
        for lit in literals(node.value):
            add(lit, used[tgt.id])
    return out


def drawn_text_pairs(path, with_docstring=False, call_kinds=None):
    """
    抽出"会被画到画面上"的文本并带上它的字体键, 返回 [(文本, 字体键或 None)]

    只收画字调用的实参与被它们引用到的模块级常量: 场景模块里大量非上屏字面量
    (print 的 CLI 提示, 报错文案, argparse 的 help) 在等宽字体下必然"缺字形",
    会把真问题淹掉
    """
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    return [(node.value, kind) for node, kind in
            _drawn_pairs(tree, with_docstring, call_kinds)]


def check_by_kind(kinds, pairs, uniq):
    """--drawn-only 的体检: 每个字体键只检查真正用它的文本, 没有文本的键直接跳过"""
    rc = 0
    per_kind = {}
    for k in kinds:
        if k not in FONTS:
            print("[bad]  未知字体键 %s, 可用: %s" % (k, " ".join(FONTS)))
            rc |= 1
            continue
        per_kind[k] = []
    unknown = []
    for t, kind in pairs:
        if kind is None:
            unknown.append(t)
        elif kind in per_kind:
            per_kind[kind].append(t)
        else:
            print("[提示] 画字调用用了未登记的字体键 %s, 已跳过该段文本" % kind)
    for k in kinds:
        if k not in per_kind:
            continue
        got = per_kind[k] + (unknown if unknown else [])
        seen = set()
        rows = []
        for t in got:
            if t not in seen:
                seen.add(t)
                rows.append(t)
        if not rows:
            print("[跳过] %-6s 没有用它画的中文或符号, 不做体检" % k)
            continue
        rc |= check(FONTS[k], k, rows)
    if unknown:
        print("[提示] %d 段文本来自模块级常量, 没有标注字体键, 已按全部字体键体检"
              % len(set(unknown)))
    return rc


def texts_from_source(path, with_docstring=False, drawn_only=False):
    """
    用 ast 抽场景模块里的字符串字面量 (含 f-string 的静态部分), 默认跳过 docstring

    drawn_only 打开时再收一道: 只要画字调用的实参与模块级常量里的字面量, 精度更高,
    代价是"先存进局部变量再传给画字调用"的文本会漏掉, 所以它不是缺省行为
    场景代码里的拼接文本是体检盲区, ast 只能给字面量, 兜底靠渲染期审计
    """
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    skip = set() if with_docstring else _docstring_ids(tree)
    keep = _drawn_literal_ids(tree) if drawn_only else None
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if id(child) not in skip and child.value.strip():
                    if keep is None or id(child) in keep:
                        out.append(child.value)
            elif isinstance(child, ast.JoinedStr):
                for v in child.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        if v.value.strip() and (keep is None or id(v) in keep):
                            out.append(v.value)
            walk(child)

    walk(tree)
    return out


def main():
    args = sys.argv[1:]
    kinds = list(FONTS)
    texts = []
    sources = []
    pairs = []
    # 先整表扫一遍开关与 --call-kind: 它们可能写在 --from-source 之后, 边扫边判会漏掉
    with_docstring = "--with-docstring" in args
    drawn_only = "--drawn-only" in args
    call_kinds = {}
    for j, tok in enumerate(args):
        if tok == "--call-kind" and j + 1 < len(args) and "=" in args[j + 1]:
            cname, _, ckind = args[j + 1].partition("=")
            call_kinds[cname.strip()] = ckind
    i = 0
    while i < len(args):
        if args[i] == "--font":
            if i + 1 >= len(args):
                print("--font 需要一个字体键: %s" % " ".join(FONTS))
                return 1
            kinds = [args[i + 1]]
            i += 2
        elif args[i] == "--from-plan":
            if i + 1 >= len(args):
                print("--from-plan 需要 plan.json 路径")
                return 1
            sources.append(("--from-plan %s" % args[i + 1],
                            texts_from_plan(args[i + 1])))
            i += 2
        elif args[i] == "--from-source":
            if i + 1 >= len(args):
                print("--from-source 需要场景模块路径")
                return 1
            if drawn_only:
                # 这一档连字体键一起抽出来: 只有真正用 mono 画的中文才算缺字形,
                # 拿中文文案去撞 mono 是纯噪声, 实测模板里 21 个汉字全是这种误报
                pairs.extend(drawn_text_pairs(args[i + 1], with_docstring, call_kinds))
                sources.append(("--from-source %s --drawn-only" % args[i + 1],
                                [t for t, _k in pairs]))
            else:
                sources.append(("--from-source %s" % args[i + 1],
                                texts_from_source(args[i + 1], with_docstring, False)))
            i += 2
        elif args[i] == "--with-docstring":
            i += 1
        elif args[i] == "--drawn-only":
            i += 1
        elif args[i] == "--call-kind":
            if i + 1 >= len(args) or "=" not in args[i + 1]:
                print("--call-kind 需要 NAME=KIND 形式, 例如 --call-kind caption=cnb")
                return 1
            cname, _, ckind = args[i + 1].partition("=")
            if ckind not in FONTS:
                print("--call-kind 的字体键 %s 不认识, 可用: %s" % (ckind, " ".join(FONTS)))
                return 1
            call_kinds[cname.strip()] = ckind
            i += 2
        else:
            texts.append(args[i])
            i += 1

    rc = 0
    for name, got in sources:
        print("[%s] 抽到 %d 段文本" % (name, len(got)))
        if not got:
            print("  [提示] 没抽到文本: 检查 plan.json 的 scenes[].screens[].text 或源码里的字符串字面量")
            rc |= 1
        texts.extend(got)

    if not texts:
        texts = DEFAULT_TEXTS
        print("[提示] 未给文本与来源, 用内置样例")
    seen = set()
    uniq = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    if not "".join(uniq).strip():
        print("[提示] 抽到的文本全是空白, 没有可体检的字符; 不当作通过, 防止空输入静默过关")
        return 1
    if pairs:
        # --drawn-only: 按抽到的字体键分组体检, 未标注字体键的按全部键体检
        return check_by_kind(kinds, pairs, uniq)
    for k in kinds:
        if k not in FONTS:
            print("[bad]  未知字体键 %s, 可用: %s" % (k, " ".join(FONTS)))
            rc |= 1
            continue
        rc |= check(FONTS[k], k, uniq)
    print()
    print("缺字形时不要硬写, 换成 ASCII 写法或换字体, 例如 iPr₂Zn 改成 iPr2Zn")
    print("ast 只覆盖字面量, 拼接出来的文本与从未执行的分支靠渲染期审计兜底")
    return rc


if __name__ == "__main__":
    sys.exit(main())

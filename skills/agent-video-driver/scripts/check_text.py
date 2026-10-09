# -*- coding: utf-8 -*-
"""
文本字形体检: 渲染前确认字体认不认识你要写的字

  python scripts/check_text.py
  python scripts/check_text.py "坐标系 · 向量" "≈¥0.05" "iPr2Zn"
  python scripts/check_text.py --font cnb "硤 硖 卡甘"
  python scripts/check_text.py --from-plan temp/plan.json
  python scripts/check_text.py --from-source scene_module.py
  python scripts/check_text.py --from-plan temp/plan.json --from-source scene_module.py

上屏字符串的真正单一来源是 plan.json 加场景代码里的字面量, 手工整理常量表必然漂移;
--from-plan 读计划里每屏的文字, --from-source 用 ast 抽场景模块里全部字符串字面量,
两种来源可以同时给, 合并去重后逐字体体检. 渲染期审计是最后一道兜底, 两者都要用.

判定方式是位图精确比对: 把待测字符与私用区字符分别渲染成位图, 完全相同即为豆腐块
不要用字宽做判据, 上标下标这类窄字符的字宽与豆腐块接近, 会大量误报
"""
import ast
import json
import os
import sys

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


def texts_from_source(path):
    """
    用 ast 抽场景模块里全部字符串字面量 (含 f-string 的静态部分)
    场景代码里的拼接文本是体检盲区, ast 只能给字面量, 兜底靠渲染期审计
    """
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if child.value.strip():
                    out.append(child.value)
            elif isinstance(child, ast.JoinedStr):
                for v in child.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        if v.value.strip():
                            out.append(v.value)
            walk(child)

    walk(tree)
    return out


def main():
    args = sys.argv[1:]
    kinds = list(FONTS)
    texts = []
    sources = []
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
            sources.append(("--from-source %s" % args[i + 1],
                            texts_from_source(args[i + 1])))
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

# -*- coding: utf-8 -*-
"""
文本字形体检: 渲染前确认字体认不认识你要写的字

  python scripts/check_text.py
  python scripts/check_text.py "坐标系 · 向量" "≈¥0.05" "iPr2Zn"
  python scripts/check_text.py --font cnb "硤 硖 卡甘"

判定方式是位图精确比对: 把待测字符与私用区字符分别渲染成位图, 完全相同即为豆腐块
不要用字宽做判据, 上标下标这类窄字符的字宽与豆腐块接近, 会大量误报
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

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
    font = ImageFont.truetype(font_path, 64)
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


def main():
    args = sys.argv[1:]
    kinds = list(FONTS)
    if args and args[0] == "--font":
        kinds = [args[1]]
        args = args[2:]
    texts = args or DEFAULT_TEXTS
    rc = 0
    for k in kinds:
        rc |= check(FONTS[k], k, texts)
    print()
    print("缺字形时不要硬写, 换成 ASCII 写法或换字体, 例如 iPr₂Zn 改成 iPr2Zn")
    return rc


if __name__ == "__main__":
    sys.exit(main())

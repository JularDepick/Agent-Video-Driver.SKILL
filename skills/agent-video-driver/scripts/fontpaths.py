# -*- coding: utf-8 -*-
"""
字体路径表的唯一来源

渲染 (canvas) 与两处体检 (check_text 字形体检, check_layout 版面体检) 必须共用同一张表:
体检的字体表与渲染的字体表不是一份时, 会出现"体检报缺字形, 渲染其实正常"或反过来的
假警报, 而这类分歧无法从成片上判断, 排查成本很高.

键名 (字体键) 是全项目的约定, 写进 theme.py 与场景模块的就是这几个:
    cnb    中文粗体, 主标题与强调文字
    cn     中文常规, 正文与字幕
    mono   等宽粗体, 数字读数与代码
    monor  等宽常规, 次要标注

字形回退链在 canvas.FALLBACK: 中文字体常常缺上下标与数学符号而等宽字体有, 等宽字体
缺中文而中文字体有, 所以两边互相回退. 新增字体键时别忘了在 canvas.FALLBACK 里补一条.

跨平台时不要改这个文件, 跑 `python scripts/fonts.py --script` 拿探测结果, 把输出接到
canvas.FONT_PATH 上 (theme.py 里的 FONT_* 字体键也要一起对齐).
"""

# 缺省按 Windows 系统字体目录解析. 这些路径在 Linux 与 macOS 上通常不存在,
# scripts/fonts.py 的三级探测 (环境变量目录 -> fc-list -> 常见安装路径) 负责补齐.
DEFAULT_FONTS = {
    "cnb": r"C:\Windows\Fonts\msyhbd.ttc",
    "cn": r"C:\Windows\Fonts\msyh.ttc",
    "mono": r"C:\Windows\Fonts\consolab.ttf",
    "monor": r"C:\Windows\Fonts\consola.ttf",
}

# 字形回退链: 某个字体键缺字形时按表里的顺序往后试.
# 写成一份而不是各处各写, 是为了让"新增字体键"只改一处.
FALLBACK = {
    "mono": ("cnb", "cn"),
    "monor": ("cn", "cnb"),
    "cnb": ("monor", "mono"),
    "cn": ("monor", "mono"),
}

# 四个字体键各自适合的用途, 写 theme.py 时的取值依据
FONT_ROLES = {
    "cnb": "中文标题与强调",
    "cn": "中文正文与字幕",
    "mono": "数字读数与代码 (粗)",
    "monor": "次要标注 (细)",
}


def resolve(overrides=None):
    """
    取最终字体表: 缺省表加调用方给的覆盖项

    overrides 是 {字体键: 路径} 字典, 通常来自 scripts/fonts.py 的探测输出.
    覆盖项里出现表里没有的新键时照样收下, 于是用户可以自定义字体而不必改本文件.
    """
    out = dict(DEFAULT_FONTS)
    for k, v in (overrides or {}).items():
        out[str(k).strip()] = v
    return out


def missing_keys(paths):
    """返回 (paths) 里指向不存在文件的那些键, 便于体检脚本报缺字体而不是报缺字形"""
    import os
    return sorted(k for k, v in paths.items() if v and not os.path.exists(v))

# -*- coding: utf-8 -*-
"""
风格牌堆: 本技能的机器可读风格表

为什么是牌堆而不是一份风格清单: 引擎能做的风格差别很大, 而放任自流时它总是做最响的那一支
(近黑底加霓虹加发光大字加一次立体镜头). 那只是牌堆里的一张, 不是本技能的家风. 一张安静的牌
做好了(编辑排版, 标本图录, 手绘速写)比第四遍做最响的那张更像作品, 所以缺省是抽一张, 不是重来.

每张牌带这些字段:

  id           kebab-case 标识, 抽签与 --avoid 用它
  name         中文名
  tone         loud / steady / light, 用于检查"是不是每次都抽到响的"
  idiom        一句话说清这张牌是什么
  plate        底板与墨色方向
  moves        让它读起来像自己的几个动作
  type         字体搭配
  sound        配乐取向
  engine       要读哪个文档, 用哪部分引擎
  delivery     是否必须按交付尺寸排版(靠细纹理吃饭的牌)
  note         最容易踩的那一条

`references/styles.md` 是前十张牌的详细版(带配色十六进制与参数); 本文件是抽签与落盘用的
单一来源, `--list` 打印的就是它. 两张表的 id 与名称必须一致, 由 temp/plan/check_styles.py 校验.
"""

DECK = [
    {
        "id": "deep-space-neon",
        "name": "深空霓虹",
        "tone": "loud",
        "idiom": "近黑底上的冷光晕, 硬白闪切段, 元素回弹入场.",
        "plate": "深蓝黑, 中心偏左上一团冷光晕",
        "moves": ["段落切换用硬白闪, 切点后镜头从 1.05 收到 1.0",
                  "元素用 back() 回弹入场", "发光用三层描边叠加加小区域 bloom"],
        "type": "中文粗体大字, 数字用等宽",
        "sound": "120 BPM, 底鼓推进, 锯齿贝斯, 侧链闪避",
        "engine": "visual-engine.md 的发光与组件",
        "delivery": False,
        "note": "最容易被滥用的一张. 没有品牌色或数据要读时, 先想想为什么不做张安静的.",
    },
    {
        "id": "cold-documentary",
        "name": "冷调纪录片",
        "tone": "steady",
        "idiom": "大面积暗场, 横向柔光扫过切段, 镜头缓慢推进.",
        "plate": "深蓝黑, 大面积暗场, 只留必要的环境光",
        "moves": ["段落切换用横向柔光扫过", "镜头 0.5 秒缓慢推进",
                  "元素用缓出, 全局漂移 0.012"],
        "type": "标题 38 到 76px, 正文 26 到 36px, 注释 22px",
        "sound": "100 BPM, 弦乐群打底, 木管主奏, 竖琴琶音, 拨弦拍点",
        "engine": "visual-engine.md 加 audio-engine.md 的管弦乐",
        "delivery": False,
        "note": "本技能的缺省推荐: 演示元素多时它最不容易翻车.",
    },
    {
        "id": "warm-paper",
        "name": "温暖纸感",
        "tone": "light",
        "idiom": "暖褐底加贴纸式入场, 切点用交叉溶解.",
        "plate": "暖褐, 像旧纸",
        "moves": ["元素像贴纸一样轻微旋转入场, 倾角 2 到 4 度",
                  "纸张纹理用噪点色块", "切点用交叉溶解而不是硬切"],
        "type": "中文常规体, 标题不要超粗, 字号偏大",
        "sound": "90 BPM, 木吉他式拨弦, 手鼓低频, 少量弦乐 pad",
        "engine": "visual-engine.md",
        "delivery": False,
        "note": "纸纹要真的做出来, 只调色不做纹理的话会像加了褐色滤镜.",
    },
    {
        "id": "minimal-white",
        "name": "极简白场",
        "tone": "light",
        "idiom": "纯浅底, 只做位移与不透明度, 大量留白.",
        "plate": "纯浅底, 只有极淡的径向灰",
        "moves": ["只做位移与不透明度, 不做发光不做旋转", "缓动用 eio()",
                  "切点直接硬切"],
        "type": "中文常规或细体, 大字号",
        "sound": "极简, 只有钢琴单音与低频 pad, 无鼓",
        "engine": "visual-engine.md 的排版工具",
        "delivery": False,
        "note": "留白就是这张牌的内容, 不要因为看着空就往里加元素.",
    },
    {
        "id": "retro-terminal",
        "name": "复古终端",
        "tone": "loud",
        "idiom": "深绿黑加扫描线, 打字机逐字, 面板按拍呼吸.",
        "plate": "深绿黑, 叠加极淡扫描线",
        "moves": ["打字机逐字出现, 光标按 2Hz 闪烁", "面板边框按拍呼吸",
                  "元素硬切不做缓动"],
        "type": "等宽为主, 中文用黑体凑等宽感",
        "sound": "芯片音, 方波琶音, 噪声底鼓, 或只保留打字声",
        "engine": "visual-engine.md 加 music.py 的芯片音色",
        "delivery": False,
        "note": "扫描线是细节, 幅度给大了会像坏掉的显示器.",
    },
    {
        "id": "academic-chart",
        "name": "学术图表",
        "tone": "light",
        "idiom": "浅底或深色学术底, 曲线逐段绘制, 数据点按拍弹出.",
        "plate": "纯白或极浅灰, 或深色学术风",
        "moves": ["曲线用逐段绘制, 数据点按拍依次弹出", "坐标轴先画后标",
                  "禁止发光与缩放"],
        "type": "中文常规, 数字等宽, 坐标轴标签 24px",
        "sound": "无鼓或极轻鼓, 以 pad 与钢琴为主",
        "engine": "visual-engine.md 的 draw_grid 与 draw_axes",
        "delivery": False,
        "note": "坐标轴上的每个数字都要与数据源对账, 不要顺手编.",
    },
    {
        "id": "hand-drawn",
        "name": "手绘涂鸦",
        "tone": "light",
        "idiom": "米白底, 线条像被画出来一样生长, 入场带轻微弹跳.",
        "plate": "米白, 高饱和马克笔色",
        "moves": ["线条逐段生长", "元素入场带轻微弹跳", "允许出现抖动"],
        "type": "圆体或手写体, 系统缺字体时用黑体加描边代替",
        "sound": "尤克里里拨弦, 木鱼, 口哨式正弦",
        "engine": "visual-engine.md 的逐段绘制",
        "delivery": False,
        "note": "手绘感来自线条的不规整, 全靠直线与正圆会立刻变成图表风.",
    },
    {
        "id": "film-grain",
        "name": "电影胶片",
        "tone": "loud",
        "idiom": "低饱和暖高光加冷阴影, 全程缓慢推拉, 黑场过渡.",
        "plate": "深褐黑, 低饱和",
        "moves": ["全程缓慢推拉", "切点用黑场过渡", "加颗粒与暗角"],
        "type": "细体大字, 字距放大",
        "sound": "弦乐 pad 长音, 钢琴稀疏, 无鼓, 长混响",
        "engine": "visual-engine.md 加 FFmpeg 的 noise 滤镜",
        "delivery": False,
        "note": "颗粒交给 FFmpeg, 不要画进帧里, 否则 PNG 体积涨十倍.",
    },
    {
        "id": "brand-light-plate",
        "name": "品牌亮色产品片",
        "tone": "light",
        "idiom": "品牌纸白加品牌色满幅, 大标题骑在发丝网格上.",
        "plate": "品牌自己的纸白, 两场暗场用来换气",
        "moves": ["位移与不透明度为主, 入场带错帧, 落位带压印",
                  "品牌色满幅的那一场不给切点爆闪", "界面元素自绘"],
        "type": "高对比衬线做标题, 无衬线做图注, 等宽做读数",
        "sound": "100 到 120 BPM, 电钢或弦乐加轻鼓, 中段抽掉底鼓两拍做 break",
        "engine": "visual-engine.md 加 content-and-rights.md 的品牌素材与品牌色",
        "delivery": False,
        "note": "品牌色必须实测, 亮色品牌的暗色版是同一组色读到曝光的另一端, 不是另挑一套.",
    },
    {
        "id": "riso-press",
        "name": "丝网印与 riso 四色",
        "tone": "light",
        "idiom": "暖米纸加荧光油墨, 网点与套印, 像一张刚下机的印刷品.",
        "plate": "暖米纸, 纸纹用 paper_field 的三层",
        "moves": ["分色成四块油墨版, 每版不同网线角度",
                  "multiply 叠印: 粉压蓝是真紫, 黄压蓝是真绿",
                  "套印偏移几个像素再归位", "主版线先出, 网点随后补上"],
        "type": "粗标题字加印刷体小字, 字距收紧",
        "sound": "96 到 120 BPM, 颗粒感的鼓与贝斯, 中频偏暖",
        "engine": "print-engine.md 的印刷原语",
        "delivery": True,
        "note": "网点是细节, 要按交付尺寸算; 而且所有版必须用同一个 cell, 否则会出摩尔纹.",
    },
    {
        "id": "blueprint",
        "name": "蓝图工程图",
        "tone": "light",
        "idiom": "普鲁士蓝底加白色线稿加尺寸标注, 像一张工程图.",
        "plate": "普鲁士蓝, 白线 1 到 2px",
        "moves": ["白线工程图: 剖视, 尺寸线, 引出线, 剖面线",
                  "网格纸底加图框标题栏", "线稿逐段画出, 按拍推进",
                  "局部套一个红色标注"],
        "type": "等宽工程体为主, 标题用窄体大写",
        "sound": "规律的机械节拍, 打点与咔哒声",
        "engine": "visual-engine.md 的画线与网格",
        "delivery": False,
        "note": "尺寸数字要与画面里的图形一致, 编数字会被一眼看穿.",
    },
    {
        "id": "darkroom-silver",
        "name": "暗房银盐",
        "tone": "light",
        "idiom": "中性纸白加碳黑, 唯一的色彩是安全灯红.",
        "plate": "纸白到碳黑, 唯一色彩是安全灯红",
        "moves": ["光晕: 亮部溢出的红边", "片门微抖加两级颗粒",
                  "点云刻线做主体", "曝光表与灰阶卡做读数"],
        "type": "衬线或窄体无衬线, 字重中等, 不要超粗",
        "sound": "中低频铺底, 几乎无打击乐",
        "engine": "three-d.md 的点云刻版加 FFmpeg 的 noise 滤镜",
        "delivery": False,
        "note": "安静的一张, 力量来自留白与颗粒, 不要往里塞版面家具.",
    },
    {
        "id": "deckle-paper",
        "name": "纸艺纸感",
        "tone": "light",
        "idiom": "日光下的桌面, 纸的纤维, 毛边与投影.",
        "plate": "日光纸白加偏冷投影, 全部是物理质感",
        "moves": ["纸质纤维加纸浆斑", "毛边: 边缘用噪声切",
                  "软高斯投影乘在底板上", "实物摆放: 叠纸, 卡片, 便签"],
        "type": "印刷体加手写批注",
        "sound": "80 BPM, 木琴或电钢, 干燥的房间感",
        "engine": "print-engine.md 的 paper_field 加缓动",
        "delivery": True,
        "note": "投影要软要偏冷, 硬阴影会立刻把这张牌变成剪贴画.",
    },
    {
        "id": "swiss-editorial",
        "name": "瑞士编辑排版",
        "tone": "light",
        "idiom": "大号无衬线加十二栏网格加发丝线, 两个墨色一个强调色, 没有光.",
        "plate": "纸白或近黑, 只有墨色与一档灰阶",
        "moves": ["十二栏网格与发丝分割线", "大字号标题按字高对齐",
                  "数字与图注用等宽, 全部左对齐到栏线", "切点硬切"],
        "type": "大号无衬线做标题, 等宽做图注",
        "sound": "极简, 只有低频 pad 与稀疏的点",
        "engine": "visual-engine.md 的字号反解与字高对齐",
        "delivery": False,
        "note": "这张牌全靠对齐与留白, 元素位置差几像素就散了.",
    },
    {
        "id": "kinetic-type",
        "name": "动态字体",
        "tone": "light",
        "idiom": "只有字, 靠逐字错帧与字距变化把一句话演完.",
        "plate": "单色底, 与字形成最大对比",
        "moves": ["逐字错帧入场, 延迟 0.04 到 0.06 秒",
                  "字距按拍收放", "整行按字高带对齐, 换行时保持视觉基线",
                  "落位带压印"],
        "type": "一种字重走到底, 靠字号与字距做层次",
        "sound": "与字同步的打击点, 其余留白",
        "engine": "visual-engine.md 的字距与 stagger",
        "delivery": False,
        "note": "字距要按字号倍数给, 写固定像素会让大字号松散小字号挤死.",
    },
    {
        "id": "data-plate",
        "name": "数据图版",
        "tone": "light",
        "idiom": "把数据画成版面上的图形, 数字与图形同时在场.",
        "plate": "浅底或深色学术底, 一档灰阶加两个语义色",
        "moves": ["曲线逐段绘制, 数据点按拍弹出",
                  "数值标签随图形生长而更新", "坐标轴先画后标",
                  "关键数值给一次强调"],
        "type": "中文常规, 数字等宽",
        "sound": "无鼓, pad 与钢琴为主, 段落切换用低频 thump",
        "engine": "visual-engine.md 的 draw_grid 与 draw_axes",
        "delivery": False,
        "note": "图上的每个数字都要与数据源对账, 这一类片子的观众最会看这里.",
    },
    {
        "id": "collage",
        "name": "拼贴剪纸",
        "tone": "light",
        "idiom": "多层剪纸上浮, 边缘用噪声切, 投影把它们分开.",
        "plate": "纸白或暖灰, 三到四个色块",
        "moves": ["三到六层主体各自漂移, 做视差",
                  "边缘用噪声切出毛边", "碎片从画面外飘入",
                  "标牌与卡片用圆角矩形加轻微旋转"],
        "type": "印刷体加手写标签",
        "sound": "木琴与手鼓, 中速, 干燥的房间感",
        "engine": "print-engine.md 的纸底与主版线加缓动",
        "delivery": True,
        "note": "层与层之间要有投影分开, 否则会糊成一张平面图.",
    },
]

BY_ID = {c["id"]: c for c in DECK}

TONE_ORDER = ("loud", "steady", "light")


def all_cards():
    """整副牌, 顺序与文件里一致"""
    return list(DECK)


def card_ids():
    return [c["id"] for c in DECK]


def get(card_id):
    """按 id 取牌, 取不到返回 None"""
    return BY_ID.get(str(card_id).strip().lower())


def tone_counts():
    out = {t: 0 for t in TONE_ORDER}
    for c in DECK:
        out[c["tone"]] = out.get(c["tone"], 0) + 1
    return out


def draw(seed=None, avoid=(), tone=None, rng=None):
    """
    抽一张牌

    seed 给了就复现同一张; avoid 里的 id 会被排除; tone 可以限定只抽某一档.
    抽不到时返回 None, 由调用方决定是放宽条件还是报错.
    """
    import random
    pool = [c for c in DECK if c["id"] not in set(avoid)]
    if tone:
        pool = [c for c in pool if c["tone"] == tone]
    if not pool:
        return None
    r = rng or random.Random(seed)
    return r.choice(pool)


def style_md(card, seed=None, avoided=()):
    """
    把一张牌写成 STYLE.md 的正文

    落盘是给项目留痕: 半年后回来看这条片子, 还能知道当时抽到的是哪张, 以及它要求什么.
    """
    lines = [
        "# 风格牌面",
        "",
        "- 牌: %s (%s)" % (card["name"], card["id"]),
        "- 档: %s" % card["tone"],
        "- 一句话: %s" % card["idiom"],
    ]
    if seed is not None:
        lines.append("- 抽签种子: %s (用同一个种子可以复现这张)" % seed)
    if avoided:
        lines.append("- 本次排除: %s" % ", ".join(sorted(avoided)))
    lines += [
        "",
        "## 底板与墨色",
        "",
        card["plate"],
        "",
        "## 招式",
        "",
    ]
    lines += ["- %s" % m for m in card["moves"]]
    lines += [
        "",
        "## 字体",
        "",
        card["type"],
        "",
        "## 配乐",
        "",
        card["sound"],
        "",
        "## 要读的文档与要用的引擎",
        "",
        card["engine"],
        "",
        "## 注意",
        "",
        card["note"],
        "",
        "## 纪律",
        "",
        "- 抽到哪张做哪张, 不要因为这张不够炫就换牌; 牌里一半是轻的, 轻的做干净了一样好看",
        "- 逐场实现顺序: 底板与环境光, 主体, 运动, 版面家具, 每一档先用 at 看一帧",
    ]
    if card.get("delivery"):
        lines.append("- 这张牌靠细纹理吃饭: 画布要按交付尺寸排版, 不要让网点或纸纹来自重采样")
    return "\n".join(lines) + "\n"

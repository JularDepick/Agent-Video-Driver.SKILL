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
    {
        "id": "frame-by-frame",
        "name": "逐帧手绘",
        "tone": "light",
        "idiom": "线条微颤像还在被画, 每一帧都是手绘的当下, 保留手作温度.",
        "plate": "纸白或米白, 笔触墨色加一两个马克笔强调色",
        "moves": ["boiling line: 同一条线的折点在三组微扰位置之间按 8 到 12fps 轮换, 画面像在沸腾",
                  "线条逐段生长, 起笔重收笔轻", "填充色块故意涂出线外几像素",
                  "只做加法不做补间: 形态变化全靠逐帧重画"],
        "type": "手写体或圆体, 标题带描边",
        "sound": "铅笔沙沙的噪声层垫底, 木鱼与拨弦打拍点, 88 到 100 BPM",
        "engine": "visual-engine.md 的逐段绘制加 determinism 的定种子噪声",
        "delivery": False,
        "note": "微颤必须按帧定种子, 不能逐帧随机, 否则违反画面只依赖时间的底线; 抖动幅度 1 到 2px, 大了像故障.",
    },
    {
        "id": "isometric-25d",
        "name": "等轴2.5D",
        "tone": "light",
        "idiom": "无透视的等轴视角里, 微缩模型按拍生长, 街区与机器一件件搭起来.",
        "plate": "浅灰或浅蓝底, 建筑与地面各两档明度, 顶面亮左面中右面暗",
        "moves": ["等轴投影: 屏幕坐标 x=(u-v)*cos30, y=(u+v)*sin30-h, 用 G() 之外自己封装 iso()",
                  "元素沿地面格线滑入, 楼层逐层向上生长",
                  "三面受光: 顶面最亮, 两个侧面差 12 到 18 个明度",
                  "浮空标签从主体上方弹出加引出线"],
        "type": "无衬线做标注, 等宽做数值",
        "sound": "96 到 110 BPM, 马林巴或拨弦的颗粒感, 每次生长落一个木鱼点",
        "engine": "visual-engine.md 的 poly 与 line 加自封装的等轴投影函数",
        "delivery": False,
        "note": "等轴没有透视收敛, 出了透视就是画错; 同屏只允许一个等轴原点, 两个原点会让地面接不上.",
    },
    {
        "id": "flat-vector",
        "name": "扁平矢量",
        "tone": "light",
        "idiom": "纯色几何零阴影零渐变, 高饱和色块拼接, 信息靠形状与位置不讲质感.",
        "plate": "一个中性浅底加三到四个高饱和色块, 严格不出现渐变与投影",
        "moves": ["只允许纯色矩形圆与多边形, 半透明是禁手",
                  "元素按网格对齐滑入, 缓动用 eio, 不回弹",
                  "切点用色块整幅覆盖转场, 下一幕从新色块底开始",
                  "图形之间留 0.5 到 1 倍元素宽的呼吸空隙"],
        "type": "几何无衬线, 字重两档走到底",
        "sound": "110 到 120 BPM, 圆润的正弦贝斯加掌拍, 干净无混响",
        "engine": "visual-engine.md 的 poly 与 rrect",
        "delivery": False,
        "note": "这张牌的全部力量来自克制: 出现一个渐变一个阴影就退化成普通 PPT 风.",
    },
    {
        "id": "single-line",
        "name": "线条动画",
        "tone": "light",
        "idiom": "一根线勾勒万物, 线头从不抬起, 极简叙事里画面自己长出张力.",
        "plate": "单色浅底加一根近黑线条, 唯一强调色给线头光点",
        "moves": ["全片只有一条连续路径, 段与段之间线头移动到画面边缘再重新进入",
                  "线头带一个亮点与短拖尾, 是全片唯一的强调",
                  "路径逐段绘制, 复杂形体先外轮廓后内部细节",
                  "文字少而大, 只在路径让出空间的地方出现"],
        "type": "细无衬线, 字重最轻一档",
        "sound": "极简, 大提琴长音跟随线头起伏, 落笔处给一次轻拨弦",
        "engine": "visual-engine.md 的逐段绘制加 line 与 curve",
        "delivery": False,
        "note": "路径要预先在纸上走通一遍再写代码: 一笔画不通的形体, 画到一半必然断.",
    },
    {
        "id": "soft-3d",
        "name": "3D渲染",
        "tone": "light",
        "idiom": "柔材质加软光影的物理质感, 像捏过的黏土又像渲染过的产品.",
        "plate": "浅灰摄影棚底, 主体一团柔光, 地面有接触阴影",
        "moves": ["用 three.py 的参数曲面加画家算法, 材质只给两档明度的方向光",
                  "接触阴影比投影重要: 物体落地处一圈更深的模糊",
                  "镜头缓慢环绕或推近, 不做快切",
                  "金属与哑光靠高光锐度区分: 锐一点是金属, 散一点是塑料"],
        "type": "无衬线细体, 像产品标签",
        "sound": "90 到 100 BPM, 弦乐 pad 加玻璃质感的高频点缀, 极少打击",
        "engine": "three-d.md 的点云与相机加 visual-engine.md 的 bloom",
        "delivery": False,
        "note": "这套引擎是刻版点云不是真 3D 渲染: 质感靠三面光加接触阴影逼近, 不要承诺材质级细节.",
    },
    {
        "id": "morph-shape",
        "name": "形变动画",
        "tone": "steady",
        "idiom": "图形无缝形变, 一形化万象, 变化本身就是叙事.",
        "plate": "单色或双色底, 形体只用一两个强调色",
        "moves": ["两个多边形顶点数一致, 按顶点对应插值, 中间态就是形变帧",
                  "形变节奏落在拍上: 出发拍与到达拍各一拍, 中间走 eio",
                  "轮廓线保持恒定粗细, 形变时只动顶点不动线宽",
                  "每段只讲一次形变, 变完停两拍给观众看清"],
        "type": "无衬线, 出现在形变停稳的空档",
        "sound": "与形变同步的滑音或弦乐 glissando, 到位时落一次压印鼓点",
        "engine": "visual-engine.md 的 poly 加 lerp, 顶点对应表自己维护",
        "delivery": False,
        "note": "顶点对应是成败关键: 对应错了中间态会自交翻转, 先在纸上标好顶点顺序再写.",
    },
    {
        "id": "sticker-science",
        "name": "贴纸风科普",
        "tone": "light",
        "idiom": "元素做成贴纸拆解, 引出线加标签讲解, 知识被一块块贴到画面上.",
        "plate": "浅底加浅色网格, 贴纸白色描边加轻投影",
        "moves": ["每个讲解元素是带白边与投影的贴纸, 按拍啪地贴上",
                  "标注用引出线加圆角标签, 标签跟着主体轻微漂移",
                  "讲完的部分收进角落缩略图, 画面始终只展开当前一步",
                  "关键结论贴一张星形或强调色贴纸"],
        "type": "圆体做标签, 等宽做数据",
        "sound": "100 BPM, 明亮木管加拨弦, 贴上瞬间一次短促打击",
        "engine": "visual-engine.md 的 rrect 加引出线, 投影用偏移深色副本",
        "delivery": False,
        "note": "贴纸投影要轻要同向, 四个方向乱投会像贴纸飞起来了; 标签文字必须与事实核查表对账.",
    },
    {
        "id": "cyber-hud",
        "name": "赛博朋克HUD",
        "tone": "loud",
        "idiom": "全息界面加数据流, 读数滚动扫描推进, 未来感从屏幕里长出来.",
        "plate": "近黑深蓝底, 霓虹青与品红读数, 网格透视地面",
        "moves": ["HUD 框角用直角加缺口, 不用圆角",
                  "数字滚动到目标值, 波形与柱状按拍跳动",
                  "数据流: 细竖线按拍从上往下扫, 扫过处字符闪亮",
                  "关键警报用一次整幅色偏移加扫描故障"],
        "type": "等宽为主, 中文黑体凑等宽感, 全大写英文",
        "sound": "120 到 128 BPM, 合成器贝斯加电子军鼓, 高频数据哔声按拍点缀",
        "engine": "visual-engine.md 的发光与组件加 music.py 的电子音色",
        "delivery": False,
        "note": "全片都在响会让警报不响: 平时收着, 只在关键拍给一次满强度故障帧.",
    },
    {
        "id": "aurora-glass",
        "name": "弥散渐变玻璃拟态",
        "tone": "steady",
        "idiom": "极光渐变上浮着半透明玻璃卡, 现代界面的高级感与呼吸感.",
        "plate": "深海军蓝底加三团低透明度极光渐变 (蓝紫青, 各 16 到 20 透明度)",
        "moves": ["极光是三团径向渐变, 缓慢漂移换位, 永远别让一团盖过一半画面",
                  "玻璃卡: 白色低透明度填充加顶部内亮边加底部内暗边加轻投影",
                  "玻璃卡后面必须有极光经过, 没有内容的玻璃就是一片奶白",
                  "入场 600ms 缓出, 悬浮层轻微上下漂 2 到 3px"],
        "type": "细无衬线, 标题可用同色系渐变",
        "sound": "85 到 95 BPM, 空气感 pad 加远处的钢琴, 无鼓",
        "engine": "visual-engine.md 的 bloom 与半透明色加缓动",
        "delivery": False,
        "note": "玻璃感等于亮边加暗边加模糊, 缺一条就退化成半透明色块; 极光透明度别超过两成, 高了会浑.",
    },
    {
        "id": "bauhaus-geo",
        "name": "几何构成包豪斯",
        "tone": "light",
        "idiom": "红黄蓝几何块与严谨网格, 一百年前的经典构成在拍点上重新排布.",
        "plate": "米白纸底, 红黄蓝三原色块加黑色粗线",
        "moves": ["只允许圆, 半圆, 三角, 矩形与直线, 黑色粗线做结构",
                  "构成元素沿拍重排: 每一小节一次大规模位移, 一次到位不拖泥带水",
                  "三原色轮换主次, 但同屏不超过四块彩色",
                  "切点用黑场或色块硬切"],
        "type": "几何无衬线全大写, 字距放宽",
        "sound": "100 到 120 BPM, 干燥的打击乐 (木鱼鼓棒) 与低音单簧管, 无混响",
        "engine": "visual-engine.md 的 poly 与 rrect",
        "delivery": False,
        "note": "包豪斯的力量来自构图均衡: 每帧抽出来要像一张海报, 歪一格就散了; 禁渐变禁纹理禁光效.",
    },
    {
        "id": "synthwave",
        "name": "复古Synthwave",
        "tone": "loud",
        "idiom": "霓虹网格日落与地平线飞驰, 八十年代的电子怀旧.",
        "plate": "深紫蓝夜空加品红橙落日, 地面透视网格向地平线滚动",
        "moves": ["透视网格按拍向地平线滚动, 是全片的速度感来源",
                  "落日带水平切线 (百叶窗太阳), 颜色从黄到品红渐变",
                  "标题用霓虹描边加外发光, 可轻微色差分离",
                  "切点配一次地平线闪光或网格加速"],
        "type": "斜体无衬线或像素体, 大写字距宽",
        "sound": "100 到 112 BPM, 锯齿贝斯走句加 gated recharge 军鼓, 合成器主旋律",
        "engine": "visual-engine.md 的透视画线与 bloom 加 music.py 的电子音色",
        "delivery": False,
        "note": "色差与发光是最容易过量的两个旋钮, 各给两三像素就够了, 满屏色差像显卡故障.",
    },
    {
        "id": "pixel-8bit",
        "name": "像素风",
        "tone": "light",
        "idiom": "8位点阵与有限色板, 每个像素都是画出来的, 昼夜在色板间切换.",
        "plate": "低分辨率画布放大 (逻辑 240x135 放大到 1920x1080), 16 到 32 色固定色板",
        "moves": ["全部图形画在低分辨率数组上再最近邻放大, 抗锯齿是禁手",
                  "元素按像素网格对齐移动, 一次一个像素, 不要亚像素",
                  "昼夜或情绪切换用色板替换: 同一帧结构换一组色值",
                  "文字也用点阵字或等宽体, 小字号加放大"],
        "type": "点阵体或等宽, 禁用平滑大字",
        "sound": "方波与三角波芯片音, 4 到 8 拍一个乐句循环, 100 到 140 BPM",
        "engine": "自建低分辨率 numpy 数组加 PIL 的 NEAREST 放大, 配乐走 music.py 的芯片音色",
        "delivery": False,
        "note": "canvas 的 SS 超采样要关掉 (SS=1) 且放大必须 NEAREST, 任何平滑都会毁掉像素感.",
    },
    {
        "id": "liquid-flow",
        "name": "液态流动",
        "tone": "steady",
        "idiom": "液滴融合弹跳, 流体般的丝滑运动, 万物都是液体.",
        "plate": "浅色底加一团高饱和流体主色, 渐变只给流体本体",
        "moves": ["metaball: 两个圆距离近到阈值时融合, 用标量场阈值化的近似",
                  "液滴落下带挤压回弹, 融合瞬间体积守恒 (一大滴等于两小滴)",
                  "流体表面给一条高光带, 高光始终在上方",
                  "一切缓动都是缓入缓出, 没有硬切与直线运动"],
        "type": "圆体, 跟着液体的柔软感走",
        "sound": "水滴声与低频鼓对应融合, 弦乐滑音连接段落, 88 到 100 BPM",
        "engine": "自建 metaball 标量场 (numpy 网格求和取阈值) 加 visual-engine.md 的缓动",
        "delivery": False,
        "note": "metaball 逐像素算标量场很贵, 网格按四分之一分辨率算再放大; 融合阈值调不好会粘连成一团.",
    },
    {
        "id": "variety-huazi",
        "name": "综艺花字",
        "tone": "loud",
        "idiom": "大字报式花字加吐槽贴纸, 表情与弹幕感拉满的综艺节奏.",
        "plate": "画面本体保持简洁, 花字与贴纸叠加其上, 高饱和描边字",
        "moves": ["花字: 超粗描边加多层色阶, 关键词比正文大三倍",
                  "吐槽贴纸带短促旋转入场加回弹, 1.5 秒内必须退场",
                  "同屏花字不超过两处, 重要的一处就够",
                  "音画重锤: 花字出现瞬间配一声镲或鼓, 节奏感由音效顶起来"],
        "type": "超粗黑体或综艺体, 描边加投影",
        "sound": "130 BPM 上下, 综艺打击乐组 (镲, 响板, 嗖声), 段落间用音效衔接",
        "engine": "visual-engine.md 的 text 描边自绘加 back 回弹",
        "delivery": False,
        "note": "花字是调味不是主菜: 同屏超过两处或者常驻不退场, 综艺感立刻变成廉价感.",
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

    seed 给了就复现同一张; avoid 里的 id 会被排除 (大小写不敏感, 与 get 同一口径);
    tone 可以限定只抽某一档. 抽不到时返回 None, 由调用方决定是放宽条件还是报错.
    """
    import random
    banned = {str(x).strip().lower() for x in avoid}
    pool = [c for c in DECK if c["id"] not in banned]
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

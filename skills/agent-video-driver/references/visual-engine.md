# 画面引擎

引擎在 `scripts/canvas.py`. 设计坐标固定 1920x1080 px, 实际按 `SS=2` 渲染成 3840x2160 再 `reduce(2)` 降采样得到抗锯齿, 这是本项目画质的主要来源.

## 初始化

```python
import canvas as cv
cv.configure(BPM=100, DUR=108.0, CUTS=[7.2, 16.8, 26.4],
             FRAMES=r"temp\frames_nobel",
             FONT_PATH={"cnb": r"C:\Windows\Fonts\msyhbd.ttc",
                        "cn": r"C:\Windows\Fonts\msyh.ttc",
                        "mono": r"C:\Windows\Fonts\consolab.ttf",
                        "monor": r"C:\Windows\Fonts\consola.ttf"})
cv.ensure_bg(force=True, top=(9,17,35), bot=(2,4,9), light=(8,19,38))
```

必须 `import canvas as cv` 而不是 `from canvas import *`, 否则 `configure` 改不到模块全局量.

换亮场时用 `cv.ensure_bg(force=True, **cv.light_plate_bg())`. 亮场的两个参数容易取反: `build_bg` 的 `vignette` 是四角的亮度**下限**, 取 0.9 左右才是"几乎不压角", 取 0.04 会把四角压成近黑, 那是暗场的取值.

## 画布方法

所有坐标都是设计 px, 内部自动乘 SS 与镜头缩放.

| 方法 | 用途 |
|:---:|:---|
| `P(x, y)` | 设计坐标转实际像素, 一般不用手调 |
| `cam(z, dx, dy)` | 设置镜头缩放与平移, 以画面中心为缩放中心 |
| `line(p0, p1, color, w, alpha)` | 直线 |
| `gline(...)` | 带发光直线, 三层宽低透明度描边再叠实线 |
| `poly(pts, fill, alpha, outline, ow, oalpha)` | 多边形, fill 传 None 就只描边 |
| `disc(p, r, color, alpha)` / `gdisc(...)` | 实心圆与发光圆 |
| `ring(p, r, color, w, alpha)` | 圆环, 用来做节拍脉冲 |
| `rrect(box, r, fill, falpha, outline, ow, oalpha)` | 圆角矩形, 卡片与面板 |
| `dashed(p0, p1, color, w, dash, gap, alpha, offset, glow)` | 虚线, offset 传负时间可做蚂蚁线 |
| `arrow(p0, p1, color, w, head, alpha, glow)` | 带箭头直线 |
| `arc(center, r, a0, a1, color, w, alpha, glow)` | 圆弧, 角度是屏幕角 (三点钟方向为 0, 顺时针增大) |
| `bloom(cp, r, color, alpha)` | 加性光晕, 用 screen 混合, 只在小区域做所以很便宜 |
| `text(p, s, size, color, alpha, anchor, kind, track)` | 文字, anchor 常用 `lm` `mm` `la` `ls` `rm`; 内部逐字做字形回退; `track` 是字距, 单位是字号的倍数, 负值收紧 |
| `text_fit(p, s, target_w, color, alpha, anchor, kind, track)` | 字号由目标宽度反解后画, 返回用到的字号; 凡是要"这一行占满多宽"的地方都用它 |
| `text_cap(p, s, size, color, alpha, cap, kind, track, halign)` | 按大写字母的字高带对齐, `cap` 取 `center` 或 `top`, `halign` 取 `l` `m` `r`; 多行多字号混排时用它保证视觉基线一致 |
| `text_runs(s, kind)` | 返回该字符串的回退方案 `((片段, 字体键), ...)`, 用来自查会被怎么拆 |
| `measure(s, size, kind, track)` | 量文本宽度, 打字机与混排要用; 按回退后的实际字体累加, 并把字距算进去 |
| `rich(p, parts, size, alpha, track)` | 多字体混排, parts 是 (文本, 字体键, 颜色) 列表 |

模块级还有几个排版工具, 不依赖画布实例:

| 函数 | 用途 |
|:---:|:---|
| `measure_width(s, size, kind, track, zoom)` | 不建画布就能量宽, 用于预排 |
| `fit_size(s, target_w, kind, track, lo, hi)` | 反解字号; 返回 hi 说明目标宽度相对内容过宽, 该换行了 |
| `cap_metrics(kind, size)` | 大写字母 H 的字高带相对基线的上下偏移 |
| `cap_band(kind, size, cy)` | 字高带上下边, 中心落在 cy 上 |
| `baseline_for_cap_centre` / `baseline_for_cap_top` | 由字高带反推基线 y |

颜色是 `(r,g,b)` 三元组, 透明度单独传. 画布内部用 `ImageDraw.Draw(img, "RGBA")`, 这个模式才会做 alpha 混合, 直接 `Draw(img)` 会覆盖像素.

## 字号反解, 字距与字高对齐

**字号不要硬写**. 硬写字号是最常见的翻车点: 标题换一个词就撑出画幅, 换一种字体又显得松散. 做法是反过来, 指定"这一行要占多宽", 让字号由它解出来.

```python
size = cv.fit_size("不对称有机催化", cv.W * 0.82)      # 先解字号
c.text((cv.W / 2, 420), "不对称有机催化", size, TXT, 1.0, anchor="mm")
c.text_fit((112, 200), "副标题写这里", cv.W * 0.55, ACC)  # 或者一步到位, 它会返回字号
```

- `track` 是**字距**, 单位是字号的倍数, 不是像素. 按比例给, 字距才会随字号缩放; 写成固定像素会让大字号显松散, 小字号挤死
- 中文标题一般 `track=0` 到 `0.02`, 大号无衬线拉丁标题可以给负值收紧, 例如 `-0.026`
- 混排里要自己算宽度时一律用 `measure(s, size, kind, track)`, 它与真正画出来的宽度一致

**字高对齐用于多行与多字号混排**. Pillow 的锚点 `la` `lm` 是按上伸线或行框算的, 而人眼对齐的是大写字母的字高带; 两者在中文与拉丁混排时会差出小半个字身.

```python
c.text_cap((112, 300), "章节标题", 64, TXT, 1.0, cap="center")            # 字高带中心落在 y=300
c.text_cap((112, 380), "Section Title", 40, DIM, 1.0, cap="top")         # 字高带上边落在 y=380
c.text_cap((cv.W / 2, 300), "居中大标题", 96, TXT, 1.0, halign="m")       # 水平居中
cv.cap_band("cnb", 64, 300)                                              # 拿字高带做底纹或下划线
```

- 单行大字用 `text()` 的 `mm` 锚点就够了; 一旦有两行以上或两种字号并排, 换成 `text_cap` 才不会一高一低
- `cap_metrics(kind, size)` 返回的是**相对基线**的偏移, 上偏移为负; 它已经减掉了 Pillow 的上伸线, 自己算的时候别再减一次, 原因见 `pitfalls.md` 的 PIL 字高对齐一条

**中文大字不能拿字高带去反推纵向间距**. `cap_metrics` 量的是拉丁字母 `H` 的字高带, 约 `0.72em`; 而中文字形占满 em 框, 实际墨迹高度约 `1.0em`, 比字高带高出约四成.

- 用 `text_cap` 做**单行对齐**是对的, 它的目的就是让多行多字号看起来基线一致
- 用字高带反推**相邻元素的纵向间距**会重叠: 两块中文大字按字高带排得刚好不相交时, 真实墨迹已经压了 `1.0 - 0.72 = 0.28` 个字号
- 实测一次翻车: 顶杠画在 y 104 到 152, 主句字号 168.7 按字高带中心排在 y 168 (实际墨迹 y 107 到 229), 副句 44px 排在 y 248 (实际墨迹 232 到 264), 于是顶杠压主句, 主句又压副句, 三块连成一片
- **按墨迹留白**: 两个中文大字块之间至少留 `0.15 x 前一块字号` 的空隙; 拿不准就先用 `scripts/check_layout.py` 静态量一遍
- 中英混排时按**较高的那一块**留白, 中文字号小但墨迹高, 只按拉丁那一侧算会不够

`scripts/check_layout.py` 就是干这件事的: 它从场景模块里抽出全部文字绘制调用, 用真实墨迹算墨迹框, 两两检查相交. 用法与判据见 `verification.md` 的版面静态体检一节.

## 字形回退与渲染期审计

`text()` 会逐字检查当前字体键有没有该字符的字形, 没有就沿 `FALLBACK` 链换键, 同一句里换键的地方自动分段渲染. 既不需要回退也不给字距时走 Pillow 原生路径; 需要回退或给了字距时改走逐字排版, 每个字符的 x 由同字体片段内的累计 advance 得出, 于是字体自身的字偶距仍然保留.

- 需要自己算宽度时一律用 `measure()`, 它已经按回退后的字体累加并把字距算进去, 与真正画出来的宽度一致
- 纵向位置仍交给 Pillow 的 anchor; 只有横向起点是引擎自己按逐字排版的总宽度算的
- 回退链上所有字体都缺字形时仍会画成豆腐块, 必须看下面的审计

`render_range()` 渲染时自动开启审计, 区间渲完打印一份报告, 列出真实上屏的 (字符串, 字体键) 组合, 哪些发生了回退, 以及哪些字符回退链也找不到字形. 自定义渲染驱动可以手动控制:

```python
cv.audit_start()
cv.render_frame(pick, t)      # 或自己循环
cv.audit_report("试渲染")
cv.audit_stop()
```

判据与处置见 `text-and-encoding.md` 的渲染期审计一节.

## 缓动与节拍

```python
clamp(x, a, b)  seg(t, a, b)  eo(x)  eo5(x)  eio(x)  back(x, s)  lerp(a, b, p)  keyframes(p, ks)
beat_on(lb, k, d)      # 第 k 拍入场, 返回 0..1
beat_pulse(t, decay)   # 拍点脉冲, 用来驱动发光呼吸
beat_phase(t)          # 当前拍内的进度 0..1
across(t0, dur, t, ease)              # 子区间进度, 用秒定位
stagger(i, n, t, t0, span, every)     # 逐项错帧入场
impact(x, k, at, width, s)            # 落位压印, 起点 0 终点 1, 中段过冲到约 k
```

`lb` 是局部拍数, 计算方式 `lb = (t - 段起点) / BEAT`. 所有入场一律用 `beat_on`, 不要用秒数.

三条纪律:

- **一个缓动函数的返回值只能当一种用途**. `eo` `eo5` `eio` `back` 都饱和在 1 以下, 拿 `if eo(x) > 0.98:` 当"这段动画播完了"的门, 那一段就永远不会画出来, 而且静默无报错. 完成判定另给一个线性时钟 `clamp((t - t0) / dur)`, 缓动只作用在单个元素自己的淡入上
- **`beat_on` 只承担入场进度**, 不要拿它当完成门, 也不要拿它去算时长
- **入场三件套**: 错帧用 `stagger` (逐项延迟 0.04 到 0.06 秒, 整块一起出现最死板), 缓动用 `eo5` 或 `eio`, 落位用 `impact` 把光晕强度或线宽推过 1 再回落. `impact` 的返回值不是 alpha, 用之前先 `clamp` 到 1

## 通用组件

| 组件 | 说明 |
|:---:|:---|
| `motes(c, t, alpha)` | 缓慢上浮微粒, 让静止画面有呼吸感, 比加噪点便宜 |
| `section(c, t, num, title, sub, accent, appear)` | 左上角章节标签, 强调线按拍扫出 |
| `caption(c, lb, k, text, ...)` | 底部字幕, 第 k 拍入场 |
| `progress_footer(c, t, alpha, label)` | 底部进度线加四拍指示灯 |
| `cut_sweep(c, t, cuts)` | 切点横向柔光扫过, 纪录片风格 |
| `cut_flash(c, t, cuts)` | 切点硬白闪, 燃向风格 |
| `camera_settle(t, cuts, amount, tau, drift)` | 切点推进加全片漂移 |
| `fade_to_black(c, a)` | 压黑收尾 |
| `c.wash(a, color)` | 画布方法, 整幅洗成某色, 缺省洗成亮场底色; 用于整场反白两侧的过渡, 与 `fade_to_black` 是同一动作的两种取色 |
| `draw_grid` / `draw_axes` | 数学网格与坐标轴, 讲解类题材直接可用 |
| `beat_ring(c, t, color, base, span, alpha)` | 每拍从原点扩散的圆环 |

## 版面家具与四角纪律

版面家具指章节标签, 片名, 时间码, 进度线这类常驻元素. 它们最容易喧宾夺主, 所以位置先分配好再写内容.

| 位置 | 放什么 | 用哪个组件 |
|:---:|:---|:---|
| 左上 | 章节标签与编号 | `section()` |
| 右上 | 片名或系列名 | 直接调 `text()`, 字号不超过正文 |
| 左下 | 时间码或年份戳 | 直接调 `text()`, 用等宽字体 |
| 右下 | 当前段名或读数 | 直接调 `text()`, 用等宽字体 |
| 中下 | 屏序指示器 | `progress_footer()` 的四拍指示灯 |
| 最底 | 一条进度线 | `progress_footer()` |

三条纪律:

- **一个角落只放一样东西**. 四角固定之后不要往里塞内容, 尤其是主体图形与文字块
- 版面家具最后加, 它是全片最容易抢主体的东西; 先把底板, 主体与运动做对, 再回来加家具
- 版面家具的透明度一般压在 0.5 到 0.8, 与主体同亮度会让人分不清哪个是重点

## 常用图形配方

**手性分子 (楔形与虚楔)** 见本次实现: 中心圆加三条键, 上键用实心三角表示朝向观众, 下键用四道渐窄横线表示背向观众, 左右键用普通线. 镜像只需把 x 取反, 视觉上立刻可读.

**锁与钥匙 / 手套** 用圆角矩形拼出手套轮廓 (掌加四指加拇指), 再在掌心放三个不同颜色的小孔, 钥匙用三个不同颜色和角度的臂, 镜像后颜色顺序反转, 于是能直观演示匹配与不匹配.

**函数曲线** 先生成点列再逐段画:

```python
pts = [(lerp(x0, x1, i/80), lerp(y1, y0, 1-(1-i/80)**1.9)) for i in range(81)]
curve(c, pts, cv.CYAN, 4.2, alpha, upto=cv.eo(seg(lb, 5.0, 7.6)))
```

**放大级联** 用同一坐标轴上的点列, 前几个点几乎贴在轴上, 最后一个点跳到顶部, 视觉冲击比等距柱状图强得多.

## 图表配方

坐标系与网格直接用 `draw_grid` / `draw_axes`, 下面几类图在它之上组装; 数据点一入场就随拍生长, 生长进度用 `beat_on` 或 `seg(lb, a, b)` 驱动, 不要用秒数.

**柱状图** 每根柱从轴线向上生长: 高度乘入场进度, 柱顶读数在柱长到位后的那一拍出现, 全部柱用 `stagger` 错帧. 数值差的敏感靠柱高比例表达, 不要靠颜色深浅.

**折线与曲线** 点列逐段画 (见上面的函数曲线), 生长头用发光圆点标记, 读数标签等线走完再入.

**进度与占比** 环形用 `arc` 扫角, 条形用一根线的实际长度表达; 百分比数字与图形同时入场, 数字按第 18 条铁律与代码实际值对账.

**对照图** 左右两栏共用同一坐标轴与同一比例尺, 否则对照失效; 两栏的入场拍错开一拍, 先到的先读.

- 图表类屏的图形层是亮部面积的主力, 主句仍按 narrative.md 的主句尺寸标尺给, 两者互不替代
- 图例与轴标签属于图注层 (18 到 28 号), 不要放大到与主句抢层级

## 性能

- 1080p 单帧约 0.08 到 0.12 秒, 4K 中间画布是主要成本
- 发光用多层描边而不是高斯模糊, 模糊在 4K 下每帧要几百毫秒
- `bloom` 只在小区域做 screen 混合, 单次约 2 到 4 毫秒
- 背景预渲染一次然后每帧 copy, 不要逐像素重算
- 颗粒不要画进帧里, 交给 FFmpeg 的 `noise` 滤镜, 否则 PNG 体积涨十倍

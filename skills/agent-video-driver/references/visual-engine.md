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
| `text(p, s, size, color, alpha, anchor, kind)` | 文字, anchor 常用 `lm` `mm` `la` `rm`; 内部逐字做字形回退 |
| `text_runs(s, kind)` | 返回该字符串的回退方案 `((片段, 字体键), ...)`, 用来自查会被怎么拆 |
| `measure(s, size, kind)` | 量文本宽度, 打字机与混排要用; 按回退后的实际字体累加 |
| `rich(p, parts, size, alpha)` | 多字体混排, parts 是 (文本, 字体键, 颜色) 列表 |

颜色是 `(r,g,b)` 三元组, 透明度单独传. 画布内部用 `ImageDraw.Draw(img, "RGBA")`, 这个模式才会做 alpha 混合, 直接 `Draw(img)` 会覆盖像素.

## 字形回退与渲染期审计

`text()` 会逐字检查当前字体键有没有该字符的字形, 没有就沿 `FALLBACK` 链换键, 同一句里换键的地方自动分段渲染. 不需要回退时走 Pillow 原生路径, 结果与加入回退功能之前逐像素相同.

- 需要自己算宽度时一律用 `measure()`, 它已经按回退后的字体累加, 与真正画出来的宽度一致
- 纵向位置仍交给 Pillow 的 anchor; 只有横向起点是引擎自己按回退后的总宽度算的
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
```

`lb` 是局部拍数, 计算方式 `lb = (t - 段起点) / BEAT`. 所有入场一律用 `beat_on`, 不要用秒数.

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
| `draw_grid` / `draw_axes` | 数学网格与坐标轴, 讲解类题材直接可用 |
| `beat_ring(c, t, color, base, span, alpha)` | 每拍从原点扩散的圆环 |

## 常用图形配方

**手性分子 (楔形与虚楔)** 见本次实现: 中心圆加三条键, 上键用实心三角表示朝向观众, 下键用四道渐窄横线表示背向观众, 左右键用普通线. 镜像只需把 x 取反, 视觉上立刻可读.

**锁与钥匙 / 手套** 用圆角矩形拼出手套轮廓 (掌加四指加拇指), 再在掌心放三个不同颜色的小孔, 钥匙用三个不同颜色和角度的臂, 镜像后颜色顺序反转, 于是能直观演示匹配与不匹配.

**函数曲线** 先生成点列再逐段画:

```python
pts = [(lerp(x0, x1, i/80), lerp(y1, y0, 1-(1-i/80)**1.9)) for i in range(81)]
curve(c, pts, cv.CYAN, 4.2, alpha, upto=cv.eo(seg(lb, 5.0, 7.6)))
```

**放大级联** 用同一坐标轴上的点列, 前几个点几乎贴在轴上, 最后一个点跳到顶部, 视觉冲击比等距柱状图强得多.

## 性能

- 1080p 单帧约 0.08 到 0.12 秒, 4K 中间画布是主要成本
- 发光用多层描边而不是高斯模糊, 模糊在 4K 下每帧要几百毫秒
- `bloom` 只在小区域做 screen 混合, 单次约 2 到 4 毫秒
- 背景预渲染一次然后每帧 copy, 不要逐像素重算
- 颗粒不要画进帧里, 交给 FFmpeg 的 `noise` 滤镜, 否则 PNG 体积涨十倍

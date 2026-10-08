# 卡点方法论

卡点不是后期对轨, 而是从第一行代码就把音乐和画面绑在同一张拍表上.

## 拍表从哪里来

拍表只有两个合法来源, 二者必居其一, 不要手写秒数:

| 来源 | 取法 | 适用 |
|:---:|:---|:---|
| 本技能合成配乐 | BPM 是常量, 段落边界由 `scripts/timing.py` 从屏文案表排出, 落成 `temp/plan.json` | 默认路线 |
| 用户自备音乐 | `python scripts/beats.py <音频> --json temp/beats.json` 反推 BPM, 首拍相位, 小节线, 逐小节响度变化 | 用户带 BGM 来时 |

拿到 `plan.json` 或 `beats.json` 后, 画面模块与配乐脚本都从它取同一份数组, 于是不可能错位.
用 `beats.py` 反推时注意两件事: 测出的 BPM 与首拍相位要先给用户确认一遍; 逐小节响度变化清单直接告诉你哪几小节适合放揭晓与反转.

## 三层对齐

| 层 | 对齐对象 | 做法 |
|:---:|:---|:---|
| 结构层 | 段落边界 = 小节线 | 段落起止时间由小节序号算出来, 不手写秒数 |
| 事件层 | 元素入场 = 拍 | 场景内所有入场用 `beat_on(lb, k, d)`, k 是段内拍序号 |
| 音效层 | 转场音 = 切点 | 配乐脚本与音效 cue 表接收同一份切点数组, 在每个切点前起 swell, 切点处落 thump |

三层的源头是同一个常量数组, 例如:

```python
BAR = 2.4
SEG = [k * BAR for k in (0, 3, 7, 11, 15, 21, 27, 33, 38, 43, 45)]
CUTS = SEG[1:]
```

画面模块与配乐脚本都从这份数组取值, 于是不可能错位.
有 `temp/plan.json` 时, 这份数组由它生成, 场景模块直接读, 不要再抄一份常量.

## 段内事件怎么写

```python
def s_vector(c, t):
    u = t - SEG[3]
    lb = u / cv.BEAT
    # 第 1 拍画出主箭头
    g = cv.beat_on(lb, 1.0, 0.8)
    c.arrow(cv.G(0,0), cv.G(3*g, 2*g), cv.CYAN, 5.0, 27, 1.0, glow=1.2)
    # 第 3 拍标出分量
    ca = cv.beat_on(lb, 3.0, 0.6)
    if ca > 0:
        c.arrow(cv.G(0,0), cv.G(3*ca, 0), cv.AMBER, 3.4, 20, 0.95)
    # 第 5 拍打字机式弹出结论
    caption(c, lb, 5.0, "产物手性高于催化剂手性")
```

判断标准: 把 `BEAT` 改掉, 所有元素应当整体跟着挪, 如果某个元素没动, 说明它写成了秒数.

## 转场手法按风格选

| 手法 | 参数 | 风格 |
|:---:|:---|:---|
| 硬白闪 | `cut_flash(dur=0.11, peak=128)` | 燃向 |
| 横向柔光扫过 | `cut_sweep(dur=0.75, alpha=0.075)` | 纪录片 |
| 交叉溶解 | 两段同帧绘制, 后段 alpha 从 0 到 1 用 0.4 秒 | 人文 |
| 黑场过渡 | 前段末尾压黑 0.3s, 后段开头提亮 0.3s | 电影感 |
| 无转场 | 直接硬切 | 极简与学术 |

配合镜头: `camera_settle(t, CUTS, amount=0.05, tau=0.22, drift=0.012)` 让切点有轻微推进, 硬切不显得干.

## 验证卡点 (必须做, 两种手段互补)

第一种是**全片证据**: 用逐帧差分找运动峰值, 再核对是否落在小节线上:

```powershell
ffmpeg -i temp\video_only.mp4 -vf "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG" -an -f null - 2>&1 | Select-String "YAVG" | ForEach-Object { [double]($_.ToString().Split('=')[-1]) } | Set-Content temp\motion.txt
```

```python
import numpy as np
m = np.array([float(x) for x in open(r"temp/motion.txt")])
cuts = [int(round(s*30)) for s in (7.2, 16.8, 26.4)]
top = sorted(np.argsort(m)[-14:].tolist())
beats = np.arange(0, 108, 0.6) * 30
print("切点是否在峰值里:", all(any(abs(c-i) <= 1 for i in top) for c in cuts))
```

判据: 每个切点都必须出现在运动峰值前列, 且与小节线的距离不超过 1 帧 (33ms).
本次 108s 片的实测结果是九个切点全部落在正负 1 帧内.

第二种是**单点直接证据**: 对揭晓, 反转, 末屏这类锚点屏, 取切点时刻前后各一帧比对.

```
python scripts/qa.py out/成片.mp4 --plan temp/plan.json --anchor 8 14 21
```

它抽出 `t - 1/fps` 与 `t + 1/fps` 两张图算平均绝对差, 并打印 `t` 前后各 3 帧的逐帧差分数列.
判据: 该数列的峰值必须正好落在 `t` 这一帧上, 误差 0 帧.
第一种手段证明全片的运动峰值在切点上, 第二种证明某一屏的落点就在这一帧, 两个都要做.

## 常见错位原因

- 帧索引与秒数换算取整方向不一致, 用 `int(round(s*FPS))` 统一
- 配乐切点用了浮点累加 (0.6 累加 180 次会漂), 改用 `k * BEAT` 一次算出来
- 段落调度区间写成了左闭右闭, 导致切点那一帧画的是上一段
- 片尾淡出与配乐渐出起点不一致, 结尾会显得秃
- `plan.json` 改过之后没有重新跑 `segments` 核对每段起止帧, 场景模块的段数与段落表对不上

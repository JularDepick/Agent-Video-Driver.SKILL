<div align="center">

# Agent-Video-Driver.SKILL

[![Version](https://img.shields.io/badge/Version-0.1.0-green)](https://github.com/JularDepick/Agent-Video-Driver.SKILL/tree/v0.1.0)
[![Copyright](https://img.shields.io/badge/Copyright-JularDepick-0066AA)](./COPYRIGHT)
[![License](https://img.shields.io/badge/License-Apache--2.0-yellow)](./LICENSE)
[![Website](https://img.shields.io/badge/Website-online-38BDF8)](https://julardepick.github.io/Agent-Video-Driver.SKILL/)

[English](./README_en-US.md) |
[简体中文]

</div>

---

## 这是什么?

一个 Agent SKILL, 让你的 Agent 用脚本化的工具链自主生成视频, 不需要任何视频生成模型.

它不依赖素材库, 也不依赖剪辑软件: 画面由代码逐帧算出来, 配乐由代码合成出来, 最后用 FFmpeg 编码封装. 观感走的是动效设计, 因此每一帧都可复现, 每一处卡点都可验证.

覆盖通用内容场景: 科普讲解片, 产品宣传片, 数据动画, 片头片尾, 年度回顾.

核心产物是 [`skills/agent-video-driver`](./skills/agent-video-driver), 一份可直接装进技能目录的 SKILL bundle.

## 参考成片

<https://julardepick.github.io/Agent-Video-Driver.SKILL/>

这条 108 秒的科普解说片由本技能从零做出来: 画面由代码逐帧算出来, 配乐由代码合成出来, 最后用 FFmpeg 编码封装, 全程没有使用任何视频生成模型. 视频在站点的参考成片区, 打开上面的地址即可播放.

## 能做什么

| 能力 | 说明 |
|:---:|:---|
| 结构化提示词脚手架 | 一份全片共用的简报, 加上每阶段七模块提示词 (role / context / task / specs / style / avoid / check), 子代理只拿简报与当阶段提示词, 上下文干净 |
| 内容与合规底线 | 事实有出处且追不到就删, 素材许可逐项核实并写进署名文件, 不画真人脸并标注 AI 生成内容, 画面只依赖时间且定种子; 品牌色必须实测, 画面上的数字要与代码实际值对账; 含个人信息的素材走三层去敏并自动推导禁用词反查 |
| 文案与节奏 | 开场语法, 单屏字数与阅读速度的量化模型, 叙事线索, 关键句落在音乐能量变化的那一小节 |
| 逐拍卡点 | 结构层, 事件层, 音效层三层对齐; 段内四拍职责; 全片运动峰值与锚点前后帧两种验证手段互补 |
| 画面引擎 | 超采样画布抗锯齿, 缓动与节拍原语, 字号反解与字高对齐, 字距与逐字错帧, 落位压印, 发光与加性光晕, 通用 UI 组件; 转场手法目录覆盖硬切到遮盖揭示与出入画 |
| 立体与印刷 | 纯 Python 3D 点云渲染与隐藏线刻版; 印刷与 riso 路线的纸底, 网点, 分色, 乘法叠印与套印偏移 |
| 风格牌堆 | 31 张可直接落地的风格牌 (含逐帧手绘, 等轴2.5D, 扁平矢量, 线条动画, 3D渲染, 形变动画, 贴纸风科普, 赛博朋克HUD, 弥散渐变玻璃拟态, 几何构成包豪斯, 复古Synthwave, 像素风, 液态流动, 综艺花字等商用流行风格), 缺省抽签并支持排除上一条, 牌面落成项目里的 `STYLE.md` |
| 配乐引擎 | 管弦乐与电子两套音色库, 配器表按切点分段取用 (长片后段同样有节奏层), 暖调母带链含过采样真峰压制; 低内存机器可降采样合成或分段写盘拼接 |
| 用户自备音乐 | 反推拍表, 找无接缝小节, 按小节剪接且接缝落在精确的小节线上, 剪完复测拍表 |
| 无视觉验收 | 字符图构图核对 (亮场用墨迹模式, 细线稿用梯度模式), 前后帧对比, 编码前逐屏终检表 (带幕号与 p95), 屏号到幕号到场景函数的反查, 计划抽帧总览, GIF 运动预览, 亮度多张输入与 markdown 落表, 字形体检 (可读计划与场景源码), 去敏反查, 独立 PSNR 复测, 从成片解码回来量真峰 |
| 编码封装 | 帧序列编码, 混音, 响度归一, 真峰验收, 流信息与画质质检; 长片走分批路线: 断点续跑, `--redo` 只重编指定批次, 配套只读进度前端轮询状态文件, 帧空洞与批次自检在进门前拦截; 可选硬件编码器, 并附编码路线对比工具 (先分离解码与滤镜与编码三段开销) |
| 流程安全门 | 开工前一张需求确认单一次问完 (画幅 16:9 / 9:16 / 1:1 / 自定义, 时长, 帧率, BPM, 配乐引擎, 配色, 风格来源, 确认模式, 是否分批, 署名, 命名, 输出目录, 每项带选项与缺省, 可整单回复或全按默认), 全量渲染与最终合成前各再确认一次; 重活先探测核数, 负载, 内存与磁盘, 按限额跑, 不按满核跑; 任何要用户拍板的节点都先交产物路径再提问 |
| 跨平台字体 | 中文字体与等宽字体跨平台探测: 环境变量目录, fc-list, 系统字体目录三级, 探测结果生成 `FONT_PATH` 片段; 并行渲染按帧区间开独立进程, 帧目录与总帧数以场景模块为准 |
| 画幅自适应 | 画面引擎支持 16:9 / 9:16 / 1:1 三档预设与自定义偶数宽高, 组件坐标由画幅短边派生, 竖屏与方屏不是简单裁切而是完整构图; 资源限额按画幅面积折算 |
| 工程脚手架 | 一条命令起工程: 建目录, 把脚本复制成工程内的自包含副本, 生成四份骨架并写好顶部常量; `--aspect` 定画幅, 随 `--bpm --dur --fps` 一起写进场景模块 |

## 工作流程

```
0 探测环境 -> 1 简报与提示词 -> 2 内容与文案 -> 3 风格与分镜
  -> 4 配乐先行 -> 5 分段渲染 -> 6 逐屏终检 -> 7 编码封装 -> 8 客观验收
```

每个阶段都落一个可检查的产物再往下走. 前三个阶段与用户往返, 确认模式可选逐步确认或一次确认.

不可省略的交付节点: 配色先由用户拍板 (给三到五个色相方向挑, 或直接给主色), 风格缺省抽签, 配色与抽到的牌合成一个方向后出两张带色值的样图 (标题卡加该方向最典型的演示屏) 交用户回执; 全量渲染前再出开头约 10 秒的带音轨连续样片, 交出文件路径等回执. 每个节点都是先交产物再提问, 静态帧判断不了节奏与转场.

## 快速开始

在一个空目录里打开你的 Agent, 说:

```
用 agent-video-driver 技能把 <你的主题> 做成一条 <时长> 的视频
```

Agent 会先报告代价 (token 消耗, 中间帧数量, 渲染耗时, 机器占用, 会话独占) 并取得同意, 再开始探测环境与写分镜.
到全量渲染与最终合成这两步, 它会各自再确认一次, 并把资源探测结果与打算采用的限额一起给你看.

想手动跑通一遍, 在技能目录内依次执行:

```
python scripts/new_project.py ../my-video --bpm 100 --dur 108 --prefix proj
cd ../my-video
python scripts/style_lottery.py --write . --tone light
python scripts/check_env.py
python scripts/timing.py script.md --bpm 100 --bars 45
python scripts/orchestra.py 108 100 score.wav "7.2,16.8,26.4,36,50.4,64.8,79.2,91.2,103.2"
python scene_module.py probe
python scene_module.py plan
python scripts/resources.py --for render --frames 3240
python scene_module.py render 0 810
python scripts/resources.py --for encode --frames 3240 --out-dir out
powershell -ExecutionPolicy Bypass -File scripts\assemble.ps1 -Frames temp\frames_proj -Audio audio\score.wav -Out out\成片.mp4 -ProbeOnly
powershell -ExecutionPolicy Bypass -File scripts\assemble.ps1 -Frames temp\frames_proj -Audio audio\score.wav -Out out\成片.mp4 -ConfirmAssembly
python scripts/qa.py out/成片.mp4 --plan temp/plan.json
```

`new_project.py` 会把脚本复制成工程内的自包含副本并生成四份骨架, 之后在工程目录里跑即可; 手工起工程时, `script.md` 与 `scene_module.py` 从 `templates/` 里复制后填写, 见 `templates/screen-script.md` 与 `templates/scene_module.py`.
只装了 Windows PowerShell 5.1 的机器不要写 `pwsh` (根本不存在), 并且务必带 `-ExecutionPolicy Bypass`, 否则默认执行策略会拦下未签名脚本; 换成 `pwsh` 时同样保留 `-File` 形式.
长片把最后两条命令换成分批路线, 进度另开一个终端看:

```
python scripts/assemble_core.py --frames temp\frames_proj --audio audio\score.wav --out out\成片.mp4 --batches 8 --preset medium --yes
python scripts/assemble_progress.py --watch
```

## 需要什么

| 依赖 | 用途 | 缺失影响 |
|:---:|:---|:---|
| Python 3 | 全部脚本 | 无法运行 |
| numpy | 画面背景, 配乐合成, 验收指标 | 无法渲染与合成 |
| Pillow | 画面绘制与帧导出 | 无法渲染 |
| FFmpeg 与 FFprobe | 编码, 混音, 抽帧, 质检 | 无法出片 |
| 中文字体 | 上屏文字 | 中文变豆腐块 |
| zstandard | 可选, 仅 token 统计 | 失去片尾成本字幕 |

默认路线不需要浏览器, 不需要 Node.js, 不需要任何素材库. `python scripts/check_env.py` 会逐项报告当前环境能不能跑.

## 安装

把整个 [`skills/agent-video-driver`](./skills/agent-video-driver) 目录拷进你的技能目录即可, 发现深度只有一层.

也可以直接从 [Releases](https://github.com/JularDepick/Agent-Video-Driver.SKILL/releases) 下载 `Agent-Video-Driver.SKILL*.zip`, 解压出来的 `agent-video-driver/` 直接可用.

也可以把这一句交给任何编程 Agent:

```
从 https://github.com/JularDepick/Agent-Video-Driver.SKILL 安装 agent-video-driver 技能
```

## 目录结构

仓库:

```
Agent-Video-Driver.SKILL/
├── .github/                    # GitHub Actions 工作流
├── site/                       # 项目站点, 说明见 site/README.md
├── skills/
│   └── agent-video-driver/     # 核心产物, 技能本体
├── COPYRIGHT                   # 版权文件
├── LICENSE                     # 许可证文件
├── README.md                   # 中文 README
└── README_en-US.md             # 英文 README
```

技能本体:

```
agent-video-driver/
├── SKILL.md                    # 入口: 两道确认门, 九阶段流程, 内容底线, 工程铁律, 验收标准
├── references/                 # 按需读取的深度文档
├── scripts/                    # 可直接复用或复制的脚本
└── templates/                  # 骨架文件与模板
```

`SKILL.md` 第十节的参考文档索引给出推荐阅读顺序, 排序只由那张表承担, 文件名不带序号.

## 设计取舍

- **代码出片而不是生成式出片**: 画面与音乐都由代码算出来, 于是同一帧每次渲出来都一样, 卡点可以量化验证, 修改只需改参数. 代价是画面风格有边界, 不适合写实影像与真人出镜
- **配乐先行**: 先定音乐就锁死了时间轴, 画面切点跟着音乐切点走, 不需要后期对轨
- **风格缺省抽签**: 引擎能做的风格差别很大, 放任自流时它总做最响的那一支; 所以缺省抽一张牌并排掉上一条抽过的, 而牌里一半以上是轻的
- **无视觉也要能验收**: 多数 Agent 看不到自己渲的图, 所以验收全部建立在可量化的替代手段上, 并由 Agent 明确告知用户"观感需要你过目"
- **不引入外部依赖**: 只用 Python 标准库加 numpy 加 Pillow 加 FFmpeg, 离线可用, 版本可控

## 版权信息

Copyright &copy; 2026 JularDepick

详见 [COPYRIGHT](./COPYRIGHT).

## 许可证

本仓库采用 [Apache-2.0 许可证](./LICENSE).

## 友情链接

- 开源本地优先的对话式 AI 多轨视频剪辑器: https://github.com/0xsline/OpenChatCut/
- 43 种影片风格的 Agent 导演技能库, 每种风格配一支纯代码短片, 含导演与技法两份方法论: https://github.com/lemomo-ai/lemo-opuscar/
- 两种视觉风格各一份的 Agent 视频技能: https://github.com/tuzhechen2005/opus-video-skills/
- Remotion 视频框架的最佳实践技能库: https://github.com/buainoai/remotion-skills/
- 纯代码生成动态图形成片的 Agent 技能: https://github.com/HRuiCcc/RuiC-motion-reel/
- 把一个主题做成科普讲解片的 Agent 技能: https://github.com/Win-Hao/knowledge-video/

## 迭代说明

本项目技能由 Agent 驱动迭代,参考了 [#友情链接](#友情链接) 各个仓库的工作流程和设计思路,并在多轮实际生产中进行"实测-反馈-优化"迭代

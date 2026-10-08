// 站点全部可替换内容集中在这里, 页面只负责渲染
// 换作者, 换仓库地址, 换参考视频, 改版面文案都只动本文件
// 版本号不在这里: 它单独放在 site/version.ts, 迭代时只改那一处

import { SITE_VERSION } from '~~/version'

// 作者信息: AGENTS.md 第 18 章要求前端页面底部标注, 并把文案抽成常量方便替换
export const AUTHOR = {
  name: 'JularDepick',
  email: 'JularDepick@gmail.com',
  github: 'https://github.com/JularDepick',
  copyrightYear: 2026,
}

export const SITE = {
  name: 'Agent-Video-Driver.SKILL',
  version: SITE_VERSION,
  license: 'Apache-2.0',
  repo: 'https://github.com/JularDepick/Agent-Video-Driver.SKILL',
  releases: 'https://github.com/JularDepick/Agent-Video-Driver.SKILL/releases',
  zipName: 'Agent-Video-Driver.SKILL.zip',
  skillDir: 'skills/agent-video-driver',
  // 一句话介绍: 与 README 两版以及 SKILL.md 的 description 保持一致
  tagline: '一个 Agent SKILL, 让你的 Agent 用脚本化的工具链自主生成视频, 不需要任何视频生成模型.',
  intro: [
    '它不依赖素材库, 也不依赖剪辑软件: 画面由代码逐帧算出来, 配乐由代码合成出来, 最后用 FFmpeg 编码封装. 观感走的是动效设计, 因此每一帧都可复现, 每一处卡点都可验证.',
    '覆盖通用内容场景: 科普讲解片, 产品宣传片, 数据动画, 片头片尾, 年度回顾.',
  ],
  // 参考视频放在 site/resource/video/ 下, 页面用相对目录引入, 不重复拷进 public/
  video: {
    file: '2026-nobel-prize-in-chemistry-asymmetric-organocatalysis-explainer.mp4',
    title: '2026 诺贝尔化学奖: 不对称有机合成',
    note: '这条 108 秒科普解说片由本技能生成: 画面由 Python 与 Pillow 逐帧绘制, 配乐由 NumPy 合成, 最后用 FFmpeg 编码封装. 全片没有使用任何视频生成模型.',
    sizeHint: '约 11.8 MB',
  },
}

export const CAPABILITIES = [
  ['结构化提示词脚手架', '一份全片共用的简报, 加上每阶段七模块提示词, 子代理只拿简报与当阶段提示词, 上下文干净'],
  ['内容与合规底线', '事实有出处且追不到就删, 素材许可逐项核实并写进署名文件, 不画真人脸并标注 AI 生成内容'],
  ['文案与节奏', '开场语法, 单屏字数与阅读速度的量化模型, 叙事线索, 关键句落在音乐能量变化的那一小节'],
  ['逐拍卡点', '结构层, 事件层, 音效层三层对齐; 全片运动峰值与锚点前后帧两种验证手段互补'],
  ['画面引擎', '超采样画布抗锯齿, 缓动与节拍原语, 发光与加性光晕, 通用 UI 组件, 逐字字形回退与渲染期审计'],
  ['配乐引擎', '管弦乐与电子两套音色库, 十段式配器表避免单调, 暖调母带链避免刺耳, 附客观判据'],
  ['无视觉验收', '字符图构图核对, 前后帧对比, 计划抽帧总览, 字形体检, 逐帧差分, PSNR, 响度与真峰值'],
  ['流程安全门', '开工前一次启动确认, 全量渲染与最终合成前各再确认一次; 重活先探测核数, 负载, 内存与磁盘, 按限额跑'],
]

export const STAGES = [
  ['0', '探测环境', 'ffmpeg, Python 库, 字体, 磁盘与沙箱限制'],
  ['1', '简报与提示词', 'prompts/brief.md 与各阶段七模块提示词'],
  ['2', '内容与文案', '带出处的知识节点与一屏一句的屏文案表'],
  ['3', '风格与分镜', '三个风格方向各出样图, 再排拍表与写分镜'],
  ['4', '配乐先行', '先出 score.wav, 画面切点跟着配乐切点走'],
  ['5', '分段渲染', '代表帧核对, 开头预览, 过确认门后按限额全量渲染'],
  ['6', '编码封装', 'H.264 编码, AAC 混音, 响度归一, 流信息核对'],
  ['7', '客观验收', '卡点, 画质, 响度, 体积, 字形与内容逐项过判据'],
]

export const REQUIREMENTS = [
  ['Python 3', '全部脚本', '无法运行'],
  ['numpy', '画面背景, 配乐合成, 验收指标', '无法渲染与合成'],
  ['Pillow', '画面绘制与帧导出', '无法渲染'],
  ['FFmpeg 与 FFprobe', '编码, 混音, 抽帧, 质检', '无法出片'],
  ['中文字体', '上屏文字', '中文变豆腐块'],
  ['zstandard', '可选, 仅 token 统计', '失去片尾成本字幕'],
]

export const INSTALLS = [
  {
    label: '下载技能包',
    hint: '从 Releases 取 zip, 解压出来的 agent-video-driver/ 直接可用',
    command: '',
    link: 'releases',
  },
  {
    label: '拷贝目录',
    hint: '把仓库里的技能目录拷进你的技能目录, 发现深度只有一层',
    command: 'cp -R skills/agent-video-driver ~/.claude/skills/',
    link: '',
  },
  {
    label: '交给 Agent',
    hint: '把这句话交给任何编程 Agent, 让它自己安装',
    command: '从 https://github.com/JularDepick/Agent-Video-Driver.SKILL 安装 agent-video-driver 技能',
    link: '',
  },
]

export const TRADEOFFS = [
  ['代码出片而不是生成式出片', '画面与音乐都由代码算出来, 于是同一帧每次渲出来都一样, 卡点可以量化验证, 修改只需改参数. 代价是画面风格有边界, 不适合写实影像与真人出镜'],
  ['配乐先行', '先定音乐就锁死了时间轴, 画面切点跟着音乐切点走, 不需要后期对轨'],
  ['无视觉也要能验收', '多数 Agent 看不到自己渲的图, 所以验收全部建立在可量化的替代手段上, 并由 Agent 明确告知用户观感需要你过目'],
  ['不引入外部依赖', '只用 Python 标准库加 numpy 加 Pillow 加 FFmpeg, 离线可用, 版本可控'],
]

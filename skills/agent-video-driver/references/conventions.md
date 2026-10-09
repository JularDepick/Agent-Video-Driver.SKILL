# 目录与协作规范

本节规定视频任务在工作目录下的目录布局, 命名, 代码, 文档与协作约定. 本技能自带完整约定, 不依赖外部文档.

## 目录规范

```
<工作目录>/
├── <技能发现根>/<技能名>/      # 技能本体, 一个技能一个目录 bundle
│   ├── SKILL.md              # 入口, 必填 frontmatter, 控制在 8192 字符内
│   ├── references/           # 按需读取的深度文档, 不会被当作独立技能发现
│   ├── scripts/              # 可直接复用或复制的脚本
│   └── templates/            # 骨架文件与模板
├── prompts/                  # brief.md 与各阶段提示词
├── script.md                 # 屏文案表, timing.py 的输入
├── storyboard.md             # 分镜表与启动确认门
├── STYLE.md                  # 抽到或点名的风格牌面, 由 style_lottery.py 落盘
├── credits.md                # 外部素材的署名与许可
├── temp/                     # 一切中间产物, 帧序列, plan.json, 试渲染, 校验图
├── audio/                    # 配乐与音效 WAV
└── <产物目录或根目录>/        # 最终交付文件与源脚本
```

硬性要求:

- **起工程用 `scripts/new_project.py`**, 不要手工照抄目录与模板: 它建目录, 把技能脚本复制成工程内的自包含副本, 生成四份骨架, 并把 BPM, 时长, 帧率, 帧目录前缀写进复制出来的场景模块顶部
- 技能必须是 `<技能发现根>/<技能名>/SKILL.md` 或 `<技能发现根>/<技能名>.md`, 发现深度只有一层, 嵌套的 `SKILL.md` 不会被识别; 技能发现根本身可以是仓库根, 也可以是仓库根下的一个目录, 本仓库用的是 `skills/`
- `name` 必须 kebab-case, `description` 必填
- 中间产物只放 `temp/`, `.agent/` 或 `.agents/`, 不污染交付目录
- 相对路径优先, 脚本内不写死绝对路径, 保证目录整体搬迁后仍可运行
- 不主动碰工作目录以外的位置, 有需要时先问用户能否在工作目录内解决
- 交付前清理 `temp/` 下的帧序列, 只留成片与源脚本
- 目录结构发生变化时同步更新忽略规则

## 命名规范

| 对象 | 规则 | 示例 |
|:---:|:---|:---|
| 技能目录 | 大驼峰或 kebab-case, 与 frontmatter 的 name 对应 | `Agent-Video-Driver` |
| 简报 | 固定 `brief.md`, 放在 `prompts/` | `prompts/brief.md` |
| 阶段提示词 | 阶段名小写下划线加 `.md`, 放在 `prompts/` | `prompts/storyboard.md` |
| 屏文案表 | 固定 `script.md` | `script.md` |
| 分镜表 | 固定 `storyboard.md` | `storyboard.md` |
| 风格牌面 | 固定 `STYLE.md`, 由 `style_lottery.py --write` 落盘 | `STYLE.md` |
| 署名文件 | 固定 `credits.md` | `credits.md` |
| 排程结果 | 固定 `plan.json` 与 `plan.md`, 放在 `temp/` | `temp/plan.json` |
| 帧序列 | 前缀加五位序号 | `temp/frames_nobel/n001200.png` |
| 成片 | 主题 + 时长 + 版本 | `2026诺贝尔化学奖_不对称有机合成_108s.mp4` |
| 源脚本 | 小写下划线 | `canvas.py` `music.py` `assemble.ps1` |
| 配乐 | `score` 加限定 | `audio/score_nobel.wav` |
| 音效 | `sfx` 加限定 | `audio/sfx_nobel.wav` |

一个视频一个命名前缀, 帧目录与成片名对应, 避免多任务互相覆盖.

## 代码规范

- 面向对象封装可复用能力, 有复用价值的对象提取到独立文件
- 可个性化修改但不影响核心功能的设计细节, 用全局常量或独立配置文件隔离
- 注释一律独立成行, 不用行尾注释
- 不使用 emoji, 不留无意义的连续空白
- 同一个问题多次修复失败时, 先完整读完相关代码再动手
- 文件编码: `.py` 与 `.md` 一律 UTF-8 不带 BOM; **含中文的 `.ps1` 必须 UTF-8 带 BOM**, 否则 Windows PowerShell 5.1 会按 GBK 解码, 中文变乱码并吞掉换行导致解析失败, 原因见 `pitfalls.md`
- `.py` 的 `print` 到 GBK 控制台时可能抛 `UnicodeEncodeError` 把脚本打断 (例如要打的内容里有别的进程留下的替换字符); 脚本开头把输出流的错误降级: `sys.stdout.reconfigure(errors="replace")`, 读到子进程输出时同时给 `encoding="utf-8"` 与子进程环境的 `PYTHONIOENCODING=utf-8`
- PowerShell 脚本调用一律用 `-File`, 不要用 `-Command "& ..."`, 后者会吞掉脚本退出码, 而安全门正是靠退出码表达状态的
- 调用 `.ps1` 一律写成 `powershell -ExecutionPolicy Bypass -File <脚本> <参数>`: 只写 `powershell -File` 会在默认执行策略下被拦下 (报 `is not digitally signed`), `pwsh` 在只装了 Windows PowerShell 5.1 的机器上根本不存在, 两种都要能跑

### PowerShell 5.1 可用写法 (白名单与黑名单)

本技能的 `.ps1` 只允许用 Windows PowerShell 5.1 就有的能力, 因为 `pwsh` 在只装了系统自带 PowerShell 的机器上不存在. 写脚本前对照下表:

| 类别 | 允许 (5.1 就有) | 禁止 (只有 PowerShell 7 有, 或者会踩坑) |
|:---:|:---|:---|
| 整数除法 | `[math]::Floor($a / $b)` 与 `$a % $b` | `[math]::DivRem($a, $b)` 的二参数写法; .NET 只有三参数重载 (要 `[ref]` 承接余数), 5.1 下报 `Cannot find an overload ... argument count: "2"` |
| 条件取值 | `if () { } else { }` | 三目运算符 `条件 ? 甲 : 乙` |
| 空合并 | `if ($null -eq $x) { ... }` | `??` 与 `?.` |
| JSON | `ConvertFrom-Json` `ConvertTo-Json` | 依赖 `-AsHashtable` 之类的 7 版参数 |
| 读输入 | `Read-Host`, `[Console]::IsInputRedirected`, `[Environment]::UserInteractive` | 7 版才有的 `-Prompt` 参数族 |
| 读文件 | `Get-Content -Encoding utf8` | `-AsUTF8` 之类的新参数 |
| ffmpeg 帧率同步 | 只给 `-framerate`, 让输入帧率决定时间基 | `-vsync` 在新版 ffmpeg 上会打弃用告警; 确实需要时用 `-fps_mode passthrough` |
| 原生命令 stderr | 调用前后局部把 `$ErrorActionPreference` 降为 `Continue`, stderr 重定向到日志再读回 | 在 `Stop` 偏好下直接让 ffmpeg 写 stderr (会抛 `NativeCommandError`), 或降成 `SilentlyContinue` (日志是空的) |
| 进程优先级 | `[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = "BelowNormal"` | 依赖 7 版才有的 cmdlet 参数 |

## 文档规范

- 中文文档标点使用半角 `(),:;`, 不使用 `。、` 与中文引号
- 不使用 emoji
- 表格用 `|:---:|` 居中
- 目录结构用代码块包裹的树形字符表达
- 不写时间顺序, 工时估算, 预期效果

## 协作规范

- 全程使用用户所用语言
- 事实核查, 素材许可, 署名, AI 生成内容标注一律按 `content-and-rights.md` 执行, 不靠推断
- 用户追加新任务时先完成旧任务, 不打断
- 环境缺依赖时告知影响与安装位置, 由用户决策, 不擅自安装
- 网络异常时先向用户确认环境
- 子代理并发上限默认 5, 用完及时关闭
- 交给子代理的只有三样: `prompts/brief.md`, 本阶段提示词文件, 以及需要读写的文件路径
- git 读取类命令随时可用, 写入类命令 (add, commit, push) 需用户当次明确授权

## 作者信息

- 本技能作者 JularDepick, 版本见 SKILL.md frontmatter 的 metadata
- 视频产物默认不添加作者信息, 由启动确认门询问一次, 用户要求时才加
- 若用户要求署名, 只在片尾卡出现, 并把文案抽成模块顶部常量便于替换
- 代码类产物的作者标注方式 (后端注释头, 前端页面底部) 不适用于视频产物

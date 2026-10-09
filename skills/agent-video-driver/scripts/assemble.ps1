# Agent-Video-Driver 编码与封装
# 两种调用方式都可以, 脚本本身只用 Windows PowerShell 5.1 就有的能力, 不写死 pwsh
#   PowerShell 7:        pwsh -File scripts/assemble.ps1 -Frames temp\frames_proj -Audio audio\score.wav -Out out\成片.mp4
#   Windows PowerShell:  powershell -File scripts\assemble.ps1 -Frames temp\frames_proj -Audio audio\score.wav -Out out\成片.mp4
#
# 合成确认门 (最终合成会把 CPU 长时间打满, 必须先过这道门)
#   1. 先数帧, 再调 scripts/resources.py --for encode 做资源探测, 探测报告原样打印,
#      建议同时写进 temp\resources_encode.json
#   2. 打印确认门内容: 帧数, 目标盘剩余空间, 建议线程数, 建议编码预设, 进程优先级,
#      是否建议拦截, 以及限额说明 (被拦截时是拦截原因) 与 warnings 逐条
#   3. -ProbeOnly 只探测并打印这道门, 不做任何编码
#   4. 没给 -ConfirmAssembly 时: 可交互控制台会要求输入 YES 才继续;
#      不可交互 (Agent 后台作业的情形) 直接退出 3, 等用户同意后加 -ConfirmAssembly 重跑
#   5. 探测判定应拦截 (blocked) 且没给 -Force 时退出 4, 不做任何编码
#   6. 过门之后才编码, 并施加限额: -threads, -filter_threads, -preset, 以及进程优先级
#      命令行给了 -Threads 或 -Preset 时以命令行为准, 否则用探测建议
#   7. -ExactLoudness 走精确响度路径 (量测 -> 按差值补偿 -> 限幅 -> 与视频流合成),
#      不加时仍是原来的单遍 loudnorm; 限额对两条路径都生效
#   8. 音轨一律 AAC, 码率由 -AudioBitrate 决定 (缺省 384k); 不要降到 256k:
#      瞬态密集的素材在 256k 下解码回来的真峰会冲到 0 dBFS 以上
#   9. 验收阶段从成片里解码回来量真峰 (ebur128=peak=true 的 True peak 行),
#      超过 -TruePeakCeiling (缺省 -1.0 dBFS) 判不合格并退出 5; 只信波形文件的数会漏判
#
# 退出码: 0 成功; 3 等待用户二次确认; 4 探测判定应拦截; 5 真峰不合格; 其余非零表示编码或混音失败
param(
    [string]$Frames = "temp\frames",
    [string]$Audio = "audio\score.wav",
    [string]$Out = "out\video.mp4",
    [int]$Fps = 30,
    [int]$Crf = 19,
    [int]$Noise = 2,
    [double]$Lufs = -15.0,
    [int]$AudioBitrate = 384,
    [double]$TruePeakCeiling = -1.0,
    [switch]$SkipQualityCheck,
    [switch]$ExactLoudness,
    [int]$Threads = 0,
    [string]$Preset = "",
    [string]$Priority = "BelowNormal",
    [switch]$ConfirmAssembly,
    [switch]$ProbeOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$dir = Split-Path $Out -Parent
$tmp = Join-Path $dir "_video_only.mp4"
$log = Join-Path $dir "_ffmpeg_stderr.log"
$mix = Join-Path $dir "_mix_measure.m4a"
$probeJson = "temp\resources_encode.json"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

function Get-IntegratedLufs {
    # 量测集成响度 I, 解析不到时返回 $null
    # ffmpeg 把量测结果写在 stderr, 而 Stop 偏好下原生命令的 stderr 会变成终止性错误
    # 所以这里局部降级为 Continue, 并把 stderr 重定向到日志文件, 再读回来解析
    # 注意不能降成 SilentlyContinue: 那样 stderr 会被直接丢弃, 日志文件是空的
    param([string]$Path, [string]$LogPath)
    $ErrorActionPreference = "Continue"
    ffmpeg -hide_banner -nostats -i $Path -map 0:a -af "ebur128=peak=true" -f null - 2> $LogPath
    $ErrorActionPreference = "Stop"
    $hit = Select-String -Path $LogPath -Pattern "^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS" | Select-Object -Last 1
    if (-not $hit) { return $null }
    return [double]$hit.Matches[0].Groups[1].Value
}

function Get-FreeGb {
    # 目标盘剩余空间, 探测报告拿不到时的兜底算法
    param([string]$Path)
    try {
        $root = [System.IO.Path]::GetPathRoot((Resolve-Path $Path).Path)
        $d = New-Object System.IO.DriveInfo($root)
        return [math]::Round($d.AvailableFreeSpace / 1GB, 2)
    } catch {
        return $null
    }
}

# ---------------------------------------------------------------- 资源探测与确认门
Write-Host "[0/4] 资源探测与合成确认门"
# 变量不能叫 $frames: PowerShell 变量不分大小写, 会覆盖参数 -Frames
$frameCount = @(Get-ChildItem "$Frames\n*.png" -ErrorAction SilentlyContinue).Count
if ($frameCount -eq 0) { Write-Host "警告: 在 $Frames 下没数到 n%05d.png, 帧数按 0 计" }

$probeScript = Join-Path $PSScriptRoot "resources.py"
$probeArgs = @($probeScript, "--for", "encode", "--json", $probeJson,
               "--out-dir", $dir, "--frames", "$frameCount")
if (Test-Path $Audio) { $probeArgs += @("--audio", $Audio) }

$report = $null
$python = Get-Command python -ErrorAction SilentlyContinue
# 先删掉上一次的探测结果, 免得探测失败时读到过期的 JSON
Remove-Item $probeJson -Force -ErrorAction SilentlyContinue
if ($python -and (Test-Path $probeScript)) {
    # 探测报告原样透传到控制台, 不捕获
    # 原生命令写 stderr 在 Stop 偏好下会变成终止性错误, 这里局部降级为 Continue
    $ErrorActionPreference = "Continue"
    & $python.Source @probeArgs | Out-Host
    $probeCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    # resources.py 的退出码 1 表示"建议拦截", 由下面的 blocked 判定接管, 不算异常
    if ($probeCode -ne 0 -and $probeCode -ne 1) {
        Write-Host "警告: 探测脚本退出码 $probeCode (正常是 0, 建议拦截是 1), 这次结果可能不完整"
    }
    try {
        $report = Get-Content $probeJson -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        $report = $null
    }
}

$freeGb = Get-FreeGb -Path $dir
if ($null -ne $report -and $null -ne $report.advice) {
    $useThreads = if ($Threads -gt 0) { $Threads } else { [int]$report.advice.threads }
    $usePreset = if ($Preset -ne "") { $Preset } else { [string]$report.advice.preset }
    $usePriority = if ($Priority -ne "") { $Priority } else { [string]$report.advice.priority }
    $blocked = [bool]$report.advice.blocked
    $reasons = @($report.advice.reasons | Where-Object { $_ })
    $warnings = @($report.advice.warnings | Where-Object { $_ })
    if ($null -ne $report.disk -and $null -ne $report.disk.free_gb) {
        $freeGb = [math]::Round([double]$report.disk.free_gb, 2)
    }
} else {
    # 探测不可用 (python 不在 PATH, 或 JSON 读不出来) 时的内置规则
    Write-Host "探测不可用, 已退回内置规则"
    $cores = [Environment]::ProcessorCount
    $fallbackThreads = [math]::Min([math]::Max([math]::Floor($cores / 4), 1), 8)
    $useThreads = if ($Threads -gt 0) { $Threads } else { [int]$fallbackThreads }
    $usePreset = if ($Preset -ne "") { $Preset } else { "slow" }
    $usePriority = if ($Priority -ne "") { $Priority } else { "BelowNormal" }
    $blocked = $false
    $reasons = @()
    $warnings = @("探测不可用, 已退回内置规则: 线程数 = floor(核数/4) 夹到 1 到 8 (本机 $cores 核 -> $useThreads), preset 取 slow, 优先级取 BelowNormal, 不做拦截判定")
}

$freeText = if ($null -ne $freeGb) { "$freeGb GB" } else { "未知 (探测不可用)" }
$blockedText = if ($blocked) { "是, 建议先处理下面的原因" } else { "否" }
# reasons 里多数条目只是解释限额为什么下调, 只有 blocked 为真时才是拦截理由
$reasonTitle = if ($blocked) { "  拦截原因:" } else { "  限额说明:" }

Write-Host ("=" * 62)
Write-Host "合成确认门"
Write-Host "  帧数                  $frameCount"
Write-Host "  目标盘剩余空间        $freeText"
Write-Host "  建议编码线程数        -threads $useThreads"
Write-Host "  建议编码预设          $usePreset"
Write-Host "  进程优先级            $usePriority"
Write-Host "  是否建议拦截          $blockedText"
Write-Host $reasonTitle
if (@($reasons).Count -gt 0) {
    foreach ($r in $reasons) { Write-Host "    - $r" }
} else {
    Write-Host "    - 无"
}
Write-Host "  警告:"
if (@($warnings).Count -gt 0) {
    foreach ($w in $warnings) { Write-Host "    - $w" }
} else {
    Write-Host "    - 无"
}
Write-Host ("=" * 62)

if ($ProbeOnly) {
    Write-Host "仅探测: 未做任何编码, 退出 0"
    exit 0
}

if (-not $ConfirmAssembly) {
    $interactive = (-not [Console]::IsInputRedirected) -and [Environment]::UserInteractive
    if ($interactive) {
        $reply = Read-Host "确认开始合成? 输入 YES 继续:"
        if ($reply -notmatch "^(?i)yes$") {
            Write-Host "没有拿到确认, 已取消合成"
            exit 3
        }
    } else {
        Write-Host "正在等待用户二次确认, 拿到同意后加 -ConfirmAssembly 重跑"
        exit 3
    }
}

if ($blocked -and -not $Force) {
    Write-Host "探测判定应拦截, 未给 -Force, 已停止, 不做任何编码"
    foreach ($r in $reasons) { Write-Host "  原因: $r" }
    exit 4
}

# 自身进程优先级降下来, 子进程会继承; 设置失败不中断
try {
    [System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = $usePriority
    Write-Host "已把本进程优先级设为 $usePriority, 子进程会继承"
} catch {
    Write-Host "优先级设置失败, 已跳过"
}
Write-Host "限额: -threads $useThreads -filter_threads $useThreads -preset $usePreset"

# -filter_threads 是全局选项, 放在输入之前; -threads 是输出选项, 放在输出文件之前
$filterThreads = @("-filter_threads", "$useThreads")
$encodeThreads = @("-threads", "$useThreads")

Write-Host "[1/4] 编码帧序列 -> $tmp"
$vf = "noise=alls=${Noise}:allf=t,format=yuv420p"
ffmpeg -y -hide_banner -loglevel warning @filterThreads -framerate $Fps -i "$Frames\n%05d.png" `
    -vf $vf -c:v libx264 -preset $usePreset -crf $Crf @encodeThreads -pix_fmt yuv420p -movflags +faststart $tmp
if ($LASTEXITCODE -ne 0) { throw "编码失败" }

if ($ExactLoudness) {
    # 精确响度路径: 单遍 loudnorm 会过冲 (实测目标 -15 LUFS 时落在 -13.7 LUFS), 这里闭环补偿
    Write-Host "[2/4] 精确响度: 量测 -> 补偿 -> 限幅 -> 与视频流合成"
    Write-Host "      2.1 按最终编码参数生成待量测的音频 -> $mix"
    # 视频流用 -c:v copy 不会改变音频, 所以量测只需针对要混入的音频
    # 按最终 AAC 参数编码, 把有损编码带来的响度偏差一并算进量测
    ffmpeg -y -hide_banner -loglevel error @filterThreads -i $Audio -ar 48000 -c:a aac -b:a "$AudioBitrate"k @encodeThreads $mix
    if ($LASTEXITCODE -ne 0) { throw "生成量测音频失败" }

    $i0 = Get-IntegratedLufs -Path $mix -LogPath $log
    if ($null -eq $i0) { throw "量测集成响度失败, 详见 $log" }
    Write-Host "      2.2 混音前实测集成响度 I = $i0 LUFS"

    # 限幅阈值与单遍 loudnorm 的 TP=-1.5 对齐, 换算成线性值给 alimiter
    $gain = [math]::Round($Lufs - $i0, 2)
    $limLevel = [math]::Round([math]::Pow(10, -1.5 / 20), 4)
    Write-Host "      2.3 目标 $Lufs LUFS, 差值 $gain dB, 限幅阈值 $limLevel (-1.5 dBFS)"
    if ([math]::Abs($gain) -gt 12) {
        Write-Host "      注意: 补偿量超过 12dB, 限幅器会明显介入, 建议先修配乐电平"
    }

    Write-Host "      2.4 施加 volume 与 alimiter, 再与视频流合成 (-c:v copy, 不重渲画面)"
    ffmpeg -y -hide_banner -loglevel error @filterThreads -i $tmp -i $Audio `
        -map 0:v -map 1:a -c:v copy -af "volume=${gain}dB,alimiter=limit=${limLevel}:level=false" `
        -ar 48000 -c:a aac -b:a "$AudioBitrate"k @encodeThreads -movflags +faststart -shortest $Out
    if ($LASTEXITCODE -ne 0) { throw "混音失败" }
    Remove-Item $mix -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "[2/4] 混音并归一响度到 $Lufs LUFS"
    $af = "loudnorm=I=${Lufs}:TP=-1.5:LRA=11"
    ffmpeg -y -hide_banner -loglevel error @filterThreads -i $tmp -i $Audio `
        -map 0:v -map 1:a -c:v copy -af $af -ar 48000 -c:a aac -b:a "$AudioBitrate"k @encodeThreads `
        -movflags +faststart -shortest $Out
    if ($LASTEXITCODE -ne 0) { throw "混音失败" }
}

Write-Host "[3/4] 流信息"
ffprobe -v error -show_entries format=duration,size `
    -show_entries stream=codec_name,codec_type,width,height,r_frame_rate,channels,sample_rate `
    -of default=nw=1 $Out

Write-Host "[4/4] 响度与真峰值"
# 真峰必须从成片里解码回来量: AAC 是有损编码, 重建波形的采样间峰值可以超过原采样点,
# 只信波形文件的数会漏判; 实测同一段瞬态密集的素材编解码一趟能涨 3dB 以上
# 原生命令的 stderr 先落到日志文件, 再筛出摘要行; 用锚定正则避免命中别的行
$ErrorActionPreference = "Continue"
ffmpeg -hide_banner -nostats -i $Out -map 0:a -af ebur128=peak=true -f null - 2> $log
$ErrorActionPreference = "Stop"
Get-Content $log | Select-String -Pattern "^\s*(I|LRA|Peak|True peak):\s*-?\d" | Select-Object -Last 4

$peakFailed = $false
$tpHit = Select-String -Path $log -Pattern "^\s*True peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS" | Select-Object -Last 1
if ($tpHit) {
    $tp = [double]$tpHit.Matches[0].Groups[1].Value
    if ($tp -gt $TruePeakCeiling) {
        Write-Host ("真峰不合格: 实测 {0} dBFS, 判据是不高于 {1} dBFS" -f $tp, $TruePeakCeiling)
        Write-Host "  处置: 降配乐峰值, 提高 -AudioBitrate, 或改用 -ExactLoudness 的精确响度路径"
        $peakFailed = $true
    } else {
        Write-Host ("真峰合格: 实测 {0} dBFS, 判据是不高于 {1} dBFS" -f $tp, $TruePeakCeiling)
    }
} else {
    Write-Host "警告: 日志里没有 True peak 行, 真峰未能核对"
}

if (-not $SkipQualityCheck) {
    Write-Host "[质检] 编码前后 PSNR (高于 45dB 为视觉无损)"
    $ErrorActionPreference = "Continue"
    ffmpeg -hide_banner -nostats -framerate $Fps -i "$Frames\n%05d.png" -i $tmp `
        -lavfi "[0:v][1:v]psnr" -f null - 2> $log
    $ErrorActionPreference = "Stop"
    Get-Content $log | Select-String -Pattern "average" | Select-Object -Last 1
}

Remove-Item $tmp -Force -ErrorAction SilentlyContinue
Remove-Item $log -Force -ErrorAction SilentlyContinue
Remove-Item $mix -Force -ErrorAction SilentlyContinue

if ($peakFailed) {
    Write-Host "完成但有不合格项: $Out"
    exit 5
}
Write-Host "完成: $Out"

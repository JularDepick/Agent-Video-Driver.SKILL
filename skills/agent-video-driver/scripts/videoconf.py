# -*- coding: utf-8 -*-
"""
全技能共享的常量与参数映射

这个文件存在的理由: 帧文件命名与编码参数各有多个消费方, 过去每处各写一份,
改一处漏其余几处的症状是**静默**的, 不会报错, 只会在成片上体现为偏色, 掉帧或残片.
于是把"一个值只有一处定义"当成硬纪律, 收拢到这里:

  FRAME_PATTERN      渲染落盘 (canvas.frame_path) 与外部消费方 (编码, 抽帧, 验收,
                     预览, 并行渲染, 编码器基准) 之间的唯一真源.
  MIN_FRAME_BYTES    帧完整性第一道闸的字节下限, 两条编码路线共用.
  EXIT_*             编码与验收的退出码, 两条编码路线共用同一套语义.
  color_args/gop_args/encoder_args
                     编码参数映射. 一次编完路线 (assemble.ps1) 与分批路线
                     (assemble_core.py) 必须逐字一致, 基准脚本 (bench_encode.py)
                     量出来的数才能直接当标定.

本文件只含常量与纯函数, 不 import 任何东西, 不碰 Pillow / numpy / ffmpeg,
任何脚本 (含 PowerShell 侧经参数传入) 都能安全读取.
"""
import os

# ----------------------------------------------------------------- 帧文件命名
# 帧文件命名的唯一来源. 渲染侧 canvas.frame_path() 用它拼路径, 外部脚本
# (编码, 抽帧, 验收, 预览, 并行渲染, 编码器基准) 也一律引用它, 不要各写一份字面量.
FRAME_PATTERN = "n%05d.png"

# 帧文件字节数下限. 这条闸只拦"0 字节与只写了文件头就被截断"的坏帧, 不是画质判据.
# 阈值刻意压得很低: 低分辨率试渲染的合法帧可能只有几百字节, 定高了下会误报.
# 写到一半被截断但还能解码的帧拦不住, 那种交给编码后的 nb_read_frames 硬闸.
MIN_FRAME_BYTES = 128

# 允许的帧数误差; 拼接与混音都可能引入 1 帧内的取整偏差, 超过 1 帧才算残片.
FRAME_TOLERANCE = 1


def frame_path(frames_dir, index):
    """第 index 帧在帧目录里的完整路径 (外部脚本统一走它)"""
    return os.path.join(frames_dir, FRAME_PATTERN % index)


def frame_pattern_in(frames_dir):
    """给 ffmpeg 的 image2 输入通配路径, 例如 temp/frames_proj/n%05d.png"""
    return os.path.join(frames_dir, FRAME_PATTERN)


# ----------------------------------------------------------------- 退出码
# 两条编码路线 (assemble.ps1 一次编完, assemble_core.py 分批) 共用同一套语义.
# 过去两个文件的 docstring 对 6 与 8 的定义正好互换, 于是按退出码写自动化判断时
# 同一语义在两条路线返回不同码, 调用方无法区分. 语义只有这一处定义.
EXIT_OK = 0
EXIT_USAGE = 2          # 用法错误 (与 argparse 的错误码一致)
EXIT_WAIT_CONFIRM = 3   # 正在等待用户二次确认, 本次没有编码
EXIT_BLOCKED = 4        # 资源探测判定应当拦截, 没有开工
EXIT_TRUE_PEAK = 5      # 成片解码回来的真峰超过天花板
EXIT_FRAME_INTEGRITY = 6  # 帧完整性不合格: 编码前字节体检不通过, 或编码后帧数对不上
EXIT_STATE_MISMATCH = 7   # 状态文件与本次配置不一致, 拒绝续跑
EXIT_ENCODE = 8           # 编码或混音失败 (ffmpeg 自身报错)
EXIT_STREAM_INFO = 9      # 成片流信息不合格: 色彩标签不是 bt709, 或音画不等长
EXIT_INTERRUPTED = 130    # 被中断, 断点已保留

# 人读的一行摘要, 给脚本头部与文档共用. 改这里等于改三条地方的表述.
EXIT_MEANING = (
    (EXIT_OK, "成功"),
    (EXIT_USAGE, "用法错误"),
    (EXIT_WAIT_CONFIRM, "等待用户二次确认, 本次没有编码"),
    (EXIT_BLOCKED, "资源探测判定应当拦截, 没有开工"),
    (EXIT_TRUE_PEAK, "成片真峰超过天花板"),
    (EXIT_FRAME_INTEGRITY, "帧完整性不合格 (坏帧或帧数对不上)"),
    (EXIT_STATE_MISMATCH, "状态文件与本次配置不一致, 拒绝续跑"),
    (EXIT_ENCODE, "编码或混音失败"),
    (EXIT_STREAM_INFO, "成片流信息不合格 (色彩标签或音画等长)"),
    (EXIT_INTERRUPTED, "被中断, 断点已保留"),
)


def exit_table():
    """给人读的退出码表, 两条编码路线的头部注释与文档都按这个生成"""
    return ["退出码: " + "; ".join("%d %s" % (c, m) for c, m in EXIT_MEANING)]


# ----------------------------------------------------------------- 编码参数映射
def color_args():
    """
    bt709 色彩标签与限幅范围. 四个都要显式写: 不写时由 ffmpeg 按分辨率推断,
    推断结果随编码器与滤镜链变化, 现象是"本机正常, 上传后整体偏色".
    """
    return ["-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-color_range", "tv"]


def gop_args(fps, encoder):
    """
    固定 GOP. 各批参数必须完全一致, 否则 -c copy 拼接会失败或在接缝处掉帧.
    libx264 另加 -sc_threshold 0 禁止场景切换插入新的 I 帧.
    """
    g = str(int(fps))
    if encoder.startswith("libx264"):
        return ["-g", g, "-keyint_min", g, "-sc_threshold", "0"]
    if encoder.startswith("libx265"):
        return ["-g", g, "-keyint_min", g]
    # 硬件编码器用 keyint 表达关键帧间隔, 其余交给各自的 rate control
    if "qsv" in encoder:
        return ["-g", g]
    if "nvenc" in encoder:
        return ["-g", g, "-forced-idr", "1"]
    if "amf" in encoder:
        return ["-g", g]
    return ["-g", g]


# 编码器 preset 名到各家 preset 的映射.
# slow / medium 是本技能的两档生产 preset; 另外两档供 bench_encode 做对照.
NVENC_PRESET = {"slow": "p7", "medium": "p6", "fast": "p5", "veryfast": "p4"}
QSV_PRESET = {"slow": "slower", "medium": "medium", "fast": "faster",
              "veryfast": "veryfast"}
AMF_PRESET = {"slow": "quality", "medium": "balanced", "fast": "speed",
              "veryfast": "transcode"}


def encoder_args(encoder, preset, crf, fps):
    """
    按编码器展开成完整的编码参数. 一次编完与分批两条路线都调它, 于是
    "各批参数完全一致" 与 "bench 量出来的数可以直接当标定" 两条承诺才是真的.

    crf 档的换算口径: x264/x265 用 CRF, NVENC 用 -cq, QSV 用 -global_quality,
    AMF 用 -qp_i. 这几个不是同一标度, 换显卡或换编码器必须重新标定.

    画面全部由代码绘制, 平面色块与细线条占多数, 因此 libx264 给 -tune animation
    (加大去块滤波与参考帧数, 对平坦区域更省码率); 换 tune 会改变体积与 PSNR.
    """
    name = encoder or "libx264"
    p = (preset or "").strip().lower()
    crf = int(crf)
    if name == "libx264":
        return (["-c:v", "libx264", "-preset", p or "medium", "-crf", str(crf),
                 "-tune", "animation", "-profile:v", "high"]
                + gop_args(fps, name))
    if name.endswith("_nvenc"):
        # NVENC 用 vbr 加 cq, 并把目标码率交给 cq 决定, 否则它按固定码率跑, 体积会失控
        return (["-c:v", name, "-preset", NVENC_PRESET.get(p, "p6"), "-tune", "hq",
                 "-rc", "vbr", "-cq", str(crf), "-b:v", "0", "-profile:v", "high"]
                + gop_args(fps, name))
    if name.endswith("_qsv"):
        return (["-c:v", name, "-preset", QSV_PRESET.get(p, "medium"),
                 "-global_quality", str(crf)]
                + gop_args(fps, name))
    if name.endswith("_amf"):
        return (["-c:v", name, "-quality", AMF_PRESET.get(p, "balanced"), "-rc", "cqp",
                 "-qp_i", str(crf), "-qp_p", str(crf)]
                + gop_args(fps, name))
    # 其余硬件编码器 (例如 vaapi) 参数语义差别更大, 只透传编码器与 crf, 由使用者自己核对
    return ["-c:v", name, "-crf", str(crf)] + gop_args(fps, name)


def is_cpu_encoder(encoder):
    """x264/x265 是纯 CPU 编码器, 换 NVENC 等于换编码器, 不是给同一个编码器加开关"""
    return (encoder or "").startswith("libx")


# ----------------------------------------------------------------- 验收门槛
# 以下数值是验收底线, 不进任何确认单, 不问不改. 文档与代码共用同一处定义,
# 避免出现"文档写一个值, 脚本判另一个值"这种静默分歧.
PSNR_MIN_DB = 45.0            # 编码后与源帧的 PSNR 下限, 低于此说明码率给少了
LUFS_MIN = -16.0              # 集成响度区间
LUFS_MAX = -14.0
LUFS_TARGET = -15.0           # loudnorm 的目标值, 取区间中值
TRUE_PEAK_CEILING = -1.0      # 成片解码回来的真峰上限 (dBTP)
AUDIO_BITRATE_K = 384         # 音轨码率, 256k 会把瞬态密集素材的解码真峰顶到 0 dBFS 以上
SIZE_MB_PER_30S = 15.0        # 1080p 每 30 秒的体积上限 (CRF 18 到 20)
INK_MIN_RATIO = 0.02          # 文字墨迹覆盖率下限, "框里有没有字"的唯一自动判据

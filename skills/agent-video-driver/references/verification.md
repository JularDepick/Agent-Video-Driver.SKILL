# 验收方法

核心问题: 多数模型没有视觉输入, 看不到自己渲的图. 所以验收必须靠可量化的替代手段.

## 一, 字符图预览 (构图验收)

`scripts/preview.py` 把帧做 20x20 最大池化, 取每块最亮像素并按色相分类, 打印成 96x48 的字符图:

```
python scripts/preview.py temp/frames/n001200.png
```

字符含义: `#` 高亮白, `+` 中亮, `C/c` 青蓝, `P/p` 品红, `A/a` 琥珀, `G/g` 绿, `.` 暗部, 空格近黑.

判据:

- 章节标签应在左上第 3 到 6 行
- 主体元素应落在画面中部, 不要贴边
- 文字块应连续成块, 出现断裂说明字号太小或位置重叠
- 底部进度线应在第 46 行附近

每段至少抽 2 帧 (入场后与出场前) 核对, 共 20 到 30 帧.

要证明"画面变化正好发生在这一帧"时, 用前后帧对比模式:

```
python scripts/preview.py --around temp/frames 1200 3
```

它打印第 1200 帧前后各 3 帧的字符图, 每帧带平均亮度与与前一帧的平均绝对差, 末了给出差分峰值落在第几帧.
判据: 峰值帧与给定帧号相差 0 帧. 这是卡点的直接证据, 与下面的运动峰值手段互补.

## 一之二, 计划抽帧与总览 (给用户过片用)

```
python scripts/qa.py out/成片.mp4 --plan temp/plan.json --anchor 8 14 21 --sheet 24
```

它做四件事:

1. 用 ffprobe 取实际时长与流信息, 与 `plan.json` 对照, 偏差超过 1 帧标为不合格
2. 每屏取屏内 80% 处抽 1 帧 (避开入场动画未完成段), 输出到 `temp/qa/`
3. 对每个锚点屏抽 `t - 1/fps` 与 `t + 1/fps`, 算平均绝对差, 再打印 `t` 前后各 3 帧的逐帧差分数列
4. 每 24 张拼成一页 `sheet-K.jpg`, 供用户肉眼过片

打印出的数值表 (屏号, 时间, 平均亮度, 高亮占比, 与上一屏的平均绝对差) 是无视觉能力时的主要判据:
同屏内亮度突然掉到 3 以下说明该屏渲染成了空场; 相邻屏差异接近 0 说明两屏画面几乎一样, 分镜没起到作用.

## 二, 亮度扫描 (整片异常检测)

```powershell
ffmpeg -i temp\video_only.mp4 -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG" -an -f null - 2>&1 | Select-String "YAVG"
```

- 全黑帧只应出现在片尾淡出
- 若某帧亮度突然冲到 150 以上, 说明是转场闪白, 应恰好落在切点帧
- 若中间出现亮度 3 以下的帧, 说明某段渲染失败成了空场

## 三, 画质 (PSNR)

```powershell
ffmpeg -framerate 30 -i temp\frames\n%05d.png -i temp\video_only.mp4 -lavfi "[0:v][1:v]psnr" -f null -
```

判据: `average` 高于 45dB 为视觉无损, 低于 40dB 说明 CRF 给大了或码率被压狠了.
本次 108s 片实测 53.7dB.

## 四, 响度与真峰值

```powershell
ffmpeg -i <成片> -map 0:a -af ebur128=peak=true -f null -
```

判据: 集成响度 I 在 -16 到 -14 LUFS, 真峰值 TPK 不高于 -1.0 dBFS, LRA 在 3 到 8 LU.

注意单遍 `loudnorm` 会过冲: 实测目标 -15 LUFS 时成片落在 -13.7 LUFS, 高出约 1.3dB.
要求严格时打开 `scripts/assemble.ps1` 的精确响度路径 (量测 `ebur128` 的集成响度, 按差值做精确增益, 再过限幅器), 它不重渲画面.
只在响度要求宽松时才保留单遍 `loudnorm`.

实测对照: 诺奖片 -13.7 LUFS / -1.5 dBFS / LRA 5.0 LU.

## 五, 音频内部平衡

`python scripts/check_audio.py <wav> <BPM>`, 判据见 `audio-engine.md` 的客观判据表.

## 六, 时长与流信息

```powershell
ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,codec_type,width,height,r_frame_rate,channels -of default=nw=1 <成片>
```

判据: 时长精确到毫秒, 视频 h264, 音频 aac, 帧率与设计一致, 音频 48kHz 双声道.

## 七, 体积

1080p 每 30 秒控制在 15MB 以内 (CRF 18 到 20 加轻颗粒).
若体积暴涨到十倍, 检查是不是把颗粒画进了帧里, 或者用了 CRF 14 以下.

## 交付前的自检清单

| 项 | 命令或方法 | 通过标准 |
|:---:|:---|:---|
| 帧数完整 | 统计 temp 下 PNG 数量 | 等于 时长 x 帧率 |
| 段数一致 | `scene_module.py segments` | 段数与场景函数个数一致, 起止帧与段落表相同 |
| 无空场 | 亮度扫描 | 无异常黑帧 |
| 卡点 (全片) | 运动能量峰值 | 切点在正负 1 帧内 |
| 卡点 (锚点) | `qa.py --anchor` | 差分峰值落在切点帧, 误差 0 帧 |
| 构图 | 字符图 | 每段 2 帧以上核对通过 |
| 抽帧总览 | `qa.py` 的 sheet | 每屏 1 帧, 用户已过目 |
| 画质 | PSNR | 高于 45dB |
| 响度 | ebur128 | -16 到 -14 LUFS |
| 音频平衡 | check_audio | 各项达标 |
| 音效混音 | 加入音效轨后重跑 ebur128 与 check_audio | 集成响度仍达标, 拍上/拍间能量比仍大于 1.8 |
| 时长 | ffprobe | 与设计一致 |
| 体积 | 文件属性 | 30s 内小于 15MB |
| 字形 | `check_text.py` 加渲染期审计报告 | 每个字体键渲染前体检无缺字形, 且审计报告里没有"回退链也找不到字形"的项 |
| 内容 | 发布前清单见 content-and-rights.md | 上屏每行都有出处 |
| 资源限额 | `resources.py` | 渲染进程数与编码线程数不超过探测建议值, 探测报告的限额已记录在 `storyboard.md` |
| 两道确认门 | 启动确认门与合成确认门 | 均已取得用户同意并记录在 `storyboard.md` |
| 清理 | 删除 temp 帧序列 | 交付目录只剩成片与源脚本 |

// 站点对外展示的技能版本号
//
// 站点侧的版本号只有这一个来源: 迭代版本号时改这一行即可, 页面与页脚都跟着变
//
// 需要同步的地方 (这三处在仓库根侧, 不在站点构建范围内, 所以只能靠这条注释提醒):
//   skills/agent-video-driver/SKILL.md 的 metadata.version
//   README.md 与 README_en-US.md 的版本徽章
export const SITE_VERSION = '0.1.0'

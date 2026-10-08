# 项目站点

本目录是 [Agent-Video-Driver.SKILL](../README.md) 的在线落地页, 独立于技能本体维护: 技能本体只用 Python, 站点只用 Node.js, 两者没有代码依赖.

线上地址: https://julardepick.github.io/Agent-Video-Driver.SKILL/

站点的职责只有一件事: 把技能本体说清楚, 并用一条真实成片证明它可用. 技能本身怎么工作, 见技能内的 `references/`.

## 技术栈

| 层 | 技术 | 说明 |
|:---:|:---:|:---:|
| 框架 | Nuxt.js | 静态生成, 产出可直接托管的静态站点 |
| 视图 | Vue 3 | 组合式 API 加 `<script setup>` |
| 样式 | 手写 CSS | 不引入 CSS 框架, 全部样式集中在 `src/assets/css/main.css` |
| 语言 | TypeScript | 组件与常量都用 TS |

## 源码结构

```
site/
├── public/                                  # 站点静态资源
├── resource/
│   └── video/                               # 参考成片
├── src/                                     # 核心源码
│   ├── assets/css/main.css                  # 全局样式与设计令牌
│   ├── components/                          # 组件
│   ├── composables/                         # 组合式函数
│   ├── constants/site.ts                    # 全部可替换内容与作者信息
│   ├── constants/storage.ts                 # 与首屏脚本共用的存储键名与类名
│   ├── layouts/default.vue                  # 默认布局
│   ├── pages/index.vue                      # 首页
│   └── app.vue                              # 应用根组件
├── .gitignore                               # 本目录的忽略规则
├── .nvmrc                                   # 构建用的 Node 主版本
├── nuxt.config.ts                           # 构建配置
├── package.json                             # 依赖与脚本
├── tsconfig.json
└── version.ts                               # 站点版本号, 迭代时只改这里
```

## 内容怎么改

对外文案全部数据化在一个文件里: `src/constants/site.ts`. 一句话介绍, 能力清单, 八阶段划分, 依赖表, 安装方式, 设计取舍都在里面, 页面组件只负责渲染, 改文案不需要动组件.

作者信息也在同一个文件, 改 `AUTHOR` 常量即可, 页脚由 `src/components/AuthorFooter.vue` 渲染并挂在默认布局上, 每个页面都会带上.

站点与技能本体共用同一份对外口径, 改其一要同步另一处:

| 内容 | 站点位置 | 技能侧位置 |
|:---:|:---:|:---:|
| 一句话介绍 | `src/constants/site.ts` 的 `tagline` | `README.md`, `README_en-US.md`, 技能 `SKILL.md` 的 `description` |
| 能力与阶段划分 | `src/constants/site.ts` 的 `CAPABILITIES` 与 `STAGES` | `README.md` 的能做什么与工作流程 |
| 许可证 | `src/constants/site.ts` 的 `SITE.license` | 根目录 `LICENSE` |

## 版本号怎么改

站点版本号只有一个来源: `version.ts` 的 `SITE_VERSION`. 页脚与徽章都从它读, 改这一行即可.

它要与仓库根侧的三处保持一致. 这三处不在站点构建范围内, 所以只能手工同步:

| 位置 | 内容 |
|:---:|:---:|
| `../skills/agent-video-driver/SKILL.md` | frontmatter 的 `metadata.version` |
| `../README.md` | 版本徽章 |
| `../README_en-US.md` | 版本徽章 |

## 资源

参考成片放在 `resource/video/` 下, 页面用相对目录引入, 不重复拷进 `public/`. `nuxt.config.ts` 的 `nitro.publicAssets` 把 `resource/` 挂成 `/resource`, 视频文件名含连字符与长单词, 页面侧统一由 `src/composables/useAssetUrl.ts` 拼路径并做 URL 编码.

视频海报不引用任何成片画面, 也不使用封面图, 只用 `src/assets/css/main.css` 的 `--poster-bg` 渐变作底, 两套主题各一份取值. 主 `../README.md` 与 `../README_en-US.md` 的参考成片区不引用仓库内的视频文件, 只放在线演示的地址, 原因见下.

## 本地开发

```
cd site
npm install
npm run dev
```

开发地址是 http://localhost:7878 , 端口与地址在 `nuxt.config.ts` 的 `devServer` 里设定.

地址写的是 `localhost`, 在当前 Node 版本下优先解析到 IPv6, 开发服务器实际监听在 `::1:7878`. 所以浏览器访问 `localhost:7878` 正常, 换成 `127.0.0.1:7878` 会连不上; 想在 IPv4 上访问就把 `devServer.host` 改成 `127.0.0.1`.

## 构建与部署

```
cd site
npm run generate
```

构建产物的目录已列入本目录 `.gitignore`. 部署由 `../.github/workflows/build-site-and-deploy-as-pages.yml` 完成: 装依赖, 构建, 自检产物里的首页与参考视频, 再发布到 GitHub Pages. 工作流里那几条自检不要删, 它们挡的是白屏与缺成片两类线上事故.

站点挂在仓库子路径下, `nuxt.config.ts` 的 `app.baseURL` 默认写死为 `/Agent-Video-Driver.SKILL/`; 换域名或换成根路径时, 构建前用环境变量 `NUXT_APP_BASE_URL` 覆盖即可.

## 前端规范

站点遵守本仓库对前端的既有约定, 具体落点:

| 要求 | 落点 |
|:---:|:---:|
| 不用浏览器原生弹窗提醒 | `src/composables/useSiteToast.ts` 加 `src/components/SiteToast.vue` |
| 不用原生二次确认 | `src/components/ConfirmButton.vue`: 原按钮替换为确认按钮, 3 秒内再点一次才执行, 超时回归初始状态 |
| 默认隐藏侧边滚动条并允许回退 | `src/composables/useScrollbar.ts` 加 `src/components/ScrollbarToggle.vue`, 开关在导航栏, 选择记在 localStorage; 首次访问用飘窗告知一次 |
| 默认暗色, 可切亮色, 刷新不丢选择 | `src/composables/useTheme.ts` 加 `src/components/ThemeToggle.vue`, 开关在导航栏 |
| 首屏不闪烁 | `nuxt.config.ts` 里的内联脚本在样式生效前就把主题与滚动条偏好写到 `html` 上, 失败时退回默认值 |
| 两套主题各自达标 | 亮色不是反转暗色, 而是换更深一档的同色系, 两套都单独测过对比度 |
| 表格文本水平居中 | `src/assets/css/main.css` |
| 页面底部标注作者信息 | `src/components/AuthorFooter.vue`, 文案由 `AUTHOR` 常量控制 |
| 正文对比度 >= 4.5:1 | 颜色令牌在 `src/assets/css/main.css`; 最紧的一档是 `--text-mute`, 4.66:1 |
| 交互控件边框 >= 3:1 | `--line-control`, 对 `--bg` / `--bg-soft` / `--panel` 分别是 3.90 / 3.71 / 3.37 |
| 焦点环必须可见 | 全局 `:focus-visible`, 不允许为了好看去掉 |
| 尊重系统的减弱动效设置 | 全局 `prefers-reduced-motion`, 关掉位移与脉冲, 只留状态颜色变化 |
| 可点区域 >= 44px | `--tap` 令牌, 按钮与导航链接统一用 `min-height` 保证, 不靠 padding 凑 |
| 水平内边距自适应 | `--gutter: clamp(20px, 5vw, 48px)`, 窄屏 20px 宽屏 48px |
| 长文行宽受限 | `--measure: 68ch`, 避免大屏上文字边到边 |
| 移动端不横向滚动 | 每个区块都套 `.wrap`, 宽表格交给 `.table-wrap` 局部滚动 |
| 预留尺寸避免加载抖动 | `.video-frame` 用 `aspect-ratio: 16 / 9` |
| 锚点跳转不被吸顶导航遮挡 | `section[id]` 的 `scroll-margin-top` 留出导航高度 |
| 无横向滚动 | 命令行文本与 `.cmd-stack` 子项显式设 `min-width: 0`; 卡片网格用 `minmax(min(268px, 100%), 1fr)` |
| 手机首屏一屏内 | 手机宽度下隐藏技术栈徽章与导航里的 GitHub 文字入口, 主题与滚动条开关保留 |

## 响应式

断点只有三档, 都在 `src/assets/css/main.css` 末尾:

| 断点 | 变化 |
|:---:|:---:|
| `>= 1024px` | 流程与取舍改成两列, 单列时每行右侧会空出一大片 |
| `<= 1023px` | 收紧导航的字号与间距, 让它在平板上仍排成一行 |
| `<= 767px` | 导航排两行(第二行链接横向滚动); 隐藏技术栈徽章与导航里的 GitHub 文字入口; 区块内边距收窄 |
| `<= 400px` | 流程行的序号缩小, 把宽度让给文字 |

手机宽度下导航约 112px, 首屏约 614px, 两者相加仍在 844px 的视口之内.

两个已经踩过的坑, 记在这里备查:

- **flex 与 grid 子项的 `min-width` 默认是 `auto`**: 命令行块里是长串不换行文本, 它会把整页撑宽, 手机宽度下能撑出 200 多像素的横向滚动. 命令行的文本节点与 `.cmd-stack` 的子项都显式设了 `min-width: 0`, 超出的部分交给自身的 `overflow-x: auto`
- **grid 容器的 `gap` 与子元素的 `margin` 会叠加**: 首屏曾经因此把间距从 32px 翻倍到 56px. 现在首屏间距统一交给 `gap`, 子元素只留少量 `margin-top` 作分组

## 为什么 README 不直接嵌视频

GitHub 不为仓库里已提交的 MP4 渲染播放器, 三条路都走不通, 所以主 README 只放在线演示的地址:

| 尝试的形式 | 结果 |
|:---:|:---:|
| 图片语法指向 MP4 | 渲染成破图, 图片语法不适用于视频 |
| `video` 标签 | 被 GitHub 的 HTML 白名单过滤掉, 白名单里没有这个元素 |
| 裸链接指向仓库 MP4 | 落到文件页或直接下载, 不是页面内播放 |
| 拖进编辑框上传附件 | GitHub 会内嵌播放器, 但单个文件上限 10 MB, 本项目的成片是 11.79 MB |

README 里唯一能自动播放的内联形式是动图 GIF, 代价是没有声音, 只有 256 色, 且体积随秒数迅速上涨. 权衡后选择不嵌, 改成指向在线演示: 站点由 GitHub Pages 提供, MP4 会带正确的视频响应头, 浏览器原生播放器可以直接放.

## 样式组织

样式只有 `src/assets/css/main.css` 一个文件, 不引入 CSS 框架. 颜色, 间距, 字号, 层级全部走文件顶部的设计令牌, 组件里不写裸值:

| 令牌组 | 取值 |
|:---:|:---:|
| 间距 | `--sp-1` 到 `--sp-9`, 4 的倍数 |
| 字号 | `--fs-xs` 12px 到 `--fs-2xl` 32px |
| 层级 | `--z-nav` 20, `--z-toast` 60 |
| 版心 | `--wrap` 1120px, `--gutter` 自适应内边距 |
| 可点区域 | `--tap` 44px |

颜色令牌分两套, 都只写颜色, 间距与字号不重复: 暗色写在 `:root` 与 `html[data-theme="dark"]`, 是默认值; 亮色写在 `html[data-theme="light"]`. 两者都声明 `color-scheme`, 让滚动条与视频控件这类原生部件跟着主题走.

切换只改 `html` 上的 `data-theme`, 不做逐元素换肤. 主题与滚动条的取舍记在 localStorage, 首屏套用由 `nuxt.config.ts` 生成的内联脚本负责, 该脚本排在样式表之前, 所以不会出现先亮后暗或滚动条闪一下.

## 为什么锁定 Nuxt 版本

`package.json` 里的 `nuxt` 是精确版本, 不带 `^`. 原因是最新的 `4.6.0` 会让 `npm run generate` 的预渲染全部返回 500, 报 `Either manifest or precomputed data must be provided`; 该问题在一个全新的空工程里也能复现, 与本目录的代码无关.

升级 `nuxt` 之前, 先在本目录跑一遍 `npm run generate`, 确认首页与参考视频都进了构建产物再提交.

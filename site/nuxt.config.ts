import { fileURLToPath } from 'node:url'
import {
  SCROLLBAR_CLASS,
  SCROLLBAR_STORAGE_KEY,
  THEME_STORAGE_KEY,
} from './src/constants/storage'

// 站点挂在仓库子路径下, 与 GitHub Pages 的地址一致
// 需要改成根路径或自定义域名时, 构建前设置环境变量 NUXT_APP_BASE_URL 覆盖, 例如 '/'
const BASE_URL = process.env.NUXT_APP_BASE_URL || '/Agent-Video-Driver.SKILL/'

const SITE_NAME = 'Agent-Video-Driver.SKILL'
const SITE_DESC = '让你的 Agent 用脚本化的工具链自主生成视频, 不需要任何视频生成模型'

// 首屏套用主题与滚动条偏好: 必须早于样式生效, 否则会先亮后暗, 滚动条也会闪一下
// 失败时退回默认值 (暗色主题, 隐藏滚动条)
const BOOT_SCRIPT = `(function(){var d=document.documentElement;try{d.dataset.theme=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)})==='light'?'light':'dark';if(localStorage.getItem(${JSON.stringify(SCROLLBAR_STORAGE_KEY)})==='0'){d.classList.remove(${JSON.stringify(SCROLLBAR_CLASS)})}else{d.classList.add(${JSON.stringify(SCROLLBAR_CLASS)})}}catch(e){d.dataset.theme='dark';d.classList.add(${JSON.stringify(SCROLLBAR_CLASS)})}})();`

export default defineNuxtConfig({
  compatibilityDate: '2026-10-08',
  // 核心源码放在 src/, 与 site/resource/ 这类静态资源分开
  srcDir: 'src',
  ssr: true,
  devtools: { enabled: false },
  // 本地地址与端口按项目设计细节定为 localhost:7878 (Nuxt 原生默认是 3000)
  devServer: { host: 'localhost', port: 7878 },
  app: {
    baseURL: BASE_URL,
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      title: SITE_NAME,
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: SITE_DESC },
        { name: 'theme-color', content: '#0b1220' },
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: `${BASE_URL}favicon.svg` }],
      script: [{ innerHTML: BOOT_SCRIPT, tagPosition: 'head' }],
    },
  },
  css: ['~/assets/css/main.css'],
  nitro: {
    // github_pages 预设会产出 .nojekyll, 否则以下划线开头的 _nuxt/ 会被 Jekyll 忽略
    preset: 'github_pages',
    // 参考视频不在 src/ 也不在 public/, 单独把 resource/ 挂成 /resource 静态目录
    publicAssets: [
      {
        dir: fileURLToPath(new URL('./resource', import.meta.url)),
        baseURL: '/resource',
        maxAge: 60 * 60 * 24 * 7,
      },
    ],
  },
})

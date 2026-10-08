// 首屏内联脚本与浏览器端共用这几个键名与类名, 集中放这里, 保证只有一处定义
// 内联脚本由 nuxt.config.ts 生成, 它也从这里读

// 主题名
export const THEME_STORAGE_KEY = 'avd-theme'
// 滚动条是否隐藏
export const SCROLLBAR_STORAGE_KEY = 'avd-scrollbar-hidden'
// 隐藏滚动条时挂在 html 上的类名
export const SCROLLBAR_CLASS = 'avd-hide-scrollbar'

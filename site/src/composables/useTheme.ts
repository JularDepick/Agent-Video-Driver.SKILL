import { ref } from 'vue'
import { THEME_STORAGE_KEY } from '~/constants/storage'

// 站点主题: 只有暗色与亮色两种, 默认暗色
// 选择记在 localStorage; 首屏套用由 nuxt.config 里的内联脚本完成, 避免先亮后暗的闪烁
export type ThemeName = 'dark' | 'light'

const theme = ref<ThemeName>('dark')
let ready = false

export function useTheme() {
  function apply() {
    if (!import.meta.client) return
    document.documentElement.dataset.theme = theme.value
  }

  function init() {
    if (!import.meta.client || ready) return
    ready = true
    // 内联脚本已经写过一次, 这里只把真实值同步进响应式状态, 保证按钮图标与页面一致
    theme.value = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
  }

  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    if (import.meta.client) {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme.value)
    }
    apply()
  }

  return { theme, init, toggle }
}

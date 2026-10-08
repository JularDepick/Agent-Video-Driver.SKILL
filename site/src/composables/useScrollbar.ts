import { ref } from 'vue'
import { SCROLLBAR_CLASS, SCROLLBAR_STORAGE_KEY } from '~/constants/storage'

// 默认隐藏浏览器侧边滚动条, 导航栏提供回退开关, 选择记在 localStorage
// 首屏套用由 nuxt.config 里的内联脚本完成, 避免滚动条闪现

const hidden = ref(true)
let ready = false

export function useScrollbar() {
  function apply() {
    if (!import.meta.client) return
    document.documentElement.classList.toggle(SCROLLBAR_CLASS, hidden.value)
  }

  function init() {
    if (!import.meta.client || ready) return
    ready = true
    // 内联脚本已按 localStorage 设好类名, 这里同步真实状态, 避免 SSR 与客户端不一致
    hidden.value = document.documentElement.classList.contains(SCROLLBAR_CLASS)
    if (window.localStorage.getItem(SCROLLBAR_STORAGE_KEY) === null) {
      // 首次访问时告知用户默认隐藏了滚动条, 并说明去哪里切回来
      useSiteToast().push('已默认隐藏浏览器滚动条, 可在导航栏点滑块图标切回来', 'info', 7000)
    }
  }

  function toggle() {
    hidden.value = !hidden.value
    if (import.meta.client) {
      window.localStorage.setItem(SCROLLBAR_STORAGE_KEY, hidden.value ? '1' : '0')
    }
    apply()
  }

  return { hidden, init, toggle }
}

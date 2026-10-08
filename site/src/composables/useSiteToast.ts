import { ref } from 'vue'

// 自定义飘窗提醒: AGENTS.md 第 11 章禁止使用浏览器原生弹窗
// 状态放在模块级, 于是任何组件里调 useSiteToast() 拿到的都是同一份队列
export type ToastKind = 'info' | 'ok' | 'warn'

export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
}

const items = ref<ToastItem[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let seq = 0

export function useSiteToast() {
  function dismiss(id: number) {
    items.value = items.value.filter((t) => t.id !== id)
    const timer = timers.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.delete(id)
    }
  }

  function push(text: string, kind: ToastKind = 'info', ms = 2800) {
    const id = ++seq
    items.value = [...items.value, { id, kind, text }]
    timers.set(
      id,
      setTimeout(() => dismiss(id), ms),
    )
    return id
  }

  return { items, push, dismiss }
}

<template>
  <div class="cmd">
    <code class="cmd-text">{{ command }}</code>
    <button class="cmd-copy" type="button" @click="copy">
      {{ copied ? '已复制' : '复制' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ command: string }>()
const { push } = useSiteToast()
const copied = ref(false)

// 复制失败时用自定义飘窗提示, 不用原生 alert
async function copy() {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(props.command)
    } else {
      const area = document.createElement('textarea')
      area.value = props.command
      area.setAttribute('readonly', 'readonly')
      area.style.position = 'fixed'
      area.style.top = '-1000px'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      document.body.removeChild(area)
    }
    copied.value = true
    push('已复制到剪贴板', 'ok')
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    push('复制失败, 请手动选中命令后复制', 'warn')
  }
}
</script>

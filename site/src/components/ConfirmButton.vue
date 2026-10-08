<template>
  <button
    class="btn"
    :class="[`btn-${variant}`, { 'is-armed': armed }]"
    type="button"
    :disabled="disabled"
    @click="onClick"
  >
    {{ armed ? confirmLabel : label }}
    <span v-if="armed" class="btn-count" aria-hidden="true">3s</span>
  </button>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

// AGENTS.md 第 11 章: 前端不用浏览器原生二次确认
// 改为在原按钮上"替换为确认按钮, 3 秒内再点一次确认, 超时回归初始状态"
const props = withDefaults(
  defineProps<{
    label: string
    confirmLabel?: string
    variant?: string
    armMs?: number
    disabled?: boolean
  }>(),
  {
    confirmLabel: '再点一次确认',
    variant: 'primary',
    armMs: 3000,
    disabled: false,
  },
)

const emit = defineEmits<{ confirm: [] }>()

const armed = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

function disarm() {
  armed.value = false
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function onClick() {
  if (!armed.value) {
    armed.value = true
    timer = setTimeout(disarm, props.armMs)
    return
  }
  disarm()
  emit('confirm')
}

onBeforeUnmount(disarm)
</script>

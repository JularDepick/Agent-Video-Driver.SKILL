<template>
  <div class="toast-layer" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <button
        v-for="t in items"
        :key="t.id"
        class="toast"
        :class="`toast-${t.kind}`"
        type="button"
        @click="dismiss(t.id)"
      >
        <span class="toast-mark" aria-hidden="true" />
        <span class="toast-text">{{ t.text }}</span>
      </button>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
// 自定义飘窗容器: 替代浏览器原生 alert, 点击可立即关闭
const { items, dismiss } = useSiteToast()
</script>

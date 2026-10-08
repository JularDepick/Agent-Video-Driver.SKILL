<template>
  <button class="icon-btn" type="button" :aria-label="label" :title="label" @click="toggle">
    <!-- 轨道加滑块, 滑块长短表示当前是隐藏还是显示 -->
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="3" width="6" height="18" rx="3" />
      <path :d="hidden ? 'M12 7v3' : 'M12 7v10'" />
    </svg>
  </button>
</template>

<script setup lang="ts">
const { hidden, toggle } = useScrollbar()

const label = computed(() =>
  hidden.value ? '显示浏览器滚动条' : '隐藏浏览器滚动条',
)
</script>

<template>
  <button class="icon-btn" type="button" :aria-label="label" :title="label" @click="toggle">
    <!-- 当前是暗色时显示太阳 (点了变亮), 当前是亮色时显示月亮 -->
    <svg
      v-if="theme === 'dark'"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4L17 7M7 17l-1.6 1.6" />
    </svg>
    <svg
      v-else
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M20.5 14.8A8.6 8.6 0 0 1 9.2 3.5a8.6 8.6 0 1 0 11.3 11.3Z" />
    </svg>
  </button>
</template>

<script setup lang="ts">
const { theme, toggle } = useTheme()

const label = computed(() => (theme.value === 'dark' ? '切换到亮色主题' : '切换到暗色主题'))
</script>

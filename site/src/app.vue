<template>
  <div class="app">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
    <SiteToast />
  </div>
</template>

<script setup lang="ts">
// 首屏的 data-theme 与滚动条类名由 nuxt.config 里的内联脚本先写好, 这里只把真实值同步进响应式状态
const { init: initTheme } = useTheme()
const { init: initScrollbar } = useScrollbar()

onMounted(() => {
  initTheme()
  initScrollbar()
})
</script>

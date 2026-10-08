<template>
  <header class="nav">
    <div class="wrap nav-inner">
      <a class="nav-brand" :href="base">
        <span class="nav-dot" aria-hidden="true" />
        <span>{{ SITE.name }}</span>
      </a>
      <nav class="nav-links" aria-label="主导航">
        <a href="#showcase">参考成片</a>
        <a href="#features">能做什么</a>
        <a href="#flow">工作流程</a>
        <a href="#start">快速开始</a>
        <a href="#install">安装</a>
      </nav>
      <div class="nav-tools">
        <a class="nav-ext" :href="SITE.repo" target="_blank" rel="noopener">GitHub</a>
        <ThemeToggle />
        <ScrollbarToggle />
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { SITE } from '~/constants/site'

const base = useRuntimeConfig().app.baseURL || '/'
</script>

<template>
  <footer class="foot">
    <div class="wrap foot-inner">
      <p class="foot-author">
        Copyright &copy; {{ AUTHOR.copyrightYear }}
        <a :href="AUTHOR.github" target="_blank" rel="noopener">{{ AUTHOR.name }}</a>
        <span class="foot-sep">|</span>
        <a :href="`mailto:${AUTHOR.email}`">{{ AUTHOR.email }}</a>
      </p>
      <p class="foot-meta">
        <a :href="SITE.repo" target="_blank" rel="noopener">{{ SITE.name }}</a>
        版本 {{ SITE.version }}
        <span class="foot-sep">|</span>
        许可证
        <a :href="`${SITE.repo}/blob/main/LICENSE`" target="_blank" rel="noopener">{{ SITE.license }}</a>
      </p>
    </div>
  </footer>
</template>

<script setup lang="ts">
import { AUTHOR, SITE } from '~/constants/site'
</script>

<template>
  <section :id="anchor" class="block">
    <div class="wrap">
      <header class="block-head">
        <p v-if="kicker" class="block-kicker">{{ kicker }}</p>
        <h2 class="block-title">{{ title }}</h2>
        <p v-if="lead" class="block-lead">{{ lead }}</p>
      </header>
      <div class="block-body">
        <slot />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    kicker?: string
    lead?: string
    anchor?: string
  }>(),
  { kicker: '', lead: '', anchor: '' },
)
</script>

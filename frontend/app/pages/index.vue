<template>
  <main>
    <Navigation :class="{ 'nav--visible': isStarted }" />
    <Hero @started="isStarted = true" />
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const isStarted = ref(false)

useHead({
  title: 'Genlab® — Freshly Engineered Creative Agency',
  meta: [
    {
      name: 'description',
      content:
        'Genlab® is a premium creative agency blending AI, design, and engineering to build legendary digital experiences.',
    },
  ],
})
</script>

<style scoped>
main {
  width: 100%;
  min-height: 100vh;
}
</style>

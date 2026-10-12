<template>
  <div class="suggestions" aria-label="Suggested prompts">
    <button
      v-for="suggestion in suggestions"
      :key="suggestion"
      type="button"
      class="hero__btn"
      @click="$emit('send', suggestion)"
      :aria-label="`Ask: ${suggestion}`"
    >
      {{ suggestion }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  suggestions: string[]
}>()

defineEmits<{
  (event: 'send', value: string): void
}>()
</script>

<style scoped>
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.625rem;
}

.hero__btn {
  display: inline-flex;
  align-items: center;
  padding: 0.6rem 1.25rem;
  font-size: 0.8125rem;
  font-weight: 450;
  color: #333;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(26, 26, 26, 0.08);
  border-radius: 100px;
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  cursor: pointer;
  text-decoration: none;
}

.hero__btn:hover {
  background: #1a1a1a;
  color: #fff;
  border-color: #1a1a1a;
  transform: translateY(-2px);
}

.hero__btn:focus-visible {
  outline: 2px solid #1a1a1a;
  outline-offset: 2px;
}
</style>

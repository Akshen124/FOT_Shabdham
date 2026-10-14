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
  font-weight: 500;
  color: #1e293b;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(35, 115, 244, 0.18);
  border-radius: 100px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 2px 8px rgba(35, 115, 244, 0.05);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  cursor: pointer;
  text-decoration: none;
}

.hero__btn:hover {
  background: #2373F4;
  color: #ffffff;
  border-color: #2373F4;
  box-shadow: 0 4px 14px rgba(35, 115, 244, 0.28);
  transform: translateY(-2px);
}

.hero__btn:focus-visible {
  outline: 2px solid #2373F4;
  outline-offset: 2px;
}
</style>

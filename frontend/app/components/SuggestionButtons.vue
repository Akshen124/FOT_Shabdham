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
  border: 1px solid rgba(91, 50, 91, 0.18);
  border-radius: 100px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 2px 8px rgba(91, 50, 91, 0.05);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  cursor: pointer;
  text-decoration: none;
}

.hero__btn:hover {
  background: #5B325B;
  color: #ffffff;
  border-color: #5B325B;
  box-shadow: 0 4px 14px rgba(91, 50, 91, 0.28);
  transform: translateY(-2px);
}

.hero__btn:focus-visible {
  outline: 2px solid #5B325B;
  outline-offset: 2px;
}

@media (max-width: 768px) {
  .suggestions {
    gap: 0.4rem;
  }

  .hero__btn {
    padding: 0.45rem 0.85rem;
    font-size: 0.775rem;
    white-space: normal;
    text-align: left;
    line-height: 1.35;
    max-width: 100%;
    word-break: break-word;
  }
}
</style>

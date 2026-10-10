<template>
  <button
    type="button"
    class="voice-button"
    :class="{
      'voice-button--listening': listening,
      'voice-button--processing': processing,
      'voice-button--speaking': speaking,
      'voice-button--error': error,
      'voice-button--disabled': disabled,
    }"
    :disabled="disabled"
    :aria-label="ariaLabel"
    @click="$emit('click')"
  >
    <span class="voice-button__icon" aria-hidden="true">{{ icon }}</span>
    <span class="voice-button__label">{{ label }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    disabled?: boolean
    listening?: boolean
    processing?: boolean
    speaking?: boolean
    error?: boolean
  }>(),
  {
    disabled: false,
    listening: false,
    processing: false,
    speaking: false,
    error: false,
  },
)

const emit = defineEmits<{
  (event: 'click'): void
}>()

const icon = computed(() => {
  if (props.error) return '⚠️'
  if (props.listening) return '🔴'
  if (props.processing) return '⏳'
  if (props.speaking) return '🔊'
  return '🎤'
})

const label = computed(() => {
  if (props.error) return 'Try again'
  if (props.listening) return 'Listening...'
  if (props.processing) return 'Processing...'
  if (props.speaking) return 'Speaking...'
  return 'Click to speak'
})

const ariaLabel = computed(() => {
  if (props.error) return 'Try again'
  if (props.listening) return 'Listening to your voice'
  if (props.processing) return 'Processing your voice input'
  if (props.speaking) return 'Speaking response'
  return 'Start voice input'
})
</script>

<style scoped>
.voice-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 11.5rem;
  min-height: 3.5rem;
  border-radius: 999px;
  padding: 0.75rem 1.25rem;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(26, 26, 26, 0.12);
  color: #1a1a1a;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 12px 28px rgba(28, 28, 28, 0.08);
  transition: all 0.2s ease;
}

.voice-button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 16px 32px rgba(28, 28, 28, 0.12);
}

.voice-button:active:not(:disabled) {
  transform: translateY(0);
}

.voice-button:focus-visible {
  outline: 2px solid #1a1a1a;
  outline-offset: 2px;
}

.voice-button--listening {
  background: rgba(255, 255, 255, 0.85);
  border-color: rgba(200, 37, 54, 0.4);
  box-shadow: 0 0 0 0 rgba(209, 52, 52, 0.35);
  animation: pulse 1.4s ease-out infinite;
}

.voice-button--processing,
.voice-button--speaking {
  background: rgba(17, 17, 17, 0.96);
  color: #fff;
}

.voice-button--error {
  background: rgba(128, 77, 77, 0.12);
  border-color: rgba(128, 77, 77, 0.24);
  color: #4d2a2a;
}

.voice-button--disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.voice-button__icon {
  font-size: 1.1rem;
  line-height: 1;
}

.voice-button__label {
  font-size: 0.8rem;
  font-weight: 500;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(217, 59, 76, 0.35);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(217, 59, 76, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(217, 59, 76, 0);
  }
}
</style>

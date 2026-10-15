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
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(35, 115, 244, 0.2);
  color: #0f172a;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 10px 25px rgba(35, 115, 244, 0.08);
  transition: all 0.2s ease;
}

.voice-button:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: #2373F4;
  box-shadow: 0 14px 30px rgba(35, 115, 244, 0.16);
}

.voice-button:active:not(:disabled) {
  transform: translateY(0);
}

.voice-button:focus-visible {
  outline: 2px solid #2373F4;
  outline-offset: 2px;
}

.voice-button--listening {
  background: rgba(255, 255, 255, 0.95);
  border-color: #2373F4;
  box-shadow: 0 0 0 0 rgba(35, 115, 244, 0.4);
  animation: pulse 1.4s ease-out infinite;
}

.voice-button--processing,
.voice-button--speaking {
  background: #2373F4;
  border-color: #2373F4;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(35, 115, 244, 0.35);
}

.voice-button--error {
  background: rgba(220, 38, 38, 0.1);
  border-color: rgba(220, 38, 38, 0.25);
  color: #b91c1c;
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
    box-shadow: 0 0 0 0 rgba(35, 115, 244, 0.4);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(35, 115, 244, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(35, 115, 244, 0);
  }
}
</style>

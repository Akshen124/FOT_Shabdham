<template>
  <div ref="root" class="chat-message" :class="[`chat-message--${role}`]">
    <div class="chat-message__bubble">
      <span class="chat-message__label">{{ role === 'user' ? '' : '' }}</span>
      <p v-if="role === 'assistant'" class="assistant-text">{{ displayedText }}<span v-if="!typingDone" class="caret"></span></p>
      <p v-else>{{ text }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps<{
  role: 'user' | 'assistant'
  text: string
}>()

// Root element reference for scrolling
const root = ref<HTMLElement | null>(null)

// Typewriter state
const displayedText = ref('')
const typingDone = ref(false)
let typingTimer: ReturnType<typeof setTimeout> | null = null
let typingIndex = 0

function clearTyping() {
  if (typingTimer) {
    clearTimeout(typingTimer)
    typingTimer = null
  }
  typingDone.value = true
}

function typeChar() {
  if (typingTimer) {
    clearTimeout(typingTimer)
    typingTimer = null
  }
  const full = props.text
  const speed = 25
  const step = () => {
    if (typingIndex < full.length) {
      displayedText.value += full.charAt(typingIndex)
      typingIndex++
      typingTimer = setTimeout(step, speed)
    } else {
      typingDone.value = true
    }
  }
  step()
}

function startTyping() {
  displayedText.value = ''
  typingDone.value = false
  typingIndex = 0
  typeChar()
}

watch(
  () => props.text,
  (newVal, oldVal) => {
    if (props.role === 'assistant') {
      if (oldVal && newVal.startsWith(oldVal) && typingIndex <= newVal.length) {
        typingDone.value = false
        typeChar()
      } else {
        clearTyping()
        startTyping()
      }
    } else {
      clearTyping()
      displayedText.value = newVal
      typingDone.value = true
    }
  },
  { immediate: true }
)

// Auto‑scroll whenever the displayed text changes (typewriter updates)
watch(displayedText, async () => {
  await nextTick()
  const container = root.value?.closest('.hero__chat') as HTMLElement | null
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }
})

function onStopTyping() {
  clearTyping()
}

onMounted(() => {
  window.addEventListener('stop-typing', onStopTyping)
})

onUnmounted(() => {
  window.removeEventListener('stop-typing', onStopTyping)
  clearTyping()
})
</script>

<style scoped>
.chat-message {
  display: flex;
  width: 100%;
}

.chat-message--user {
  justify-content: flex-end;
}

.chat-message--assistant {
  justify-content: flex-start;
}


.chat-message__bubble {
  max-width: min(100%, 28rem);
  padding: 0.85rem 1.15rem 0.9rem;
  border-radius: 1.25rem;
}

.chat-message--user .chat-message__bubble {
  background: #5B325B;
  color: #ffffff;
  border-radius: 1.25rem 1.25rem 0.25rem 1.25rem;
  box-shadow: 0 4px 14px rgba(91, 50, 91, 0.28);
}

.chat-message__label {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  opacity: 0.85;
  margin-bottom: 0.4rem;
}

.chat-message__label:empty {
  display: none;
}

.chat-message--assistant .chat-message__label {
  color: #5B325B;
}

.chat-message__bubble p {
  font-size: 0.94rem;
  line-height: 1.6;
  color: inherit;
  white-space: pre-wrap;
}



/* Assistant message typography */
.chat-message--assistant .chat-message__bubble p {
  font-size: 1.625rem; /* ~26px */
  line-height: 1.3;
  color: #0f172a;
  font-family: "HelveticaNowDisplay", 'Inter', sans-serif;
}

.caret {
  display: inline-block;
  width: 2px;
  background: #5B325B;
  animation: blink 1s steps(2, start) infinite;
  margin-left: 3px;
}
@keyframes blink { to { visibility: hidden; } }

@media (max-width: 768px) {
  .chat-message__bubble {
    max-width: 92%;
    padding: 0.65rem 0.95rem;
    border-radius: 1rem;
  }

  .chat-message--user .chat-message__bubble {
    border-radius: 1rem 1rem 0.25rem 1rem;
  }

  .chat-message__bubble p {
    font-size: 0.88rem;
    line-height: 1.5;
  }

  .chat-message--assistant .chat-message__bubble p {
    font-size: clamp(1.05rem, 4.4vw, 1.35rem);
    line-height: 1.35;
  }
}
</style>

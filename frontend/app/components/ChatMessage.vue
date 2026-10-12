<template>
  <div ref="root" class="chat-message" :class="[`chat-message--${role}`]">
    <div class="chat-message__bubble">
      <span class="chat-message__label">{{ role === 'user' ? 'USER' : 'AI' }}</span>
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

function startTyping() {
  displayedText.value = ''
  typingDone.value = false
  typingIndex = 0
  const full = props.text
  const speed = 30 // ms per char, can tweak
  const typeChar = () => {
    if (typingIndex < full.length) {
      displayedText.value += full.charAt(typingIndex)
      typingIndex++
      typingTimer = setTimeout(typeChar, speed)
    } else {
      typingDone.value = true
    }
  }
  typeChar()
}

watch(
  () => props.text,
  (newVal, oldVal) => {
    clearTyping()
    if (props.role === 'assistant') {
      startTyping()
    } else {
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
  padding: 0.85rem 1rem 0.9rem;
}

.chat-message--user .chat-message__bubble {
  background: rgba(17, 17, 17, 0.96);
  color: #fff;
}

.chat-message__label {
  display: inline-block;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  opacity: 0.7;
  margin-bottom: 0.4rem;
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
    color: #000000;
    font-family: "HelveticaNowDisplay", 'Inter', sans-serif;
  }

  .caret {
    display: inline-block;
    width: 1px;
    background: #000;
    animation: blink 1s steps(2, start) infinite;
    margin-left: 2px;
  }
  @keyframes blink { to { visibility: hidden; } }
</style>

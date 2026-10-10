<template>
  <section
    class="hero"
    :class="{
      'hero--started': isStarted,
      'hero--interactive': !isStarted && modelLoaded,
      'hero--chat-active': messages.length > 0 || isThinking || Boolean(error),
    }"
    aria-label="Hero section"
    @click="handleHeroClick"
  >
    <div class="hero__bg" aria-hidden="true" />

    <div class="hero__model" aria-hidden="true">
      <ClientOnly>
        <TVHead
          ref="tvHeadRef"
          @loaded="onModelLoaded"
          @error="onModelError"
          @started="onModelStarted"
        />
      </ClientOnly>
    </div>

    <div class="hero__content" :class="{ 'hero__content--visible': contentVisible }">
      <p class="hero__intro font-body">
        OK, hi! I'm your<br />freshly engineered assistant.
      </p>

      <h1 class="hero__heading font-display">
        <span class="hero__heading-line">A legend enters the chat.</span>
        <span class="hero__heading-line hero__heading-line--italic">Let's make magic.</span>
      </h1>

      <div class="hero__actions">
        <SuggestionButtons :suggestions="suggestions" @send="handleSuggestedMessage" />
      </div>

      <div class="hero__composer" v-if="messages.length || isThinking || Boolean(error)">
        <div class="hero__chat" role="log" aria-live="polite">
          <ChatMessage
            v-for="message in messages"
            :key="message.id"
            :role="message.role"
            :text="message.text"
          />
        </div>

        <div v-if="isThinking" class="hero__thinking">⏳ Thinking...</div>
        <div v-if="error" class="hero__error">{{ error }}</div>
      </div>

      <div class="hero__composer-controls">
        <form class="hero__input-row" @submit.prevent="submitInput">
          <label class="sr-only" for="chat-message-input">Type a message</label>
          <input
            id="chat-message-input"
            v-model="input"
            class="hero__input"
            type="text"
            placeholder="What are the services they provide?"
            :disabled="isThinking"
            aria-label="Type your message"
          />
          <button class="hero__send" type="submit" :disabled="isThinking || !input.trim()" aria-label="Send message">
            Send
          </button>
        </form>

        <div class="hero__voice-area">
          <VoiceButton
            :listening="isListening"
            :processing="isThinking"
            :speaking="isSpeaking"
            :error="Boolean(voiceError)"
            :disabled="isThinking"
            @click="toggleVoiceInput"
          />
          <p v-if="voiceError || ttsWarning" class="hero__voice-error">
            {{ voiceError || ttsWarning }}
          </p>
        </div>
      </div>
    </div>

    <Transition name="fade">
      <div v-if="!modelLoaded" class="hero__loader" aria-label="Loading 3D model">
        <div class="hero__loader-dot" />
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import ChatMessage from '~/components/ChatMessage.vue'
import SuggestionButtons from '~/components/SuggestionButtons.vue'
import VoiceButton from '~/components/VoiceButton.vue'
import { unlockAudioPlayback } from '~/services/chatService'
import { useChat } from '~/composables/useChat'
import { useSpeechRecognition } from '~/composables/useSpeechRecognition'

const suggestions = [
  'What about GenLab',
  'Services',
  'Drop a quick word',
  'Discover our culture',
  'Write us: info@genlab.com',
]

const input = ref('')
const tvHeadRef = ref<any>(null)
const modelLoaded = ref(false)
const isStarted = ref(false)
const contentVisible = ref(false)

const { messages, isThinking, isSpeaking, error, ttsWarning, sendMessage } = useChat()
const {
  isListening,
  isSupported,
  error: voiceError,
  transcript: speechTranscript,
  startListening,
  stopListening,
} = useSpeechRecognition()

const emit = defineEmits<{
  (e: 'started'): void
}>()

async function handleSuggestedMessage(message: string) {
  input.value = message
  await sendMessage(message)
}

async function submitInput() {
  const trimmed = input.value.trim()
  if (!trimmed) return

  console.info('[CHAT-FRONTEND-DIAG] Exact typed text submitted:', trimmed)
  input.value = ''
  await sendMessage(trimmed)
}

async function handleVoiceTranscript(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return

  console.info('[CHAT-FRONTEND-DIAG] Exact voice transcript submitted:', trimmed)
  await sendMessage(trimmed)
}

watch(speechTranscript, (value) => {
  if (value) {
    handleVoiceTranscript(value)
  }
})

function onModelLoaded() {
  modelLoaded.value = true
}

function onModelStarted() {
  if (!isStarted.value) {
    isStarted.value = true
    emit('started')
    setTimeout(() => {
      contentVisible.value = true
    }, 280)
  }
}

function handleHeroClick() {
  if (tvHeadRef.value?.triggerBlink) {
    tvHeadRef.value.triggerBlink()
  }
  if (!isStarted.value && modelLoaded.value) {
    isStarted.value = true
    emit('started')
    if (tvHeadRef.value?.triggerStart) {
      tvHeadRef.value.triggerStart()
    }
    setTimeout(() => {
      contentVisible.value = true
    }, 280)
  }
}

function onModelError(err: Error) {
  console.error('[Hero] Model loading failed:', err)
  modelLoaded.value = true
  isStarted.value = true
  contentVisible.value = true
}

function toggleVoiceInput() {
  if (isThinking.value) {
    return
  }

  if (isListening.value) {
    stopListening()
    return
  }

  if (!isSupported.value) {
    voiceError.value = 'Voice input is not supported in this browser.'
    return
  }

  unlockAudioPlayback()
  startListening()
}
</script>

<style scoped>
.hero {
  position: relative;
  width: 100vw;
  height: 100vh;
  min-height: 600px;
  overflow: hidden;
  display: flex;
  align-items: center;
}

.hero__bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      ellipse 80% 70% at 62% 46%,
      #dcd9d4 0%,
      #cac5bf 45%,
      #aba7a1 100%
    );
  z-index: 0;
}

.hero__model {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}

.hero__content {
  position: relative;
  z-index: 2;
  padding-left: clamp(2rem, 6vw, 7rem);
  padding-right: 2rem;
  width: min(100%, 660px);
  opacity: 0;
  transform: translateY(20px);
  pointer-events: auto;
  transition:
    opacity 0.9s cubic-bezier(0.16, 1, 0.3, 1) 0.1s,
    transform 0.9s cubic-bezier(0.16, 1, 0.3, 1) 0.1s;
}

.hero__content--visible {
  opacity: 1;
  transform: translateY(0);
}

.hero__content a,
.hero__content button,
.hero__content input {
  pointer-events: auto;
}

.hero__intro {
  font-size: clamp(0.875rem, 1.2vw, 1rem);
  font-weight: 400;
  line-height: 1.7;
  color: #6b6560;
  margin-bottom: 1.5rem;
  letter-spacing: 0.01em;
}

.hero__heading {
  font-size: clamp(2rem, 4.5vw, 3.5rem);
  font-weight: 600;
  line-height: 1.15;
  color: #1a1a1a;
  letter-spacing: -0.03em;
  margin-bottom: 2rem;
}

.hero__heading-line {
  display: block;
}

.hero__heading-line--italic {
  font-style: italic;
  font-weight: 400;
  color: #444;
  margin-top: 0.15em;
}

.hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.625rem;
  margin-bottom: 1rem;
}

.hero__composer {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 0.5rem;
  margin-bottom: 1rem;
  max-width: 36rem;
}

.hero__chat {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-height: 15rem;
  overflow-y: auto;
  padding-right: 0.25rem;
}

.hero__thinking,
.hero__error,
.hero__voice-error {
  font-size: 0.8rem;
  color: #3c3a36;
}

.hero__error,
.hero__voice-error {
  color: #7a3b3b;
}

.hero__input-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
  min-width: 0;
}

.hero__composer-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: min(100%, 36rem);
  margin-top: 0.5rem;
}

.hero__input {
  flex: 1;
  min-width: 0;
  border: 1px solid rgba(26, 26, 26, 0.12);
  background: rgba(255, 255, 255, 0.7);
  color: #1a1a1a;
  border-radius: 999px;
  padding: 0.95rem 1.1rem;
  font-size: 0.95rem;
  outline: none;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.hero__input:focus {
  border-color: rgba(26, 26, 26, 0.22);
  box-shadow: 0 0 0 3px rgba(26, 26, 26, 0.08);
}

.hero__send {
  border-radius: 999px;
  border: 1px solid rgba(26, 26, 26, 0.12);
  background: #1a1a1a;
  color: #fff;
  padding: 0.9rem 1.3rem;
  font-size: 0.8rem;
  font-weight: 500;
  transition: all 0.2s ease;
}

.hero__send:hover:not(:disabled) {
  opacity: 0.92;
}

.hero__send:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.hero__voice-area {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  flex: 0 0 auto;
}

.hero--chat-active {
  align-items: flex-start;
}

.hero--chat-active .hero__content {
  max-height: calc(100svh - 7rem);
  margin-top: 5.5rem;
  margin-bottom: 1rem;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-color: rgba(26, 26, 26, 0.25) transparent;
  scrollbar-width: thin;
}

.hero--chat-active .hero__intro {
  margin-bottom: 0.5rem;
}

.hero--chat-active .hero__heading {
  font-size: clamp(2rem, 3.6vw, 3rem);
  line-height: 1.08;
  margin-bottom: 1.25rem;
}

.hero--chat-active .hero__actions {
  margin-bottom: 0.5rem;
}

.hero--chat-active .hero__composer {
  gap: 0.5rem;
  margin-top: 0;
  margin-bottom: 0.5rem;
}

.hero--chat-active .hero__chat {
  max-height: clamp(7.5rem, 22vh, 11.25rem);
}

.hero--chat-active .hero__composer-controls {
  gap: 0.625rem;
  margin-top: 0;
}

.hero--interactive {
  cursor: pointer;
}

.hero__loader {
  position: absolute;
  bottom: 3rem;
  right: 3rem;
  z-index: 10;
}

.hero__loader-dot {
  width: 6px;
  height: 6px;
  background: #999;
  border-radius: 50%;
  animation: pulse-dot 1.4s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 0.3; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.5); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.5s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .hero {
    min-height: 100vh;
  }

  .hero__content {
    width: min(100%, 100%);
    padding-left: clamp(1.25rem, 5vw, 2rem);
    padding-right: clamp(1.25rem, 5vw, 2rem);
    max-width: 100%;
  }

  .hero__input-row {
    flex-direction: column;
    align-items: stretch;
  }

  .hero__composer-controls {
    flex-direction: column;
    align-items: stretch;
  }

  .hero__voice-area {
    align-items: stretch;
  }

  .hero--chat-active .hero__content {
    max-height: calc(100svh - 5rem);
    margin-top: 4.5rem;
    margin-bottom: 0.5rem;
  }

  .hero--chat-active .hero__chat {
    max-height: 24vh;
  }

  .hero__send {
    width: 100%;
  }
}
</style>

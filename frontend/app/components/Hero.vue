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
      <div ref="scrollAreaRef" class="hero__scroll-area">
        <p class="hero__intro font-body">
          OK, hi! I'm your<br />freshly engineered assistant.
        </p>

        <h1 class="hero__heading font-display">
          <span class="hero__heading-line hero__heading-line--cyber" data-text="Hey, I'm Shabdam. Let's make some magic!">
            Hey, I’m Shabdam. Let’s make some magic!<span class="hero__cyber-cursor" aria-hidden="true">_</span>
          </span>
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

          <div v-if="isThinking" class="hero__thinking"> Thinking...</div>
          <div v-if="error && !error.toLowerCase().includes('failed to fetch')" class="hero__error">{{ error }}</div>
        </div>
      </div>

      <div class="hero__composer-controls">
        <form class="hero__input-row" @submit.prevent="submitInput">
          <label class="sr-only" for="chat-message-input">Type a message</label>
          <input
            id="chat-message-input"
            v-model="input"
            class="hero__input"
            type="text"
            placeholder="Enter your request"
            :disabled="isThinking || isSpeaking"
            aria-label="Type your message"
          />
          <button v-if="!isThinking && !isSpeaking" class="hero__send" type="submit" :disabled="!input.trim()" aria-label="Send message">Send</button>
          <button v-if="isThinking || isSpeaking" class="hero__stop" type="button" @click="stopProcessing" aria-label="Stop generation">
            <!-- Simple stop square icon -->
            
            Stop
          </button>

        </form>

        <div class="hero__voice-area">
          <VoiceButton
            :listening="isListening"
            :processing="isThinking"
            :speaking="isSpeaking"
            :error="Boolean(displayVoiceError)"
            :disabled="isThinking || isSpeaking"
            @click="toggleVoiceInput"
          />
          <p v-if="displayVoiceError" class="hero__voice-error">
            {{ displayVoiceError }}
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
import { ref, computed, watch, nextTick } from 'vue'
import ChatMessage from '~/components/ChatMessage.vue'
import SuggestionButtons from '~/components/SuggestionButtons.vue'
import VoiceButton from '~/components/VoiceButton.vue'
import { unlockAudioPlayback } from '~/services/chatService'
import { useChat } from '~/composables/useChat'
import { useSpeechRecognition } from '~/composables/useSpeechRecognition'

const suggestions = [
  'What about GenLab',
  'Drop a quick word about GenLab',
  'Discover GenLab culture',
  'Services',
 
]

const scrollAreaRef = ref<HTMLDivElement | null>(null)
const input = ref('')
const tvHeadRef = ref<any>(null)
const modelLoaded = ref(false)
const isStarted = ref(false)
const contentVisible = ref(false)

const { messages, isThinking, isSpeaking, error, ttsWarning, sendMessage, stopProcessing, addMessage } = useChat()

watch(messages, () => {
  nextTick(() => {
    if (scrollAreaRef.value) {
      scrollAreaRef.value.scrollTo({
        top: scrollAreaRef.value.scrollHeight,
        behavior: 'smooth',
      })
    }
  })
}, { deep: true })

const {
  isListening,
  isSupported,
  error: voiceError,
  transcript: speechTranscript,
  startListening,
  stopListening,
} = useSpeechRecognition({
  onDisconnected: () => {
    addMessage('assistant', 'Shabdam is disconnected at the moment.')
  },
})

const displayVoiceError = computed(() => {
  const err = voiceError.value || ttsWarning.value
  if (!err) return null
  if (err.toLowerCase().includes('failed to fetch') || err.toLowerCase().includes('networkerror')) {
    return null
  }
  return err
})

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
  if (typeof window !== 'undefined' && window.innerWidth <= 768) {
    setTimeout(() => {
      if (!isStarted.value) {
        handleHeroClick()
      }
    }, 450)
  }
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
  width: 100%;
  height: 100vh;
  min-height: 600px;
  overflow: hidden;
  display: flex;
  align-items: center;
}

.hero__bg {
  position: absolute;
  inset: 0;
  background: #ffffff;
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

.hero__scroll-area {
  display: contents;
}

.hero__content a,
.hero__content button,
.hero__content input {
  pointer-events: auto;
}

.hero__intro {
  font-size: clamp(0.875rem, 1.2vw, 1rem);
  font-weight: 500;
  line-height: 1.7;
  color: #475569;
  margin-bottom: 1.5rem;
  letter-spacing: 0.01em;
}

.hero__heading {
  font-family: 'Share Tech Mono', monospace;
  font-size: clamp(2rem, 4.5vw, 3.5rem);
  font-weight: 600;
  line-height: 1.15;
  color: #0f172a;
  letter-spacing: -0.03em;
  margin-bottom: 2rem;
}

.hero__heading-line {
  display: block;
}

.hero__heading-line--cyber {
  display: inline-block;
  position: relative;
  font-family: 'Orbitron', sans-serif;
  font-size: clamp(1.75rem, 3.8vw, 3.1rem);
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: #0f172a;
  background: linear-gradient(135deg, #0f172a 35%, #5B325B 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 0 14px rgba(91, 50, 91, 0.26));
  user-select: none;
}

.hero__heading-line--cyber::before,
.hero__heading-line--cyber::after {
  content: attr(data-text);
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  background: inherit;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero__heading-line--cyber::before {
  left: -2px;
  text-shadow: 2px 0 rgba(91, 50, 91, 0.65);
  clip-path: inset(20% 0 50% 0);
  animation: cyber-glitch-slice-1 3.8s infinite linear alternate-reverse;
}

.hero__heading-line--cyber::after {
  left: 2px;
  text-shadow: -2px 0 rgba(168, 110, 168, 0.65);
  clip-path: inset(55% 0 15% 0);
  animation: cyber-glitch-slice-2 3.1s infinite linear alternate-reverse;
}

.hero__cyber-cursor {
  display: inline-block;
  margin-left: 2px;
  font-weight: 800;
  color: #5B325B;
  -webkit-text-fill-color: #5B325B;
  text-shadow: 0 0 10px rgba(91, 50, 91, 0.85);
  animation: cyber-cursor-blink 0.9s step-start infinite;
}

@keyframes cyber-cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

@keyframes cyber-glitch-slice-1 {
  0%, 88% {
    transform: translate(0, 0);
    opacity: 0;
  }
  89% {
    transform: translate(-3px, 1px);
    opacity: 0.85;
    clip-path: inset(10% 0 60% 0);
  }
  91% {
    transform: translate(2px, -1px);
    opacity: 0.9;
    clip-path: inset(38% 0 25% 0);
  }
  93% {
    transform: translate(-1px, 2px);
    opacity: 0.75;
    clip-path: inset(68% 0 12% 0);
  }
  95%, 100% {
    transform: translate(0, 0);
    opacity: 0;
  }
}

@keyframes cyber-glitch-slice-2 {
  0%, 84% {
    transform: translate(0, 0);
    opacity: 0;
  }
  85% {
    transform: translate(3px, -1px);
    opacity: 0.85;
    clip-path: inset(48% 0 18% 0);
  }
  87% {
    transform: translate(-2px, 1px);
    opacity: 0.9;
    clip-path: inset(22% 0 48% 0);
  }
  89% {
    transform: translate(1px, -2px);
    opacity: 0.75;
    clip-path: inset(12% 0 72% 0);
  }
  91%, 100% {
    transform: translate(0, 0);
    opacity: 0;
  }
}

.hero__heading-line--italic {
  font-style: italic;
  font-weight: 500;
  color: #5B325B;
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

.hero__thinking {
  color: #5B325B;
  font-weight: 500;
}

.hero__error,
.hero__voice-error {
  color: #dc2626;
}

.hero__input-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex: 1;
  min-width: 0;
}

.hero__composer-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: min(100%, 36rem);
  margin-top: 0.35rem;
}

.hero__input {
  flex: 1;
  min-width: 0;
  height: 2.375rem;
  border: 1px solid rgba(91, 50, 91, 0.2);
  background: rgba(255, 255, 255, 0.85);
  color: #0f172a;
  border-radius: 999px;
  padding: 0.45rem 0.95rem;
  font-size: 0.875rem;
  line-height: 1.4;
  outline: none;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 2px 8px rgba(91, 50, 91, 0.04);
  transition: all 0.25s ease;
}

.hero__input:focus {
  border-color: #5B325B;
  box-shadow: 0 0 0 3px rgba(91, 50, 91, 0.18);
  background: #ffffff;
}

.hero__send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 2.375rem;
  border-radius: 999px;
  border: 1px solid #5B325B;
  background: #5B325B;
  color: #fff;
  padding: 0 1.1rem;
  font-size: 0.8rem;
  font-weight: 500;
  box-shadow: 0 3px 10px rgba(91, 50, 91, 0.25);
  transition: all 0.2s ease;
  white-space: nowrap;
}

.hero__send:hover:not(:disabled) {
  background: #482448;
  border-color: #482448;
  box-shadow: 0 6px 18px rgba(91, 50, 91, 0.4);
  transform: translateY(-1px);
}

.hero__send:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.hero__stop {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 2.375rem;
  border-radius: 999px;
  border: 1px solid rgba(220, 38, 38, 0.25);
  background: #ef4444;
  color: #fff;
  padding: 0 1rem;
  font-size: 0.8rem;
  font-weight: 500;
  box-shadow: 0 3px 10px rgba(239, 68, 68, 0.25);
  transition: all 0.2s ease;
  white-space: nowrap;
}

.hero__stop:hover:not(:disabled) {
  background: #dc2626;
  transform: translateY(-1px);
}

.hero__stop:disabled {
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
  scrollbar-color: rgba(91, 50, 91, 0.3) transparent;
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
  width: 7px;
  height: 7px;
  background: #5B325B;
  border-radius: 50%;
  box-shadow: 0 0 10px rgba(91, 50, 91, 0.6);
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
  .hero,
  .hero.hero--chat-active {
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    align-items: stretch;
    height: 100vh;
    height: 100dvh;
    min-height: 100dvh;
    max-height: 100dvh;
    overflow: hidden;
    position: relative;
    background: #ffffff;
  }

  .hero__bg {
    display: none;
  }

  /* Top 60%: Animated 3D robot head section */
  .hero__model {
    position: relative;
    width: 100%;
    height: 60vh;
    height: 60dvh;
    flex: 0 0 60dvh;
    max-height: 60dvh;
    pointer-events: auto;
    padding-top: env(safe-area-inset-top, 0px);
    background: radial-gradient(circle at 50% 50%, rgba(91, 50, 91, 0.04) 0%, rgba(248, 250, 252, 0.95) 75%);
    overflow: hidden;
    box-sizing: border-box;
  }

  /* Bottom 40%: Independently scrollable content & chat interface (no overlap) */
  .hero__content,
  .hero--chat-active .hero__content {
    opacity: 1;
    transform: translateY(0);
    position: relative;
    z-index: 10;
    width: 100%;
    max-width: 100%;
    height: 40vh;
    height: 40dvh;
    flex: 0 0 40dvh;
    max-height: 40dvh;
    margin-top: 0; /* No overlap with top robot section */
    margin-bottom: 0;
    background: #ffffff;
    border-top: 1px solid rgba(91, 50, 91, 0.08);
    box-shadow: 0 -4px 20px rgba(15, 23, 42, 0.04);
    padding: 0.75rem clamp(1rem, 4vw, 1.25rem) calc(0.55rem + env(safe-area-inset-bottom, 0px));
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-sizing: border-box;
    overflow-y: auto; /* Independently scrollable */
    overscroll-behavior: contain;
    scrollbar-width: thin;
  }

  /* Scrollable upper area containing greeting, heading, suggestions & messages */
  .hero__scroll-area {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    flex: 1 0 auto;
  }

  /* Typography on mobile */
  .hero__intro {
    font-size: 0.8rem;
    line-height: 1.4;
    margin-bottom: 0.2rem;
    color: #64748b;
  }

  .hero__heading {
    margin-bottom: 0.5rem;
  }

  .hero__heading-line--cyber {
    font-size: clamp(1.2rem, 5vw, 1.55rem);
    line-height: 1.2;
    word-break: break-word;
    filter: none;
  }

  /* Hide blurry multi-line glitch slice duplicates on mobile */
  .hero__heading-line--cyber::before,
  .hero__heading-line--cyber::after {
    display: none;
  }

  .hero__actions {
    margin-bottom: 0.45rem;
    width: 100%;
  }

  .hero__composer {
    width: 100%;
    max-width: 100%;
    margin-top: 0.25rem;
    margin-bottom: 0.45rem;
  }

  .hero__chat {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }

  /* Typing screen / composer controls: pinned at bottom of the bottom 50% */
  .hero__composer-controls {
    flex: 0 0 auto;
    margin-top: auto;
    padding-top: 0.4rem;
    flex-direction: column;
    align-items: stretch;
    gap: 0.35rem;
    width: 100%;
    max-width: 100%;
    background: #ffffff;
    border-top: 1px solid rgba(91, 50, 91, 0.06);
    position: sticky;
    bottom: 0;
    z-index: 20;
  }

  .hero__input-row {
    flex-direction: row;
    align-items: center;
    gap: 0.35rem;
    width: 100%;
  }

  .hero__input {
    flex: 1;
    min-width: 0;
    height: 2.375rem;
    font-size: 0.875rem;
    padding: 0.45rem 0.95rem;
  }

  .hero__send,
  .hero__stop {
    flex: 0 0 auto;
    height: 2.375rem;
    padding: 0 1rem;
    font-size: 0.8rem;
    white-space: nowrap;
  }

  .hero__voice-area {
    width: 100%;
    align-items: stretch;
  }

  .hero__loader {
    bottom: 1rem;
    right: 1rem;
  }
}

@media (min-width: 769px) and (max-width: 1024px) {
  .hero__content {
    width: min(100%, 540px);
    padding-left: clamp(1.5rem, 4vw, 3rem);
    padding-right: 1.5rem;
  }

  .hero__heading-line--cyber {
    font-size: clamp(1.8rem, 3.4vw, 2.5rem);
  }

  .hero__composer {
    max-width: 100%;
  }

  .hero__composer-controls {
    max-width: 100%;
  }
}
</style>

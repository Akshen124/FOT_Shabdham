import { ref } from 'vue'
import {
  playResponseAudio,
  sendChatMessage,
  startAudioPipeline,
  queueAudioSentence,
  markAudioAllReceived,
  stopAudioPlayback,
  hasAudioPendingRequests,
  hasPlayableAudio,
} from '~/services/chatService'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

let activeRequestId = 0

export function useChat() {
  const messages = ref<ChatMessage[]>([])
  const isThinking = ref(false)
  const abortController = ref<AbortController | null>(null)
  const isSpeaking = ref(false)
  const error = ref<string | null>(null)
  const ttsWarning = ref<string | null>(null)
  const transcript = ref('')
  const messageId = ref(0)
  const apiBase = (useRuntimeConfig().public.apiBase as string) || ''
  const sessionId = useState<string>('chat-session-id', () => {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return crypto.randomUUID()
    }
    return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`
  })

  let safetyTimer: ReturnType<typeof setTimeout> | null = null

  function addMessage(role: 'user' | 'assistant', text: string) {
    messageId.value += 1
    messages.value.push({
      id: `message-${messageId.value}`,
      role,
      text,
    })
  }

  async function sendMessage(message: string): Promise<boolean> {
    const normalized = message.trim()

    if (!normalized || isThinking.value) {
      return false
    }

    const currentRequestId = ++activeRequestId

    if (safetyTimer) {
      clearTimeout(safetyTimer)
      safetyTimer = null
    }

    addMessage('user', normalized)
    transcript.value = normalized
    error.value = null
    ttsWarning.value = null
    isThinking.value = true

    abortController.value = new AbortController()
    const requestStartTime = performance.now()
    let accumulatedText = ''
    let hasRevealedText = false
    let sentenceCount = 0

    const revealText = (isTtsError = false) => {
      if (currentRequestId !== activeRequestId) return // Stale audio or cancelled turn

      // If text is already revealed, update warning state if audio playback starts
      if (hasRevealedText) {
        if (!isTtsError && ttsWarning.value) {
          console.info('[TTS] Warning cleared: audio playback started successfully, hiding error warning')
          ttsWarning.value = null
        }
        return
      }

      hasRevealedText = true

      if (safetyTimer) {
        clearTimeout(safetyTimer)
        safetyTimer = null
      }

      isThinking.value = false

      const cleanText = accumulatedText.trim()
      if (cleanText) {
        addMessage('assistant', cleanText)
      }

      if (isTtsError) {
        console.warn('[TTS] Audio playback failed or unavailable; showing fallback warning')
        ttsWarning.value = 'Voice response unavailable.'
      } else if (ttsWarning.value) {
        console.info('[TTS] Warning cleared: audio playback started successfully, hiding error warning')
        ttsWarning.value = null
      }
    }

    // Initialize audio queue pipeline with playback start, complete & error callbacks
    startAudioPipeline(
      requestStartTime,
      (speaking) => {
        if (currentRequestId === activeRequestId) {
          isSpeaking.value = speaking
        }
      },
      () => {
        // Audio playback actually started!
        console.info('[TTS] Playback started: audio playback has begun')
        if (ttsWarning.value) {
          console.info('[TTS] Warning cleared: audio playback started successfully, hiding error warning')
          ttsWarning.value = null
        }
        revealText(false)
      },
      (err) => {
        // Genuine terminal failure: all sentence chunks finished processing and no playable audio
        console.error('[TTS] TTS request failed: all audio attempts failed:', err)
        revealText(true)
      },
      () => {
        // All audio playback completed
        console.info('[TTS] Playback completed: audio finished successfully')
        if (ttsWarning.value) {
          console.info('[TTS] Warning cleared: audio playback completed, ensuring no error warning')
          ttsWarning.value = null
        }
      },
    )

    try {
      const { response } = await sendChatMessage({
        message: normalized,
        sessionId: sessionId.value,
        apiBase,
        abortSignal: abortController.value.signal,
        onFirstToken: (latencyMs) => {
          console.info(`[TIMING-TTS] LLM First Token received: ${latencyMs.toFixed(1)}ms`)
        },
        onSentence: (sentence, index) => {
          if (currentRequestId !== activeRequestId) return
          sentenceCount++
          const elapsed = (performance.now() - requestStartTime).toFixed(1)
          console.info(`[TIMING-TTS] Sentence ${index} received at +${elapsed}ms: "${sentence}"`)

          // Store the generated answer internally, DO NOT display in chat UI while TTS is processing
          accumulatedText = accumulatedText ? `${accumulatedText} ${sentence}` : sentence

          // Immediately dispatch TTS fetch for this sentence
          queueAudioSentence(sentence, index, apiBase)
        },
        onComplete: (fullText) => {
          if (currentRequestId !== activeRequestId) return
          const totalElapsed = (performance.now() - requestStartTime).toFixed(1)
          console.info(`[TIMING-TTS] Full LLM text ready in ${totalElapsed}ms (${sentenceCount} sentences)`)

          if (fullText && fullText.trim()) {
            accumulatedText = fullText.trim()
          }

          markAudioAllReceived(sentenceCount)
        },
      })

      // If no sentences were streamed via SSE (legacy / fallback)
      if (sentenceCount === 0 && currentRequestId === activeRequestId) {
        const cleaned = response.trim()
        if (cleaned) {
          accumulatedText = cleaned
          try {
            await playResponseAudio(
              cleaned,
              apiBase,
              () => {
                if (ttsWarning.value) {
                  console.info('[TTS] Warning cleared: fallback audio started successfully')
                  ttsWarning.value = null
                }
                revealText(false)
              },
              () => {
                console.error('[TTS] TTS request failed: fallback audio playback failed')
                revealText(true)
              },
              (speaking) => {
                if (currentRequestId === activeRequestId) {
                  isSpeaking.value = speaking
                }
              },
            )
          } catch (caughtError) {
            console.error('[TTS] Voice response unavailable:', caughtError)
            revealText(true)
          }
        } else {
          revealText(false)
        }
      }

      // Safety timeout: if audio has not started within 8s of LLM completion
      if (!hasRevealedText && currentRequestId === activeRequestId) {
        safetyTimer = setTimeout(() => {
          if (currentRequestId !== activeRequestId) return
          const isPending = hasAudioPendingRequests()
          console.warn(
            `[TTS] Timeout triggered after 8s of LLM completion. TTS requests pending: ${isPending}`
          )

          // Reveal the text answer so user can read without waiting indefinitely
          if (!hasRevealedText) {
            revealText(false)
          }

          // Do NOT mark voice as failed while TTS requests are still active in-flight!
          if (!isPending && !isSpeaking.value && !hasPlayableAudio()) {
            console.error('[TTS] TTS request failed: timeout expired with no pending requests and no playable audio.')
            ttsWarning.value = 'Voice response unavailable.'
          }
        }, 8000)
      }

      return true
    } catch (caughtError) {
      if (caughtError instanceof DOMException && caughtError.name === 'AbortError') {
        console.info('[Chat] Request aborted')
      } else {
        console.error('[Chat] Communication failed:', caughtError)
        if (!hasRevealedText && accumulatedText.trim()) {
          revealText(true)
        } else if (!hasRevealedText) {
          addMessage('assistant', 'I am disconnected at the moment.')
        }
        error.value = null
      }
      isThinking.value = false
      return false
    } finally {
      abortController.value = null
    }
  }

  function stopProcessing() {
    activeRequestId++
    if (safetyTimer) {
      clearTimeout(safetyTimer)
      safetyTimer = null
    }
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    stopAudioPlayback()
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('stop-typing'))
    }
    isThinking.value = false
    isSpeaking.value = false
  }

  return {
    messages,
    isThinking,
    isSpeaking,
    error,
    ttsWarning,
    transcript,
    sendMessage,
    stopProcessing,
    addMessage,
  }
}

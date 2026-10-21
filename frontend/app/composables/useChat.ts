import { ref } from 'vue'
import { playResponseAudio, sendChatMessage, stopAudioPlayback } from '~/services/chatService'


export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

export function useChat() {
  const messages = ref<ChatMessage[]>([])
  const isThinking = ref(false)
  // Holds AbortController for cancelling in‑flight request
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

    addMessage('user', normalized)
    transcript.value = normalized
    error.value = null
    ttsWarning.value = null
    isThinking.value = true

    try {
      const { response } = await sendChatMessage(normalized, sessionId.value, apiBase, abortController.value?.signal)
      const cleanedResponse = response.trim()

      if (cleanedResponse) {
        addMessage('assistant', cleanedResponse)
      }

      if (cleanedResponse) {
        isSpeaking.value = true
        try {
          await playResponseAudio(cleanedResponse, apiBase)
        } catch (caughtError) {
          console.error('[TTS] Voice response unavailable:', caughtError)
          ttsWarning.value = 'Voice response unavailable.'
        } finally {
          isSpeaking.value = false
        }
      }

      return true
    } catch (caughtError) {
      // Distinguish aborts from real errors
      if (caughtError instanceof DOMException && caughtError.name === 'AbortError') {
        console.info('[Chat] Request aborted')
        // No error UI for intentional cancellation
      } else {
        console.error('[Chat] Communication failed:', caughtError)
        addMessage('assistant', 'I am disconnected at the moment.')
        error.value = null
      }
      return false
    } finally {
      isThinking.value = false
      abortController.value = null
    }
  }

  function stopProcessing() {
    // Abort the network request if present
    if (abortController.value) {
      abortController.value.abort()
    }
    // Stop any ongoing TTS playback
    stopAudioPlayback()
    // Emit global event to stop typewriter animation
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('stop-typing'))
    }
    // Reset UI flags
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

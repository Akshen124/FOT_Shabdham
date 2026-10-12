import { ref } from 'vue'
import { playResponseAudio, sendChatMessage } from '~/services/chatService'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

export function useChat() {
  const messages = ref<ChatMessage[]>([])
  const isThinking = ref(false)
  const isSpeaking = ref(false)
  const error = ref<string | null>(null)
  const ttsWarning = ref<string | null>(null)
  const transcript = ref('')
  const messageId = ref(0)
  const apiBase = useRuntimeConfig().public.apiBase
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
      const { response } = await sendChatMessage(normalized, sessionId.value, apiBase)
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
      const messageText = caughtError instanceof Error ? caughtError.message : 'Something went wrong while generating the response.'
      error.value = messageText
      return false
    } finally {
      isThinking.value = false
    }
  }

  return {
    messages,
    isThinking,
    isSpeaking,
    error,
    ttsWarning,
    transcript,
    sendMessage,
  }
}

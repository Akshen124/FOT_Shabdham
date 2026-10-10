export interface ChatResponse {
  response: string
}

let currentAudio: HTMLAudioElement | null = null
let currentAudioUrl: string | null = null
let currentPlaybackResolve: (() => void) | null = null
let audioContext: AudioContext | null = null

export async function sendChatMessage(
  message: string,
  sessionId: string,
  apiBase: string,
): Promise<ChatResponse> {
  const chatUrl = `${apiBase.replace(/\/+$/, '')}/api/chat`
  console.info('[CHAT-FRONTEND-DIAG] Exact text sent to /api/chat:', message)
  const chatResponse = await fetch(chatUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,
    }),
  })

  if (!chatResponse.ok) {
    const errorText = await chatResponse.text()
    throw new Error(`Chat backend returned ${chatResponse.status}: ${errorText}`)
  }

  const payload: unknown = await chatResponse.json()
  if (
    typeof payload !== 'object' ||
    payload === null ||
    !('response' in payload) ||
    typeof payload.response !== 'string'
  ) {
    throw new Error('Chat backend returned an invalid response; expected a string "response" field.')
  }

  return { response: payload.response }
}

export function unlockAudioPlayback(): void {
  if (typeof window === 'undefined' || !window.AudioContext) {
    console.warn('[TTS] AudioContext is unavailable; delayed playback may be blocked.')
    return
  }

  if (!audioContext || audioContext.state === 'closed') {
    audioContext = new AudioContext()
  }

  if (audioContext.state === 'suspended') {
    void audioContext
      .resume()
      .then(() => console.log('[TTS] AudioContext unlocked'))
      .catch((error: unknown) => console.error('[TTS] AudioContext unlock failed:', error))
  }
}

function releaseAudio(audio: HTMLAudioElement, audioUrl: string): void {
  audio.pause()
  audio.currentTime = 0
  audio.src = ''
  URL.revokeObjectURL(audioUrl)

  if (currentAudio === audio) {
    currentAudio = null
    currentAudioUrl = null
    currentPlaybackResolve = null
  }
}

function stopCurrentAudio(): void {
  if (!currentAudio || !currentAudioUrl) {
    return
  }

  const audio = currentAudio
  const audioUrl = currentAudioUrl
  const resolvePlayback = currentPlaybackResolve
  releaseAudio(audio, audioUrl)
  resolvePlayback?.()
}

export async function playResponseAudio(text: string, apiBase: string): Promise<void> {
  const answer = text.trim()
  const ttsUrl = `${apiBase.replace(/\/+$/, '')}/api/tts`

  if (!answer) {
    throw new Error('[TTS] Cannot speak an empty response.')
  }

  stopCurrentAudio()
  console.log('[TTS] Starting TTS')
  console.log('[TTS] Text:', answer)
  console.log('[TTS] URL:', ttsUrl)

  let ttsResponse: Response
  try {
    ttsResponse = await fetch(ttsUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'audio/wav',
      },
      body: JSON.stringify({ text: answer }),
    })
  } catch (error) {
    console.error('[TTS] Request failed:', error)
    throw error
  }

  const contentType = ttsResponse.headers.get('content-type')
  console.log('[TTS] Status:', ttsResponse.status)
  console.log('[TTS] Content-Type:', contentType)

  if (!ttsResponse.ok) {
    const errorText = await ttsResponse.text()
    console.error('[TTS] Backend error:', errorText)
    throw new Error(`[TTS] Backend returned ${ttsResponse.status}: ${errorText}`)
  }

  const blob = await ttsResponse.blob()
  console.log('[TTS] Blob type:', blob.type)
  console.log('[TTS] Blob size:', blob.size)

  if (blob.size === 0) {
    throw new Error('[TTS] Backend returned an empty audio response.')
  }

  if (!blob.type.startsWith('audio/')) {
    const responseText = await blob.text()
    console.error('[TTS] Backend returned a non-audio response:', responseText)
    throw new Error(`[TTS] Expected audio but received ${blob.type || 'an unknown content type'}.`)
  }

  const audioUrl = URL.createObjectURL(blob)
  console.log('[TTS] Object URL created')
  const audio = new Audio(audioUrl)
  currentAudio = audio
  currentAudioUrl = audioUrl

  let rejectPlayback: (error: Error) => void = () => {}
  const playbackEnded = new Promise<void>((resolve, reject) => {
    rejectPlayback = reject
    currentPlaybackResolve = resolve

    audio.onplay = () => {
      console.log('[TTS] Playback started')
    }

    audio.onended = () => {
      console.log('[TTS] Playback ended')
      releaseAudio(audio, audioUrl)
      resolve()
    }

    audio.onerror = (event) => {
      const playbackError = audio.error
      console.error('[TTS] Audio element error:', event)
      console.error('[TTS] audio.error:', playbackError)
      releaseAudio(audio, audioUrl)
      reject(new Error(`[TTS] Audio playback failed${playbackError ? ` (code ${playbackError.code})` : ''}.`))
    }
  })

  try {
    await audio.play()
    console.log('[TTS] audio.play() succeeded')
  } catch (error) {
    console.error('[TTS] audio.play() failed:', error)
    releaseAudio(audio, audioUrl)
    rejectPlayback(error instanceof Error ? error : new Error(String(error)))
  }

  await playbackEnded
}

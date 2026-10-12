
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
  abortSignal?: AbortSignal,
): Promise<ChatResponse> {
  const chatUrl = `${apiBase.replace(/\/+$/, '')}/api/chat`

  console.info(
    '[CHAT-FRONTEND-DIAG] Exact text sent to /api/chat:',
    message,
  )

  const chatResponse = await fetch(chatUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,
    }),
    signal: abortSignal,
  })

  if (!chatResponse.ok) {
    const errorText = await chatResponse.text()

    throw new Error(
      `Chat backend returned ${chatResponse.status}: ${errorText}`,
    )
  }

  const payload: unknown = await chatResponse.json()

  if (
    typeof payload !== 'object' ||
    payload === null ||
    !('response' in payload) ||
    typeof payload.response !== 'string'
  ) {
    throw new Error(
      'Chat backend returned an invalid response; expected a string "response" field.',
    )
  }

  return { response: payload.response }
}

export function unlockAudioPlayback(): void {
  if (typeof window === 'undefined' || !window.AudioContext) {
    console.warn(
      '[TTS] AudioContext is unavailable; delayed playback may be blocked.',
    )
    return
  }

  if (!audioContext || audioContext.state === 'closed') {
    audioContext = new AudioContext()
  }

  if (audioContext.state === 'suspended') {
    void audioContext
      .resume()
      .then(() => console.log('[TTS] AudioContext unlocked'))
      .catch((error: unknown) => {
        console.error('[TTS] AudioContext unlock failed:', error)
      })
  }
}

/**
 * Release an audio element without allowing cleanup to trigger
 * the same onerror handler again.
 */
function releaseAudio(
  audio: HTMLAudioElement,
  audioUrl: string,
): void {
  // Detach handlers before changing the media source.
  audio.onplay = null
  audio.onended = null
  audio.onerror = null

  audio.pause()

  // Reset playback position safely.
  try {
    audio.currentTime = 0
  } catch {
    // The media may not have loaded enough to seek.
  }

  // Remove the source and reset the media element.
  audio.removeAttribute('src')
  audio.load()

  // Revoke only this audio element's object URL.
  URL.revokeObjectURL(audioUrl)

  // Clear global references only if this is still the active audio.
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

  // Resolve the previous playback promise so it doesn't remain pending.
  resolvePlayback?.()
}

export function stopAudioPlayback(): void {
  stopCurrentAudio()
}
export async function playResponseAudio(text: string, apiBase: string): Promise<void> {
  const answer = text.trim()
  const ttsUrl = `${apiBase.replace(/\/+$/, '')}/api/tts`

  if (!answer) {
    throw new Error('[TTS] Cannot speak an empty response.')
  }

  // Stop the previous response before starting another.
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

    throw new Error(
      `[TTS] Backend returned ${ttsResponse.status}: ${errorText}`,
    )
  }

  const blob = await ttsResponse.blob()

  console.log('[TTS] Blob type:', blob.type)
  console.log('[TTS] Blob size:', blob.size)

  if (blob.size === 0) {
    throw new Error('[TTS] Backend returned an empty audio response.')
  }

  if (!blob.type.startsWith('audio/')) {
    const responseText = await blob.text()

    console.error(
      '[TTS] Backend returned a non-audio response:',
      responseText,
    )

    throw new Error(
      `[TTS] Expected audio but received ${
        blob.type || 'an unknown content type'
      }.`,
    )
  }

  const audioUrl = URL.createObjectURL(blob)
  const audio = new Audio()

  // Set the source before playback.
  audio.preload = 'auto'
  audio.src = audioUrl

  currentAudio = audio
  currentAudioUrl = audioUrl

  console.log('[TTS] Object URL created:', audioUrl)

  let rejectPlayback: (error: Error) => void = () => {}
  let settled = false

  const playbackEnded = new Promise<void>((resolve, reject) => {
    rejectPlayback = (error: Error) => {
      if (settled) return
      settled = true
      reject(error)
    }

    currentPlaybackResolve = () => {
      if (settled) return
      settled = true
      resolve()
    }

    audio.onplay = () => {
      console.log('[TTS] Playback started')
    }

    audio.onended = () => {
      console.log('[TTS] Playback ended')

      if (!settled) {
        settled = true
        releaseAudio(audio, audioUrl)
        resolve()
      }
    }

    audio.onerror = (event) => {
      // Capture diagnostics before cleanup changes the element.
      const playbackError = audio.error

      console.error('[TTS] Audio element error:', event)
      console.error('[TTS] Audio diagnostics:', {
        srcAttribute: audio.getAttribute('src'),
        src: audio.src,
        currentSrc: audio.currentSrc,
        readyState: audio.readyState,
        networkState: audio.networkState,
        errorCode: playbackError?.code,
        errorMessage: playbackError?.message,
        audioUrl,
        blobType: blob.type,
        blobSize: blob.size,
      })

      if (settled) return

      settled = true

      releaseAudio(audio, audioUrl)

      reject(
        new Error(
          `[TTS] Audio playback failed${
            playbackError
              ? ` (code ${playbackError.code}: ${playbackError.message})`
              : ''
          }.`,
        ),
      )
    }
  })

  try {
    await audio.play()
    console.log('[TTS] audio.play() succeeded')
  } catch (error) {
    console.error('[TTS] audio.play() failed:', error)

    if (!settled) {
      settled = true
      releaseAudio(audio, audioUrl)

      rejectPlayback(
        error instanceof Error
          ? error
          : new Error(String(error)),
      )
    }
  }

  await playbackEnded;
}

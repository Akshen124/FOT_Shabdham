export interface ChatResponse {
  response: string
}

export interface SendChatOptions {
  message: string
  sessionId: string
  apiBase: string
  abortSignal?: AbortSignal
  onFirstToken?: (latencyMs: number) => void
  onSentence?: (sentence: string, index: number) => void
  onComplete?: (fullText: string) => void
  onError?: (error: Error) => void
}

let audioContext: AudioContext | null = null

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
      .catch((error: unknown) => {
        console.error('[TTS] AudioContext unlock failed:', error)
      })
  }
}

export function splitIntoSentences(text: string): string[] {
  const stripped = text.trim()
  if (!stripped) return []

  const protectedText = stripped
    .replace(/(\d)\.(\d)/g, '$1<DECIMAL_DOT>$2')
    .replace(/\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|vs|etc|i\.e|e\.g)\./gi, '$1<ABBREV_DOT>')
    .replace(/(^|\n)\s*(\d+)\./g, '$1$2<LIST_DOT>')

  const raw = protectedText.split(/(?<=[.!?])\s+|\n+/)
  const result: string[] = []

  for (const r of raw) {
    const cleaned = r
      .replace(/<DECIMAL_DOT>/g, '.')
      .replace(/<ABBREV_DOT>/g, '.')
      .replace(/<LIST_DOT>/g, '.')
      .trim()
    if (cleaned) {
      result.push(cleaned)
    }
  }

  return result.length > 0 ? result : [stripped]
}

interface QueuedAudioChunk {
  index: number
  text: string
  audioBlob?: Blob
  audioUrl?: string
  fetchPromise?: Promise<void>
  ready: boolean
  error?: Error
}

class AudioQueueManager {
  private activePipelineId: number = 0
  private ttsAbortController: AbortController | null = null
  private chunks: Map<number, QueuedAudioChunk> = new Map()
  private nextPlayIndex: number = 0
  private isPlaying: boolean = false
  private currentAudio: HTMLAudioElement | null = null
  private currentAudioUrl: string | null = null
  private onSpeakingChange?: (isSpeaking: boolean) => void
  private onPlaybackStart?: () => void
  private onPlaybackComplete?: () => void
  private onPlaybackError?: (error: any) => void
  private playbackStartedFired: boolean = false
  private allSentencesReceived: boolean = false
  private totalSentences: number = 0
  private requestStartTime: number = 0
  private playbackDoneResolve: (() => void) | null = null

  startPipeline(
    startTime: number,
    onSpeakingChange?: (isSpeaking: boolean) => void,
    onPlaybackStart?: () => void,
    onPlaybackError?: (error: any) => void,
    onPlaybackComplete?: () => void,
  ): Promise<void> {
    this.stop()
    this.activePipelineId = Date.now() + Math.random()
    this.requestStartTime = startTime
    this.onSpeakingChange = onSpeakingChange
    this.onPlaybackStart = onPlaybackStart
    this.onPlaybackError = onPlaybackError
    this.onPlaybackComplete = onPlaybackComplete
    this.playbackStartedFired = false
    this.ttsAbortController = new AbortController()
    this.chunks.clear()
    this.nextPlayIndex = 0
    this.isPlaying = false
    this.allSentencesReceived = false
    this.totalSentences = 0

    return new Promise<void>((resolve) => {
      this.playbackDoneResolve = resolve
    })
  }

  hasPendingRequests(): boolean {
    if (!this.allSentencesReceived) return true
    for (const chunk of this.chunks.values()) {
      if (!chunk.ready) return true
    }
    return false
  }

  hasPlayableAudio(): boolean {
    for (const chunk of this.chunks.values()) {
      if (chunk.ready && !chunk.error && chunk.audioUrl) return true
    }
    return false
  }

  queueSentence(sentence: string, index: number, apiBase: string): void {
    const pipelineId = this.activePipelineId
    const cleanSentence = sentence.trim()
    if (!cleanSentence) return

    const chunk: QueuedAudioChunk = {
      index,
      text: cleanSentence,
      ready: false,
    }

    const ttsUrl = `${apiBase.replace(/\/+$/, '')}/api/tts`
    const t0 = performance.now()
    console.info(
      `[TTS] TTS request pending: Sentence ${index} ("${cleanSentence.slice(0, 45)}...") fetch initiated at +${(t0 - this.requestStartTime).toFixed(1)}ms`
    )

    chunk.fetchPromise = (async () => {
      const chunkAbortController = new AbortController()
      const fetchTimeoutId = setTimeout(() => {
        chunkAbortController.abort(new Error(`TTS fetch timed out after 25s for sentence ${index}`))
      }, 25000)

      const onParentAbort = () => chunkAbortController.abort()
      if (this.ttsAbortController) {
        this.ttsAbortController.signal.addEventListener('abort', onParentAbort, { once: true })
      }

      try {
        const resp = await fetch(ttsUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'audio/wav',
          },
          body: JSON.stringify({ text: cleanSentence }),
          signal: chunkAbortController.signal,
        })

        if (!resp.ok) {
          const errText = await resp.text()
          throw new Error(`TTS failed (${resp.status}): ${errText}`)
        }

        const blob = await resp.blob()
        const tFetch = performance.now()
        console.info(
          `[TTS] TTS request completed: Sentence ${index} audio received in ${(tFetch - t0).toFixed(1)}ms (${blob.size} bytes, +${(tFetch - this.requestStartTime).toFixed(1)}ms from start)`
        )

        if (this.activePipelineId !== pipelineId) {
          return // Pipeline was cancelled or replaced
        }

        chunk.audioBlob = blob
        chunk.audioUrl = URL.createObjectURL(blob)
        chunk.ready = true

        this.playNext()
      } catch (err: any) {
        if (err?.name === 'AbortError' && this.activePipelineId !== pipelineId) return
        console.error(`[TTS] TTS request failed: Sentence ${index} synthesis error:`, err)
        chunk.error = err
        chunk.ready = true
        // Do not prematurely mark terminal failure here; let playNext evaluate when all chunks finish
        this.playNext()
      } finally {
        clearTimeout(fetchTimeoutId)
        if (this.ttsAbortController) {
          this.ttsAbortController.signal.removeEventListener('abort', onParentAbort)
        }
      }
    })()

    this.chunks.set(index, chunk)
    this.totalSentences = Math.max(this.totalSentences, index + 1)
  }

  markAllReceived(total: number): void {
    this.allSentencesReceived = true
    this.totalSentences = total
    this.playNext()
  }

  private playNext(): void {
    if (this.isPlaying) return

    const chunk = this.chunks.get(this.nextPlayIndex)
    if (!chunk) {
      if (this.allSentencesReceived && this.nextPlayIndex >= this.totalSentences) {
        const anyPending = Array.from(this.chunks.values()).some((c) => !c.ready)
        if (anyPending) {
          // Still waiting for remaining sentences to finish fetching
          return
        }

        if (this.playbackStartedFired) {
          console.info('[TTS] Playback completed: all queued sentences have finished playing.')
          this.onSpeakingChange?.(false)
          this.onPlaybackComplete?.()
        } else {
          // Terminal failure: all chunks completed and none were playable
          console.error('[TTS] TTS request failed: all sentence chunks finished processing but no playable audio could be generated.')
          this.playbackStartedFired = true
          this.onPlaybackError?.(new Error('No playable audio generated'))
        }

        if (this.playbackDoneResolve) {
          this.playbackDoneResolve()
          this.playbackDoneResolve = null
        }
      }
      return
    }

    if (!chunk.ready) {
      // Waiting for this chunk's audio fetch to arrive
      console.info(`[TTS] TTS request pending: waiting for Sentence ${this.nextPlayIndex} audio fetch to complete...`)
      return
    }

    if (chunk.error || !chunk.audioUrl) {
      // Skip failed chunk and continue to next sentence
      console.warn(`[TTS] Sentence ${this.nextPlayIndex} audio is unavailable; advancing to next chunk.`)
      this.nextPlayIndex++
      this.playNext()
      return
    }

    const audioUrl = chunk.audioUrl
    const audio = new Audio()
    audio.preload = 'auto'
    audio.src = audioUrl
    this.currentAudio = audio
    this.currentAudioUrl = audioUrl
    this.isPlaying = true
    this.onSpeakingChange?.(true)

    audio.onplay = () => {
      const tPlay = performance.now()
      console.info(
        `[TTS] Playback started: Sentence ${chunk.index} ("${chunk.text.slice(0, 35)}..."). Actual elapsed: ${(tPlay - this.requestStartTime).toFixed(1)}ms`
      )
      if (!this.playbackStartedFired) {
        this.playbackStartedFired = true
        this.onPlaybackStart?.()
      }
    }

    audio.onended = () => {
      console.info(`[TTS] Playback completed: Sentence ${chunk.index} playback finished.`)
      this.releaseCurrentAudio()
      this.isPlaying = false
      this.nextPlayIndex++
      this.playNext()
    }

    audio.onerror = (err) => {
      console.error(`[TTS] Sentence ${chunk.index} audio playback error:`, err)
      this.releaseCurrentAudio()
      this.isPlaying = false
      this.nextPlayIndex++
      this.playNext()
    }

    audio.play().catch((err) => {
      console.error(`[TTS] audio.play() failed for sentence ${chunk.index}:`, err)
      this.releaseCurrentAudio()
      this.isPlaying = false
      this.nextPlayIndex++
      this.playNext()
    })
  }

  private releaseCurrentAudio(): void {
    if (!this.currentAudio) return
    const a = this.currentAudio
    const u = this.currentAudioUrl
    a.onplay = null
    a.onended = null
    a.onerror = null
    a.pause()
    try {
      a.currentTime = 0
    } catch { }
    a.removeAttribute('src')
    a.load()
    if (u) URL.revokeObjectURL(u)
    this.currentAudio = null
    this.currentAudioUrl = null
  }

  stop(): void {
    this.activePipelineId = Date.now() + Math.random()
    this.onPlaybackStart = undefined
    this.onPlaybackComplete = undefined
    this.onPlaybackError = undefined
    if (this.ttsAbortController) {
      this.ttsAbortController.abort()
      this.ttsAbortController = null
    }
    this.releaseCurrentAudio()
    for (const chunk of this.chunks.values()) {
      if (chunk.audioUrl) {
        URL.revokeObjectURL(chunk.audioUrl)
      }
    }
    this.chunks.clear()
    this.isPlaying = false
    this.nextPlayIndex = 0
    this.allSentencesReceived = false
    this.onSpeakingChange?.(false)
    if (this.playbackDoneResolve) {
      this.playbackDoneResolve()
      this.playbackDoneResolve = null
    }
  }
}

const audioQueueManager = new AudioQueueManager()

export function startAudioPipeline(
  startTime: number,
  onSpeakingChange?: (isSpeaking: boolean) => void,
  onPlaybackStart?: () => void,
  onPlaybackError?: (error: any) => void,
  onPlaybackComplete?: () => void,
): Promise<void> {
  return audioQueueManager.startPipeline(startTime, onSpeakingChange, onPlaybackStart, onPlaybackError, onPlaybackComplete)
}

export function hasAudioPendingRequests(): boolean {
  return audioQueueManager.hasPendingRequests()
}

export function hasPlayableAudio(): boolean {
  return audioQueueManager.hasPlayableAudio()
}

export function queueAudioSentence(
  sentence: string,
  index: number,
  apiBase: string,
): void {
  audioQueueManager.queueSentence(sentence, index, apiBase)
}

export function markAudioAllReceived(totalSentences: number): void {
  audioQueueManager.markAllReceived(totalSentences)
}

export function stopAudioPlayback(): void {
  audioQueueManager.stop()
}

export async function sendChatMessage(
  optionsOrMessage: SendChatOptions | string,
  sessionId?: string,
  apiBase?: string,
  abortSignal?: AbortSignal,
): Promise<ChatResponse> {
  let opts: SendChatOptions

  if (typeof optionsOrMessage === 'string') {
    opts = {
      message: optionsOrMessage,
      sessionId: sessionId || '',
      apiBase: apiBase || '',
      abortSignal,
    }
  } else {
    opts = optionsOrMessage
  }

  const chatUrl = `${opts.apiBase.replace(/\/+$/, '')}/api/chat`
  const t0 = performance.now()

  console.info('[CHAT-FRONTEND-DIAG] Sending to /api/chat:', opts.message)

  const chatResponse = await fetch(chatUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      message: opts.message,
      session_id: opts.sessionId,
      stream: true,
    }),
    signal: opts.abortSignal,
  })

  if (!chatResponse.ok) {
    const errorText = await chatResponse.text()
    throw new Error(`Chat backend returned ${chatResponse.status}: ${errorText}`)
  }

  const contentType = chatResponse.headers.get('content-type') || ''

  if (contentType.includes('text/event-stream') && chatResponse.body) {
    const reader = chatResponse.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullResponse = ''
    let sentenceCount = 0

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEventType = 'message'
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue

          if (trimmed.startsWith('event:')) {
            currentEventType = trimmed.slice(6).trim()
            continue
          }

          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim()
            try {
              const data = JSON.parse(dataStr)

              if (currentEventType === 'sentence' || data.type === 'sentence') {
                if (data.first_token_ms && opts.onFirstToken) {
                  opts.onFirstToken(data.first_token_ms)
                }
                const sentenceText = data.text as string
                const index = typeof data.index === 'number' ? data.index : sentenceCount
                sentenceCount++
                fullResponse = fullResponse ? `${fullResponse} ${sentenceText}` : sentenceText
                opts.onSentence?.(sentenceText, index)
              } else if (currentEventType === 'done' || data.type === 'done') {
                const finalResp = (data.response as string) || fullResponse
                opts.onComplete?.(finalResp)
                return { response: finalResp }
              } else if (currentEventType === 'error' || data.type === 'error') {
                throw new Error(data.error || 'Server stream error')
              }
            } catch (err) {
              console.warn('[SSE] Parse error on data line:', trimmed, err)
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    if (fullResponse) {
      opts.onComplete?.(fullResponse)
      return { response: fullResponse }
    }
  }

  // Fallback to plain JSON response
  const payload: unknown = await chatResponse.json()
  const tJson = performance.now()
  console.info(`[TIMING-TTS] JSON response received in ${(tJson - t0).toFixed(1)}ms`)

  if (
    typeof payload !== 'object' ||
    payload === null ||
    !('response' in payload) ||
    typeof (payload as any).response !== 'string'
  ) {
    throw new Error('Chat backend returned an invalid response; expected string "response".')
  }

  const responseText = (payload as any).response as string
  const sentences = splitIntoSentences(responseText)
  sentences.forEach((s, i) => opts.onSentence?.(s, i))
  opts.onComplete?.(responseText)

  return { response: responseText }
}

export async function playResponseAudio(
  text: string,
  apiBase: string,
  onPlaybackStart?: () => void,
  onPlaybackError?: (error: any) => void,
  onSpeakingChange?: (isSpeaking: boolean) => void,
): Promise<void> {
  const answer = text.trim()
  if (!answer) {
    throw new Error('[TTS] Cannot speak an empty response.')
  }

  const sentences = splitIntoSentences(answer)
  const startTime = performance.now()
  const playbackPromise = startAudioPipeline(startTime, onSpeakingChange, onPlaybackStart, onPlaybackError)

  sentences.forEach((s, idx) => {
    queueAudioSentence(s, idx, apiBase)
  })
  markAudioAllReceived(sentences.length)

  await playbackPromise
}

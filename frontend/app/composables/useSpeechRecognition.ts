import { computed, ref } from 'vue'

const SILENCE_DURATION_MS = 1_200
const MAX_RECORDING_DURATION_MS = 30_000
const SILENCE_THRESHOLD = 0.008

export interface UseSpeechRecognitionOptions {
  onDisconnected?: () => void
}

export function useSpeechRecognition(options?: UseSpeechRecognitionOptions) {
  const isListening = ref(false)
  const error = ref<string | null>(null)
  const transcript = ref('')
  const apiBase = useRuntimeConfig().public.apiBase

  const isSupported = computed(
    () =>
      typeof window !== 'undefined' &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      typeof AudioContext !== 'undefined' &&
      typeof MediaRecorder !== 'undefined',
  )

  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let mutedOutput: GainNode | null = null
  let mediaRecorder: MediaRecorder | null = null
  let recordedChunks: Blob[] = []
  let animationFrame = 0
  let recordingStartedAt = 0
  let lastSpeechAt = 0
  let speechDetected = false
  let startupCancelled = false

  function stopTracks() {
    mediaStream?.getTracks().forEach((track) => track.stop())
    mediaStream = null
  }

  function stopMonitoring() {
    if (animationFrame) {
      cancelAnimationFrame(animationFrame)
      animationFrame = 0
    }
  }

  function releaseCapture() {
    source?.disconnect()
    analyser?.disconnect()
    mutedOutput?.disconnect()
    source = null
    analyser = null
    mutedOutput = null
    stopTracks()
    if (audioContext && audioContext.state !== 'closed') {
      void audioContext.close()
    }
    audioContext = null
  }

  function stopListening() {
    startupCancelled = true
    stopMonitoring()

    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
      return
    }

    releaseCapture()
    isListening.value = false
  }

  function monitorAudioLevel() {
    if (!analyser || !audioContext) {
      return
    }

    const samples = new Float32Array(analyser.fftSize)
    analyser.getFloatTimeDomainData(samples)
    let squaredSum = 0
    for (const sample of samples) {
      squaredSum += sample * sample
    }
    const rms = Math.sqrt(squaredSum / samples.length)
    const now = performance.now()
    if (rms >= SILENCE_THRESHOLD) {
      speechDetected = true
      lastSpeechAt = now
    }

    if (
      (speechDetected && now - lastSpeechAt >= SILENCE_DURATION_MS) ||
      now - recordingStartedAt >= MAX_RECORDING_DURATION_MS
    ) {
      stopListening()
      return
    }

    animationFrame = requestAnimationFrame(monitorAudioLevel)
  }

  function selectRecorderMimeType(): string | undefined {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
    ]
    return candidates.find((mimeType) => MediaRecorder.isTypeSupported(mimeType))
  }

  async function transcribeRecording(blob: Blob, mimeType: string) {
    try {
      if (!blob.size) {
        throw new Error('No audio was captured. Please try again.')
      }

      const extension = mimeType.includes('ogg')
        ? 'ogg'
        : mimeType.includes('mp4')
          ? 'mp4'
          : 'webm'
      const audioFile = new File([blob], `recording.${extension}`, {
        type: mimeType || blob.type || 'application/octet-stream',
      })
      if (!audioFile.size) {
        throw new Error('No audio was captured. Please try again.')
      }

      console.info('[STT-FRONTEND] Sending audio to /api/stt')
      console.info('[STT-FRONTEND] File size:', audioFile.size)
      console.info('[STT-FRONTEND] File type:', audioFile.type)
      console.info('[STT-FRONTEND] Filename:', audioFile.name)

      const formData = new FormData()
      formData.append('file', audioFile)
      const response = await fetch(`${apiBase.replace(/\/+$/, '')}/api/stt`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        let detail = ''
        try {
          const payload: unknown = await response.json()
          if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
            detail = String(payload.detail)
          }
        } catch {
          detail = ''
        }
        throw new Error(detail || `Speech transcription failed (${response.status}).`)
      }

      const payload: unknown = await response.json()
      if (
        typeof payload !== 'object' ||
        payload === null ||
        !('text' in payload) ||
        typeof payload.text !== 'string'
      ) {
        throw new Error('Speech service returned an invalid transcript.')
      }

      console.info('[STT-FRONTEND-DIAG] Exact transcript returned by /api/stt:', payload.text)
      transcript.value = payload.text.trim()
      if (!transcript.value) {
        throw new Error('No speech was detected. Please try again.')
      }
    } catch (caughtError) {
      console.error('[STT-FRONTEND] Speech error:', caughtError)
      const message = caughtError instanceof Error ? caughtError.message : String(caughtError)
      const isFetchError =
        message.toLowerCase().includes('failed to fetch') ||
        message.toLowerCase().includes('networkerror') ||
        message.toLowerCase().includes('load failed') ||
        message.includes('Speech transcription failed (50')

      if (isFetchError) {
        error.value = null
        options?.onDisconnected?.()
      } else {
        error.value =
          caughtError instanceof Error
            ? caughtError.message
            : 'Something went wrong while processing your voice input.'
      }
    }
  }

  async function beginRecording() {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1 },
      })
      if (startupCancelled) {
        releaseCapture()
        isListening.value = false
        return
      }

      const track = mediaStream.getAudioTracks()[0]
      console.log('[STT-FRONTEND] microphone permission granted')
      console.log('[STT-FRONTEND] tracks:', mediaStream.getAudioTracks())
      if (track) {
        console.log('[STT-FRONTEND] track enabled:', track.enabled)
        console.log('[STT-FRONTEND] track muted:', track.muted)
        console.log('[STT-FRONTEND] track readyState:', track.readyState)
      }

      const requestedMimeType = selectRecorderMimeType()
      mediaRecorder = requestedMimeType
        ? new MediaRecorder(mediaStream, { mimeType: requestedMimeType })
        : new MediaRecorder(mediaStream)
      recordedChunks = []

      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        console.log('[STT-FRONTEND] chunk size:', event.data.size)
        console.log('[STT-FRONTEND] chunk type:', event.data.type)
        if (event.data.size > 0) {
          recordedChunks.push(event.data)
        }
      }
      mediaRecorder.onstop = () => {
        const recorder = mediaRecorder
        const chunks = recordedChunks
        recordedChunks = []
        const mimeType = recorder?.mimeType || chunks[0]?.type || requestedMimeType || 'audio/webm'
        const blob = new Blob(chunks, { type: mimeType })
        console.log('[STT-FRONTEND] total chunks:', chunks.length)
        console.log('[STT-FRONTEND] final blob size:', blob.size)
        console.log('[STT-FRONTEND] final blob type:', blob.type)
        mediaRecorder = null
        releaseCapture()
        isListening.value = false

        if (!blob.size) {
          error.value = 'The microphone recording is empty. Check microphone permission and try again.'
          return
        }
        void transcribeRecording(blob, mimeType)
      }
      mediaRecorder.onerror = (event: Event) => {
        console.error('[STT-FRONTEND] MediaRecorder error:', event)
        error.value = 'The microphone recording failed. Please try again.'
        stopMonitoring()
        mediaRecorder = null
        releaseCapture()
        isListening.value = false
      }

      audioContext = new AudioContext()
      source = audioContext.createMediaStreamSource(mediaStream)
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 2_048
      mutedOutput = audioContext.createGain()
      mutedOutput.gain.value = 0
      source.connect(analyser)
      analyser.connect(mutedOutput)
      mutedOutput.connect(audioContext.destination)

      console.log('[STT-FRONTEND] AudioContext state:', audioContext.state)
      recordingStartedAt = performance.now()
      lastSpeechAt = recordingStartedAt
      await audioContext.resume()
      if (startupCancelled) {
        releaseCapture()
        isListening.value = false
        return
      }
      console.log('[STT-FRONTEND] AudioContext state:', audioContext.state)

      mediaRecorder.start(250)
      console.log('[STT-FRONTEND] MediaRecorder started')
      console.log('[STT-FRONTEND] MIME type:', mediaRecorder.mimeType)
      console.log('[STT-FRONTEND] Recording started')
      animationFrame = requestAnimationFrame(monitorAudioLevel)
    } catch (caughtError) {
      stopMonitoring()
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop()
      }
      mediaRecorder = null
      releaseCapture()
      isListening.value = false
      if (caughtError instanceof DOMException && caughtError.name === 'NotAllowedError') {
        error.value = 'Microphone permission was denied.'
      } else if (caughtError instanceof DOMException && caughtError.name === 'NotFoundError') {
        error.value = 'Microphone is unavailable.'
      } else {
        error.value = 'Something went wrong while starting the microphone.'
      }
    }
  }

  function startListening() {
    if (!isSupported.value) {
      error.value = 'Voice input is not supported in this browser.'
      return false
    }

    startupCancelled = false
    error.value = null
    transcript.value = ''
    isListening.value = true
    void beginRecording()
    return true
  }

  return {
    isListening,
    isSupported,
    error,
    transcript,
    startListening,
    stopListening,
  }
}

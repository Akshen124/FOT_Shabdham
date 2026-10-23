# FOT AI Assistant

The assistant supports typed chat and one-question-at-a-time microphone input.
Both send text to the same `run_agent` function and existing Qdrant-backed RAG
retrieval. Final answers from both input methods are spoken through the local
Windows speakers using Groq Cloud TTS (`canopylabs/orpheus-v1-english`) with
automatic Deepgram Cloud TTS (`aura-asteria-en`) fallback. Playback is synchronous;
the answer remains visible if speech generation or playback fails.

## Run the chat interface

Install the project dependencies with `uv sync`, then run:

```powershell
uv run streamlit run app.py
```

Configure `GROQ_API_KEY`, `DEEPGRAM_API_KEY`, `QDRANT_URL`, and `QDRANT_API_KEY` in `.env` as for
the command-line assistant. For Redis-backed conversation memory, set
`REDIS_URL=redis://localhost:6379/0` and optionally `REDIS_MEMORY_TTL=3600`.
Voice transcription uses the local NVIDIA NeMo Parakeet Unified English 0.6B
model on CUDA. `PARAKEET_MODEL_NAME` optionally selects a model name; it
defaults to `nvidia/parakeet-unified-en-0.6b`. `STT_DEVICE` defaults to
`cuda`; CPU transcription is disabled. The model is loaded when voice input is
first used in Streamlit. Windows speaker playback uses the built-in `winsound`
module. Allow microphone access for the Streamlit site to record a voice
question.

Text-to-speech uses Groq Cloud TTS as the primary provider with automatic fallback
to Deepgram Aura. Configure these backend settings in `.env`:

```dotenv
GROQ_API_KEY=your_groq_api_key
GROQ_TTS_MODEL=canopylabs/orpheus-v1-english
GROQ_TTS_VOICE=autumn
DEEPGRAM_API_KEY=your_deepgram_api_key
DEEPGRAM_TTS_VOICE=aura-asteria-en
TTS_PROVIDER=auto
TTS_AUDIO_FORMAT=wav
TTS_TIMEOUT_SECONDS=30.0
```

A local Redis instance can be started with:

```powershell
docker run -d --name shabdham-redis -p 6379:6379 redis:7-alpine
```

The backend keeps the most recent 10 messages for each `session_id` in Redis and
expires each session after the configured TTL (default 1 hour) of inactivity.

The original command-line interface remains available with `uv run main.py`.

## Run the HTTP API

The backend exposes a FastAPI service for external clients such as a Nuxt frontend:

```powershell
uv run python main.py --api --host 0.0.0.0 --port 8000
```

or:

```powershell
uv run uvicorn api:app --host 0.0.0.0 --port 8000
```

The API permits the local Nuxt origins `http://localhost:3000` and
`http://127.0.0.1:3000`. Override this comma-separated allowlist with
`FRONTEND_ORIGINS` when developing from a different origin. In the Nuxt
frontend, set `NUXT_PUBLIC_API_BASE=http://localhost:8000` if the backend is
running at a different address. Configure `GEMINI_API_KEY` and `GROQ_API_KEY`
in the backend `.env`; keep both keys out of Nuxt client configuration.

The Nuxt microphone sends its completed recording as a multipart `file` upload
to `/api/stt`. The API streams that recording through one Gemini Live
Transcription session using `gemini-3.5-transcribe-live`. If Gemini errors,
times out, or returns an empty transcript, the backend tries Groq
`whisper-large-v3` with the original upload. The endpoint continues to return
`{"text": "..."}`, which is submitted through the existing chat and
conversation-memory flow. `STT_PRIMARY_PROVIDER` defaults to `gemini_live`,
`STT_FALLBACK_PROVIDER` defaults to `groq_whisper`, and
`STT_TIMEOUT_SECONDS` (default `45`) bounds each provider attempt.
`STT_MAX_CONCURRENT_REQUESTS` (default `4`) limits simultaneous transcription
sessions. The separate Streamlit interface continues to use local Parakeet.

Set `RAG_DEBUG=1` before starting the backend to log each original question,
model-suggested and actual retrieval query, retrieved chunk IDs/scores/sources
and text, and the final context sent to the answer model. These logs may contain
user questions and indexed document text.

Available routes:

- `GET /api/health` -> `{"status": "ok"}`
- `POST /api/chat` -> `{"response": "..."}`
- `POST /api/stt` -> `{"text": "..."}` for uploaded audio
- `POST /api/tts` -> raw audio bytes (WAV by default, `audio/wav`); the existing optional JSON response is also retained

The Nuxt frontend continues to call the FastAPI `/api/tts` route. The backend calls Groq Cloud TTS (`canopylabs/orpheus-v1-english`) with automatic fallback to Deepgram Cloud TTS (`aura-asteria-en`). Provider credentials and voice settings are not exposed to the frontend.
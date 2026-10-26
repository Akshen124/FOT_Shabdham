import asyncio
import io
import logging
import math
import os
import re
import time
import wave

from groq import AsyncGroq, Groq
from groq import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    RateLimitError,
)
import httpx


logger = logging.getLogger(__name__)

DEFAULT_GROQ_MODEL = "canopylabs/orpheus-v1-english"
DEFAULT_GROQ_VOICE = "hannah"
DEFAULT_DEEPGRAM_VOICE = "Kelsey"

_AUDIO_TYPES = {
    "aac": "audio/aac",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
}
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


class TextToSpeechError(RuntimeError):
    """Raised when speech generation or local playback is unavailable."""

    status_code = 503


class EmptyTTSTextError(TextToSpeechError):
    status_code = 400


class TTSUpstreamError(TextToSpeechError):
    status_code = 502


class TTSTimeoutError(TextToSpeechError):
    status_code = 504


class TTSRateLimitError(TTSUpstreamError):
    status_code = 502


# Backward compatibility aliases
KokoroUpstreamError = TTSUpstreamError
KokoroTimeoutError = TTSTimeoutError


def _sanitize_log_message(msg: str) -> str:
    """Mask sensitive tokens and keys from log messages."""
    msg = re.sub(r"(gsk_[a-zA-Z0-9_\-]+)", "[REDACTED_GROQ_KEY]", msg)
    msg = re.sub(r"(Token\s+[a-zA-Z0-9_\-]+)", "Token [REDACTED_KEY]", msg)
    msg = re.sub(r"(Bearer\s+[a-zA-Z0-9_\-]+)", "Bearer [REDACTED_KEY]", msg)
    return msg


def clean_text_for_tts(text: str) -> str:
    """Remove common Markdown and web formatting while preserving spoken text and bracketed directions."""
    cleaned = re.sub(r"```[\s\S]*?```", " ", text)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+|www\.\S+", " ", cleaned, flags=re.IGNORECASE)

    lines: list[str] = []
    for line in cleaned.splitlines():
        if _TABLE_SEPARATOR.match(line):
            continue
        if "|" in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            line = ", ".join(cell for cell in cells if cell)
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
        lines.append(line)

    cleaned = " ".join(lines)
    cleaned = re.sub(r"```|`", "", cleaned)
    cleaned = re.sub(r"(\*\*|__|~~|[*_])", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[^\w\s.,!?;:'’\"()\-–—\[\]]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+([.,!?;:])", r"\1", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


async def _async_groq_tts(
    text: str,
    audio_format: str = "wav",
    model: str | None = None,
    voice: str | None = None,
) -> tuple[bytes, str]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise TextToSpeechError("GROQ_API_KEY is not configured.")

    tts_model = model or os.getenv("GROQ_TTS_MODEL", DEFAULT_GROQ_MODEL)
    tts_voice = voice or os.getenv("GROQ_TTS_VOICE", DEFAULT_GROQ_VOICE)
    format_val = audio_format.strip().lower() or "wav"
    try:
        timeout_sec = float(os.getenv("TTS_TIMEOUT_SECONDS", "30.0"))
    except ValueError:
        timeout_sec = 30.0

    logger.info(
        "[TTS] Provider: Groq (model=%s, voice=%s, format=%s, text length=%d)",
        tts_model,
        tts_voice,
        format_val,
        len(text),
    )

    async with AsyncGroq(api_key=api_key, timeout=timeout_sec) as client:
        response = await client.audio.speech.create(
            model=tts_model,
            voice=tts_voice,
            input=text,
            response_format=format_val,
        )
        audio_bytes = await response.read()

    if not audio_bytes:
        logger.warning("[TTS] Groq returned an empty audio response.")
        raise TTSUpstreamError("Groq TTS returned empty audio.")

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = _AUDIO_TYPES.get(format_val, "audio/wav")

    logger.info(
        "[TTS] Audio generated successfully using Groq (%d bytes, %s).",
        len(audio_bytes),
        content_type,
    )
    return audio_bytes, content_type


def _sync_groq_tts(
    text: str,
    audio_format: str = "wav",
    model: str | None = None,
    voice: str | None = None,
) -> tuple[bytes, str]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise TextToSpeechError("GROQ_API_KEY is not configured.")

    tts_model = model or os.getenv("GROQ_TTS_MODEL", DEFAULT_GROQ_MODEL)
    tts_voice = voice or os.getenv("GROQ_TTS_VOICE", DEFAULT_GROQ_VOICE)
    format_val = audio_format.strip().lower() or "wav"
    try:
        timeout_sec = float(os.getenv("TTS_TIMEOUT_SECONDS", "30.0"))
    except ValueError:
        timeout_sec = 30.0

    logger.info(
        "[TTS] Provider: Groq (model=%s, voice=%s, format=%s, text length=%d)",
        tts_model,
        tts_voice,
        format_val,
        len(text),
    )

    with Groq(api_key=api_key, timeout=timeout_sec) as client:
        response = client.audio.speech.create(
            model=tts_model,
            voice=tts_voice,
            input=text,
            response_format=format_val,
        )
        audio_bytes = response.read()

    if not audio_bytes:
        logger.warning("[TTS] Groq returned an empty audio response.")
        raise TTSUpstreamError("Groq TTS returned empty audio.")

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = _AUDIO_TYPES.get(format_val, "audio/wav")

    logger.info(
        "[TTS] Audio generated successfully using Groq (%d bytes, %s).",
        len(audio_bytes),
        content_type,
    )
    return audio_bytes, content_type


MAX_DEEPGRAM_CHARS = 800


def combine_wav_bytes(wav_chunks: list[bytes]) -> bytes:
    """Concatenate multiple valid WAV audio byte sequences into one valid WAV file."""
    if not wav_chunks:
        return b""
    if len(wav_chunks) == 1:
        return wav_chunks[0]

    out_io = io.BytesIO()
    try:
        with wave.open(io.BytesIO(wav_chunks[0]), "rb") as first_wav:
            params = first_wav.getparams()

        with wave.open(out_io, "wb") as out_wav:
            out_wav.setparams(params)
            for chunk in wav_chunks:
                with wave.open(io.BytesIO(chunk), "rb") as w:
                    out_wav.writeframes(w.readframes(w.getnframes()))

        return out_io.getvalue()
    except Exception as exc:
        logger.warning("[TTS] Error combining WAV chunks with wave module: %s; using binary fallback", exc)
        return b"".join(wav_chunks)


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences while preserving trailing punctuation and list numbers."""
    stripped = text.strip()
    if not stripped:
        return []

    # Protect abbreviations, decimals, and list dots before splitting
    p = re.sub(r'(\d)\.(\d)', r'\1<DECIMAL_DOT>\2', stripped)
    p = re.sub(r'\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|vs|etc|i\.e|e\.g)\.', r'\1<ABBREV_DOT>', p, flags=re.IGNORECASE)
    p = re.sub(r'(^|\n)\s*(\d+)\.', r'\1\2<LIST_DOT>', p)
    raw = re.split(r'(?<=[.!?])\s+|\n+', p)
    sentences = [
        r.replace('<DECIMAL_DOT>', '.').replace('<ABBREV_DOT>', '.').replace('<LIST_DOT>', '.').strip()
        for r in raw
        if r.strip()
    ]
    return sentences or [stripped]


def chunk_text_by_sentences(text: str, max_chars: int = MAX_DEEPGRAM_CHARS) -> list[str]:
    """Split text into sentence-bounded chunks that do not exceed max_chars,
    preserving punctuation and sentence completeness without duplication or omission.
    """
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return [stripped]

    sentences = split_into_sentences(stripped)
    chunks: list[str] = []
    current_chunk = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            clause_parts = re.split(r'(?<=[,;])\s+', sentence)
            sub_chunk = ""
            for part in clause_parts:
                part = part.strip()
                if not part:
                    continue
                if len(part) > max_chars:
                    if sub_chunk:
                        chunks.append(sub_chunk)
                        sub_chunk = ""
                    words = part.split()
                    w_chunk = ""
                    for word in words:
                        if not w_chunk:
                            w_chunk = word
                        elif len(w_chunk) + len(word) + 1 <= max_chars:
                            w_chunk += " " + word
                        else:
                            chunks.append(w_chunk)
                            w_chunk = word
                    if w_chunk:
                        sub_chunk = w_chunk
                elif not sub_chunk:
                    sub_chunk = part
                elif len(sub_chunk) + len(part) + 1 <= max_chars:
                    sub_chunk += " " + part
                else:
                    chunks.append(sub_chunk)
                    sub_chunk = part
            if sub_chunk:
                current_chunk = sub_chunk
        elif not current_chunk:
            current_chunk = sentence
        elif len(current_chunk) + len(sentence) + 1 <= max_chars:
            current_chunk += " " + sentence
        else:
            chunks.append(current_chunk)
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks or [stripped]


def _get_deepgram_endpoint_and_model(voice_setting: str) -> tuple[str, str]:
    """Map voice setting (e.g. 'Kelsey', 'flux-kelsey-en', 'aura-asteria-en') to the correct Deepgram endpoint and model."""
    v = voice_setting.strip()
    lowered = v.lower()
    if lowered in ("kelsey", "flux-kelsey-en", "aura-kelsey-en", "aura-2-kelsey-en"):
        return "https://api.deepgram.com/v2/speak", "flux-kelsey-en"
    if lowered in ("meena", "flux-meena-en", "aura-meena-en", "aura-2-meena-en"):
        return "https://api.deepgram.com/v2/speak", "flux-meena-en"
    if lowered.startswith("flux-") or lowered.startswith("aura-2-"):
        return "https://api.deepgram.com/v2/speak", lowered
    return "https://api.deepgram.com/v1/speak", v


_shared_async_client: httpx.AsyncClient | None = None


def get_shared_async_client() -> httpx.AsyncClient:
    global _shared_async_client
    if _shared_async_client is None or _shared_async_client.is_closed:
        _shared_async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
        )
    return _shared_async_client


async def _async_deepgram_tts_single(
    text: str,
    audio_format: str = "wav",
    client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise TextToSpeechError("DEEPGRAM_API_KEY is not configured.")
    configured_voice = os.getenv("DEEPGRAM_TTS_VOICE", DEFAULT_DEEPGRAM_VOICE)
    base_url, model = _get_deepgram_endpoint_and_model(configured_voice)

    url = f"{base_url}?model={model}"
    if audio_format == "wav":
        url += "&container=wav&encoding=linear16"

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    logger.info(
        "[TTS] Provider: Deepgram (model=%s, voice=%s, format=%s, text length=%d)",
        model,
        configured_voice,
        audio_format,
        len(text),
    )

    should_close = False
    if client is None:
        client = get_shared_async_client()
        should_close = False

    t_dg_start = time.perf_counter()
    try:
        response = await client.post(url, headers=headers, json={"text": text})
    finally:
        if should_close:
            await client.aclose()
    dg_ms = (time.perf_counter() - t_dg_start) * 1000
    logger.info("[TTS-TIMING] Deepgram request completed in %.1fms (status=%d, %d bytes)", dg_ms, response.status_code, len(response.content))

    if not response.is_success:
        sanitized_err = _sanitize_log_message(response.text)
        logger.warning(
            "[TTS] Deepgram returned HTTP %d: %s",
            response.status_code,
            sanitized_err,
        )
        raise TTSUpstreamError(f"Deepgram TTS request failed with status {response.status_code}: {sanitized_err}")

    audio_bytes = response.content
    if not audio_bytes:
        raise TTSUpstreamError("Deepgram TTS returned empty audio.")

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"

    return audio_bytes, content_type


async def _async_deepgram_tts(text: str, audio_format: str = "wav") -> tuple[bytes, str]:
    chunks = chunk_text_by_sentences(text, max_chars=MAX_DEEPGRAM_CHARS)
    if len(chunks) == 1:
        audio_bytes, content_type = await _async_deepgram_tts_single(chunks[0], audio_format=audio_format)
        logger.info("[TTS] Audio generated successfully using Deepgram (%d bytes, %s).", len(audio_bytes), content_type)
        return audio_bytes, content_type

    logger.info(
        "[TTS] Text length (%d chars) exceeds threshold (%d chars). Splitting into %d sentence chunks.",
        len(text),
        MAX_DEEPGRAM_CHARS,
        len(chunks),
    )

    audio_chunks: list[bytes] = []
    final_content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"

    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
        for idx, chunk in enumerate(chunks):
            logger.info("[TTS] Processing Deepgram chunk %d/%d (%d chars)", idx + 1, len(chunks), len(chunk))
            try:
                chunk_audio, ctype = await _async_deepgram_tts_single(chunk, audio_format=audio_format, client=client)
            except Exception as chunk_err:
                logger.error("[TTS] Failed synthesizing Deepgram chunk %d/%d (%d chars): %s", idx + 1, len(chunks), len(chunk), chunk_err)
                raise
            audio_chunks.append(chunk_audio)
            final_content_type = ctype

    if audio_format == "wav":
        combined_audio = combine_wav_bytes(audio_chunks)
    else:
        combined_audio = b"".join(audio_chunks)

    logger.info(
        "[TTS] Audio generated successfully using Deepgram (%d chunks merged into %d bytes, %s).",
        len(audio_chunks),
        len(combined_audio),
        final_content_type,
    )
    return combined_audio, final_content_type


def _sync_deepgram_tts_single(
    text: str,
    audio_format: str = "wav",
    client: httpx.Client | None = None,
) -> tuple[bytes, str]:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise TextToSpeechError("DEEPGRAM_API_KEY is not configured.")
    configured_voice = os.getenv("DEEPGRAM_TTS_VOICE", DEFAULT_DEEPGRAM_VOICE)
    base_url, model = _get_deepgram_endpoint_and_model(configured_voice)

    url = f"{base_url}?model={model}"
    if audio_format == "wav":
        url += "&container=wav&encoding=linear16"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    logger.info(
        "[TTS] Provider: Deepgram (model=%s, voice=%s, format=%s, text length=%d)",
        model,
        configured_voice,
        audio_format,
        len(text),
    )

    should_close = False
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(45.0, connect=5.0))
        should_close = True

    try:
        response = client.post(url, headers=headers, json={"text": text})
    finally:
        if should_close:
            client.close()

    if not response.is_success:
        sanitized_err = _sanitize_log_message(response.text)
        logger.warning(
            "[TTS] Deepgram returned HTTP %d: %s",
            response.status_code,
            sanitized_err,
        )
        raise TTSUpstreamError(f"Deepgram TTS request failed with status {response.status_code}: {sanitized_err}")
    audio_bytes = response.content
    if not audio_bytes:
        raise TTSUpstreamError("Deepgram TTS returned empty audio.")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"
    return audio_bytes, content_type


def _sync_deepgram_tts(text: str, audio_format: str = "wav") -> tuple[bytes, str]:
    chunks = chunk_text_by_sentences(text, max_chars=MAX_DEEPGRAM_CHARS)
    if len(chunks) == 1:
        audio_bytes, content_type = _sync_deepgram_tts_single(chunks[0], audio_format=audio_format)
        logger.info("[TTS] Audio generated successfully using Deepgram (%d bytes, %s).", len(audio_bytes), content_type)
        return audio_bytes, content_type

    logger.info(
        "[TTS] Text length (%d chars) exceeds threshold (%d chars). Splitting into %d sentence chunks.",
        len(text),
        MAX_DEEPGRAM_CHARS,
        len(chunks),
    )

    audio_chunks: list[bytes] = []
    final_content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"

    with httpx.Client(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
        for idx, chunk in enumerate(chunks):
            logger.info("[TTS] Processing Deepgram chunk %d/%d (%d chars)", idx + 1, len(chunks), len(chunk))
            try:
                chunk_audio, ctype = _sync_deepgram_tts_single(chunk, audio_format=audio_format, client=client)
            except Exception as chunk_err:
                logger.error("[TTS] Failed synthesizing Deepgram chunk %d/%d (%d chars): %s", idx + 1, len(chunks), len(chunk), chunk_err)
                raise
            audio_chunks.append(chunk_audio)
            final_content_type = ctype

    if audio_format == "wav":
        combined_audio = combine_wav_bytes(audio_chunks)
    else:
        combined_audio = b"".join(audio_chunks)

    logger.info(
        "[TTS] Audio generated successfully using Deepgram (%d chunks merged into %d bytes, %s).",
        len(audio_chunks),
        len(combined_audio),
        final_content_type,
    )
    return combined_audio, final_content_type


def _map_tts_error(error: Exception | None, provider: str = "Groq") -> TextToSpeechError:
    if isinstance(error, (APITimeoutError, httpx.TimeoutException)):
        return TTSTimeoutError(f"{provider} TTS request timed out.")
    if isinstance(error, RateLimitError):
        return TTSRateLimitError(f"{provider} TTS rate limit exceeded.")
    if isinstance(error, (APIConnectionError, httpx.RequestError)):
        return TTSUpstreamError(f"{provider} TTS connection error: {error}")
    if isinstance(error, TextToSpeechError):
        return error
    if isinstance(error, APIError):
        return TTSUpstreamError(f"{provider} TTS API error: {type(error).__name__}")
    if error is not None:
        return TTSUpstreamError(f"{provider} TTS service error: {type(error).__name__}")
    return TextToSpeechError(f"{provider} TTS service is unavailable.")


async def async_text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio asynchronously for FastAPI endpoints.
    Tries Deepgram Aura TTS primary; automatically falls back to Groq Orpheus if configured.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    preferred_provider = os.getenv("TTS_PROVIDER", "auto").strip().lower()
    audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower() or "wav"

    # If explicitly set to groq, use Groq directly
    if preferred_provider in ("groq", "orpheus"):
        return await _async_groq_tts(cleaned_text, audio_format=audio_format)

    dg_error: Exception | None = None
    if os.getenv("DEEPGRAM_API_KEY"):
        try:
            return await _async_deepgram_tts(cleaned_text, audio_format=audio_format)
        except Exception as error:
            dg_error = error
            logger.warning(
                "[TTS] Deepgram Aura request failed with %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
    else:
        dg_error = TextToSpeechError("DEEPGRAM_API_KEY is not configured.")
        logger.warning("[TTS] DEEPGRAM_API_KEY is not set.")

    # Fallback to Groq Orpheus if configured
    if os.getenv("GROQ_API_KEY"):
        logger.info("[TTS] Deepgram Aura unavailable; attempting Groq Orpheus TTS fallback...")
        try:
            return await _async_groq_tts(cleaned_text, audio_format=audio_format)
        except (
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIError,
            httpx.RequestError,
            TextToSpeechError,
        ) as error:
            logger.error(
                "[TTS] Groq Orpheus fallback also failed: %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
        except Exception as error:
            logger.error(
                "[TTS] Groq Orpheus fallback unexpected failure: %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )

    # If both providers failed or were unavailable, raise the mapped error
    raise _map_tts_error(dg_error, provider="Deepgram")


def text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio synchronously for the Streamlit interface.
    Tries Deepgram Aura TTS primary; automatically falls back to Groq Orpheus if configured.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    preferred_provider = os.getenv("TTS_PROVIDER", "auto").strip().lower()
    audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower() or "wav"

    if preferred_provider in ("groq", "orpheus"):
        return _sync_groq_tts(cleaned_text, audio_format=audio_format)

    dg_error: Exception | None = None
    if os.getenv("DEEPGRAM_API_KEY"):
        try:
            return _sync_deepgram_tts(cleaned_text, audio_format=audio_format)
        except Exception as error:
            dg_error = error
            logger.warning(
                "[TTS] Deepgram Aura request failed with %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
    else:
        dg_error = TextToSpeechError("DEEPGRAM_API_KEY is not configured.")
        logger.warning("[TTS] DEEPGRAM_API_KEY is not set.")

    if os.getenv("GROQ_API_KEY"):
        logger.info("[TTS] Deepgram Aura unavailable; attempting Groq Orpheus TTS fallback...")
        try:
            return _sync_groq_tts(cleaned_text, audio_format=audio_format)
        except (
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIError,
            httpx.RequestError,
            TextToSpeechError,
        ) as error:
            logger.error(
                "[TTS] Groq Orpheus fallback also failed: %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
        except Exception as error:
            logger.error(
                "[TTS] Groq Orpheus fallback unexpected failure: %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )

    raise _map_tts_error(dg_error, provider="Deepgram")

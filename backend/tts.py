import asyncio
import logging
import math
import os
import re

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
DEFAULT_DEEPGRAM_VOICE = "aura-asteria-en"

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


async def _async_deepgram_tts(text: str, audio_format: str = "wav") -> tuple[bytes, str]:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise TextToSpeechError("DEEPGRAM_API_KEY is not configured for TTS fallback.")
    voice = os.getenv("DEEPGRAM_TTS_VOICE", DEFAULT_DEEPGRAM_VOICE)

    url = f"https://api.deepgram.com/v1/speak?model={voice}"
    if audio_format == "wav":
        url += "&container=wav&encoding=linear16"

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    logger.info("[TTS] Provider: Deepgram Aura (voice=%s, format=%s, text length=%d)", voice, audio_format, len(text))
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        response = await client.post(url, headers=headers, json={"text": text})

    if not response.is_success:
        logger.warning(
            "[TTS] Deepgram returned HTTP %d: %s",
            response.status_code,
            _sanitize_log_message(response.text[:200]),
        )
        raise TTSUpstreamError(f"Deepgram TTS request failed with status {response.status_code}.")

    audio_bytes = response.content
    if not audio_bytes:
        raise TTSUpstreamError("Deepgram TTS returned empty audio.")

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"

    logger.info("[TTS] Audio generated successfully using Deepgram (%d bytes, %s).", len(audio_bytes), content_type)
    return audio_bytes, content_type


def _sync_deepgram_tts(text: str, audio_format: str = "wav") -> tuple[bytes, str]:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise TextToSpeechError("DEEPGRAM_API_KEY is not configured for TTS fallback.")
    voice = os.getenv("DEEPGRAM_TTS_VOICE", DEFAULT_DEEPGRAM_VOICE)
    url = f"https://api.deepgram.com/v1/speak?model={voice}"
    if audio_format == "wav":
        url += "&container=wav&encoding=linear16"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    logger.info("[TTS] Provider: Deepgram Aura (voice=%s, format=%s, text length=%d)", voice, audio_format, len(text))
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        response = client.post(url, headers=headers, json={"text": text})
    if not response.is_success:
        logger.warning(
            "[TTS] Deepgram returned HTTP %d: %s",
            response.status_code,
            _sanitize_log_message(response.text[:200]),
        )
        raise TTSUpstreamError(f"Deepgram TTS request failed with status {response.status_code}.")
    audio_bytes = response.content
    if not audio_bytes:
        raise TTSUpstreamError("Deepgram TTS returned empty audio.")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"
    logger.info("[TTS] Audio generated successfully using Deepgram (%d bytes, %s).", len(audio_bytes), content_type)
    return audio_bytes, content_type


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
    Tries Groq Orpheus TTS primary; automatically falls back to Deepgram Aura if configured.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    preferred_provider = os.getenv("TTS_PROVIDER", "auto").strip().lower()
    audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower() or "wav"

    # If explicitly set to deepgram, use Deepgram directly
    if preferred_provider == "deepgram":
        return await _async_deepgram_tts(cleaned_text, audio_format=audio_format)

    groq_error: Exception | None = None
    if os.getenv("GROQ_API_KEY"):
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
            groq_error = error
            logger.warning(
                "[TTS] Groq request failed with %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
        except Exception as error:
            groq_error = error
            logger.warning(
                "[TTS] Unexpected Groq failure with %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
    else:
        groq_error = TextToSpeechError("GROQ_API_KEY is not configured.")
        logger.warning("[TTS] GROQ_API_KEY is not set.")

    # Fallback to Deepgram Aura if configured
    if os.getenv("DEEPGRAM_API_KEY"):
        logger.info("[TTS] Groq unavailable; attempting Deepgram Aura TTS fallback...")
        try:
            return await _async_deepgram_tts(cleaned_text, audio_format=audio_format)
        except Exception as dg_error:
            logger.error(
                "[TTS] Deepgram Aura fallback also failed: %s: %s",
                type(dg_error).__name__,
                _sanitize_log_message(str(dg_error)),
            )

    # If both providers failed or were unavailable, raise the mapped error
    raise _map_tts_error(groq_error, provider="Groq")


def text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio synchronously for the Streamlit interface.
    Tries Groq Orpheus TTS primary; automatically falls back to Deepgram Aura if configured.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    preferred_provider = os.getenv("TTS_PROVIDER", "auto").strip().lower()
    audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower() or "wav"

    if preferred_provider == "deepgram":
        return _sync_deepgram_tts(cleaned_text, audio_format=audio_format)

    groq_error: Exception | None = None
    if os.getenv("GROQ_API_KEY"):
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
            groq_error = error
            logger.warning(
                "[TTS] Groq request failed with %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
        except Exception as error:
            groq_error = error
            logger.warning(
                "[TTS] Unexpected Groq failure with %s: %s",
                type(error).__name__,
                _sanitize_log_message(str(error)),
            )
    else:
        groq_error = TextToSpeechError("GROQ_API_KEY is not configured.")
        logger.warning("[TTS] GROQ_API_KEY is not set.")

    if os.getenv("DEEPGRAM_API_KEY"):
        logger.info("[TTS] Groq unavailable; attempting Deepgram Aura TTS fallback...")
        try:
            return _sync_deepgram_tts(cleaned_text, audio_format=audio_format)
        except Exception as dg_error:
            logger.error(
                "[TTS] Deepgram Aura fallback also failed: %s: %s",
                type(dg_error).__name__,
                _sanitize_log_message(str(dg_error)),
            )

    raise _map_tts_error(groq_error, provider="Groq")

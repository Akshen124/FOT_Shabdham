import logging
import math
import os
import re

import httpx


logger = logging.getLogger(__name__)

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


class KokoroUpstreamError(TextToSpeechError):
    status_code = 502


class KokoroTimeoutError(TextToSpeechError):
    status_code = 504


def clean_text_for_tts(text: str) -> str:
    """Remove common Markdown and web formatting while preserving spoken text."""
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
    cleaned = re.sub(r"[^\w\s.,!?;:'’\"()\-–—]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+([.,!?;:])", r"\1", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _build_request(text: str) -> tuple[str, dict[str, str | float], str]:
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    base_url = os.getenv("KOKORO_TTS_URL", "http://localhost:8880").rstrip("/")
    voice = os.getenv("KOKORO_TTS_VOICE", "af_bella")
    model = os.getenv("KOKORO_TTS_MODEL", "kokoro")
    audio_format = os.getenv("KOKORO_TTS_FORMAT", "mp3").strip().lower()
    try:
        speed = float(os.getenv("KOKORO_TTS_SPEED", "1.0"))
    except ValueError as exc:
        raise TextToSpeechError("KOKORO_TTS_SPEED must be a positive number.") from exc
    if not math.isfinite(speed) or speed <= 0:
        raise TextToSpeechError("KOKORO_TTS_SPEED must be a positive number.")

    logger.info("[TTS] Provider: Kokoro")
    logger.info("[TTS] Voice: %s", voice)
    logger.info("[TTS] Text length: %d", len(cleaned_text))
    logger.info("[TTS] Requesting Kokoro")
    return (
        f"{base_url}/v1/audio/speech",
        {
            "model": model,
            "input": cleaned_text,
            "voice": voice,
            "response_format": audio_format,
            "speed": speed,
        },
        audio_format,
    )


def _read_audio(response: httpx.Response, audio_format: str) -> tuple[bytes, str]:
    if not response.is_success:
        logger.warning("[TTS] Kokoro returned HTTP status %d.", response.status_code)
        raise KokoroUpstreamError("Kokoro TTS request failed.")

    audio = response.content
    if not audio:
        logger.warning("[TTS] Kokoro returned an empty audio response.")
        raise KokoroUpstreamError("Kokoro TTS returned empty audio.")

    response_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if response_type and not response_type.startswith("audio/"):
        logger.warning("[TTS] Kokoro returned a non-audio content type.")
        raise KokoroUpstreamError("Kokoro TTS returned an invalid audio response.")

    content_type = response_type or _AUDIO_TYPES.get(audio_format, "application/octet-stream")
    if not content_type.startswith("audio/"):
        raise KokoroUpstreamError("Kokoro TTS returned an unsupported audio format.")

    logger.info("[TTS] Audio generated successfully (%d bytes, %s).", len(audio), content_type)
    return audio, content_type


def _request_failed(error: httpx.RequestError, provider: str = "Kokoro", url: str = "") -> TextToSpeechError:
    if isinstance(error, httpx.TimeoutException):
        logger.warning("[TTS] %s request timed out (endpoint=%s).", provider, url)
        return KokoroTimeoutError(f"{provider} TTS request timed out.")
    logger.warning("[TTS] %s service is unavailable (endpoint=%s, error=%s).", provider, url, error)
    return TextToSpeechError(f"{provider} TTS service is unavailable.")


async def _async_deepgram_tts(text: str, audio_format: str = "wav") -> tuple[bytes, str]:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise TextToSpeechError("DEEPGRAM_API_KEY is not configured for TTS fallback.")
    voice = os.getenv("DEEPGRAM_TTS_VOICE", "aura-asteria-en")

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
        logger.warning("[TTS] Deepgram returned HTTP %d: %s", response.status_code, response.text[:200])
        raise KokoroUpstreamError(f"Deepgram TTS request failed with status {response.status_code}.")

    audio_bytes = response.content
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"

    logger.info("[TTS] Audio generated successfully using Deepgram (%d bytes, %s).", len(audio_bytes), content_type)
    return audio_bytes, content_type


def _sync_deepgram_tts(text: str, audio_format: str = "wav") -> tuple[bytes, str]:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise TextToSpeechError("DEEPGRAM_API_KEY is not configured for TTS fallback.")
    voice = os.getenv("DEEPGRAM_TTS_VOICE", "aura-asteria-en")
    url = f"https://api.deepgram.com/v1/speak?model={voice}"
    if audio_format == "wav":
        url += "&container=wav&encoding=linear16"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        response = client.post(url, headers=headers, json={"text": text})
    if not response.is_success:
        logger.warning("[TTS] Deepgram returned HTTP %d: %s", response.status_code, response.text[:200])
        raise KokoroUpstreamError(f"Deepgram TTS request failed with status {response.status_code}.")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or not content_type.startswith("audio/"):
        content_type = "audio/wav" if audio_format == "wav" else "audio/mpeg"
    return response.content, content_type


async def async_text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio asynchronously for FastAPI endpoints.
    Tries Kokoro TTS (if reachable); automatically falls back to Deepgram Aura if configured.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    preferred_provider = os.getenv("TTS_PROVIDER", "auto").strip().lower()

    # If explicitly set to deepgram, use Deepgram directly
    if preferred_provider == "deepgram":
        audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower()
        return await _async_deepgram_tts(cleaned_text, audio_format=audio_format)

    # Otherwise, attempt Kokoro first
    url, payload, audio_format = _build_request(cleaned_text)
    kokoro_error: Exception | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=3.0)) as client:
            response = await client.post(url, json=payload)
        return _read_audio(response, audio_format)
    except (httpx.RequestError, KokoroUpstreamError) as error:
        kokoro_error = error
        logger.warning(
            "[TTS] Kokoro request to %s failed with %s: %s",
            url,
            type(error).__name__,
            str(error),
        )

    # Fallback to Deepgram Aura if available
    if os.getenv("DEEPGRAM_API_KEY"):
        logger.info("[TTS] Kokoro unavailable; falling back to Deepgram Aura TTS...")
        try:
            return await _async_deepgram_tts(cleaned_text, audio_format=audio_format)
        except Exception as dg_error:
            logger.error("[TTS] Deepgram Aura fallback also failed: %s", dg_error)

    # If no fallback succeeded, raise the appropriate Kokoro error
    if isinstance(kokoro_error, httpx.RequestError):
        raise _request_failed(kokoro_error, provider="Kokoro", url=url) from kokoro_error
    elif kokoro_error:
        raise kokoro_error
    raise TextToSpeechError("Kokoro TTS service is unavailable.")


def text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio synchronously for the Streamlit interface."""
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        raise EmptyTTSTextError("Text is empty after cleaning for speech.")

    preferred_provider = os.getenv("TTS_PROVIDER", "auto").strip().lower()

    if preferred_provider == "deepgram":
        audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower()
        return _sync_deepgram_tts(cleaned_text, audio_format=audio_format)

    url, payload, audio_format = _build_request(cleaned_text)
    kokoro_error: Exception | None = None
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=3.0)) as client:
            response = client.post(url, json=payload)
        return _read_audio(response, audio_format)
    except (httpx.RequestError, KokoroUpstreamError) as error:
        kokoro_error = error
        logger.warning("[TTS] Kokoro request failed: %s", error)

    if os.getenv("DEEPGRAM_API_KEY"):
        logger.info("[TTS] Kokoro unavailable; falling back to Deepgram Aura TTS...")
        try:
            return _sync_deepgram_tts(cleaned_text, audio_format=audio_format)
        except Exception as dg_error:
            logger.error("[TTS] Deepgram Aura fallback failed: %s", dg_error)

    if isinstance(kokoro_error, httpx.RequestError):
        raise _request_failed(kokoro_error, provider="Kokoro", url=url) from kokoro_error
    elif kokoro_error:
        raise kokoro_error
    raise TextToSpeechError("Kokoro TTS service is unavailable.")

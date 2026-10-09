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


def _request_failed(error: httpx.RequestError) -> TextToSpeechError:
    if isinstance(error, httpx.TimeoutException):
        logger.warning("[TTS] Kokoro request timed out.")
        return KokoroTimeoutError("Kokoro TTS request timed out.")
    logger.warning("[TTS] Kokoro service is unavailable.")
    return TextToSpeechError("Kokoro TTS service is unavailable.")


async def async_text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio asynchronously for FastAPI endpoints."""
    url, payload, audio_format = _build_request(text)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            response = await client.post(url, json=payload)
    except httpx.RequestError as error:
        raise _request_failed(error) from error
    return _read_audio(response, audio_format)


def text_to_speech(text: str) -> tuple[bytes, str]:
    """Generate audio synchronously for the Streamlit interface."""
    url, payload, audio_format = _build_request(text)
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            response = client.post(url, json=payload)
    except httpx.RequestError as error:
        raise _request_failed(error) from error
    return _read_audio(response, audio_format)

import asyncio
import logging
import math
import os
import time
from typing import Any

from groq import Groq, APIError, APITimeoutError, RateLimitError, APIConnectionError

logger = logging.getLogger(__name__)

GROQ_WHISPER_MODEL = "whisper-large-v3"
GROQ_PROVIDER = "groq_whisper"


class InvalidAudioError(ValueError):
    """Raised when an uploaded audio payload is empty or cannot be decoded."""


class STTTranscriptionError(RuntimeError):
    """Raised when no configured transcription provider returns usable text."""


class _EmptyTranscriptError(RuntimeError):
    """Raised when a provider completes without returning transcript text."""


def _read_positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number.") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return value


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


class SpeechToTextService:
    """Transcribe one uploaded recording with Groq Whisper."""

    def __init__(self) -> None:
        self.timeout_seconds = _read_positive_float("STT_TIMEOUT_SECONDS", 45.0)
        self._slots = asyncio.Semaphore(_read_positive_int("STT_MAX_CONCURRENT_REQUESTS", 4))

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> tuple[str, str]:
        if not audio_bytes:
            raise InvalidAudioError("No audio data was uploaded.")

        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self.timeout_seconds)
        except TimeoutError as error:
            raise STTTranscriptionError(
                "Speech transcription is busy; please retry shortly."
            ) from error

        try:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("GROQ_API_KEY is not configured.")

            client = Groq(api_key=api_key, timeout=self.timeout_seconds, max_retries=0)
            
            start_time = time.perf_counter()
            try:
                response = await asyncio.to_thread(
                    client.audio.transcriptions.create,
                    model="GROQ_WHISPER_MODE",
                    file=(filename, audio_bytes, content_type),
                    response_format="text",
                    language="en",
                    prompt=(
                      "Transcribe the spoken English accurately. "
                      "Technical terms and names include GenLab, Shabdham, "
                       "AI, and software engineering."
                      ),
                )
            except RateLimitError as error:
                logger.error("[STT] Groq API rate limit exceeded.")
                raise STTTranscriptionError("Groq API rate limit exceeded.") from error
            except APITimeoutError as error:
                logger.error("[STT] Groq API request timed out after %.3fs.", self.timeout_seconds)
                raise STTTranscriptionError("Groq API request timed out.") from error
            except APIConnectionError as error:
                logger.error("[STT] Groq API connection failed: %s", error)
                raise STTTranscriptionError("Groq API connection failed.") from error
            except APIError as error:
                logger.error("[STT] Groq API error: %s", error)
                if "unsupported" in str(error).lower() or "invalid format" in str(error).lower():
                    raise InvalidAudioError(f"Unsupported audio format: {error}") from error
                raise STTTranscriptionError(f"Groq API error: {error}") from error
            except Exception as error:
                logger.error("[STT] Unexpected error during transcription: %s", error)
                raise STTTranscriptionError("Transcription failed.") from error
            
            duration = time.perf_counter() - start_time
            
            transcript = ""
            if isinstance(response, str):
                transcript = response.strip()
            else:
                transcript_text = getattr(response, "text", None)
                if isinstance(transcript_text, str):
                    transcript = transcript_text.strip()
                else:
                    raise RuntimeError("Groq returned an unsupported transcription response.")
            
            if not transcript:
                raise _EmptyTranscriptError("Provider returned no usable transcript.")
                
            logger.info("[STT] Transcription succeeded in %.3fs using %s.", duration, GROQ_WHISPER_MODEL)
            return transcript, GROQ_PROVIDER
            
        except InvalidAudioError:
            raise
        except Exception as error:
            logger.error("[STT] Transcription failed: %s", error)
            if not isinstance(error, (STTTranscriptionError, InvalidAudioError, _EmptyTranscriptError)):
                raise STTTranscriptionError(f"Speech transcription failed: {error}") from error
            raise
        finally:
            self._slots.release()

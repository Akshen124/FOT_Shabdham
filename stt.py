
import asyncio
import logging
import math
import os
import time


from deepgram import DeepgramClient

logger = logging.getLogger(__name__)

DEEPGRAM_MODEL = "nova-3"
STT_PROVIDER = "deepgram"


class InvalidAudioError(ValueError):
    """Raised when uploaded audio is empty or invalid."""


class STTTranscriptionError(RuntimeError):
    """Raised when transcription fails."""


def _read_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number.") from error

    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")

    return value


def _read_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer.") from error

    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")

    return value


class SpeechToTextService:
    """Transcribe uploaded English audio using Deepgram Nova-3."""

    def __init__(self) -> None:
        self.timeout_seconds = _read_positive_float(
            "STT_TIMEOUT_SECONDS", 45.0
        )
        self._slots = asyncio.Semaphore(
            _read_positive_int("STT_MAX_CONCURRENT_REQUESTS", 4)
            
        )

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> tuple[str, str]:

        if not audio_bytes:
            raise InvalidAudioError("No audio data was uploaded.")

        if not os.getenv("DEEPGRAM_API_KEY"):
            raise STTTranscriptionError(
                "DEEPGRAM_API_KEY is not configured."
            )
      

        try:
            await asyncio.wait_for(
                self._slots.acquire(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as error:
            raise STTTranscriptionError(
                "Speech transcription is busy. Please retry."
            ) from error

        try:
            client = DeepgramClient(
                api_key=os.environ["DEEPGRAM_API_KEY"]
            )

            logger.info(
                "[STT] Provider=Deepgram model=%s file=%s "
                "content_type=%s bytes=%d",
                DEEPGRAM_MODEL,
                filename,
                content_type,
                len(audio_bytes),
            )

            start_time = time.perf_counter()

            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.listen.v1.media.transcribe_file,
                        request=audio_bytes,
                        model=DEEPGRAM_MODEL,
                        language="en",
                        smart_format=True,
                        keyterm=["GenLab", "Shabdham"],
                    ),
                    timeout=self.timeout_seconds,
                )

            except TimeoutError as error:
                logger.error("[STT] Deepgram request timed out.")
                raise STTTranscriptionError(
                    "Deepgram transcription timed out."
                ) from error

            except Exception as error:
                logger.exception("[STT] Deepgram request failed.")
                raise STTTranscriptionError(
                    f"Deepgram transcription failed: {error}"
                ) from error

            transcript = (
                response.results.channels[0]
                .alternatives[0].transcript
                .strip()
            )

            if not transcript:
                raise STTTranscriptionError(
                    "Deepgram returned an empty transcript."
                )

            duration = time.perf_counter() - start_time

            logger.info(
                "[STT] Transcription succeeded in %.3fs using %s.",
                duration,
                DEEPGRAM_MODEL,
            )

            return transcript, STT_PROVIDER

        finally:
            self._slots.release()

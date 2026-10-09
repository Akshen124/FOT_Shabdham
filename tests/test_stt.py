import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

from groq import APITimeoutError, RateLimitError, APIError, APIConnectionError

from stt import InvalidAudioError, SpeechToTextService, STTTranscriptionError, _EmptyTranscriptError


class SpeechToTextServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "STT_TIMEOUT_SECONDS": "2",
                "STT_MAX_CONCURRENT_REQUESTS": "2",
                "GROQ_API_KEY": "test_key"
            },
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def create_service(self) -> SpeechToTextService:
        return SpeechToTextService()

    @patch("stt.Groq")
    async def test_success_returns_transcript(self, mock_groq_class) -> None:
        service = self.create_service()
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = "This is a test transcript."
        
        result = await service.transcribe(b"audio", "voice.webm", "audio/webm")
        self.assertEqual(result, ("This is a test transcript.", "groq_whisper"))
        mock_client.audio.transcriptions.create.assert_called_once_with(
            model="whisper-large-v3",
            file=("voice.webm", b"audio", "audio/webm"),
            response_format="text"
        )

    async def test_empty_audio_raises_error(self) -> None:
        service = self.create_service()
        with self.assertRaises(InvalidAudioError):
            await service.transcribe(b"", "voice.webm", "audio/webm")

    @patch("stt.Groq")
    async def test_rate_limit_error(self, mock_groq_class) -> None:
        service = self.create_service()
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_client.audio.transcriptions.create.side_effect = RateLimitError(
            "Rate limit", response=MagicMock(), body=None
        )
        
        with self.assertRaises(STTTranscriptionError) as context:
            await service.transcribe(b"audio", "voice.webm", "audio/webm")
        
        self.assertIn("rate limit exceeded", str(context.exception))

    @patch("stt.Groq")
    async def test_timeout_error(self, mock_groq_class) -> None:
        service = self.create_service()
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_client.audio.transcriptions.create.side_effect = APITimeoutError(
            request=MagicMock()
        )
        
        with self.assertRaises(STTTranscriptionError) as context:
            await service.transcribe(b"audio", "voice.webm", "audio/webm")
        
        self.assertIn("request timed out", str(context.exception))

    @patch("stt.Groq")
    async def test_empty_transcript(self, mock_groq_class) -> None:
        service = self.create_service()
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = "   "
        
        with self.assertRaises(_EmptyTranscriptError):
            await service.transcribe(b"audio", "voice.webm", "audio/webm")
            
    @patch("stt.Groq")
    async def test_invalid_format_error(self, mock_groq_class) -> None:
        service = self.create_service()
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_client.audio.transcriptions.create.side_effect = APIError(
            message="unsupported audio format", request=MagicMock(), body=None
        )
        
        with self.assertRaises(InvalidAudioError):
            await service.transcribe(b"audio", "voice.webm", "audio/webm")

if __name__ == "__main__":
    unittest.main()

import io
import wave
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from backend.tts import (
    EmptyTTSTextError,
    TTSUpstreamError,
    async_text_to_speech,
    chunk_text_by_sentences,
    combine_wav_bytes,
    _async_deepgram_tts_single,
)


@pytest.fixture(autouse=True)
def mock_env_keys(monkeypatch):
    """Ensure environment variables are configured for test execution."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-deepgram-key-12345")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key-12345")
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_TTS_VOICE", "Kelsey")


def _make_dummy_wav(duration_frames: int = 240, framerate: int = 24000) -> bytes:
    """Helper to generate a minimal valid WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * duration_frames)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_empty_text():
    """Verify empty text or whitespace raises EmptyTTSTextError."""
    with pytest.raises(EmptyTTSTextError):
        await async_text_to_speech("")

    with pytest.raises(EmptyTTSTextError):
        await async_text_to_speech("   \n\t  ")

    with pytest.raises(EmptyTTSTextError):
        await async_text_to_speech("```code only```")


def test_chunking_preserves_sentences():
    """Verify sentence-based chunking preserves all sentences and punctuation without duplication."""
    sentences = [
        "First sentence introduces the topic.",
        "Second sentence adds technical details with numbers like 10.5%.",
        "Third sentence contains a question, doesn't it?",
        "Fourth sentence provides a concluding summary.",
    ]
    full_text = " ".join(sentences)
    chunks = chunk_text_by_sentences(full_text, max_chars=80)

    # All text must be accounted for
    reconstructed = " ".join(chunks)
    assert "First sentence" in reconstructed
    assert "10.5%" in reconstructed
    assert "question, doesn't it?" in reconstructed
    assert "concluding summary." in reconstructed

    # Every chunk must be within the max_chars limit
    for chunk in chunks:
        assert len(chunk) <= 80


def test_wav_combining():
    """Verify combine_wav_bytes stitches multiple WAV audio chunks into a valid single WAV."""
    chunk1 = _make_dummy_wav(duration_frames=100)
    chunk2 = _make_dummy_wav(duration_frames=200)

    merged = combine_wav_bytes([chunk1, chunk2])
    assert merged.startswith(b"RIFF")

    with wave.open(io.BytesIO(merged), "rb") as w:
        assert w.getnframes() == 300
        assert w.getframerate() == 24000


@pytest.mark.asyncio
async def test_short_text_synthesis():
    """Verify short text synthesis completes with valid audio/wav."""
    dummy_wav = _make_dummy_wav(duration_frames=500)

    with patch("backend.tts._async_deepgram_tts_single", new_callable=AsyncMock) as mock_single:
        mock_single.return_value = (dummy_wav, "audio/wav")

        audio_bytes, ctype = await async_text_to_speech("Short greeting from Shabdham.")
        assert ctype == "audio/wav"
        assert len(audio_bytes) == len(dummy_wav)
        mock_single.assert_awaited_once()


@pytest.mark.asyncio
async def test_long_text_chunked_synthesis():
    """Verify long text exceeding max_chars splits into multiple chunks synthesized sequentially in order."""
    dummy_wav1 = _make_dummy_wav(duration_frames=100)
    dummy_wav2 = _make_dummy_wav(duration_frames=200)
    dummy_wav3 = _make_dummy_wav(duration_frames=300)

    # 3 sentences that together exceed 100 chars
    long_text = (
        "The first segment covers initial architecture setup. "
        "The second segment covers deep learning models and speech pipelines. "
        "The third segment covers testing, metrics, and audio delivery."
    )

    with patch("backend.tts.MAX_DEEPGRAM_CHARS", 80):
        with patch("backend.tts._async_deepgram_tts_single", new_callable=AsyncMock) as mock_single:
            mock_single.side_effect = [
                (dummy_wav1, "audio/wav"),
                (dummy_wav2, "audio/wav"),
                (dummy_wav3, "audio/wav"),
            ]

            audio_bytes, ctype = await async_text_to_speech(long_text)
            assert ctype == "audio/wav"
            assert mock_single.await_count == 3

            with wave.open(io.BytesIO(audio_bytes), "rb") as w:
                assert w.getnframes() == 600


@pytest.mark.asyncio
async def test_failed_chunk_captures_error_and_triggers_fallback():
    """Verify Deepgram error response body is captured and fallback to Groq Orpheus is triggered."""
    groq_wav = _make_dummy_wav(duration_frames=150)

    # Deepgram mock fails with HTTP 400
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 400
    mock_response.text = '{"err_code":"INVALID_QUERY_PARAMETER","err_msg":"Invalid parameter."}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with patch("backend.tts._async_groq_tts", new_callable=AsyncMock) as mock_groq:
            mock_groq.return_value = (groq_wav, "audio/wav")

            # Deepgram fails, so fallback to Groq should succeed
            audio_bytes, ctype = await async_text_to_speech("Test error handling.")
            assert audio_bytes == groq_wav
            mock_groq.assert_awaited_once()

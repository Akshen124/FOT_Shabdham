import io
import logging
import math
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path


logger = logging.getLogger(__name__)
SAMPLE_RATE = 16_000
DEFAULT_MODEL_NAME = "nvidia/parakeet-unified-en-0.6b"
DEBUG_AUDIO_PATH = Path(__file__).resolve().with_name("debug_stt_input.wav")


class InvalidAudioError(ValueError):
    """Raised when an uploaded audio payload cannot be decoded."""


class ParakeetSTT:
    """Load one NeMo Parakeet model and serialize access to its GPU inference."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        import torch
        import nemo.collections.asr as nemo_asr
        from omegaconf import open_dict

        self.model_name = model_name or os.getenv("PARAKEET_MODEL_NAME", DEFAULT_MODEL_NAME)
        self.device = (device or os.getenv("STT_DEVICE", "cuda")).strip().lower()
        if self.device != "cuda":
            raise RuntimeError("STT_DEVICE must be 'cuda'; CPU inference is disabled.")
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is unavailable. Install a CUDA-enabled PyTorch build and verify the NVIDIA driver."
            )

        self._torch = torch
        self._inference_lock = threading.Lock()
        self._model = None
        logger.info("[STT] Loading Parakeet...")
        logger.info("[STT] Model: %s", self.model_name)
        logger.info("[STT] CUDA available: True")
        logger.info("[STT] Device: %s", self.device)
        logger.info("[STT] GPU: %s", torch.cuda.get_device_name(0))

        try:
            model = nemo_asr.models.ASRModel.from_pretrained(model_name=self.model_name)
            with open_dict(model.cfg):
                model.cfg.validation_ds = {
                    "manifest_filepath": None,
                    "sample_rate": SAMPLE_RATE,
                    "batch_size": 1,
                    "shuffle": False,
                    "num_workers": 0,
                    "pin_memory": False,
                    "use_start_end_token": False,
                }
            model = model.cuda()
            model.eval()
        except Exception:
            logger.exception("[STT] Parakeet model loading failed.")
            raise

        self._model = model
        allocated_gib = torch.cuda.memory_allocated(0) / (1024**3)
        logger.info("[STT] Model loaded successfully (%.2f GiB GPU memory allocated).", allocated_gib)

    @classmethod
    def _extract_transcription_text(
        cls,
        result: object,
        seen: set[int] | None = None,
    ) -> str | None:
        if isinstance(result, str):
            return result.strip()
        if result is None:
            return None

        if seen is None:
            seen = set()
        result_id = id(result)
        if result_id in seen:
            return None
        seen.add(result_id)

        if isinstance(result, Mapping):
            preferred_keys = (
                "text",
                "transcription",
                "transcriptions",
                "hypotheses",
                "predictions",
                "results",
            )
            ordered_values = [
                result[key] for key in preferred_keys if key in result
            ]
            ordered_values.extend(value for key, value in result.items() if key not in preferred_keys)
            values = ordered_values
        elif isinstance(result, (list, tuple)):
            values = result
        else:
            text = getattr(result, "text", None)
            if text is None or text is result:
                return None
            values = (text,)

        empty_text_found = False
        for value in values:
            text = cls._extract_transcription_text(value, seen)
            if text:
                return text
            if text == "":
                empty_text_found = True
        return "" if empty_text_found else None

    @staticmethod
    def _detect_audio_format(audio_bytes: bytes, content_type: str) -> str:
        if audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE":
            return "WAV"
        if audio_bytes.startswith(b"OggS"):
            return "OGG"
        if audio_bytes.startswith(b"fLaC"):
            return "FLAC"
        if audio_bytes.startswith(b"ID3"):
            return "MP3"
        if audio_bytes.startswith(b"\x1aE\xdf\xa3"):
            if b"webm" in audio_bytes[:64].lower() or "webm" in content_type.lower():
                return "WEBM"
            return "MATROSKA/EBML"
        if len(audio_bytes) > 12 and audio_bytes[4:8] == b"ftyp":
            return "MP4"
        if len(audio_bytes) > 1 and audio_bytes[0] == 0xFF and audio_bytes[1] & 0xE0 == 0xE0:
            return "MP3"
        return "unknown"

    @staticmethod
    def _read_audio(audio_bytes: bytes, content_type: str) -> tuple[object, int, str, str]:
        import soundfile as sf

        audio_source = io.BytesIO(audio_bytes)
        try:
            input_info = sf.info(audio_source)
            audio_source.seek(0)
            audio, sample_rate = sf.read(
                audio_source,
                dtype="float32",
                always_2d=True,
            )
            return audio, sample_rate, input_info.format, input_info.subtype
        except Exception as soundfile_error:
            detected_format = ParakeetSTT._detect_audio_format(audio_bytes, content_type)
            logger.warning(
                "[STT] soundfile could not decode %s audio: %s",
                detected_format,
                soundfile_error,
            )
            logger.info("[STT] Audio format detected from file signature: %s", detected_format)
            ffmpeg_path = shutil.which("ffmpeg")
            if not ffmpeg_path:
                try:
                    import imageio_ffmpeg

                    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                except (ImportError, RuntimeError) as error:
                    raise InvalidAudioError(
                        f"Could not decode {detected_format} audio with the installed audio decoder. "
                        "WebM/MP4 decoding requires the bundled FFmpeg executable."
                    ) from error

            try:
                conversion = subprocess.run(
                    [
                        ffmpeg_path,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        "pipe:0",
                        "-f",
                        "wav",
                        "-ac",
                        "1",
                        "-ar",
                        str(SAMPLE_RATE),
                        "-c:a",
                        "pcm_s16le",
                        "pipe:1",
                    ],
                    input=audio_bytes,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                if conversion.returncode != 0:
                    detail = conversion.stderr.decode("utf-8", errors="replace").strip()
                    logger.error("[STT] FFmpeg audio decoding failed: %s", detail or "unknown decoder error")
                    raise InvalidAudioError(
                        f"FFmpeg could not decode the uploaded {detected_format} audio"
                        f"{': ' + detail if detail else '.'}"
                    )
                audio, sample_rate = sf.read(
                    io.BytesIO(conversion.stdout),
                    dtype="float32",
                    always_2d=True,
                )
                return audio, sample_rate, "WAV (FFmpeg decoded)", "PCM_16"
            except (subprocess.TimeoutExpired, OSError) as error:
                raise InvalidAudioError(f"FFmpeg audio decoding failed: {error}") from error

    @staticmethod
    def _prepare_wav(
        audio_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly

        if not audio_bytes:
            raise InvalidAudioError("No audio data was uploaded.")

        logger.info("[STT-BACKEND] Filename: %s", filename)
        logger.info("[STT-BACKEND] Content-Type: %s", content_type)
        logger.info("[STT-BACKEND] Raw bytes: %d", len(audio_bytes))
        logger.info(
            "[STT] Uploaded file extension: %s",
            Path(filename).suffix or "<none>",
        )

        detected_format = ParakeetSTT._detect_audio_format(audio_bytes, content_type)
        logger.info("[STT] Detected audio format: %s", detected_format)
        audio, sample_rate, decoded_format, decoded_subtype = ParakeetSTT._read_audio(
            audio_bytes,
            content_type,
        )
        if audio.size == 0 or sample_rate <= 0:
            logger.error(
                "[STT-BACKEND] Decoding produced no samples (samples=%d, sample_rate=%d)",
                audio.shape[0] if audio.ndim else 0,
                sample_rate,
            )
            raise InvalidAudioError("The uploaded audio is empty or has an invalid sample rate.")

        decoded_rms = float(np.sqrt(np.mean(np.square(audio))))
        decoded_peak = float(np.max(np.abs(audio)))
        logger.info("[STT-BACKEND] Decoded format: %s/%s", decoded_format, decoded_subtype)
        logger.info("[STT-BACKEND] Sample rate: %d", sample_rate)
        logger.info("[STT-BACKEND] Channels: %d", audio.shape[1])
        logger.info("[STT-BACKEND] Decoded dtype: %s", audio.dtype)
        logger.info("[STT-BACKEND] Samples: %d", audio.shape[0])
        logger.info("[STT-BACKEND] Duration: %.6f sec", audio.shape[0] / sample_rate)
        logger.info("[STT-BACKEND] RMS: %.10f", decoded_rms)
        logger.info("[STT-BACKEND] Max amplitude: %.10f", decoded_peak)
        logger.info(
            "[STT] Audio RMS: %.8f",
            decoded_rms,
        )
        logger.info("[STT] Audio max amplitude: %.8f", decoded_peak)
        has_signal = bool(np.any(audio != 0))
        logger.info("[STT] Audio has signal: %s", has_signal)

        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(np.square(audio))))
        mono_audio = audio.mean(axis=1, dtype=np.float32)
        if not np.isfinite(mono_audio).all():
            raise InvalidAudioError("The uploaded audio contains invalid sample values.")
        if sample_rate != SAMPLE_RATE:
            divisor = math.gcd(int(sample_rate), SAMPLE_RATE)
            mono_audio = resample_poly(
                mono_audio,
                SAMPLE_RATE // divisor,
                int(sample_rate) // divisor,
            ).astype(np.float32, copy=False)

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
                wav_path = wav_file.name
            sf.write(wav_path, mono_audio, SAMPLE_RATE, subtype="PCM_16")
            save_debug_audio = os.getenv("PARAKEET_SAVE_DEBUG_AUDIO", "").strip().lower()
            if save_debug_audio in {"1", "true", "yes"}:
                shutil.copyfile(wav_path, DEBUG_AUDIO_PATH)
        except Exception as error:
            if "wav_path" in locals():
                Path(wav_path).unlink(missing_ok=True)
            raise RuntimeError(
                f"Audio preprocessing or debug WAV save failed: {error}"
            ) from error
        wav_info = sf.info(wav_path)
        converted_audio, converted_sample_rate = sf.read(
            wav_path,
            dtype="float32",
            always_2d=True,
        )
        if converted_audio.size == 0 or converted_sample_rate != SAMPLE_RATE:
            Path(wav_path).unlink(missing_ok=True)
            raise InvalidAudioError("Audio conversion produced an empty or invalid WAV file.")
        converted_peak = float(np.max(np.abs(converted_audio)))
        converted_rms = float(np.sqrt(np.mean(np.square(converted_audio))))
        logger.info(
            "[STT] Parakeet input: model.transcribe input=list[str], path=%s, "
            "format=%s/%s, sample_rate=%d, channels=%d, file_sample_dtype=int16, "
            "inspection_array_dtype=%s",
            wav_path,
            wav_info.format,
            wav_info.subtype,
            converted_sample_rate,
            converted_audio.shape[1],
            converted_audio.dtype,
        )
        if save_debug_audio in {"1", "true", "yes"}:
            logger.info("[STT] Debug audio copy saved: %s", DEBUG_AUDIO_PATH)
        logger.info("[STT] Temporary WAV file: %s (%s/%s)", wav_path, wav_info.format, wav_info.subtype)
        logger.info("[STT] Temporary file extension: %s", Path(wav_path).suffix)
        logger.info("[STT-BACKEND] Converted sample rate: %d", converted_sample_rate)
        logger.info("[STT-BACKEND] Converted channels: %d", converted_audio.shape[1])
        logger.info("[STT-BACKEND] Converted samples: %d", converted_audio.shape[0])
        logger.info("[STT] Duration: %.3f sec", wav_info.duration)
        logger.info("[STT-BACKEND] Converted RMS: %.10f", converted_rms)
        logger.info("[STT-BACKEND] Converted max amplitude: %.10f", converted_peak)
        logger.info("[STT] Original max amplitude: %.8f; RMS: %.8f", peak, rms)
        if not np.any(converted_audio != 0):
            Path(wav_path).unlink(missing_ok=True)
            logger.error("[STT-BACKEND] Converted audio contains only zero samples")
            raise InvalidAudioError(
                "The microphone recording contains no usable audio. Check microphone permission "
                "and input level, then try recording again."
            )
        return wav_path

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        content_type: str = "audio/wav",
    ) -> str:
        """Convert uploaded audio to mono 16 kHz WAV and transcribe on CUDA."""
        wav_path = self._prepare_wav(audio_bytes, filename, content_type)
        try:
            with self._inference_lock, self._torch.inference_mode():
                logger.info("[STT] Calling Parakeet...")
                output = self._model.transcribe([wav_path])
            first_result = output
            while isinstance(first_result, (list, tuple)) and first_result:
                first_result = first_result[0]
            logger.info(
                "[STT] Raw result type: %s.%s; first result type: %s.%s",
                type(output).__module__,
                type(output).__qualname__,
                type(first_result).__module__,
                type(first_result).__qualname__,
            )
            transcript = self._extract_transcription_text(output)
            if transcript is None:
                raise RuntimeError("Parakeet returned an unsupported or missing transcription result.")
            if not transcript:
                logger.warning("[STT] Parakeet returned an empty transcription.")
                return ""
            logger.info("[STT] Transcription completed (%d characters).", len(transcript))
            return transcript
        except Exception as error:
            logger.exception("[STT] Parakeet inference failed.")
            raise RuntimeError("Local Parakeet transcription failed.") from error
        finally:
            Path(wav_path).unlink(missing_ok=True)

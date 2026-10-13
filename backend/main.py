import argparse
import base64
import json
import logging
import os
import re
import inspect
import traceback
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
import redis
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from groq import Groq, GroqError
from pydantic import BaseModel
from qdrant_client.http.exceptions import ResponseHandlingException
from starlette.datastructures import UploadFile as StarletteUploadFile

from .agent import run_agent
from .entity_resolver import resolve_domain_entities
from .rag import KnowledgeBase
from .stt import InvalidAudioError, SpeechToTextService, STTTranscriptionError

from .tts import TextToSpeechError, async_text_to_speech



load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
logger = logging.getLogger(__name__)



def _get_redis_memory_ttl() -> int:
    raw_ttl = os.getenv("REDIS_MEMORY_TTL", "3600")
    try:
        ttl = int(raw_ttl)
    except ValueError as exc:
        raise ValueError("REDIS_MEMORY_TTL must be a positive integer.") from exc
    if ttl <= 0:
        raise ValueError("REDIS_MEMORY_TTL must be a positive integer.")
    return ttl


def _redis_session_key(session_id: str) -> str:
    return f"chat:session:{session_id.strip()}"


def _load_conversation_memory(session_id: str) -> list[dict[str, str]]:
    session_key = _redis_session_key(session_id)
    try:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            health_check_interval=30,
        )
        raw_value = client.get(session_key)
    except redis.RedisError:
        return []
    if not raw_value:
        return []

    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []

    cleaned: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role and content:
            cleaned.append({"role": role, "content": content})
    return cleaned[-10:]


def _save_conversation_memory(session_id: str, messages: list[dict[str, str]]) -> None:
    session_key = _redis_session_key(session_id)
    cleaned = [
        {"role": str(msg.get("role", "")).strip(), "content": str(msg.get("content", "")).strip()}
        for msg in messages
        if isinstance(msg, dict) and str(msg.get("role", "")).strip() and str(msg.get("content", "")).strip()
    ][-10:]
    try:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            health_check_interval=30,
        )
        client.set(session_key, json.dumps(cleaned, ensure_ascii=False), ex=_get_redis_memory_ttl())
    except redis.RedisError:
        return


def _extract_reference_entity(history: list[dict[str, str]]) -> str | None:
    context = " ".join(
        message.get("content", "")
        for message in history
        if isinstance(message, dict) and str(message.get("content", "")).strip()
    )
    if not context:
        return None

    patterns = [
        r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b",
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b",
        r"\b[A-Z][a-z][A-Za-z0-9&.-]*\b",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, context))

    for candidate in reversed(candidates):
        normalized = candidate.strip(".,!?;:\"'")
        lowered = normalized.lower()
        if lowered in {
            "ai",
            "i",
            "we",
            "you",
            "they",
            "he",
            "she",
            "it",
            "this",
            "that",
            "these",
            "those",
            "what",
            "who",
            "when",
            "where",
            "why",
            "how",
            "do",
            "does",
            "did",
            "is",
            "are",
            "was",
            "were",
            "there",
            "here",
            "please",
        }:
            continue
        if normalized:
            return normalized
    return None


def _rewrite_follow_up_question(current_question: str, history: list[dict[str, str]]) -> str:
    stripped_question = current_question.strip()
    if not stripped_question:
        return stripped_question
    if not re.search(r"\b(they|he|she|it|them|that|those|this|these)\b", stripped_question, flags=re.IGNORECASE):
        return stripped_question

    entity = _extract_reference_entity(history)
    if not entity:
        return stripped_question

    rewritten = re.sub(
        r"\b(?:that|those|this|these)\s+(?:company|companies|service|services|team|founder|person|product)\b",
        entity,
        stripped_question,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"\b(they|he|she|it|them|that|those|this|these)\b",
        entity,
        rewritten,
        flags=re.IGNORECASE,
    )
    return rewritten.strip() or stripped_question


def _format_safe_chat_traceback(error: Exception, *private_values: str) -> str:
    formatted_traceback = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    values_to_redact = [
        os.getenv(name, "")
        for name in ("GROQ_API_KEY", "QDRANT_API_KEY", "REDIS_URL")
    ]
    values_to_redact.extend(private_values)
    for value in values_to_redact:
        if value:
            formatted_traceback = formatted_traceback.replace(value, "[REDACTED]")
    return formatted_traceback
    


def _require_backend_config() -> tuple[str, str, str, int]:
    api_key = os.getenv("GROQ_API_KEY")
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is required.")
    if not qdrant_api_key:
        raise ValueError("QDRANT_API_KEY is not configured.")
    if not qdrant_url:
        raise ValueError("QDRANT_URL is not configured.")


    try:
        top_k = int(os.getenv("TOP_K", "5"))
    except ValueError as exc:
        raise ValueError("TOP_K must be a positive integer.") from exc
    if top_k < 1:
        raise ValueError("TOP_K must be a positive integer.")
    return api_key, qdrant_url, qdrant_api_key, top_k


@lru_cache(maxsize=1)
def get_backend() -> tuple[Groq, str, KnowledgeBase, int]:
    api_key, qdrant_url, qdrant_api_key, top_k = _require_backend_config()
    client = Groq(api_key=api_key, timeout=30.0, max_retries=0)
    knowledge_base = KnowledgeBase(qdrant_url, qdrant_api_key)
    try:
        knowledge_base.index_documents()
    except ConnectionError as error:
        raise RuntimeError(
            "Unable to connect to Qdrant Cloud. Please check QDRANT_URL and QDRANT_API_KEY."
        ) from error
    except ResponseHandlingException as error:
        if isinstance(error.source, (TimeoutError, OSError, httpx.TimeoutException)):
            raise RuntimeError(
                "Qdrant Cloud write timed out after retries. You can safely run indexing again."
            ) from error
        raise RuntimeError(
            "Unable to connect to Qdrant Cloud. Please check QDRANT_URL and QDRANT_API_KEY."
        ) from error
    except Exception as error:
        raise RuntimeError(
            "Could not initialize the Qdrant knowledge base. Check QDRANT_URL and QDRANT_API_KEY."
        ) from error
    return client, os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"), knowledge_base, top_k


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _get_redis_memory_ttl()
    logger.info(
    "[STT] Service loaded from: %s",
    inspect.getfile(SpeechToTextService),
)

    app.state.stt_service = SpeechToTextService()
    yield


app = FastAPI(title="FOT AI API", version="1.0.0", lifespan=lifespan)
# Build the list of allowed origins. We always ensure the Vercel front‑end URL is present.
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://fot-shabdham.vercel.app",
    ).split(",")
    if origin.strip()
]
# Defensive guard – make sure the Vercel origin is included even if an env var overrides the default.
vercel_origin = "https://fot-shabdham.vercel.app"
if vercel_origin not in allowed_origins:
    allowed_origins.append(vercel_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


async def _read_chat_payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    return payload


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
 


async def _read_stt_audio(
    request: Request,
    file: UploadFile | None = None,
) -> tuple[bytes, str, str]:
    content_type = request.headers.get("content-type", "")
    if file is None and "multipart/form-data" in content_type.lower():
        form = await request.form()
        field_names = list(form.keys())
        candidate = form.get("file")
        if isinstance(candidate, StarletteUploadFile):
            file = candidate
        else:
            logger.error(
                "[STT-BACKEND] ERROR: missing field 'file'; received fields: %s",
                field_names,
            )
            raise HTTPException(
                status_code=400,
                detail="STT audio upload field 'file' is missing.",
            )

    if file is not None:
        audio_bytes = await file.read()
        filename = file.filename or "audio.wav"
        file_content_type = file.content_type or "audio/wav"
        logger.info("[STT-BACKEND] Filename: %s", filename)
        logger.info("[STT-BACKEND] Content-Type: %s", file_content_type)
        logger.info(
            "[STT-BACKEND] Raw bytes: %d (request Content-Length: %s)",
            len(audio_bytes),
            request.headers.get("content-length", "unknown"),
        )
        if not audio_bytes:
            logger.error("[STT-BACKEND] ERROR: uploaded audio file is empty")
            raise HTTPException(status_code=400, detail="STT audio upload is empty")
        return audio_bytes, filename, file_content_type

    if content_type.startswith("application/json"):
        payload = await _read_chat_payload(request)
        audio_value = payload.get("audio") or payload.get("audio_data") or payload.get("file")
        if isinstance(audio_value, str):
            encoded = audio_value.split(",", 1)[-1] if "," in audio_value else audio_value
            try:
                audio_bytes = base64.b64decode(encoded, validate=False)
            except ValueError as exc:
                logger.exception("[STT] Invalid base64 audio payload.")
                raise HTTPException(status_code=400, detail="Invalid base64 audio payload.") from exc
            if not audio_bytes:
                logger.error("[STT-BACKEND] ERROR: uploaded audio payload is empty")
                raise HTTPException(status_code=400, detail="STT audio upload is empty")
            payload_content_type = payload.get("content_type", "audio/wav")
            logger.info("[STT-BACKEND] Filename: %s", payload.get("filename", "audio.wav"))
            logger.info("[STT-BACKEND] Content-Type: %s", payload_content_type)
            logger.info(
                "[STT-BACKEND] Raw bytes: %d (request Content-Length: %s)",
                len(audio_bytes),
                request.headers.get("content-length", "unknown"),
            )
            return (
                audio_bytes,
                payload.get("filename", "audio.wav"),
                payload_content_type,
            )
        if isinstance(audio_value, (bytes, bytearray)):
            if not audio_value:
                logger.error("[STT-BACKEND] ERROR: uploaded audio payload is empty")
                raise HTTPException(status_code=400, detail="STT audio upload is empty")
            payload_content_type = payload.get("content_type", "audio/wav")
            logger.info("[STT-BACKEND] Filename: %s", payload.get("filename", "audio.wav"))
            logger.info("[STT-BACKEND] Content-Type: %s", payload_content_type)
            logger.info(
                "[STT-BACKEND] Raw bytes: %d (request Content-Length: %s)",
                len(audio_value),
                request.headers.get("content-length", "unknown"),
            )
            return (
                bytes(audio_value),
                payload.get("filename", "audio.wav"),
                payload_content_type,
            )
        logger.error(
            "[STT-BACKEND] ERROR: missing audio field; expected one of 'audio', 'audio_data', or 'file'; received fields: %s",
            list(payload.keys()),
        )
        raise HTTPException(status_code=400, detail="No audio payload was provided.")

    body = await request.body()
    if not body:
        logger.error("[STT-BACKEND] ERROR: uploaded audio body is empty")
        raise HTTPException(status_code=400, detail="No audio body was provided.")
    logger.info("[STT-BACKEND] Filename: audio.bin")
    logger.info("[STT-BACKEND] Content-Type: %s", content_type or "application/octet-stream")
    logger.info(
        "[STT-BACKEND] Raw bytes: %d (request Content-Length: %s)",
        len(body),
        request.headers.get("content-length", "unknown"),
    )
    return (
        body,
        "audio.bin",
        content_type
        or "application/octet-stream",
    )


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest) -> dict[str, str]:
    message = request.message
    session_id = request.session_id.strip()
    if not message.strip():
        raise HTTPException(status_code=400, detail="Message is required.")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")

    stage = "backend initialization"
    try:
        client, model, knowledge_base, top_k = get_backend()
        stage = "conversation memory lookup"
        memory_history = _load_conversation_memory(session_id)
        stage = "query preparation"
        resolution = resolve_domain_entities(message)
        rewritten_question = _rewrite_follow_up_question(
            resolution.corrected_transcript,
            memory_history,
        )
        messages_for_agent = memory_history + [{"role": "user", "content": rewritten_question}]
        stage = "agent, LLM, or RAG execution"
        answer = run_agent(
            client,
            model,
            messages_for_agent,
            knowledge_base=knowledge_base,
            top_k=top_k,
        )
        stage = "conversation memory save"
        updated_history = memory_history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ]
        _save_conversation_memory(session_id, updated_history)
    except (RuntimeError, ValueError) as error:
        logger.error(
            "[CHAT] Request failed during %s with %s. Redacted traceback follows:\n%s",
            stage,
            type(error).__name__,
            _format_safe_chat_traceback(error, message, session_id),
        )
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GroqError as error:
        logger.error(
            "[CHAT] Groq request failed with %s (status=%s).",
            type(error).__name__,
            getattr(error, "status_code", "unknown"),
        )
        raise HTTPException(status_code=502, detail=f"Groq request failed: {error}") from error

    return {"response": answer}


# Explicit OPTIONS handler for CORS preflight on the chat endpoint
@app.options("/api/chat")
async def chat_options() -> Response:
    # FastAPI's CORSMiddleware already adds the appropriate CORS headers.
    # Returning an empty 200 response satisfies the browser preflight.
    return Response(status_code=200)

@app.post("/api/stt")
async def stt_endpoint(request: Request, file: UploadFile | None = File(default=None)) -> dict[str, str]:
    logger.info("[STT-BACKEND] Request received")
    logger.info("[STT-BACKEND] Request Content-Type: %s", request.headers.get("content-type", "unknown"))
    logger.info(
        "[STT-BACKEND] Request Content-Length: %s bytes",
        request.headers.get("content-length", "unknown"),
    )
    try:
        audio_bytes, filename, content_type = await _read_stt_audio(request, file)
        if not audio_bytes:
            logger.error("[STT-BACKEND] ERROR: uploaded audio file is empty")
            raise InvalidAudioError("No audio data was uploaded.")
        transcription, _ = await request.app.state.stt_service.transcribe(
            audio_bytes,
            filename,
            content_type,
        )
    except HTTPException:
        raise
    except InvalidAudioError as error:
        logger.error("[STT-BACKEND] Audio request rejected: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except STTTranscriptionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"text": transcription}


@app.post("/api/tts")
async def tts_endpoint(request: Request) -> Any:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await _read_chat_payload(request)
        text = _coerce_text(payload.get("text") or payload.get("message"))
    else:
        form = await request.form() if any(marker in content_type for marker in ("application/x-www-form-urlencoded", "multipart/form-data")) else {}
        text = _coerce_text(form.get("text") or form.get("message"))

    if not text:
        raise HTTPException(status_code=400, detail="Text is required for TTS.")

    try:
        audio_bytes, content_type = await async_text_to_speech(text)
    except TextToSpeechError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    if request.headers.get("accept", "").lower().find("application/json") != -1 or request.query_params.get("format") == "json":
        return JSONResponse(
            {"audio_base64": base64.b64encode(audio_bytes).decode("utf-8"), "content_type": content_type}
        )
    return Response(content=audio_bytes, media_type=content_type)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FOT AI assistant.")
    parser.add_argument("--api", action="store_true", help="run the FastAPI server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.api:
        import uvicorn

        uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=False)
        return

    print("=" * 60)
    print("🤖 Agentic AI")
    print("=" * 60)
    try:
        client, model, knowledge_base, top_k = get_backend()
    except Exception as error:
        print(f"Backend initialization failed: {error}")
        raise SystemExit(1) from error

    print("Model:", model)
    print("Available tools:")
    print("  🧮 Calculator")
    print("  🕒 Current date and time")
    print("  📚 Search indexed documents")
    print()
    print("Type 'exit' or 'quit' to stop.")
    print("Type 'clear' to clear the conversation.")
    print("=" * 60)

    messages: list[dict[str, str]] = []
    while True:
        try:
            prompt = input("\n👤 You: ").strip()
            if not prompt:
                continue
            if prompt.lower() in {"exit", "quit"}:
                print("\n👋 Goodbye!")
                break
            if prompt.lower() == "clear":
                messages.clear()
                print("🧹 Conversation cleared.")
                continue

            messages.append({"role": "user", "content": prompt})
            print("\n🤖 Agent: Thinking...")
            answer = run_agent(
                client,
                model,
                messages,
                knowledge_base=knowledge_base,
                top_k=top_k,
            )
            print("\n🤖 Agent:", answer)
            messages.append({"role": "assistant", "content": answer})
        except GroqError as error:
            print("\n❌ Groq request failed:")
            print(error)
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as error:
            print("\n❌ Error:")
            print(error)


if __name__ == "__main__":
    main()
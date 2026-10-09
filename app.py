import hashlib
import os
import traceback
from typing import TypedDict

import httpx
import streamlit as st
from dotenv import load_dotenv
from groq import APIConnectionError, APIStatusError, Groq, RateLimitError
from qdrant_client.http.exceptions import ResponseHandlingException

from agent import run_agent
from rag import KnowledgeBase
from speech import ParakeetSTT
from tts import TextToSpeechError, text_to_speech


class ChatMessage(TypedDict, total=False):
    role: str
    content: str
    source: str


load_dotenv()
st.set_page_config(page_title="FOT AI Assistant", page_icon="🤖")


@st.cache_resource(show_spinner=False)
def initialize_assistant() -> tuple[Groq, str, KnowledgeBase, int]:
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
    except ValueError as error:
        raise ValueError("TOP_K must be a positive integer.") from error
    if top_k < 1:
        raise ValueError("TOP_K must be a positive integer.")

    client = Groq(api_key=api_key, timeout=30.0, max_retries=0)
    knowledge_base = KnowledgeBase(qdrant_url, qdrant_api_key)
    return client, os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"), knowledge_base, top_k


@st.cache_resource(show_spinner=False)
def initialize_stt() -> ParakeetSTT:
    return ParakeetSTT()


def render_message(message: ChatMessage) -> None:
    with st.chat_message(message["role"]):
        if message.get("source") == "voice":
            st.caption("🎤 Voice transcription")
        elif message["role"] == "user":
            st.caption("⌨️ Typed message")
        st.markdown(message["content"])


def show_service_error(operation: str, error: Exception, *, voice: bool = False) -> None:
    error_text = str(error).casefold()
    if isinstance(error, RateLimitError) or "quota" in error_text:
        message = (
            "⚠️ Voice service quota exceeded. Please try again later."
            if voice
            else "⚠️ AI service quota exceeded. Please try again later."
        )
        st.warning(message)
    elif isinstance(error, APIConnectionError) or any(
        marker in error_text for marker in ("network", "connection", "timed out")
    ):
        st.warning(f"⚠️ {operation} could not reach its service. Check your connection and try again.")
    elif isinstance(error, APIStatusError):
        provider_detail = ""
        body = error.body
        if isinstance(body, dict):
            error_body = body.get("error", body)
            if isinstance(error_body, dict):
                detail = error_body.get("message") or error_body.get("detail")
            else:
                detail = error_body
            if isinstance(detail, str) and detail.strip():
                provider_detail = f" Details: {detail.strip()[:300]}"
        st.error(
            f"{operation} was rejected by its service "
            f"(HTTP {error.status_code}). Please try again later.{provider_detail}"
        )
    else:
        st.error(f"{operation} failed ({type(error).__name__}). Please try again.")


def submit_message(
    text: str,
    source: str,
    client: Groq,
    model: str,
    knowledge_base: KnowledgeBase,
    top_k: int,
) -> None:
    text = text.strip()
    if not text:
        st.warning("No speech was recognized. Please try again.")
        return

    user_message: ChatMessage = {
        "role": "user",
        "content": text,
        "source": source,
    }
    st.session_state.messages.append(user_message)
    render_message(user_message)

    try:
        agent_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in st.session_state.messages
        ]
        with st.spinner("⏳ Processing..."):
            answer = run_agent(
                client,
                model,
                agent_messages,
                knowledge_base=knowledge_base,
                top_k=top_k,
            )
    except Exception as error:
        show_service_error("Agent/RAG request", error)
        return

    assistant_message: ChatMessage = {"role": "assistant", "content": answer}
    st.session_state.messages.append(assistant_message)
    with st.chat_message("assistant"):
        st.markdown(answer)
        try:
            with st.spinner("🔊 Speaking..."):
                tts_result = text_to_speech(answer)
            print(f"TTS function return type: {type(tts_result).__name__}", flush=True)
            if (
                not isinstance(tts_result, tuple)
                or len(tts_result) != 2
                or not isinstance(tts_result[0], bytes)
                or not isinstance(tts_result[1], str)
            ):
                raise TextToSpeechError(
                    "TTS returned an invalid result. Expected (audio_bytes, mime_type); "
                    "restart the Streamlit app to load the current TTS implementation."
                )
            audio, audio_format = tts_result
            st.audio(audio, format=audio_format, autoplay=True)
        except TextToSpeechError:
            st.warning("⚠️ Voice playback unavailable. The text answer is still available.")
        except Exception as error:
            print("TTS UI ERROR:", repr(error), flush=True)
            traceback.print_exc()
            show_service_error("Text-to-speech", error, voice=True)


st.title("🤖 FOT AI Assistant")
st.caption("Ask a question by typing or recording one message.")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "processed_audio" not in st.session_state:
    st.session_state.processed_audio = None

try:
    groq_client, agent_model, knowledge_base, result_limit = initialize_assistant()
except Exception as error:
    st.error(f"Assistant initialization failed ({type(error).__name__}): {error}")
    st.stop()

with st.sidebar:
    st.subheader("Knowledge base")
    st.caption("Chat uses the documents already indexed in Qdrant.")
    if st.button("Index / refresh documents", use_container_width=True):
        try:
            with st.status("Indexing documents in Qdrant...", expanded=True) as index_status:
                indexed_chunks = knowledge_base.index_documents(
                    progress_callback=index_status.write
                )
                index_status.update(
                    label=f"Indexing completed: {indexed_chunks} chunks.",
                    state="complete",
                )
        except ConnectionError as error:
            st.error(str(error))
        except ResponseHandlingException as error:
            if isinstance(error.source, (TimeoutError, httpx.TimeoutException)):
                st.error(
                    "Qdrant Cloud write timed out after retries. Some batches may have uploaded; "
                    "indexing is safe to repeat. Please try again when Qdrant is responsive."
                )
            else:
                st.error(
                    "Unable to connect to Qdrant Cloud. Please check QDRANT_URL and QDRANT_API_KEY."
                )
        except Exception as error:
            st.error(
                f"Document indexing or retrieval verification failed "
                f"({type(error).__name__}): {error}"
            )
        else:
            st.success(f"Indexed {indexed_chunks} document chunk(s).")

for chat_message in st.session_state.messages:
    render_message(chat_message)

text_column, microphone_column = st.columns([8, 2], vertical_alignment="bottom")
with text_column:
    with st.form("text_message_form", clear_on_submit=True):
        input_column, send_column = st.columns([7, 1], vertical_alignment="bottom")
        with input_column:
            typed_message = st.text_input("Message", label_visibility="collapsed", placeholder="Type a message...")
        with send_column:
            send_clicked = st.form_submit_button("Send", use_container_width=True)

with microphone_column:
    recorded_audio = st.audio_input("🎤 Click to speak", key="voice_input")

if send_clicked and typed_message.strip():
    submit_message(
        typed_message,
        "text",
        groq_client,
        agent_model,
        knowledge_base,
        result_limit,
    )
elif send_clicked:
    st.warning("Please enter a message before sending.")

if recorded_audio is not None:
    audio_bytes = recorded_audio.getvalue()
    audio_fingerprint = hashlib.sha256(audio_bytes).hexdigest()
    if audio_fingerprint != st.session_state.processed_audio:
        st.session_state.processed_audio = audio_fingerprint
        if not audio_bytes:
            st.error(
                "Microphone unavailable or no audio was recorded. "
                "Check microphone permission and try again."
            )
        else:
            try:
                with st.spinner("⏳ Processing..."):
                    recognized_text = initialize_stt().transcribe(audio_bytes)
            except Exception as error:
                show_service_error("Speech-to-text", error, voice=True)
            else:
                if recognized_text:
                    submit_message(
                        recognized_text,
                        "voice",
                        groq_client,
                        agent_model,
                        knowledge_base,
                        result_limit,
                    )
                else:
                    st.warning("No speech was recognized. Please try recording again.")

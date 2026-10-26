import httpx
import time
import json

def test_pipeline(query):
    print(f"=== Testing Query: {query} ===")
    client = httpx.Client(timeout=60.0)
    t_start = time.perf_counter()
    
    # 1. Chat request
    t_chat_start = time.perf_counter()
    chat_resp = client.post('http://127.0.0.1:8000/api/chat', json={'message': query, 'session_id': 'test-session'})
    t_chat_end = time.perf_counter()
    chat_data = chat_resp.json()
    response_text = chat_data.get('response', '')
    word_count = len(response_text.split())
    char_count = len(response_text)
    chat_time_ms = (t_chat_end - t_chat_start) * 1000
    print(f"Chat response ({word_count} words, {char_count} chars) in {chat_time_ms:.1f}ms")
    print(f"Text snippet: {response_text[:120]}...")

    # 2. TTS request
    t_tts_start = time.perf_counter()
    tts_resp = client.post('http://127.0.0.1:8000/api/tts', json={'text': response_text})
    t_tts_end = time.perf_counter()
    tts_time_ms = (t_tts_end - t_tts_start) * 1000
    audio_bytes = len(tts_resp.content)
    ct = tts_resp.headers.get("content-type")
    print(f"TTS response ({audio_bytes} bytes, {ct}) in {tts_time_ms:.1f}ms")
    total_time_ms = (t_tts_end - t_start) * 1000
    print(f"Total time to receive audio: {total_time_ms:.1f}ms\n")

if __name__ == "__main__":
    test_pipeline("Thank you")
    test_pipeline("What is GenLab and what services does it offer?")

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import io
import json
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

def run_e2e_benchmark(query: str):
    print(f"\n========================================================")
    print(f"BENCHMARKING QUERY: \"{query}\"")
    print(f"========================================================")
    
    t_req_start = time.perf_counter()
    client = httpx.Client(timeout=60.0)
    
    # 1. Initiate Streaming Chat Request (as frontend now does)
    t_chat_start = time.perf_counter()
    req_payload = {
        "message": query,
        "session_id": f"benchmark-{int(time.time())}",
        "stream": True,
    }
    
    sentences = []
    first_token_time = None
    first_sentence_time = None
    first_tts_audio_ready = None
    full_text_time = None
    full_response_text = ""
    sentence_tts_timings = []
    
    with client.stream(
        "POST",
        "http://127.0.0.1:8000/api/chat",
        json=req_payload,
        headers={"Accept": "text/event-stream"},
    ) as response:
        connect_time = (time.perf_counter() - t_chat_start) * 1000
        print(f"[*] SSE Connection established in {connect_time:.1f}ms (HTTP {response.status_code})")
        
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            evt_type = data.get("type")
            
            if evt_type == "sentence":
                s_text = data["text"]
                s_idx = data["index"]
                t_s_ready = (time.perf_counter() - t_req_start) * 1000
                sentences.append((s_idx, s_text, t_s_ready))
                
                if first_sentence_time is None:
                    first_sentence_time = t_s_ready
                    if data.get("first_token_ms"):
                        first_token_time = data["first_token_ms"]
                    print(f"[*] [LLM First-Token] {first_token_time or first_sentence_time:.1f}ms")
                    print(f"[*] [Sentence 0 Ready] at +{first_sentence_time:.1f}ms: \"{s_text}\"")
                    
                    # IMMEDIATELY fire TTS request for Sentence 0 (as frontend does)
                    t_tts_sent = time.perf_counter()
                    tts_resp = client.post("http://127.0.0.1:8000/api/tts", json={"text": s_text})
                    t_tts_done = time.perf_counter()
                    tts_duration = (t_tts_done - t_tts_sent) * 1000
                    first_tts_audio_ready = (t_tts_done - t_req_start) * 1000
                    sentence_tts_timings.append((s_idx, tts_duration, len(tts_resp.content)))
                    print(f"[*] [Sentence 0 TTS Ready] Duration: {tts_duration:.1f}ms ({len(tts_resp.content)} bytes)")
                    print(f"[*] >>> TIME TO FIRST PLAYABLE AUDIO: {first_tts_audio_ready:.1f}ms <<<")
                else:
                    print(f"[*] [Sentence {s_idx} Ready] at +{t_s_ready:.1f}ms: \"{s_text}\"")
            
            elif evt_type == "done":
                full_text_time = (time.perf_counter() - t_req_start) * 1000
                full_response_text = data.get("response", "")
                print(f"[*] [Full Text Ready] at +{full_text_time:.1f}ms ({len(full_response_text.split())} words, {len(full_response_text)} chars)")

    print(f"\n--- TIMING SUMMARY FOR: \"{query}\" ---")
    print(f"1. LLM First-Token Time:        {first_token_time or 0.0:.1f} ms")
    print(f"2. Time until First Sentence:   {first_sentence_time or 0.0:.1f} ms")
    print(f"3. Time until Full Text Ready:  {full_text_time or 0.0:.1f} ms")
    if sentence_tts_timings:
        print(f"4. Sentence 0 TTS Request Time: {sentence_tts_timings[0][1]:.1f} ms ({sentence_tts_timings[0][2]} bytes)")
    print(f"5. Time to First Playable Audio: {first_tts_audio_ready or 0.0:.1f} ms")
    print(f"6. Full Response Word Count:    {len(full_response_text.split())} words")
    print(f"Response: {full_response_text}\n")
    return {
        "query": query,
        "first_token_ms": first_token_time,
        "first_sentence_ms": first_sentence_time,
        "full_text_ms": full_text_time,
        "tts_duration_ms": sentence_tts_timings[0][1] if sentence_tts_timings else None,
        "first_audio_ms": first_tts_audio_ready,
        "words": len(full_response_text.split()),
    }

if __name__ == "__main__":
    print("[*] Warming up backend...")
    httpx.post("http://127.0.0.1:8000/api/chat", json={"message": "ping", "session_id": "warmup"}, timeout=30.0)
    print("[*] Warmup complete. Running benchmarks...\n")

    r1 = run_e2e_benchmark("Thank you")
    r2 = run_e2e_benchmark("What is GenLab and what services does it offer?")

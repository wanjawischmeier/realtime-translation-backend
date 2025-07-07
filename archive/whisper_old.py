from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Set, Tuple
import argparse
import asyncio
import logging
import re

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description="WhisperLiveKit + LibreTranslate FastAPI server")
parser.add_argument("--model", default="small", help="Whisper model (tiny, small, medium, large, etc.)")
parser.add_argument("--diarization", action="store_true", help="Enable speaker diarization")
parser.add_argument("--lan", default="de", help="Language for Whisper model (e.g., en, de)")
parser.add_argument("--host", default="0.0.0.0", help="Host to bind FastAPI server")
parser.add_argument("--port", type=int, default=8000, help="Port to bind FastAPI server")
parser.add_argument("--libretranslate-url", default="http://127.0.0.1:5000", help="LibreTranslate API URL")
parser.add_argument("--source-lang", default="en", help="Source language for translation")
parser.add_argument("--target-lang", default="de", help="Target language for translation")
parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds for audio inactivity")
args, unknown = parser.parse_known_args()

# --- Logging ---
logging.getLogger("whisperlivekit.audio_processor").setLevel(logging.WARNING)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

transcription_engine = None
server_ready = False
lt = None

# --- AsyncLibreTranslate Wrapper ---
from libretranslatepy import LibreTranslateAPI

class AsyncLibreTranslate:
    def __init__(self, url="http://127.0.0.1:5000"):
        self.lt = LibreTranslateAPI(url)

    async def translate(self, text, source="en", target="de"):
        return await asyncio.to_thread(self.lt.translate, text, source, target)

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready, lt
    print(f"[INFO] Loading Whisper model: {args.model}, diarization={args.diarization}, language={args.lan}")
    transcription_engine = TranscriptionEngine(model=args.model, diarization=args.diarization, lan=args.lan)
    print(f"[INFO] Initializing LibreTranslate at {args.libretranslate_url}")
    lt = AsyncLibreTranslate(args.libretranslate_url)
    server_ready = True
    yield
    server_ready = False

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, restrict this!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get():
    return HTMLResponse(get_web_interface_html())

@app.get("/health")
async def health():
    if server_ready:
        return JSONResponse({"status": "ok"}, status_code=200)
    else:
        return JSONResponse({"status": "not ready"}, status_code=503)

def is_complete_sentence(text):
    # Returns True if text ends with sentence-ending punctuation
    return bool(re.search(r'[.!?]\s*$', text.strip()))

async def handle_websocket_results(websocket: WebSocket, results_generator):
    """
    Only send new, finalized, and non-overlapping lines to the client,
    and translate each line before sending.
    """
    # Map of (beg, end, speaker) -> text
    translated_segments = {}
    try:
        async for response in results_generator:
            if "lines" in response and isinstance(response["lines"], list):
                translated_lines = []
                for line in response["lines"]:
                    if not line["text"].strip():
                        print(f"[DEBUG] Skipping empty line: {line}")
                        continue
                    seg_key = (line.get("beg"), line.get("end"), line.get("speaker"))
                    prev_text = translated_segments.get(seg_key, "")
                    # Only translate if this is a new, longer, and complete sentence
                    if len(line["text"]) > len(prev_text) and is_complete_sentence(line["text"]):
                        print(f"[DEBUG] Sending to translation: {line}")
                        translated_text = await lt.translate(
                            line["text"],
                            source=args.source_lang,
                            target=args.target_lang
                        )
                        print(f"[DEBUG] Translated: '{line['text']}' -> '{translated_text}'")
                        translated_lines.append({
                            "speaker": line["speaker"],
                            "beg": line["beg"],
                            "end": line["end"],
                            "text": translated_text
                        })
                        translated_segments[seg_key] = line["text"]
                if translated_lines:
                    print(f"[DEBUG] Sending translated lines to client: {translated_lines}")
                    await websocket.send_json({
                        "status": "active_transcription",
                        "lines": translated_lines
                    })
                else:
                    print("[DEBUG] No new lines to translate/send in this response.")
        await websocket.send_json({"type": "ready_to_stop"})
    except WebSocketDisconnect:
        print("WebSocket disconnected during results handling.")
    except Exception as e:
        print(f"[ERROR] Exception in handle_websocket_results: {e}")

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine
    audio_processor = AudioProcessor(transcription_engine=transcription_engine)
    results_generator = await audio_processor.create_tasks()
    results_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))
    await websocket.accept()
    try:
        while True:
            try:
                # Wait for audio data with timeout
                message = await asyncio.wait_for(websocket.receive_bytes(), timeout=args.timeout)
                await audio_processor.process_audio(message)
            except asyncio.TimeoutError:
                print(f"[INFO] Closing connection due to {args.timeout}s of inactivity.")
                await websocket.close(code=1000)
                break
    except WebSocketDisconnect:
        print(f"Client disconnected: {websocket.client}")
    finally:
        results_task.cancel()
        try:
            await results_task
        except asyncio.CancelledError:
            pass
        if hasattr(audio_processor, "close"):
            await audio_processor.close()
        if hasattr(results_generator, "aclose"):
            await results_generator.aclose()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=args.host,
        port=args.port,
        reload=True
    )

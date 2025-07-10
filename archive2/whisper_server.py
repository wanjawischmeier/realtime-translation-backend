from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sentence_buffer import SentenceBuffer
from contextlib import asynccontextmanager
from transcription_manager import TranscriptManager
from translation_worker import TranslationWorker
from connection_manager import ConnectionManager
import subprocess
import argparse
import asyncio
import logging
import sys

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
translation_worker = None
server_ready = False
lt = None
connection_manager = ConnectionManager()
transcript_manager = TranscriptManager()

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready, lt, libretranslate_proc
    print(f"[INFO] Loading Whisper model: {args.model}, diarization={args.diarization}, language={args.lan}")
    transcription_engine = TranscriptionEngine(model=args.model, diarization=args.diarization, lan=args.lan, buffer_trimming="sentence")
    print(f"[INFO] Starting LibreTranslate server: {args.libretranslate_url}")
    # Start LibreTranslate as a subprocess
    libretranslate_proc = subprocess.Popen(
        [sys.executable, "-m", "libretranslate", "--load-only", "en,de"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    print(f"[INFO] LibreTranslate server started with PID {libretranslate_proc.pid}")
    server_ready = True
    try:
        yield
    finally:
        server_ready = False
        print("[INFO] Shutting down LibreTranslate server...")
        libretranslate_proc.terminate()
        libretranslate_proc.wait()
        print("[INFO] LibreTranslate server stopped.")

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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)

    if translation_worker != None:
        # Send existing transcript
        await websocket.send_json({"type": "translation", "data": translation_worker.translated_sentences})

    try:
        while True:
            await asyncio.sleep(60)  # Just keep the connection alive
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)

async def handle_websocket_results(websocket: WebSocket, results_generator, sentence_buffer):
    async for response in results_generator:
        await websocket.send_json(response)
        """
        # Check for new complete sentences
        if "lines" in response and isinstance(response["lines"], list):
            sentence_buffer.process(response["lines"])
        """
        # Broadcast ASR result to all clients
        transcript_manager.update_from_asr_buffer(response)
        
    await websocket.send_json({"type": "ready_to_stop"})

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine, translation_worker

    audio_processor = AudioProcessor(transcription_engine=transcription_engine)    
    results_generator = await audio_processor.create_tasks()
    sentence_buffer = SentenceBuffer()
    loop = asyncio.get_event_loop()
    translation_worker = TranslationWorker(sentence_buffer, connection_manager, loop, source_lang="de", target_lang="en")
    translation_worker.start()

    results_task = asyncio.create_task(
        handle_websocket_results(websocket, results_generator, sentence_buffer)
    )
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_bytes()
            await audio_processor.process_audio(message)
    except WebSocketDisconnect:
        translation_worker.stop()
        results_task.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=args.host,
        port=args.port,
        reload=True
    )

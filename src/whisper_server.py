from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from transcription_manager import TranscriptionManager
from translation_worker import TranslationWorker
from connection_manager import ConnectionManager
import subprocess
import argparse
import asyncio
import logging

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description="WhisperLiveKit + LibreTranslate FastAPI server")
parser.add_argument("--model", default="small", help="Whisper model (tiny, small, medium, large, etc.)")
parser.add_argument("--diarization", action="store_true", help="Enable speaker diarization")
parser.add_argument("--host", default="0.0.0.0", help="Host to bind FastAPI server")
parser.add_argument("--port", type=int, default=8000, help="Port to bind FastAPI server")
parser.add_argument("--libretranslate-url", default="http://127.0.0.1", help="LibreTranslate API URL")
parser.add_argument("--libretranslate-port", type=int, default=5000, help="Port to bind LibreTranslate server")
parser.add_argument("--source-lang", default="en", help="Source language for whisper model and translation")
parser.add_argument("--target-lang", default="de", help="Target language for translation")
parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds for audio inactivity")
args, unknown = parser.parse_known_args()

# --- Logging ---
logging.getLogger("whisperlivekit.audio_processor").setLevel(logging.WARNING)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

connection_manager = ConnectionManager()
transcription_manager = None
transcription_engine = None
server_ready = False
lt = None

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready, lt
    print(f"[INFO] Loading Whisper model: {args.model}, diarization={args.diarization}, language={args.source_lang}")
    transcription_engine = TranscriptionEngine(model=args.model, diarization=args.diarization, lan=args.source_lang) # buffer_trimming="sentence"

    print(f"[INFO] Starting LibreTranslate server: {args.libretranslate_url}:{args.libretranslate_port}")
    # Start LibreTranslate as a subprocess
    libretranslate_proc = subprocess.Popen(
        [
            "poetry", "run", "libretranslate",
            "--host", args.libretranslate_url,
            "--port", str(args.libretranslate_port),
            "--load-only", "en,de"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    print(f"[INFO] LibreTranslate server started with PID {libretranslate_proc.pid}")

    server_ready = True
    try:
        yield
    finally:
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
    
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)

    try:
        while True:
            await asyncio.sleep(60)  # Just keep the connection alive
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)

async def handle_websocket_results(websocket: WebSocket, results_generator):
    async for response in results_generator:
        # print(response)
        transcription_manager.submit_chunk(response)
        await websocket.send_json(response)
        
    await websocket.send_json({"type": "ready_to_stop"})

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine, transcription_manager

    transcription_manager = TranscriptionManager(args.source_lang)
    translation_worker = TranslationWorker(
        transcription_manager, args.source_lang, [args.target_lang],    # TODO: implement multiple target langs
        lt_url=args.libretranslate_url, lt_port=args.libretranslate_port,
        poll_interval=1
    )
    translation_worker.start()

    audio_processor = AudioProcessor(transcription_engine=transcription_engine)
    results_generator = await audio_processor.create_tasks()
    results_task = asyncio.create_task(
        handle_websocket_results(websocket, results_generator)
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
        port=args.port
    )

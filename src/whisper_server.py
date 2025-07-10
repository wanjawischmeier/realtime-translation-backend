from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from transcription_manager import TranscriptionManager
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

transcription_manager = None
transcription_engine = None
server_ready = False
lt = None

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready, lt
    print(f"[INFO] Loading Whisper model: {args.model}, diarization={args.diarization}, language={args.lan}")
    transcription_engine = TranscriptionEngine(model=args.model, diarization=args.diarization, lan=args.lan) # buffer_trimming="sentence"
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

async def handle_websocket_results(websocket: WebSocket, results_generator):
    async for response in results_generator:
        # print(response)
        ws_response = websocket.send_json(response)
        # transcription_manager.process_chunk(response)
        await ws_response
        
    await websocket.send_json({"type": "ready_to_stop"})

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine, transcription_manager

    transcription_manager = TranscriptionManager()

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
        results_task.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=args.host,
        port=args.port,
        reload=True
    )

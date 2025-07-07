from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.sentence_buffer import SentenceBuffer
from src.translation_worker import translation_worker
import argparse
import asyncio
import logging

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

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready, lt
    print(f"[INFO] Loading Whisper model: {args.model}, diarization={args.diarization}, language={args.lan}")
    transcription_engine = TranscriptionEngine(model=args.model, diarization=args.diarization, lan=args.lan)
    print(f"[INFO] Initializing LibreTranslate at {args.libretranslate_url}")
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

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine, lt
    audio_processor = AudioProcessor(transcription_engine=transcription_engine)
    results_generator = await audio_processor.create_tasks()
    await websocket.accept()
    sentence_buffer = SentenceBuffer()
    translation_task = asyncio.create_task(
        translation_worker(sentence_buffer, websocket, lt, args.source_lang, args.target_lang)
    )

    # --- Audio receiving task ---
    async def audio_receiver():
        try:
            while True:
                message = await asyncio.wait_for(websocket.receive_bytes(), timeout=args.timeout)
                await audio_processor.process_audio(message)
        except asyncio.TimeoutError:
            print(f"[INFO] Closing connection due to {args.timeout}s of inactivity.")
            # Finalize any remaining lines before closing
            sentence_buffer.finalize_all()
            await websocket.close(code=1000)
        except WebSocketDisconnect:
            print(f"Client disconnected: {websocket.client}")
            sentence_buffer.finalize_all()
        finally:
            # Always close processor on exit
            if hasattr(audio_processor, "close"):
                await audio_processor.close()

    # --- Results processing task ---
    async def results_consumer():
        try:
            async for response in results_generator:
                if "lines" in response and isinstance(response["lines"], list):
                    sentence_buffer.add_lines(response["lines"])
        except Exception as e:
            print(f"[ERROR] Exception in results_consumer: {e}")
        finally:
            if hasattr(results_generator, "aclose"):
                await results_generator.aclose()

    audio_task = asyncio.create_task(audio_receiver())
    results_task = asyncio.create_task(results_consumer())

    try:
        await asyncio.gather(audio_task, results_task)
    finally:
        translation_task.cancel()
        results_task.cancel()
        audio_task.cancel()
        # Finalize any remaining lines on total exit
        sentence_buffer.finalize_all()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=args.host,
        port=args.port,
        reload=True
    )

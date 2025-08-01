import argparse
import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html

from connection_manager import ConnectionManager
from transcription_manager import TranscriptionManager
from translation_worker import TranslationWorker, RoomManager

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
global transcr_manager
room_manager = None
conn_manager: ConnectionManager = None
transcr_manager: TranscriptionManager = None
# --- Has to stay ---
transcription_engine = None
server_ready = False

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready
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


@app.websocket("/room")
async def get_room(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
                await asyncio.sleep(1)  # Just keep the connection alive TODO: check if neccessary
    except WebSocketDisconnect:
        logging.info(f'Client x disconnected')


@app.websocket("/room/{room_id}/{role}/{source_lang}/{target_lang}/{password}")
async def connect_to_room(websocket: WebSocket, room_id: str, role: str, source_lang: str, target_lang: str, password: str):
    global conn_manager

    await websocket.accept()

    role = 'client'
    if not role or not (role == 'host' or role == 'client'):
        await websocket.close(code=1003, reason='No desired role found in headers')
    
    if role == 'host':
        if not password or password != 'letmein': # TODO: check password
            await websocket.close(code=1003, reason='No desired role found in headers')
            return
        
        source_lang = 'de'
        if not source_lang:
            await websocket.close(code=1003, reason='No source lang found in headers')
        
        transcr_manager = TranscriptionManager(args.source_lang)

        audio_processor = AudioProcessor(transcription_engine=transcription_engine)
        whisper_generator = await audio_processor.create_tasks()

        conn_manager = ConnectionManager(transcr_manager, audio_processor, whisper_generator)
        await conn_manager.listen_to_host(websocket)
    else:   # role == 'client'
        try:
            await conn_manager.connect_client(websocket)
        except Exception as e:
            logging.warning(f'Client connection failed:\n{e}')
            await websocket.close(code=1003, reason='No host connected')

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global conn_manager
    await websocket.accept()

    transcr_manager = TranscriptionManager(args.source_lang)
    room_manager = RoomManager([transcr_manager])
    translation_worker = TranslationWorker(
        room_manager, args.source_lang, [args.target_lang],    # TODO: implement multiple target langs
        lt_url=args.libretranslate_url, lt_port=args.libretranslate_port,
        poll_interval=1
    )
    translation_worker.start()

    # TODO: check websocket.headers.get or smth like that
    audio_processor = AudioProcessor(transcription_engine=transcription_engine) # TODO: move to init
    whisper_generator = await audio_processor.create_tasks()

    conn_manager = ConnectionManager(transcr_manager, audio_processor, whisper_generator)
    await conn_manager.listen_to_host(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=args.host,
        port=args.port
    )

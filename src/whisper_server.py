import asyncio
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from whisperlivekit import TranscriptionEngine, get_web_interface_html

from io_config.cli import MODEL, DIARIZATION, SOURCE_LANG
from io_config.config import LT_HOST, LT_PORT, API_HOST, API_PORT
from io_config.logger import LOGGER
from room_manager import room_manager

# --- Has to stay ---
transcription_engine = None
server_ready = False

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine, server_ready
    LOGGER.info(f"Loading Whisper model: {MODEL}, diarization={DIARIZATION}, language={SOURCE_LANG}")
    transcription_engine = TranscriptionEngine(model=MODEL, diarization=DIARIZATION, lan=SOURCE_LANG) # buffer_trimming="sentence"

    LOGGER.info(f"Starting LibreTranslate server: {LT_HOST}:{LT_PORT}")
    # Start LibreTranslate as a subprocess
    libretranslate_proc = subprocess.Popen(
        [
            "poetry", "run", "libretranslate",
            "--host", LT_HOST,
            "--port", str(LT_PORT),
            "--load-only", "en,de"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    LOGGER.info(f"LibreTranslate server started with PID {libretranslate_proc.pid}")

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
        LOGGER.info(f'Client x disconnected')


@app.websocket("/room/{room_id}/{role}/{source_lang}/{target_lang}/{password}")
async def connect_to_room(websocket: WebSocket, room_id: str, role: str, source_lang: str, target_lang: str, password: str):
    global transcription_engine

    await websocket.accept()

    if not role or not (role == 'host' or role == 'client'):
        await websocket.close(code=1003, reason='No desired role found in headers')
    
    if role == 'host':
        if not password or password != 'letmein': # TODO: check password
            await websocket.close(code=1003, reason='No desired role found in headers')
            return
        
        if not source_lang:
            await websocket.close(code=1003, reason='No source lang found in headers')
        
        await room_manager.activate_room(websocket, room_id, source_lang, transcription_engine)
    else:   # role == 'client'
        await room_manager.join_room_as_client(websocket, room_id, target_lang)

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine
    await websocket.accept()

    room_id = 'dev_room_id'
    source_lang = 'de'
    await room_manager.activate_room(websocket, room_id, source_lang, transcription_engine)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=API_HOST,
        port=API_PORT
    )

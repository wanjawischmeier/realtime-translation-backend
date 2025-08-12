import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from io_config.config import ADMIN_PASSWORD, LT_HOST, LT_PORT, API_HOST, API_PORT, HOST_PASSWORD
from io_config.logger import LOGGER
from room_system.room_manager import room_manager
from transcription_system.transcript_formatter import get_available_transcript_list, compile_transcript_from_room_id

server_ready = False

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app:FastAPI):
    global server_ready
    LOGGER.info(f"Starting LibreTranslate server: {LT_HOST}:{LT_PORT}")
    # Start LibreTranslate as a subprocess
    libretranslate_proc = subprocess.Popen(
        [
            "poetry", "run", "libretranslate",
            "--host", LT_HOST,
            "--port", str(LT_PORT),
            # "--load-only", "en,de" # Only to be used for saving resources during debugging
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
ngrok_url = "https://3ee4395e6f01.ngrok-free.app"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", ngrok_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    if server_ready:
        return JSONResponse({"status": "ok"}, status_code=200)
    else:
        return JSONResponse({"status": "not ready"}, status_code=503)

@app.post("/auth")
async def auth(request: Request):
    body = await request.json()
    password = body.get("password")
    if ngrok_url == request.headers.get('origin'):
        password = HOST_PASSWORD # TODO: remove temporary bypass for ngrok
    if not password or password != HOST_PASSWORD:
        LOGGER.info("Failed auth request")
        return JSONResponse({"status": "fail"}, status_code=503)
    else:
        LOGGER.info("Succesful auth request")
        return JSONResponse({"status": "ok"}, status_code=200)

@app.get("/room_list")
async def get_room_list():
    return JSONResponse(room_manager.get_room_list())

@app.get("/transcript_list")
async def get_transcript_list():
    return JSONResponse(get_available_transcript_list())

@app.get("/room/{room_id}/transcript/{target_lang}")
async def get_transcript_for_room(room_id: str, target_lang: str):
    return PlainTextResponse(compile_transcript_from_room_id(room_id, target_lang))

@app.post("/room/{room_id}/close")
async def request_close_room(request: Request, room_id: str):
    body = await request.json()
    password = body.get("password")
    if not password or password != ADMIN_PASSWORD:
        LOGGER.info(f"Failed to close room <{room_id}>: Incorrect admin password")
        return JSONResponse({"status": "fail"}, status_code=503)
    
    if not await room_manager.deactivate_room(room_id):
        LOGGER.info(f"Failed to close room <{room_id}>: Failed to deactivate")
        return JSONResponse({"status": "fail"}, status_code=503)
        
    LOGGER.info(f"Closed room <{room_id}> on admin request")
    return JSONResponse({"status": "ok"}, status_code=200)

@app.websocket("/room/{room_id}/{role}/{source_lang}/{target_lang}")
async def connect_to_room(websocket: WebSocket, room_id: str, role: str, source_lang: str, target_lang: str):
    await websocket.accept()

    if not role or not (role == 'host' or role == 'client'):
        await websocket.close(code=1003, reason='No desired role found in url')
        return
    
    if not target_lang:
        await websocket.close(code=1003, reason='No target lang found in url')
        return

    if role == 'host':
        password = websocket.cookies.get('authenticated')  
        if ngrok_url == websocket.headers.get('origin'):
            password = ADMIN_PASSWORD # TODO: remove temporary bypass for ngrok
        if not password or not (password == HOST_PASSWORD or password == ADMIN_PASSWORD):
            await websocket.close(code=1003, reason='Authentification failed: no valid password in session cookie')
            return
        
        if not source_lang:
            await websocket.close(code=1003, reason='No source lang found in url')
            return
        
        await room_manager.activate_room_as_host(websocket, room_id, source_lang, target_lang)
    else:   # role == 'client'
        await room_manager.join_room_as_client(websocket, room_id, target_lang)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "whisper_server:app",
        host=API_HOST,
        port=API_PORT
    )

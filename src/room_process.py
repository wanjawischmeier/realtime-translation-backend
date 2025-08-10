import asyncio
from multiprocessing import Process
from typing import Awaitable, Callable
from aioprocessing import AioQueue
from io_config.logger import LOGGER
from room_worker import room_worker, READY_SIGNAL, STOP_SIGNAL

from io_config.cli import MODEL, DEVICE, COMPUTE_TYPE, DIARIZATION, VAC, BUFFER_TRIMMING, MIN_CHUNK_SIZE, VAC_CHUNK_SIZE

class RoomProcess:
    def __init__(self, room_id: str, source_lang: str):
        self._room_id = room_id
        self.audio_queue = AioQueue()
        self.transcript_queue = AioQueue()
        self._on_ready: Callable[[None], Awaitable[None]] = None
        
        self.process = Process(
            target=room_worker,
            args=(
                room_id, self.audio_queue, self.transcript_queue, source_lang,
                MODEL, DIARIZATION, VAC, BUFFER_TRIMMING, # CLI args can't be acessed directly in other process
                MIN_CHUNK_SIZE, VAC_CHUNK_SIZE, DEVICE, COMPUTE_TYPE
            ),
            daemon=True
        )
    
    def start(self, on_ready: Callable[[None], Awaitable[None]]=None):
        self._on_ready = on_ready
        self.process.start()

    async def stop(self):
        # Send the sentinel to the audio queue for graceful shutdown
        await self.audio_queue.coro_put(STOP_SIGNAL)
       
        # Await process termination in a background thread
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.process.join, 10) # 10 second timeout
        if self.process.is_alive():
            LOGGER.warning(f'Failed to stop worker process for room <{self._room_id}>')
       

    async def send_audio_chunk(self, chunk: bytes):
        await self.audio_queue.coro_put(chunk)
    
    async def get_transcript_chunk(self):
        chunk = await self.transcript_queue.coro_get()
        if chunk == READY_SIGNAL:
            if self._on_ready:
                await self._on_ready()
        else:
            return chunk

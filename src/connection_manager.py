import asyncio
from types import CoroutineType
from typing import Any, Awaitable, Callable
from fastapi import WebSocket, WebSocketDisconnect

from io_config.logger import LOGGER
from transcription_manager import TranscriptionManager


class ConnectionManager:
    def __init__(
            self, room_id: str, transcription_manager: TranscriptionManager,
            audio_chunk_recieved: Callable[[Any], Awaitable[None]],     # async -> send_audio_chunk
            transcript_chunk_recieved: Callable[[dict], None],          # sync  -> transcription_manager.submit_chunk
            transcript_chunk_provider: CoroutineType,                   # async -> get_transcript_chunk
            restart_request_recieved: Callable[[None], Awaitable[None]]
        ):
        self._room_id = room_id
        self._transcription_manager = transcription_manager
        self._audio_chunk_recieved = audio_chunk_recieved
        self._transcript_chunk_recieved = transcript_chunk_recieved
        self._transcript_chunk_provider = transcript_chunk_provider
        self._restart_request_recieved = restart_request_recieved
        self._host: WebSocket = None
        self._clients: list[WebSocket] = []

    async def listen_to_host(self, websocket: WebSocket):
        if self._host:   # can't connect to multiple hosts at the same time
            await websocket.close(code=1003, reason='Multiple hosts not allowed')
            return
        
        self._host = websocket
        self._transcript_generator_handler_task = asyncio.create_task(
            self._handle_whisper_generator()
        )
        self._transcript_generator_handler_task = asyncio.create_task(
            self._handle_transcript_generator(self._transcription_manager.transcript_generator()) # TODO: pass generator directly
        )
        LOGGER.info(f'Host connected in room <{self._room_id}>, listening...')

        try:
            while True:
                message = await websocket.receive_bytes()
                await self._audio_chunk_recieved(message)
        except WebSocketDisconnect:
            self.cancel()
            self._host = None
            LOGGER.info(f'Host disconnected in room <{self._room_id}>')

    async def connect_client(self, websocket: WebSocket):
        self._clients.append(websocket)
        LOGGER.info(f'Client {len(self._clients)} connected in room <{self._room_id}>')

        try:
            while True:
                await asyncio.sleep(1)  # Just keep the connection alive TODO: check if neccessary
        except WebSocketDisconnect:
            self._clients.remove(websocket)
            LOGGER.info(f'Client {len(self._clients) + 1} disconnected in room <{self._room_id}>') # TODO: fix recognition of client detection
    
    async def _handle_whisper_generator(self):
        while True:
            transcript = await self._transcript_chunk_provider()
            # print(f'Result for room <{self._room_id}>: {transcript}')
            self._transcript_chunk_recieved(transcript)
    
    async def _handle_transcript_generator(self, transcript_generator):
        async for transcript in transcript_generator:
            print(f'Result for room <{self._room_id}>:')
            print(transcript)
            
            await self._host.send_json(transcript) # Host also wants to recieve transcript
            for client in self._clients:
                try:
                    await client.send_json(transcript)
                except WebSocketDisconnect:
                    LOGGER.info(f'Removing dead client {len(self._clients)} in room <{self._room_id}>')
                    self._clients.remove(client)
        
        for client in self._clients: # TODO: implement this in the frontend?
            await client.send_json({'type': 'ready_to_stop'})
        LOGGER.info(f'Results generator closed in room <{self._room_id}>')
        self._transcript_generator_handler_task.cancel() # TODO: check if this is necessary/working

    def cancel(self):
        if self._transcript_generator_handler_task:
            self._transcript_generator_handler_task.cancel()